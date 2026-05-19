from __future__ import annotations

"""
Georgia Secretary of State — Georgia Administrative Code Spider
===============================================================
Source   : https://rules.sos.ga.gov/gac/
Publisher: Georgia Secretary of State / Georgia Administrative Code

Targets 3 agencies only:
  Department 150  →  Board of Dental Examiners of Georgia   (site title: Georgia Board of Dentistry)
  Department 360  →  Medical Licensure Commission of Georgia (site title: Georgia Composite Medical Board)
  Department 520  →  Georgia Real Estate Commission         (real-estate)

HOW THE SITE WORKS
──────────────────
The Georgia rules site is server-rendered. No Playwright is needed.

Navigation pattern:
  Department page: https://rules.sos.ga.gov/gac/{dept}
  Chapter page   : https://rules.sos.ga.gov/gac/{dept}-{chapter}

Department pages contain chapter links near the bottom of the page.
Chapter pages render all rules inline under H2 headings, e.g.:
  #  Chapter 150-3 LICENSE REQUIREMENTS
  ## Rule 150-3-.01 Examination for Dental Licensure
     ...body text...
  ## Rule 150-3-.02 License Issuance
     ...body text...

This spider:
  1. loads the 3 target department pages;
  2. follows only chapter links for those departments;
  3. splits each chapter page into individual rule records; and
  4. yields one RegDocItem per rule.
"""

import hashlib
import re
from datetime import UTC, datetime
from urllib.parse import urlparse

import scrapy
from scrapy.http import Response

from sos_crawler.config import load_config
from sos_crawler.items import RegDocItem

_BASE = "https://rules.sos.ga.gov/gac"

_DEPARTMENTS: dict[str, dict] = {
    "150": {
        "agency_type": "dental",
        "agency_name": "Board of Dental Examiners of Georgia",
        "site_name": "Georgia Board of Dentistry",
    },
    "360": {
        "agency_type": "medical-licensure",
        "agency_name": "Medical Licensure Commission of Georgia",
        "site_name": "Georgia Composite Medical Board",
    },
    "520": {
        "agency_type": "real-estate",
        "agency_name": "Georgia Real Estate Commission",
        "site_name": "Georgia Real Estate Commission",
    },
}

_DEFAULT_START_URLS = [f"{_BASE}/{dept_id}" for dept_id in _DEPARTMENTS]

_CHAPTER_RE = re.compile(r"/gac/(150|360|520)-(\d+)$", re.I)
_RULE_HEADING_RE = re.compile(r"^Rule\s+((?:150|360|520)-\d+-\.\d+)\s*(.*)$", re.I)
_CHAPTER_HEADING_RE = re.compile(r"^Chapter\s+((?:150|360|520)-\d+)\s*(.*)$", re.I)


class GeorgiaSpider(scrapy.Spider):
    name = "georgia"
    state = "GA"
    state_name = "Georgia"
    allowed_domains = ["rules.sos.ga.gov"]

    custom_settings = {
        "DOWNLOAD_DELAY": 1.0,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 3,
        "ROBOTSTXT_OBEY": False,
        "HTTPCACHE_ENABLED": False,
    }

    def __init__(self, *args, departments: str | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._departments_filter = {
            d.strip() for d in (departments or "").split(",") if d.strip()
        }

    def start_requests(self):
        cfg = load_config("sources.yaml")
        state_cfg = (cfg.get("states") or {}).get(self.state, {})
        urls = state_cfg.get("entrypoints") or _DEFAULT_START_URLS

        for url in urls:
            dept_id = _department_from_url(url)
            if dept_id not in _DEPARTMENTS:
                continue
            if self._departments_filter and dept_id not in self._departments_filter:
                continue
            yield scrapy.Request(
                url,
                callback=self.parse_department_page,
                meta={"department_id": dept_id},
                errback=self.errback,
            )

    # ── Level 1: Department page → chapter links ─────────────────────────────

    def parse_department_page(self, response: Response):
        department_id = response.meta.get("department_id", "")
        agency = _DEPARTMENTS.get(department_id)
        if not agency:
            return

        seen: set[str] = set()
        chapter_count = 0

        for a in response.css("a[href]"):
            href = (a.attrib.get("href") or "").strip()
            if not href:
                continue
            full_url = response.urljoin(href)
            m = _CHAPTER_RE.search(urlparse(full_url).path)
            if not m:
                continue
            if m.group(1) != department_id:
                continue
            if full_url in seen:
                continue
            seen.add(full_url)

            chapter_num = f"{department_id}-{m.group(2)}"
            link_text = _clean_text(" ".join(a.css("::text").getall()))
            chapter_name = _strip_chapter_prefix(link_text) or chapter_num
            chapter_count += 1

            yield scrapy.Request(
                full_url,
                callback=self.parse_chapter_page,
                meta={
                    "department_id": department_id,
                    "agency": agency,
                    "chapter_num": chapter_num,
                    "chapter_name": chapter_name,
                    "source_url": response.url,
                },
                errback=self.errback,
            )

        self.logger.info(
            "[GA] Department %s (%s): %d chapter link(s)",
            department_id,
            agency["agency_name"],
            chapter_count,
        )

    # ── Level 2: Chapter page → split into rule items ────────────────────────

    def parse_chapter_page(self, response: Response):
        department_id = response.meta.get("department_id", "")
        agency = response.meta.get("agency") or _DEPARTMENTS.get(department_id, {})
        source_url = response.meta.get("source_url", "")

        chapter_heading = _clean_text(" ".join(response.css("h1::text").getall()))
        chapter_num = response.meta.get("chapter_num", "")
        chapter_name = response.meta.get("chapter_name", "")

        m = _CHAPTER_HEADING_RE.match(chapter_heading)
        if m:
            chapter_num = m.group(1).strip() or chapter_num
            chapter_name = (m.group(2) or "").strip() or chapter_name

        rules = _extract_rules_from_chapter(response)
        self.logger.info(
            "[GA] Chapter %s (%s): %d rule(s)",
            chapter_num,
            chapter_name,
            len(rules),
        )

        for rule in rules:
            rule_id = rule["rule_id"]
            rule_name = rule["rule_name"]
            rule_text = rule["rule_text"]
            if not rule_text:
                rule_text = rule_name or "(repealed or no text extracted)"

            doc_lines = [
                f"STATE: Georgia (GA)",
                f"AGENCY: {agency.get('agency_name', '')}",
                f"AGENCY (SITE TITLE): {agency.get('site_name', '')}",
                f"DEPARTMENT: {department_id}",
                f"CHAPTER: {chapter_num} — {chapter_name}",
                f"RULE: {rule_id} — {rule_name}",
                f"SOURCE: {response.url}",
                "",
                rule_text,
            ]
            doc_text = re.sub(r"\n{3,}", "\n\n", "\n".join(doc_lines)).strip()

            citation = (
                f"Georgia | {agency.get('agency_name', '')} | "
                f"Department {department_id}, Chapter {chapter_num} | {rule_id}"
            )
            safe_rule_id = re.sub(r"[^\w\-]", "_", rule_id).strip("_")
            filename = (
                f"GA_{agency.get('agency_type', 'unknown')}"
                f"_dept{department_id}_ch{chapter_num.replace('-', '_')}_{safe_rule_id}.txt"
            )

            body = doc_text.encode("utf-8")
            yield self._make_item(
                state=self.state,
                state_name=self.state_name,
                agency=agency.get("agency_name", ""),
                agency_name=agency.get("agency_name", ""),
                agency_type=agency.get("agency_type", "unknown"),
                agency_id=department_id,
                source_url=source_url,
                doc_url=response.url,
                filename=filename,
                doc_type="rule",
                rule_status="rule",
                title=f"{rule_id} — {rule_name}",
                citation=citation,
                extracted_text=doc_text,
                fetched_at=datetime.now(UTC).isoformat(),
                hash_md5=hashlib.md5(body).hexdigest(),
                size_bytes=len(body),
                content_type="text/plain; charset=utf-8",
                _body=body,
            )

    def errback(self, failure):
        self.logger.error("[GA] Request failed: %s — %s", failure.request.url, failure.value)

    def _make_item(self, **kwargs):
        item = RegDocItem()
        fields = getattr(item, "fields", {})
        for key, value in kwargs.items():
            if key in fields:
                item[key] = value
        return item


# ── Helpers ──────────────────────────────────────────────────────────────────

def _department_from_url(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    tail = path.split("/")[-1]
    return tail if tail in _DEPARTMENTS else ""


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _strip_chapter_prefix(text: str) -> str:
    text = _clean_text(text)
    m = re.match(r"^Chapter\s+(?:150|360|520)-\d+\.?\s*(.*)$", text, re.I)
    return (m.group(1) or "").strip(" .") if m else text


def _element_text(el) -> str:
    return _clean_text(" ".join(el.xpath(".//text()")))


def _is_rule_heading(el) -> bool:
    try:
        tag = (el.tag or "").lower()
    except Exception:
        return False
    if tag not in {"h2", "h3"}:
        return False
    text = _element_text(el)
    return bool(_RULE_HEADING_RE.match(text))


def _is_toc_or_footer(el) -> bool:
    text = _element_text(el)
    if not text:
        return False
    low = text.lower()
    if "copyright" in low or "fastcase" in low or "all rights reserved" in low:
        return True
    try:
        tag = (el.tag or "").lower()
    except Exception:
        tag = ""
    if tag in {"ul", "ol", "nav"}:
        items = [_clean_text(" ".join(t.xpath(".//text()"))) for t in el.xpath("./li")]
        items = [i for i in items if i]
        if items and all(i.lower().startswith("rule ") for i in items):
            return True
    # Some pages repeat a short rule-only list at the end without a semantic list tag.
    if low.startswith("rule ") and len(text) < 120:
        return True
    return False


def _extract_rules_from_chapter(response: Response) -> list[dict]:
    root = response.selector.root
    headings = root.xpath("//h2[starts-with(normalize-space(string(.)), 'Rule ')]")
    rules: list[dict] = []

    for h2 in headings:
        heading_text = _clean_text(" ".join(h2.xpath(".//text()")))
        m = _RULE_HEADING_RE.match(heading_text)
        if not m:
            continue
        rule_id = m.group(1).strip()
        rule_name = (m.group(2) or "").strip() or rule_id

        parts: list[str] = []
        sib = h2.getnext()
        while sib is not None:
            if _is_rule_heading(sib):
                break
            if _is_toc_or_footer(sib):
                break
            text = _element_text(sib)
            if text:
                parts.append(text)
            sib = sib.getnext()

        rule_text = "\n".join(parts).strip()
        rules.append(
            {
                "rule_id": rule_id,
                "rule_name": rule_name,
                "rule_text": rule_text,
            }
        )

    return rules
