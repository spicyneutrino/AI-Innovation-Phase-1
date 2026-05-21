from __future__ import annotations

"""
Louisiana Administrative Code Spider
====================================
Source  : https://www.doa.la.gov/doa/osr/louisiana-administrative-code/
Publisher: Louisiana Office of State Register / Division of Administration

Targets 3 agencies (Title 46 — Professional and Occupational Standards):
  Part XXXIII → Louisiana State Board of Dentistry         (dental)
  Part XLV    → Louisiana State Board of Medical Examiners (medical-licensure)
  Part LXVII  → Louisiana Real Estate Commission           (real-estate)

HOW THE SITE WORKS
──────────────────
The current Louisiana Administrative Code site links directly to DOCX title/part
volumes rather than exposing a clean per-rule HTML tree for these agencies.
This spider downloads the targeted DOCX files and splits them into individual
rule sections ("§...") using the document structure:

  Title → Part → Subpart → Chapter → § Section

Notes:
- Dental and Medical each use a dedicated Title 46 DOCX for the targeted agency.
- The Real Estate DOCX includes additional material beyond the commission
  (for example appraisers). This spider keeps only Subpart 1 for the Louisiana
  Real Estate Commission.
- No Playwright is needed.
"""

import hashlib
import io
import re
import xml.etree.ElementTree as ET
import zipfile
from datetime import UTC, datetime

import scrapy
from scrapy.http import Response

from sos_crawler.config import load_config
from sos_crawler.items import RegDocItem

_BASE = "https://www.doa.la.gov/doa/osr/louisiana-administrative-code/"

_TARGETS: dict[str, dict] = {
    "33": {
        "agency_type": "dental",
        "agency_name": "Louisiana State Board of Dentistry",
        "part_roman": "XXXIII",
        "part_name": "Dental Health Profession",
        "docx_url": "https://www.doa.la.gov/media/z2pl5soj/46v33.docx",
    },
    "45": {
        "agency_type": "medical-licensure",
        "agency_name": "Louisiana State Board of Medical Examiners",
        "part_roman": "XLV",
        "part_name": "Medical Professions",
        "docx_url": "https://www.doa.la.gov/media/t5scfw11/46v45.docx",
    },
    "67": {
        "agency_type": "real-estate",
        "agency_name": "Louisiana Real Estate Commission",
        "part_roman": "LXVII",
        "part_name": "Real Estate",
        "docx_url": "https://www.doa.la.gov/media/mtuakm0q/46v67.docx",
        "allowed_subparts": {"1"},
    },
}

_DEFAULT_START_URLS = [cfg["docx_url"] for cfg in _TARGETS.values()]
_TARGETS_BY_URL = {cfg["docx_url"]: cfg for cfg in _TARGETS.values()}

_TITLE_RE = re.compile(r"^Title\s+46\b", re.I)
_PART_RE = re.compile(r"^Part\s+([IVXLCDM]+)\.\s*(.+?)\s*$", re.I)
_SUBPART_RE = re.compile(r"^Subpart\s+([0-9A-Za-z]+)\.\s*(.+?)\s*$", re.I)
_CHAPTER_RE = re.compile(r"^Chapter\s+([0-9A-Za-z\-]+)\.\s*(.+?)\s*$", re.I)
_SECTION_RE = re.compile(r"^§\s*([0-9A-Za-z\-]+)\.\s*(.+?)\s*$")


class LouisianaSpider(scrapy.Spider):
    name = "louisiana"
    state = "LA"
    state_name = "Louisiana"
    allowed_domains = ["doa.la.gov"]

    custom_settings = {
        "DOWNLOAD_DELAY": 1.0,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
        "ROBOTSTXT_OBEY": False,
        "HTTPCACHE_ENABLED": False,
    }

    def start_requests(self):
        cfg = load_config("sources.yaml")
        state_cfg = (cfg.get("states") or {}).get(self.state, {})
        urls = state_cfg.get("entrypoints") or _DEFAULT_START_URLS

        for url in urls:
            target = _target_from_url(url)
            if not target:
                self.logger.warning("[LA] Unrecognized entrypoint, skipping: %s", url)
                continue
            yield scrapy.Request(
                url,
                callback=self.parse_docx,
                meta={"target": target},
                errback=self.errback,
            )

    def parse_docx(self, response: Response):
        target = response.meta["target"]
        paragraphs = _extract_docx_paragraphs(response.body)
        if not paragraphs:
            self.logger.error("[LA] No paragraphs extracted from %s", response.url)
            return

        body_start = _find_body_start(paragraphs)
        if body_start >= len(paragraphs):
            self.logger.error("[LA] Could not locate body start in %s", response.url)
            return

        paragraphs = [_normalize_paragraph(p) for p in paragraphs[body_start:] if _normalize_paragraph(p)]
        yielded = 0

        current_part_roman = target["part_roman"]
        current_part_name = target["part_name"]
        current_subpart_num = ""
        current_subpart_name = ""
        current_chapter_num = ""
        current_chapter_name = ""
        current_section_num = ""
        current_section_title = ""
        current_lines: list[str] = []

        def flush_section():
            nonlocal yielded, current_section_num, current_section_title, current_lines
            if not current_section_num:
                return
            if target.get("allowed_subparts") and current_subpart_num not in target["allowed_subparts"]:
                current_section_num = ""
                current_section_title = ""
                current_lines = []
                return

            body_lines = [line for line in current_lines if line]
            if not body_lines:
                body_lines = [current_section_title]

            doc_lines = [
                f"STATE: Louisiana (LA)",
                f"AGENCY: {target['agency_name']}",
                f"TITLE: 46 — Professional and Occupational Standards",
                f"PART: {current_part_roman} — {current_part_name}",
            ]
            if current_subpart_num:
                doc_lines.append(f"SUBPART: {current_subpart_num} — {current_subpart_name}")
            if current_chapter_num:
                doc_lines.append(f"CHAPTER: {current_chapter_num} — {current_chapter_name}")
            doc_lines += [
                f"RULE: §{current_section_num} — {current_section_title}",
                f"SOURCE: {response.url}",
                "",
                *body_lines,
            ]
            doc_text = re.sub(r"\n{3,}", "\n\n", "\n".join(doc_lines)).strip()

            citation = (
                f"Louisiana | {target['agency_name']} | "
                f"Title 46, Part {current_part_roman}"
            )
            if current_chapter_num:
                citation += f", Chapter {current_chapter_num}"
            citation += f" | §{current_section_num}"

            safe_section = re.sub(r"[^\w\-]", "_", current_section_num).strip("_") or "unknown"
            safe_chapter = re.sub(r"[^\w\-]", "_", current_chapter_num).strip("_") or "na"
            safe_subpart = re.sub(r"[^\w\-]", "_", current_subpart_num).strip("_") or "na"
            filename = (
                f"LA_{target['agency_type']}_part{current_part_roman.lower()}"
                f"_subpart{safe_subpart}_ch{safe_chapter}_sec{safe_section}.txt"
            )

            body = doc_text.encode("utf-8")
            yield RegDocItem(
                state=self.state,
                state_name=self.state_name,
                agency=target["agency_name"],
                agency_type=target["agency_type"],
                agency_id=current_part_roman,
                source_url=response.url,
                doc_url=response.url,
                filename=filename,
                doc_type="rule",
                rule_status="rule",
                title=f"§{current_section_num} — {current_section_title}",
                citation=citation,
                extracted_text=doc_text,
                fetched_at=datetime.now(UTC).isoformat(),
                hash_md5=hashlib.md5(body).hexdigest(),
                size_bytes=len(body),
                content_type="text/plain; charset=utf-8",
                _body=body,
            )
            yielded += 1
            current_section_num = ""
            current_section_title = ""
            current_lines = []

        for para in paragraphs:
            if _TITLE_RE.match(para):
                continue

            m = _PART_RE.match(para)
            if m:
                current_part_roman = m.group(1).upper()
                current_part_name = m.group(2).strip()
                continue

            m = _SUBPART_RE.match(para)
            if m:
                if current_section_num:
                    yield from flush_section()
                current_subpart_num = m.group(1).strip()
                current_subpart_name = m.group(2).strip()
                continue

            m = _CHAPTER_RE.match(para)
            if m:
                if current_section_num:
                    yield from flush_section()
                current_chapter_num = m.group(1).strip()
                current_chapter_name = m.group(2).strip()
                continue

            m = _SECTION_RE.match(para)
            if m:
                if current_section_num:
                    yield from flush_section()
                current_section_num = m.group(1).strip()
                current_section_title = m.group(2).strip()
                current_lines = []
                continue

            if current_section_num:
                current_lines.append(para)

        if current_section_num:
            yield from flush_section()

        self.logger.info(
            "[LA] %s: yielded %d rule items from %s",
            target["agency_name"], yielded, response.url,
        )

    def errback(self, failure):
        self.logger.error("[LA] Request failed: %s — %s", failure.request.url, failure.value)


def _target_from_url(url: str) -> dict | None:
    if url in _TARGETS_BY_URL:
        return _TARGETS_BY_URL[url]

    low = url.lower()
    if "46v33" in low:
        return _TARGETS["33"]
    if "46v45" in low:
        return _TARGETS["45"]
    if "46v67" in low:
        return _TARGETS["67"]
    return None


def _extract_docx_paragraphs(body: bytes) -> list[str]:
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as zf:
            xml_bytes = zf.read("word/document.xml")
    except Exception:
        return []

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []

    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs: list[str] = []
    for p in root.findall(".//w:p", ns):
        parts = [t.text or "" for t in p.findall(".//w:t", ns)]
        text = "".join(parts).strip()
        if text:
            paragraphs.append(text)
    return paragraphs


def _normalize_paragraph(text: str) -> str:
    text = (text or "").replace("\xa0", " ").strip()
    text = re.sub(r"\s+", " ", text)
    text = text.replace("―", "—")
    return text.strip()


def _find_body_start(paragraphs: list[str]) -> int:
    for idx, text in enumerate(paragraphs):
        if _TITLE_RE.match((text or "").strip()):
            return idx
    return 0
