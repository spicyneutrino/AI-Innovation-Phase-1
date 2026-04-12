from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from sos_crawler.paths import runtime_dir

try:
    import pdfplumber  # type: ignore
except Exception:  # pragma: no cover
    pdfplumber = None


_PATH_SEGMENT_MAX = 110


def _safe_path_segment(value: str | None, *, fallback: str) -> str:
    """
    Create a safe directory/file path segment (not a full path).

    Must match the crawler's filesystem constraints: avoid reserved characters
    and cap length to prevent ENAMETOOLONG on deep MS nesting.
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


def extract_text(item: dict) -> str:
    if item.get("text"):
        return str(item["text"])
    if item.get("extracted_text"):
        return str(item["extracted_text"])
    # MS fallback: load from nested data directory (pdf/txt)
    if str(item.get("state") or "").upper() == "MS":
        p = _ms_doc_path_from_item(item)
        if p and p.exists():
            if p.suffix.lower() == ".txt":
                return p.read_text(encoding="utf-8", errors="replace")
            if p.suffix.lower() == ".pdf" and pdfplumber is not None:
                try:
                    with pdfplumber.open(p) as pdf:
                        pages = []
                        for page in pdf.pages:
                            pages.append(page.extract_text() or "")
                        return "\n\n".join(t for t in pages if t.strip())
                except Exception:
                    return ""
    return ""


def chunk_text(text: str, chunk_size: int = 1200, overlap: int = 200) -> list[str]:
    if not text:
        return []
    chunks = []
    step = max(1, chunk_size - overlap)
    for i in range(0, len(text), step):
        chunk = text[i : i + chunk_size]
        if chunk:
            chunks.append(chunk)
    return chunks


def run_enrich(runtime: Path | None = None) -> int:
    rt = runtime or runtime_dir()
    out_dir = rt / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    manifests = sorted(out_dir.glob("manifest_*.jsonl"))
    if not manifests:
        return 0

    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    out = out_dir / f"knowledge_package_{ts}.jsonl"
    with out.open("w", encoding="utf-8") as w:
        for mf in manifests:
            for line in mf.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                item = json.loads(line)
                text = extract_text(item)
                chunks = chunk_text(text)
                record = {
                    "state": item.get("state"),
                    "state_name": item.get("state_name"),
                    "agency": item.get("agency"),
                    "doc_url": item.get("doc_url"),
                    "source_url": item.get("source_url"),
                    "citation": item.get("citation") or item.get("title"),
                    "citation_normalized": item.get("citation_normalized"),
                    "rule_status": item.get("rule_status") or item.get("doc_type"),
                    "topics": item.get("topics", []),
                    "fetched_at": item.get("fetched_at"),
                    "first_seen": item.get("first_seen"),
                    "last_changed_at": item.get("last_changed_at"),
                    "chunks": chunks,
                }
                w.write(json.dumps(record) + "\n")
    return 0


def enrich_from_cli(args: argparse.Namespace) -> int:
    if getattr(args, "runtime_dir", None):
        import os

        os.environ["SOS_CRAWLER_RUNTIME_DIR"] = args.runtime_dir
    return run_enrich(runtime_dir())


def _ms_doc_path_from_item(item: dict) -> Path | None:
    """
    Resolve the MS document path under:
      <repo>/data/MS/Title_{Number}-{Agency_Name}/Part_{Number}-{Rule_Name}/{SystemNumber}.{ext}

    Uses manifest fields:
      - agency: expected to contain 'Title NN - Agency Name' (or similar)
      - title: expected to be 'Part N - Rule Name'
      - filename: expected to be '<SystemNumber>.pdf' (or .txt)
    """
    agency = str(item.get("agency") or "").strip()
    title = str(item.get("title") or "").strip()
    filename = str(item.get("filename") or "").strip()
    if not filename:
        # Derive from doc_url if needed
        doc_url = str(item.get("doc_url") or "")
        filename = (doc_url.split("/")[-1] if doc_url else "").split("?", 1)[0]
    if not filename:
        return None

    m_title = re.search(r"(?i)\btitle\s*0*(\d+)\b(?:\s*[-—:]\s*|\s+)(.+)$", agency)
    title_num = (m_title.group(1) if m_title else "00").zfill(2)
    agency_name = (m_title.group(2) if m_title else (agency or "Unknown")).strip()

    m_part = re.search(r"(?i)\bpart\s*0*(\d+)\b\s*[-—:]\s*(.+)$", title)
    part_num = (m_part.group(1) if m_part else "0").strip()
    part_name = (m_part.group(2) if m_part else (title or "Unknown")).strip()

    title_folder = _safe_path_segment(
        f"Title_{title_num}-{agency_name}",
        fallback=f"Title_{title_num}-Unknown",
    )
    part_folder = _safe_path_segment(
        f"Part_{part_num}-{part_name}",
        fallback=f"Part_{part_num}-Unknown",
    )

    ms_root = runtime_dir() / "downloads" / "MS"
    return ms_root / title_folder / part_folder / filename

