from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

from scrapy.exceptions import DropItem

from sos_crawler.config import load_config
from sos_crawler.paths import downloads_dir, output_dir


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


_PATH_SEGMENT_MAX = 110


def _safe_path_segment(value: str | None, *, fallback: str) -> str:
    """
    Create a safe directory/file path segment (not a full path).

    - strips/normalizes whitespace
    - replaces path separators and reserved characters with '-'
    - caps length to avoid extreme path lengths
    """
    s = (value or "").strip()
    if not s:
        return fallback
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r'[\\\\/:"*?<>|]+', "-", s)
    s = s.strip(" .-_")
    if not s:
        return fallback
    if len(s) > _PATH_SEGMENT_MAX:
        s = s[:_PATH_SEGMENT_MAX].rstrip(" .-_")
    return s or fallback


class AgencyScopePipeline:
    """Apply full-state or designated-agency scope controls."""

    def __init__(self):
        self.mode = os.getenv("CRAWLER_MODE", "full").strip().lower()
        allowlist_path = os.getenv("AGENCY_ALLOWLIST_FILE", "agency_allowlists.yaml")
        p = Path(allowlist_path)
        cfg = load_config(p if p.exists() else allowlist_path)
        self.designated = cfg.get("designated_agencies", {})

    def process_item(self, item, spider):
        if self.mode != "designated":
            return item

        state = item.get("state")
        # Mississippi should always crawl/download all agencies regardless of designated mode.
        if state == "MS":
            return item

        allowed = self.designated.get(state, [])
        if not allowed:
            raise DropItem(f"No designated agencies configured for state={state}")

        haystack = " ".join(
            [
                str(item.get("agency", "")),
                str(item.get("title", "")),
                str(item.get("doc_url", "")),
                str(item.get("source_url", "")),
            ]
        ).lower()
        if not any(a.lower() in haystack for a in allowed):
            raise DropItem(f"Excluded by designated agency scope: state={state}")
        return item


class NormalizePipeline:
    """Normalize citations and provenance fields for downstream indexing."""

    def process_item(self, item, spider):
        item["source_system"] = "state_sos"
        item["source_portal"] = spider.name
        response_url = item.get("source_url", "")
        item["source_state_url"] = response_url
        item["rule_status"] = item.get("rule_status") or item.get("doc_type", "unknown")
        item["fetched_at"] = item.get("fetched_at") or _utc_now_iso()

        citation = item.get("citation") or item.get("title") or response_url
        item["citation"] = citation
        item["citation_normalized"] = re.sub(r"[^a-z0-9]+", "-", str(citation).lower()).strip("-")
        item["topics"] = item.get("topics") or []
        return item


class DocumentSavePipeline:
    """Save raw document bytes to disk. Skip if content unchanged (same hash)."""

    def process_item(self, item, spider):
        state = item["state"]
        url = item["doc_url"]
        body = item.get("_body", b"")

        if state == "MS":
            out_dir = _ms_out_dir(item)
            filename = _ms_filename(item)
            is_pdf = filename.lower().endswith(".pdf")
        else:
            agency_type = (item.get("agency_type") or "").strip()
            if not agency_type:
                raise DropItem(f"Missing agency_type for state={state} doc_url={url}")
            out_dir = downloads_dir() / state / _safe_path_segment(agency_type, fallback="unknown")
            raw_name = str(item.get("filename") or "").strip() or url.split("/")[-1]
            raw_name = raw_name.split("?", 1)[0]
            stem = Path(raw_name).stem or "document"
            suffix = Path(raw_name).suffix.lower()
            if suffix == ".pdf" or "pdf" in (item.get("content_type") or "").lower():
                filename = f"{stem}.pdf"
                is_pdf = True
            else:
                filename = f"{stem}.txt"
                is_pdf = False
        out_dir.mkdir(parents=True, exist_ok=True)

        filename = filename or item.get("hash_md5") or "document.bin"
        dest = out_dir / filename
        meta_dest = dest.with_name(dest.name + ".metadata.json")

        if dest.exists():
            existing_hash = hashlib.md5(dest.read_bytes()).hexdigest()
            item["is_new"] = existing_hash != item.get("hash_md5")
        else:
            item["is_new"] = True

        if item.get("is_new") and body:
            if is_pdf:
                dest.write_bytes(body)
            else:
                dest.write_text(item.get("extracted_text", ""), encoding="utf-8")
            spider.logger.info("NEW DOC saved: %s", dest)

        # MS: write sidecar with original (untruncated) strings for traceability.
        if state == "MS":
            if (item.get("is_new") and body) or (not meta_dest.exists()):
                citation = item.get("citation") or item.get("title") or item.get("doc_url") or ""
                # Preserve raw values that were used to derive folder names.
                meta = {
                    "metadataAttributes": {
                        "state": "MS",
                        "citation": str(citation),
                        "is_primary": "true",
                        "title_raw": str(item.get("agency") or ""),
                        "part_raw": str(item.get("title") or ""),
                        "doc_url": str(item.get("doc_url") or ""),
                    }
                }
                meta_dest.write_text(json.dumps(meta, indent=2), encoding="utf-8")

        # Non-MS: always ensure a Bedrock-style sidecar exists alongside the .txt
        if state != "MS":
            if (item.get("is_new") and body) or (not meta_dest.exists()):
                citation = item.get("citation") or item.get("title") or item.get("doc_url") or ""
                meta = {
                    "metadataAttributes": {
                        "state": str(state),
                        "agency_type": str((item.get("agency_type") or "").strip() or "unknown"),
                        "citation": str(citation),
                        "is_primary": "true" if str(state).upper() == "MS" else "false",
                    }
                }
                meta_dest.write_text(json.dumps(meta, indent=2), encoding="utf-8")

        return item


def _ms_parse_title_folder(agency: str) -> tuple[str, str]:
    """
    Mississippi (MS) folder structure:
      data/MS/Title_{Number}-{Agency_Name}/Part_{Number}-{Rule_Name}/

    The spider's `agency` field typically contains the Title number and agency name.
    We accept a variety of separators because upstream formatting can vary.
    """
    s = (agency or "").strip()
    m = re.search(r"(?i)\btitle\s*0*(\d+)\b(?:\s*[-—:]\s*|\s+)(.+)$", s)
    if m:
        title_num = m.group(1).zfill(2)
        agency_name = m.group(2).strip()
        return title_num, agency_name
    return "00", s or "Unknown"


def _ms_parse_part_folder(title: str) -> tuple[str, str]:
    """
    The spider's `title` field is constructed like:
      'Part {part_no} - {rule_name}'
    """
    s = (title or "").strip()
    m = re.search(r"(?i)\bpart\s*0*(\d+)\b\s*[-—:]\s*(.+)$", s)
    if m:
        part_num = m.group(1)
        rule_name = m.group(2).strip()
        return part_num, rule_name
    # Some titles may not follow the exact pattern.
    return "0", s or "Unknown"


def _ms_out_dir(item) -> Path:
    title_num, agency_name = _ms_parse_title_folder(str(item.get("agency", "")))
    part_num, rule_name = _ms_parse_part_folder(str(item.get("title", "")))

    title_folder = _safe_path_segment(
        f"Title_{title_num}-{agency_name}",
        fallback=f"Title_{title_num}-Unknown",
    )
    part_folder = _safe_path_segment(
        f"Part_{part_num}-{rule_name}",
        fallback=f"Part_{part_num}-Unknown",
    )

    # Store MS artifacts under runtime downloads (stable, nested structure).
    return downloads_dir() / "MS" / title_folder / part_folder


def _ms_filename(item) -> str:
    """
    Rename the final file to its System Number (ensures uniqueness).
    The MS spider already uses the portal filename (e.g., '179.pdf').
    """
    raw = str(item.get("filename") or "").strip()
    if raw:
        # Prefer numeric stem if present.
        stem = Path(raw).stem
        ext = Path(raw).suffix or ".pdf"
        m = re.search(r"(\d+)", stem)
        if m:
            return f"{m.group(1)}{ext}"
        return raw
    # Fallback to the last path segment of doc_url.
    url = str(item.get("doc_url") or "")
    last = (url.split("/")[-1] if url else "").split("?", 1)[0]
    if last:
        return last
    return "document.bin"


class ManifestPipeline:
    """Append every item to a JSONL manifest for downstream RAG indexing."""

    def open_spider(self, spider):
        out = output_dir()
        ts = datetime.now(UTC).strftime("%Y%m%d")
        self._path = out / f"manifest_{spider.name}_{ts}.jsonl"
        self.f = self._path.open("a", encoding="utf-8")

    def close_spider(self, spider):
        self.f.close()

    def process_item(self, item, spider):
        safe = {k: v for k, v in item.items() if k != "_body"}
        self.f.write(json.dumps(safe) + "\n")
        return item


class ChangeTrackingPipeline:
    """Track first/last seen hashes for time-based change history."""

    def process_item(self, item, spider):
        state = item["state"]
        idx_path = output_dir() / f"state_index_{state}.json"
        index = {}
        if idx_path.exists():
            index = json.loads(idx_path.read_text(encoding="utf-8"))

        key = item.get("doc_url", "")
        current_hash = item.get("hash_md5")
        now = _utc_now_iso()
        prev = index.get(key)

        if prev is None:
            item["first_seen"] = now
            item["last_seen"] = now
            item["last_changed_at"] = now
            item["previous_hash"] = None
        else:
            item["first_seen"] = prev.get("first_seen", now)
            item["last_seen"] = now
            item["previous_hash"] = prev.get("hash_md5")
            if prev.get("hash_md5") != current_hash:
                item["last_changed_at"] = now
            else:
                item["last_changed_at"] = prev.get("last_changed_at", now)

        index[key] = {
            "hash_md5": current_hash,
            "first_seen": item["first_seen"],
            "last_seen": item["last_seen"],
            "last_changed_at": item["last_changed_at"],
        }
        idx_path.write_text(json.dumps(index, indent=2), encoding="utf-8")
        return item

