from __future__ import annotations

"""
Tennessee Effective Rules Spider
================================
Source  : https://sos.tn.gov/publications/services/effective-rules-and-regulations-of-the-state-of-tennessee/
Publisher: Tennessee Secretary of State

Targets 3 agencies (effective-rules prefixes):
  0460  → Tennessee Board of Dentistry         (dental)
  0880  → Tennessee Board of Medical Examiners (medical-licensure)
  1260  → Tennessee Real Estate Commission     (real-estate)

HOW THE SITE WORKS
──────────────────
The Tennessee effective rules collection exposes chapter-level PDF files under
`publications.tnsosfiles.com/rules/{prefix}/...pdf`. This spider keeps only the
three targeted prefixes, downloads their chapter PDFs, extracts the text, and
splits each chapter into individual rules using headings such as:

  0460-01-.01 Definitions.
  0880-02-.03 Licensure Process...
  1260-02-.12 Advertising.

No Playwright is required.
"""

import hashlib
import re
from datetime import UTC, datetime
from urllib.parse import urljoin

import scrapy
from scrapy.http import Response

from sos_crawler.config import load_config
from sos_crawler.extractors import extract_pdf_text
from sos_crawler.items import RegDocItem

_EFFECTIVE_RULES_URL = (
    "https://sos.tn.gov/publications/services/"
    "effective-rules-and-regulations-of-the-state-of-tennessee/"
)

_TARGETS: dict[str, dict] = {
    "0460": {
        "agency_type": "dental",
        "agency_name": "Tennessee Board of Dentistry",
    },
    "0880": {
        "agency_type": "medical-licensure",
        "agency_name": "Tennessee Board of Medical Examiners",
    },
    "1260": {
        "agency_type": "real-estate",
        "agency_name": "Tennessee Real Estate Commission",
    },
}

_DEFAULT_START_URLS = [
    _EFFECTIVE_RULES_URL,
    "https://publications.tnsosfiles.com/rules/0460/",
    "https://publications.tnsosfiles.com/rules/0880/",
    "https://publications.tnsosfiles.com/rules/1260/",
]

_PDF_LINK_RE = re.compile(
    r"https?://[^\s\"']+/rules/(?P<prefix>0460|0880|1260)/"
    r"(?P<chapter>(?P=prefix)-\d{2})(?:\.(?P<stamp>\d{8}))?\.pdf$",
    re.I,
)
_RULE_HEADING_RE = re.compile(
    r"(?m)^(?P<id>\d{4}-\d{2}-\.\d{2,3})\s+(?P<title>[^\n]+?)\s*$"
)
_CHAPTER_NAME_RE_TEMPLATE = r"CHAPTER\s+{chapter}\s+(?P<name>.+?)\s+TABLE OF CONTENTS"

_HTML_FOLLOW_KEYWORDS = (
    "0460",
    "0880",
    "1260",
    "dentistry",
    "medical examiners",
    "real estate commission",
    "effective-rules",
    "publications/services",
    "/rules/",
)


class TennesseeSpider(scrapy.Spider):
    name = "tennessee"
    state = "TN"
    state_name = "Tennessee"
    allowed_domains = ["sos.tn.gov", "publications.tnsosfiles.com", "tnsosfiles.com"]

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
            yield scrapy.Request(url, callback=self.parse, errback=self.errback)

    def parse(self, response: Response):
        content_type = (response.headers.get("Content-Type") or b"").decode(
            "utf-8", errors="replace"
        ).lower()
        url = response.url

        if "pdf" in content_type or url.lower().endswith(".pdf"):
            if _pdf_match(url):
                yield from self.parse_pdf(response)
            return

        links_found = 0
        for href in response.css("a[href]::attr(href)").getall():
            href = (href or "").strip()
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue

            full_url = urljoin(response.url, href)
            pdf_match = _pdf_match(full_url)
            if pdf_match:
                links_found += 1
                yield scrapy.Request(
                    full_url,
                    callback=self.parse_pdf,
                    meta={"source_url": response.url},
                    errback=self.errback,
                )
                continue

            low = full_url.lower()
            if any(token in low for token in _HTML_FOLLOW_KEYWORDS):
                yield scrapy.Request(full_url, callback=self.parse, errback=self.errback)

        if links_found:
            self.logger.info("[TN] %s: queued %d targeted chapter PDFs", response.url, links_found)

    def parse_pdf(self, response: Response):
        match = _pdf_match(response.url)
        if not match:
            self.logger.debug("[TN] Skipping non-target PDF: %s", response.url)
            return

        prefix = match.group("prefix")
        chapter_num = match.group("chapter")
        stamp = match.group("stamp") or ""
        target = _TARGETS[prefix]
        source_url = response.meta.get("source_url", _EFFECTIVE_RULES_URL)

        extracted_text = extract_pdf_text(response.body) or ""
        extracted_text = _normalize_text(extracted_text)
        if not extracted_text:
            self.logger.warning("[TN] Empty PDF extraction for %s", response.url)
            return

        chapter_name = _extract_chapter_name(extracted_text, chapter_num)
        rules = _split_rules(extracted_text, chapter_num)
        if not rules:
            self.logger.warning("[TN] No rules parsed from %s", response.url)
            return

        effective_date = _stamp_to_date(stamp)
        yielded = 0
        for rule_id, rule_title, rule_body in rules:
            title = f"{rule_id} — {rule_title}".strip(" —")
            doc_lines = [
                f"STATE: Tennessee (TN)",
                f"AGENCY: {target['agency_name']}",
                f"CHAPTER: {chapter_num} — {chapter_name}",
                f"RULE: {rule_id} — {rule_title}",
                f"SOURCE: {response.url}",
                "",
                rule_body or rule_title,
            ]
            doc_text = re.sub(r"\n{3,}", "\n\n", "\n".join(doc_lines)).strip()

            citation = (
                f"Tennessee | {target['agency_name']} | "
                f"Chapter {chapter_num} | {rule_id}"
            )
            safe_rule = re.sub(r"[^\w\-]", "_", rule_id).strip("_") or "unknown"
            filename = f"TN_{target['agency_type']}_{chapter_num}_{safe_rule}.txt"
            body = doc_text.encode("utf-8")

            item_kwargs = dict(
                state=self.state,
                state_name=self.state_name,
                agency=target["agency_name"],
                agency_type=target["agency_type"],
                agency_id=prefix,
                source_url=source_url,
                doc_url=response.url,
                filename=filename,
                doc_type="rule",
                rule_status="rule",
                title=title,
                citation=citation,
                extracted_text=doc_text,
                fetched_at=datetime.now(UTC).isoformat(),
                hash_md5=hashlib.md5(body).hexdigest(),
                size_bytes=len(body),
                content_type="text/plain; charset=utf-8",
                _body=body,
            )
            if effective_date:
                item_kwargs["effective_date"] = effective_date

            yield RegDocItem(**item_kwargs)
            yielded += 1

        self.logger.info(
            "[TN] %s (%s): yielded %d rules from %s",
            target["agency_name"], chapter_num, yielded, response.url,
        )

    def errback(self, failure):
        self.logger.error("[TN] Request failed: %s — %s", failure.request.url, failure.value)


def _pdf_match(url: str):
    return _PDF_LINK_RE.search(url)


def _normalize_text(text: str) -> str:
    text = (text or "").replace("\r", "\n").replace("\x0c", "\n")
    text = re.sub(r"[\t\u00a0]+", " ", text)
    text = re.sub(r"\n[ ]+", "\n", text)
    text = re.sub(r"[ ]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_chapter_name(text: str, chapter_num: str) -> str:
    pattern = re.compile(
        _CHAPTER_NAME_RE_TEMPLATE.format(chapter=re.escape(chapter_num)),
        re.I | re.S,
    )
    m = pattern.search(re.sub(r"\s+", " ", text))
    if m:
        return _clean_heading(m.group("name"))

    m = re.search(
        rf"CHAPTER\s+{re.escape(chapter_num)}\s+(?P<name>[^\n]{{3,200}})",
        text,
        re.I,
    )
    if m:
        return _clean_heading(m.group("name"))
    return chapter_num


def _split_rules(text: str, chapter_num: str) -> list[tuple[str, str, str]]:
    matches = [m for m in _RULE_HEADING_RE.finditer(text) if m.group("id").startswith(chapter_num)]
    if not matches:
        return []

    # Skip table-of-contents matches when the first rule repeats later in the PDF.
    start_idx = 0
    first_id = matches[0].group("id")
    for idx in range(1, len(matches)):
        if matches[idx].group("id") == first_id:
            start_idx = idx
            break
    matches = matches[start_idx:]
    if not matches:
        return []

    rules: list[tuple[str, str, str]] = []
    for idx, match in enumerate(matches):
        next_start = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        rule_id = match.group("id").strip()
        rule_title = _clean_heading(match.group("title"))
        body = text[match.end():next_start].strip()
        body = _strip_toc_echo(body, chapter_num)
        body = _clean_rule_body(body)
        if not body:
            body = rule_title
        rules.append((rule_id, rule_title, body))
    return rules


def _strip_toc_echo(body: str, chapter_num: str) -> str:
    if not body:
        return ""
    # Some PDF extractions carry TOC remnants immediately before the real body.
    first_real = re.search(rf"(?m)^{re.escape(chapter_num)}-\.\d{{2,3}}\s+", body)
    if first_real:
        body = body[first_real.start():]
    return body.strip()


def _clean_heading(text: str) -> str:
    text = re.sub(r"\s+", " ", (text or "")).strip(" .-–—")
    return text


def _clean_rule_body(text: str) -> str:
    text = _normalize_text(text)
    # Remove obvious repeated chapter/page banner lines when present.
    lines = []
    for line in text.split("\n"):
        low = line.strip().lower()
        if not low:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        if low == "table of contents":
            continue
        if low.startswith("rules of the tennessee"):
            continue
        if low.startswith("chapter ") and re.search(r"\d{4}-\d{2}", low):
            continue
        lines.append(line.strip())
    text = "\n".join(lines).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def _stamp_to_date(stamp: str) -> str:
    if not stamp or len(stamp) != 8:
        return ""
    try:
        return datetime.strptime(stamp, "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError:
        return ""
