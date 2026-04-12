from __future__ import annotations

"""
Alabama Administrative Code Spider
=====================================
Source  : https://admincode.legislature.state.al.us/administrative-code
Publisher: Alabama Legislative Services Agency (LSA)

Targets 3 agencies (from sources.yaml):
  /270  →  Board of Dental Examiners of Alabama       (dental)
  /545  →  Medical Licensure Commission of Alabama    (medical-licensure)
  /790  →  Alabama Real Estate Commission             (real-estate)

HOW THE SITE WORKS
────────────────────
admincode.legislature.state.al.us is a React SPA. Playwright is required.

wait_until MUST be "domcontentloaded" — never "networkidle" on React SPAs.
React apps with analytics / polling never reach networkidle and Playwright
hangs indefinitely. Use domcontentloaded then wait_for_selector explicitly.

URL patterns (stable and predictable):
  Agency  : /administrative-code/{id}                   e.g. /270
  Chapter : /administrative-code/{id}-X-{N}             e.g. /270-X-1
  Rule    : /administrative-code/{id}-X-{N}-.{NN}       e.g. /270-X-1-.01

Navigation:
  1. Load agency page → wait for chapter links (a[href*="-X-"])
  2. Load each chapter page → wait for rule links (a[href*="-X-"][href*="-."])
  3. Load each rule page → wait for h2 → scrape text + metadata

Each rule page has:
  - Rule text in HTML paragraphs
  - PDF button (href captured as pdf_url in citation)
  - Statutory Authority field
  - Author field
  - History / effective date field
"""

import hashlib
import re
from datetime import UTC, datetime

import scrapy
from scrapy.http import HtmlResponse

from sos_crawler.config import load_config
from sos_crawler.items import RegDocItem

_BASE = "https://admincode.legislature.state.al.us/administrative-code"
_WAIT_MS = 20_000  # ms to wait for React to render links

_AGENCIES: dict[str, dict] = {
    "270": {"agency_type": "dental",            "agency_name": "Board of Dental Examiners of Alabama"},
    "545": {"agency_type": "medical-licensure", "agency_name": "Medical Licensure Commission of Alabama"},
    "790": {"agency_type": "real-estate",       "agency_name": "Alabama Real Estate Commission"},
}

_DEFAULT_START_URLS = [
    f"{_BASE}/270",
    f"{_BASE}/545",
    f"{_BASE}/790",
]


class AlabamaSpider(scrapy.Spider):
    name = "alabama"
    state = "AL"
    state_name = "Alabama"
    allowed_domains = ["admincode.legislature.state.al.us"]

    custom_settings = {
        "DOWNLOAD_DELAY": 1.5,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "ROBOTSTXT_OBEY": False,
        "HTTPCACHE_ENABLED": False,
    }

    # ── Entry points ───────────────────────────────────────────────────────────

    def start_requests(self):
        cfg = load_config("sources.yaml")
        state_cfg = (cfg.get("states") or {}).get(self.state, {})
        urls = state_cfg.get("entrypoints") or _DEFAULT_START_URLS

        for url in urls:
            agency_id = url.rstrip("/").split("/")[-1]
            yield scrapy.Request(
                url,
                callback=self.parse_agency_page,
                meta={
                    "playwright": True,
                    "playwright_include_page": True,
                    # domcontentloaded — critical, networkidle hangs forever on React
                    "playwright_page_goto_kwargs": {"wait_until": "domcontentloaded"},
                    "agency_id": agency_id,
                },
                errback=self.errback_close_page,
            )

    # ── Level 1: Agency page → chapter links ──────────────────────────────────

    async def parse_agency_page(self, response):
        page      = response.meta.get("playwright_page")
        agency_id = response.meta.get("agency_id", "")
        try:
            # Wait for React to render chapter links: a[href*="{id}-X-"]
            try:
                await page.wait_for_selector(
                    f"a[href*='{agency_id}-X-']", timeout=_WAIT_MS
                )
            except Exception:
                hrefs = await page.eval_on_selector_all(
                    "a[href]",
                    "els => els.map(e => e.getAttribute('href')).slice(0, 20)",
                )
                self.logger.warning(
                    "[AL] Timeout waiting for chapter links on agency %s. "
                    "Sample hrefs: %s",
                    agency_id, hrefs,
                )
            content = await page.content()
        finally:
            await page.close()

        sel = HtmlResponse(url=response.url, body=content, encoding="utf-8")
        chapter_pat = re.compile(rf"/{re.escape(agency_id)}-X-\d+$", re.I)
        seen: set[str] = set()

        for a in sel.css("a[href]"):
            href = a.attrib.get("href", "")
            if not chapter_pat.search(href):
                continue
            full_url = sel.urljoin(href)
            if full_url in seen:
                continue
            seen.add(full_url)
            chapter_num  = href.rstrip("/").split("/")[-1]
            chapter_name = " ".join(a.css("::text").getall()).strip()
            yield scrapy.Request(
                full_url,
                callback=self.parse_chapter_page,
                meta={
                    "playwright": True,
                    "playwright_include_page": True,
                    "playwright_page_goto_kwargs": {"wait_until": "domcontentloaded"},
                    "agency_id":    agency_id,
                    "chapter_num":  chapter_num,
                    "chapter_name": chapter_name,
                    "source_url":   response.url,
                },
                errback=self.errback_close_page,
            )

        if not seen:
            self.logger.error(
                "[AL] Agency %s: zero chapter links after JS render. "
                "Confirm Playwright is installed: playwright install chromium",
                agency_id,
            )

    # ── Level 2: Chapter page → rule links ────────────────────────────────────

    async def parse_chapter_page(self, response):
        page         = response.meta.get("playwright_page")
        agency_id    = response.meta.get("agency_id", "")
        chapter_num  = response.meta.get("chapter_num", "")
        chapter_name = response.meta.get("chapter_name", "")
        try:
            rule_sel = f"a[href*='{agency_id}-X-'][href*='-.']"
            try:
                await page.wait_for_selector(rule_sel, timeout=_WAIT_MS)
            except Exception:
                self.logger.warning(
                    "[AL] Timeout waiting for rule links on chapter %s", chapter_num
                )
            content = await page.content()
        finally:
            await page.close()

        sel      = HtmlResponse(url=response.url, body=content, encoding="utf-8")
        rule_pat = re.compile(rf"/{re.escape(agency_id)}-X-\d+-\.\d+", re.I)
        seen: set[str] = set()

        for a in sel.css("a[href]"):
            href = a.attrib.get("href", "")
            if not rule_pat.search(href):
                continue
            full_url = sel.urljoin(href)
            if full_url in seen:
                continue
            seen.add(full_url)
            rule_id   = href.rstrip("/").split("/")[-1]
            rule_name = " ".join(a.css("::text").getall()).strip()
            yield scrapy.Request(
                full_url,
                callback=self.parse_rule_page,
                meta={
                    "playwright": True,
                    "playwright_include_page": True,
                    "playwright_page_goto_kwargs": {"wait_until": "domcontentloaded"},
                    "agency_id":    agency_id,
                    "chapter_num":  chapter_num,
                    "chapter_name": chapter_name,
                    "rule_id":      rule_id,
                    "rule_name":    rule_name,
                    "source_url":   response.url,
                },
                errback=self.errback_close_page,
            )

        self.logger.info("[AL] Chapter %s: %d rule links", chapter_num, len(seen))

    # ── Level 3: Rule detail page → scrape content ────────────────────────────

    async def parse_rule_page(self, response):
        page         = response.meta.get("playwright_page")
        agency_id    = response.meta.get("agency_id", "")
        chapter_num  = response.meta.get("chapter_num", "")
        chapter_name = response.meta.get("chapter_name", "")
        rule_id      = response.meta.get("rule_id", "")
        rule_name    = response.meta.get("rule_name", "")
        source_url   = response.meta.get("source_url", "")
        try:
            try:
                await page.wait_for_selector("h2", timeout=_WAIT_MS)
            except Exception:
                pass
            content = await page.content()
        finally:
            await page.close()

        sel = HtmlResponse(url=response.url, body=content, encoding="utf-8")

        # Parse heading to fill rule_id / rule_name if missing
        heading = " ".join(sel.css("h1::text, h2::text").getall()).strip()
        if not rule_id:
            m = re.search(r"Rule\s+([\w\-\.]+)", heading)
            rule_id = m.group(1) if m else ""
        if not rule_name:
            for sep in (" - ", " – ", "  "):
                if sep in heading:
                    rule_name = heading.split(sep, 1)[-1].strip().rstrip(".")
                    break
        if not chapter_num and rule_id:
            m = re.match(r"(.*)-\.\d+$", rule_id)
            if m:
                chapter_num = m.group(1)

        # PDF link
        pdf_url = ""
        for a in sel.css("a[href]"):
            txt  = " ".join(a.css("::text").getall()).strip().upper()
            href = a.attrib.get("href", "")
            if "PDF" in txt or href.lower().endswith(".pdf"):
                pdf_url = sel.urljoin(href)
                break

        # Rule body text
        rule_text = ""
        for container in [
            "div.rule-text", "div.rule-content", "div#rule-body",
            "article", "main", "div#content", "div.content",
        ]:
            parts = sel.css(
                f"{container} p::text, {container} td::text, {container} li::text"
            ).getall()
            text = "\n".join(t.strip() for t in parts if t.strip())
            if len(text) > 80:
                rule_text = text
                break
        if not rule_text:
            parts = [
                t.strip()
                for t in sel.css("p::text, td::text").getall()
                if len(t.strip()) > 20
            ]
            rule_text = "\n".join(parts)

        # Metadata fields
        full_text = " ".join(sel.css("*::text").getall())
        stat_auth = _find_field(full_text, "Statutory Authority")
        author    = _find_field(full_text, "Author")
        history   = _find_field(full_text, "History")
        eff_date  = _parse_effective_date(history)

        agency_info = _AGENCIES.get(agency_id, {})
        agency_name = agency_info.get("agency_name", f"Alabama Agency {agency_id}")
        agency_type = agency_info.get("agency_type", "unknown")

        doc_lines = [
            f"STATE: Alabama (AL)",
            f"AGENCY: {agency_name}",
            f"CHAPTER: {chapter_num} — {chapter_name}",
            f"RULE: {rule_id} — {rule_name}",
            f"SOURCE: {response.url}",
        ]
        if pdf_url:
            doc_lines.append(f"PDF: {pdf_url}")
        doc_lines += ["", rule_text or "(no text extracted)", ""]
        if stat_auth:
            doc_lines.append(f"STATUTORY AUTHORITY: {stat_auth}")
        if author:
            doc_lines.append(f"AUTHOR: {author}")
        if history:
            doc_lines.append(f"HISTORY: {history}")
        doc_text = "\n".join(doc_lines)

        citation = (
            f"Alabama | {agency_name} | "
            f"Chapter {chapter_num} | Rule {rule_id} | {rule_name}"
        )
        safe_id  = re.sub(r"[^\w]", "-", rule_id).strip("-")
        filename = f"AL_{agency_type}_{agency_id}_{safe_id}.txt"

        body = doc_text.encode("utf-8")
        yield RegDocItem(
            state               = self.state,
            state_name          = self.state_name,
            agency              = agency_name,
            agency_type         = agency_type,
            agency_id           = agency_id,
            source_url          = source_url,
            doc_url             = response.url,
            filename            = filename,
            doc_type            = "rule",
            rule_status         = "rule",
            title               = f"Rule {rule_id} — {rule_name}",
            effective_date      = eff_date,
            statutory_authority = stat_auth,
            citation            = citation,
            extracted_text      = doc_text,
            fetched_at          = datetime.now(UTC).isoformat(),
            hash_md5            = hashlib.md5(body).hexdigest(),
            size_bytes          = len(body),
            content_type        = "text/plain; charset=utf-8",
            _body               = body,
        )

    async def errback_close_page(self, failure):
        page = failure.request.meta.get("playwright_page")
        if page:
            try:
                await page.close()
            except Exception:
                pass
        self.logger.error(
            "[AL] Request failed: %s — %s", failure.request.url, failure.value
        )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _find_field(full_text: str, label: str) -> str:
    m = re.search(rf"{re.escape(label)}\s*:?\s*([^\n]{{1,400}})", full_text, re.I)
    return m.group(1).strip() if m else ""


def _parse_effective_date(history: str) -> str:
    if not history:
        return ""
    m = re.search(r"effective\s+(\w+ \d{1,2},\s*\d{4})", history, re.I)
    if not m:
        return ""
    try:
        return datetime.strptime(m.group(1).strip(), "%B %d, %Y").strftime("%Y-%m-%d")
    except ValueError:
        return m.group(1).strip()
