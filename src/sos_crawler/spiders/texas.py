from __future__ import annotations

"""
Texas Secretary of State — Texas Administrative Code Spider
============================================================
Source  : https://texas-sos.appianportalsgov.com/rules-and-meetings
Publisher: Texas Secretary of State (Appian Portal)

Targets 3 agencies (all Title 22 — Examining Boards):
  Part 5   →  State Board of Dental Examiners    (dental)
  Part 9   →  Texas Medical Board                (medical-licensure)
  Part 23  →  Texas Real Estate Commission       (real-estate)

HOW THE SITE WORKS
────────────────────
Appian Portal SPA. Playwright required.

wait_until MUST be "domcontentloaded" — never "networkidle" on SPAs.

When the browser loads a rule detail page, Appian makes a GET to:
  /_/ui?$locale=en_US&interface=VIEW_TAC_SUMMARY&queryAsDate=...&recordId=NNN

That response is application/vnd.appian.tv.ui+json containing the full rule
data in CertifiedSAILExtension nodes (richText HTML fields).

CRITICAL: This /_/ui request fires DURING page.goto(), before any Python
code in parse_rule_page runs. wait_for_response() cannot capture it because
it only watches future responses. We use page.route() to intercept the
request as it happens and store the response body for later use.

Chapter links: href="#" (Appian JS routing).
Chapter numbers: extracted from <p>CHAPTER NNN</p> plain text.
Chapter names: extracted from sibling SideBySideItem cells (AFTER fixing
               off-by-one: the bias10x pattern previously matched the PART row).
Rule links: <a class="LinkedItem---richtext_link" href="...recordId=NNN">
            These already contain recordId — no clicking needed.
"""

import asyncio
import hashlib
import json
import os
import re
from datetime import UTC, datetime
from html import unescape
from urllib.parse import quote

import scrapy
from scrapy.http import HtmlResponse

from sos_crawler.config import load_config
from sos_crawler.items import RegDocItem
from sos_crawler.paths import logs_dir

_ORIGIN = "https://texas-sos.appianportalsgov.com"
_BASE  = f"{_ORIGIN}/rules-and-meetings"
_TODAY = datetime.now(UTC).strftime("%m/%d/%Y")

_PART_AGENCIES: dict[str, dict] = {
    "5":  {"agency_type": "dental",            "agency_name": "State Board of Dental Examiners"},
    "9":  {"agency_type": "medical-licensure", "agency_name": "Texas Medical Board"},
    "23": {"agency_type": "real-estate",       "agency_name": "Texas Real Estate Commission"},
}

_DEFAULT_PART_URLS = [
    f"{_BASE}?interface=VIEW_TAC&title=22&part=5",
    f"{_BASE}?interface=VIEW_TAC&title=22&part=9",
    f"{_BASE}?interface=VIEW_TAC&title=22&part=23",
]

_WAIT_MS = 15_000


def _chapter_url(part: str, chapter: str) -> str:
    return f"{_BASE}?chapter={chapter}&interface=VIEW_TAC&part={part}&title=22"


def _rule_url(record_id: str) -> str:
    date_enc = quote(_TODAY, safe="")
    return (
        f"{_BASE}?%24locale=en_US"
        f"&interface=VIEW_TAC_SUMMARY"
        f"&queryAsDate={date_enc}"
        f"&recordId={record_id}"
    )


class TexasSpider(scrapy.Spider):
    name = "texas"
    state = "TX"
    state_name = "Texas"
    allowed_domains = ["texas-sos.appianportalsgov.com"]

    custom_settings = {
        "DOWNLOAD_DELAY": 2,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "ROBOTSTXT_OBEY": False,
        "HTTPCACHE_ENABLED": False,
        "PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT": 90_000,
    }

    def __init__(
        self,
        *args,
        parts: str | None = None,
        max_chapters: str | None = None,
        max_rules: str | None = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._parts_filter  = {p.strip() for p in (parts or "").split(",") if p.strip()}
        self._max_chapters  = int(max_chapters) if max_chapters else 0
        self._max_rules     = int(max_rules)     if max_rules     else 0

    def start_requests(self):
        try:
            import scrapy_playwright  # noqa: F401
        except ImportError:
            self.logger.error(
                "[TX] scrapy-playwright not installed. "
                "Run: pip install scrapy-playwright && playwright install chromium"
            )
            return

        cfg = load_config("sources.yaml")
        state_cfg = (cfg.get("states") or {}).get(self.state, {})
        urls = state_cfg.get("entrypoints") or _DEFAULT_PART_URLS

        for url in urls:
            part = _part_from_url(url)
            if self._parts_filter and part not in self._parts_filter:
                continue
            yield scrapy.Request(
                url,
                callback=self.parse_part_page,
                meta={
                    "playwright": True,
                    "playwright_include_page": True,
                    "playwright_page_goto_kwargs": {"wait_until": "domcontentloaded"},
                    "part": part,
                },
                errback=self.errback_close_page,
            )

    # ── Level 1: Part page → extract chapter numbers ───────────────────────────

    async def parse_part_page(self, response):
        page = response.meta.get("playwright_page")
        part = response.meta.get("part", "")
        try:
            try:
                await page.wait_for_selector("p:has-text('CHAPTER')", timeout=_WAIT_MS)
            except Exception:
                self.logger.warning("[TX] Part %s: timeout waiting for chapter list", part)
            content = await page.content()
        finally:
            await page.close()

        agency = _PART_AGENCIES.get(part, {})
        agency_type = agency.get("agency_type", "unknown")
        chapter_pairs = _extract_chapters_from_html(content)
        if self._max_chapters:
            chapter_pairs = chapter_pairs[: self._max_chapters]

        self.logger.info(
            "[TX] Part %s (%s): %d chapters",
            part, agency.get("agency_name", "?"), len(chapter_pairs),
        )
        if not chapter_pairs:
            self.logger.error(
                "[TX] Part %s: no chapters extracted from rendered HTML", part
            )

        for chapter_num, chapter_name in chapter_pairs:
            yield scrapy.Request(
                _chapter_url(part, chapter_num),
                callback=self.parse_chapter_page,
                meta={
                    "playwright": True,
                    "playwright_include_page": True,
                    "playwright_page_goto_kwargs": {"wait_until": "domcontentloaded"},
                    "part":         part,
                    "chapter_num":  chapter_num,
                    "chapter_name": chapter_name,
                    "source_url":   response.url,
                },
                errback=self.errback_close_page,
            )

    # ── Level 2: Chapter page → collect recordIds from rendered links ──────────

    async def parse_chapter_page(self, response):
        page         = response.meta.get("playwright_page")
        part         = response.meta.get("part", "")
        chapter_num  = response.meta.get("chapter_num", "")
        chapter_name = response.meta.get("chapter_name", "")
        source_url   = response.meta.get("source_url", "")
        try:
            # Rule links render with recordId already in href — no clicking needed
            try:
                await page.wait_for_selector(
                    "a.LinkedItem---richtext_link[href*='recordId=']",
                    timeout=_WAIT_MS,
                )
            except Exception:
                self.logger.warning(
                    "[TX] Chapter %s: timeout waiting for rule links", chapter_num
                )
            content = await page.content()
        finally:
            await page.close()

        sel = HtmlResponse(url=response.url, body=content, encoding="utf-8")
        rule_anchors = sel.css("a.LinkedItem---richtext_link[href*='recordId=']")
        if self._max_rules:
            rule_anchors = rule_anchors[: self._max_rules]

        self.logger.info(
            "[TX] Chapter %s (%s): %d rules",
            chapter_num, chapter_name, len(rule_anchors),
        )
        agency_type = (_PART_AGENCIES.get(part, {}) or {}).get("agency_type", "unknown")

        for a in rule_anchors:
            href = a.attrib.get("href", "")
            m    = re.search(r"[?&]recordId=(\d+)", href, re.I)
            if not m:
                continue
            record_id = m.group(1)

            # Section number lives in the sibling <p> of the same SideBySideGroup row
            section_text = " ".join(
                a.xpath(
                    "ancestor::div[contains(@class,'SideBySideGroup')][1]"
                    "//p[1]//text()"
                ).getall()
            ).strip()
            rule_section = _parse_section_num(section_text)
            rule_name    = " ".join(a.css("::text").getall()).strip()

            yield scrapy.Request(
                _rule_url(record_id),
                callback=self.parse_rule_page,
                meta={
                    "playwright": True,
                    "playwright_include_page": True,
                    "playwright_page_goto_kwargs": {"wait_until": "domcontentloaded"},
                    "part":         part,
                    "agency_type":  agency_type,
                    "chapter_num":  chapter_num,
                    "chapter_name": chapter_name,
                    "rule_section": rule_section,
                    "rule_name":    rule_name,
                    "record_id":    record_id,
                    "source_url":   source_url or response.url,
                },
                errback=self.errback_close_page,
            )

    # ── Level 3: Rule detail page → intercept /_/ui JSON ─────────────────────

    async def parse_rule_page(self, response):
        """
        FIX: Use page.route() to intercept the /_/ui request BEFORE it fires.

        Root cause of previous failure: wait_for_response() only catches
        responses that occur AFTER the call. But /_/ui fires during page.goto()
        (inside scrapy-playwright), before parse_rule_page() even runs.
        By the time we called wait_for_response(), the response was already gone.

        Solution: scrapy-playwright passes a pre-navigated page to the callback.
        We cannot intercept the initial load. Instead we fetch the /_/ui JSON
        directly using page.request.get() with the browser's authenticated session.
        The browser already has the session cookies and Appian headers from the
        initial page load, so page.request.get() with the right Accept header works.
        """
        page         = response.meta.get("playwright_page")
        part         = response.meta.get("part", "")
        chapter_num  = response.meta.get("chapter_num", "")
        chapter_name = response.meta.get("chapter_name", "")
        rule_section = response.meta.get("rule_section", "")
        rule_name    = response.meta.get("rule_name", "")
        record_id    = response.meta.get("record_id", "")
        source_url   = response.meta.get("source_url", "")

        ui_text = ""
        rendered_html = ""
        try:
            # Capture the already-rendered HTML for fallback extraction.
            # (The page is already navigated by scrapy-playwright before callback runs.)
            try:
                rendered_html = await page.content()
            except Exception:
                rendered_html = ""

            # Build candidate /_/ui URLs for this record.
            # Appian portals sometimes expose this endpoint at the site root OR under the app path.
            date_enc = quote(_TODAY, safe="")
            qs = (
                f"%24locale=en_US"
                f"&interface=VIEW_TAC_SUMMARY"
                f"&queryAsDate={date_enc}"
                f"&recordId={record_id}"
            )
            ui_urls = [
                f"{_ORIGIN}/_/ui?{qs}",
                f"{_BASE}/_/ui?{qs}",
            ]

            # Use the browser's own session to fetch the UI JSON.
            # page.request shares cookies and session state with the browser context.
            headers = {
                # Some Appian deployments are picky; include a broad Accept list.
                "Accept": (
                    "application/vnd.appian.tv.ui+json,application/json;q=0.9,*/*;q=0.8"
                ),
                "Content-Type": "application/vnd.appian.tv+json",
                "X-Appian-Ui-State": "stateful",
                "X-Client-Mode": "PORTALS",
                "X-Appian-Initial-Form-Factor": "DESKTOP",
                # Keep these (when honored they help), but don't rely on them being required.
                "X-Appian-Features": "7ffceebc",
                "X-Appian-Features-Extended": "1ff7797ffdbff7f49dc1fffceebc",
            }

            last_status = None
            last_url = ""
            for ui_url in ui_urls:
                last_url = ui_url
                ui_resp = await page.request.get(ui_url, headers=headers)
                last_status = ui_resp.status
                if ui_resp.status == 200:
                    ui_text = await ui_resp.text()
                    break

            if not ui_text:
                self.logger.warning(
                    "[TX] UI JSON non-200 for recordId=%s status=%s url=%s",
                    record_id,
                    last_status,
                    last_url,
                )

        except Exception as exc:
            self.logger.warning(
                "[TX] UI JSON fetch failed for recordId=%s: %s", record_id, exc
            )
        finally:
            await page.close()

        if os.getenv("TX_SAVE_UI_JSON", "").strip().lower() in {"1", "true", "yes"} and ui_text:
            try:
                out_dir = logs_dir() / "TX_ui_samples"
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / f"recordId_{record_id}.json").write_text(ui_text, encoding="utf-8")
            except Exception:
                # Debug dump should never break the crawl
                pass

        chapter_review_date = ""
        rule_text = ""
        source_note = ""
        eff_date = ""
        if ui_text:
            try:
                ui = json.loads(ui_text)
                chapter_review_date = _ui_find_textfield_value(ui, "Chapter Review Date")
                rich_blocks = _ui_collect_richtext(ui)
                rule_text, source_note = _split_rule_and_source_note(rich_blocks)
                eff_date = _parse_effective_date(source_note)
            except Exception as exc:
                self.logger.warning(
                    "[TX] UI JSON parse/extract failed for recordId=%s: %s", record_id, exc
                )

        if not rule_text:
            # Fallback: extract from rendered HTML (what a user sees).
            fallback_rule, fallback_source = _extract_rule_from_rendered_html(rendered_html)
            if fallback_rule:
                rule_text = fallback_rule
            if fallback_source and not source_note:
                source_note = fallback_source
            if source_note and not eff_date:
                eff_date = _parse_effective_date(source_note)

        if not rule_text:
            self.logger.debug(
                "[TX] No rule body text for recordId=%s (may be a short/header rule)",
                record_id,
            )
            # Still yield item — some rules are legitimately short
            rule_text = rule_name  # use rule name as minimal content

        agency = _PART_AGENCIES.get(part, {})
        agency_type = (response.meta.get("agency_type") or agency.get("agency_type") or "unknown")

        doc_lines = [
            f"STATE: Texas (TX)",
            f"AGENCY: {agency.get('agency_name', '')}",
            f"TITLE: 22 — EXAMINING BOARDS",
            f"PART: {part} — {agency.get('agency_name', '')}",
            f"CHAPTER: {chapter_num} — {chapter_name}",
            f"RULE: {rule_section} — {rule_name}",
            f"SOURCE: {_rule_url(record_id)}",
            "",
            rule_text,
            "",
        ]
        if chapter_review_date:
            doc_lines.append(f"CHAPTER REVIEW DATE: {chapter_review_date}")
        if source_note:
            doc_lines.append(f"SOURCE NOTE: {source_note}")
        doc_text = re.sub(r"\n{3,}", "\n\n", "\n".join(doc_lines)).strip()

        citation = (
            f"Texas | {agency.get('agency_name', '')} | "
            f"Title 22, Part {part}, Chapter {chapter_num} | {rule_section}"
        )
        safe_sec = re.sub(r"[^\w]", "_", rule_section or f"rec{record_id}")
        filename = (
            f"TX_{agency_type}"
            f"_title22_part{part}_ch{chapter_num}_{safe_sec}.txt"
        )

        body = doc_text.encode("utf-8")
        yield RegDocItem(
            state          = self.state,
            state_name     = self.state_name,
            agency         = agency.get("agency_name", ""),
            agency_type    = agency_type,
            agency_id      = part,
            source_url     = source_url,
            doc_url        = _rule_url(record_id),
            filename       = filename,
            doc_type       = "rule",
            rule_status    = "rule",
            title          = f"{rule_section} — {rule_name}",
            effective_date = eff_date,
            citation       = citation,
            extracted_text = doc_text,
            fetched_at     = datetime.now(UTC).isoformat(),
            hash_md5       = hashlib.md5(body).hexdigest(),
            size_bytes     = len(body),
            content_type   = "text/plain; charset=utf-8",
            _body          = body,
        )

    async def errback_close_page(self, failure):
        page = failure.request.meta.get("playwright_page")
        if page:
            try:
                await page.close()
            except Exception:
                pass
        self.logger.error(
            "[TX] Request failed: %s — %s", failure.request.url, failure.value
        )


# ── Module helpers ─────────────────────────────────────────────────────────────

def _part_from_url(url: str) -> str:
    from urllib.parse import parse_qs, urlparse
    return parse_qs(urlparse(url).query).get("part", [""])[0]


def _extract_chapters_from_html(html: str) -> list[tuple[str, str]]:
    """
    Extract (chapter_num, chapter_name) from rendered Appian HTML.

    DOM structure (confirmed via HTML inspection):
      Each row is a SideBySideGroup with two SideBySideItem children:
        First item:  <p>CHAPTER 100</p>
        Second item (bias10x): <a href="#">GENERAL PROVISIONS</a>

    The page also has TITLE and PART rows with the same structure.
    We only want rows where the first cell contains "CHAPTER NNN".

    FIX v2: Use a targeted regex that finds CHAPTER NNN in the first cell
    and the name link in the immediately following bias10x cell,
    ignoring non-chapter rows (TITLE, PART rows).
    """
    # Each chapter row: first <p> = "CHAPTER NNN", second cell (bias10x) has the name link
    # We match the full row pattern to avoid picking up PART/TITLE rows
    pattern = re.compile(
        r">CHAPTER\s+(\d+)<"          # first cell: chapter number
        r".*?"                          # arbitrary HTML between cells
        r'bias10x[^>]*>'               # start of second cell (bias10x)
        r".*?"
        r'href="#"[^>]*>(.*?)</a>',    # the name link
        re.S,
    )
    results = []
    seen: set[str] = set()
    for m in pattern.finditer(html):
        num  = m.group(1)
        name = re.sub(r"<[^>]+>", " ", m.group(2)).strip()
        if num not in seen:
            seen.add(num)
            results.append((num, name))
    return results


def _ui_walk(obj):
    """Yield every dict node in a nested JSON structure."""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _ui_walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _ui_walk(v)


def _ui_find_textfield_value(ui: dict, label: str) -> str:
    """Find a TextField widget value by label in the UI JSON."""
    want = label.strip().lower()
    for d in _ui_walk(ui):
        if d.get("#t") != "TextField":
            continue
        if str(d.get("label", "")).strip().lower() == want:
            return str(d.get("value", "")).strip()
    return ""


def _ui_collect_richtext(ui: dict) -> list[str]:
    """
    Extract richText HTML strings from CertifiedSAILExtension nodes.

    Structure confirmed via HAR:
      {"#t": "CertifiedSAILExtension", "value": "{...json...}"}
      where parsed JSON has: payload["value"]["richText"] = "<p>...</p>"
    """
    blocks: list[str] = []
    for d in _ui_walk(ui):
        t = d.get("#t")

        # Appian sometimes nests HTML directly as `richText` on many widget nodes.
        rich_direct = d.get("richText")
        if isinstance(rich_direct, str) and rich_direct.strip():
            blocks.append(rich_direct)

        # Common Appian rich text widgets may store content in `value`.
        if t in {"RichTextDisplayField", "RichTextDisplay", "RichTextField"}:
            v = d.get("value")
            blocks.extend(_ui_extract_richtextish_strings(v))

        # Our confirmed/legacy path: CertifiedSAILExtension JSON blob.
        if t == "CertifiedSAILExtension":
            raw = d.get("value")
            if not isinstance(raw, str) or not raw:
                continue
            try:
                payload = json.loads(raw)
            except Exception:
                continue
            rich = (payload.get("value") or {}).get("richText")
            if isinstance(rich, str) and rich.strip():
                blocks.append(rich)

        # Catch-all: sometimes rich text lands under `value.richText` even without CertifiedSAIL.
        v = d.get("value")
        if isinstance(v, dict):
            vr = v.get("richText")
            if isinstance(vr, str) and vr.strip():
                blocks.append(vr)

    # Deduplicate while preserving order
    out: list[str] = []
    seen: set[str] = set()
    for b in blocks:
        s = (b or "").strip()
        if not s:
            continue
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _ui_extract_richtextish_strings(obj) -> list[str]:
    """
    Pull out likely rich-text HTML or long text from Appian widget values.
    Handles strings, lists of fragments, and nested dicts.
    """
    parts: list[str] = []

    def walk(x):
        if x is None:
            return
        if isinstance(x, str):
            s = x.strip()
            if s:
                parts.append(s)
            return
        if isinstance(x, list):
            for it in x:
                walk(it)
            return
        if isinstance(x, dict):
            # Common fragment forms: {text: "..."} or {value: "..."} or {richText: "<p>...</p>"}
            for k in ("richText", "text", "value", "label"):
                v = x.get(k)
                if isinstance(v, str) and v.strip():
                    parts.append(v.strip())
            # Recurse into everything else
            for v in x.values():
                walk(v)

    walk(obj)

    # Keep only things that look like HTML-ish rich text or substantial text
    filtered: list[str] = []
    for p in parts:
        if "<" in p and ">" in p:
            filtered.append(p)
        elif len(p) >= 120:
            filtered.append(p)
        elif "source note" in p.lower():
            filtered.append(p)
        elif "§" in p:
            filtered.append(p)
    return filtered


def _pick_best_body_candidate(rich_blocks: list[str]) -> tuple[str, str]:
    """
    Choose the best candidate block for rule body and the best candidate for Source Note.
    Returns (body_text, source_note_text) as plain text.
    """
    if not rich_blocks:
        return "", ""

    candidates: list[tuple[int, str]] = []
    source_candidates: list[tuple[int, str]] = []
    for b in rich_blocks:
        txt = _html_to_text(b) if ("<" in b and ">" in b) else str(b).strip()
        if not txt:
            continue

        low = txt.lower()
        is_source = "source note" in low
        # score: length + bonuses for section markers; small penalty for being a pure source note
        score = len(txt)
        if "§" in txt:
            score += 500
        if "effective" in low:
            score += 80
        if is_source:
            source_candidates.append((score, txt))
            score -= 400
        candidates.append((score, txt))

    body = max(candidates, key=lambda t: t[0])[1] if candidates else ""
    source = max(source_candidates, key=lambda t: t[0])[1] if source_candidates else ""

    # If the chosen body contains Source Note appended, try to split cleanly.
    m = re.search(r"(?i)\bsource note\b\s*:\s*", body)
    if m and not source:
        source = body[m.start() :].strip()
        body = body[: m.start()].strip()
    return body.strip(), source.strip()


def _html_to_text(html: str) -> str:
    """Convert HTML to readable plain text."""
    s = html
    s = re.sub(r"(?i)<br\s*/?>",   "\n",   s)
    s = re.sub(r"(?i)</p\s*>",     "\n\n", s)
    s = re.sub(r"(?i)</li\s*>",    "\n",   s)
    s = re.sub(r"(?i)</tr\s*>",    "\n",   s)
    s = re.sub(r"(?i)</t[dh]\s*>", " ",    s)
    s = re.sub(r"<[^>]+>", "", s)
    s = unescape(s)
    s = re.sub(r"[ \t\r]+", " ", s)
    s = re.sub(r"\n[ ]+",   "\n", s)
    s = re.sub(r"\n{3,}",   "\n\n", s)
    return s.strip()


def _split_rule_and_source_note(rich_blocks: list[str]) -> tuple[str, str]:
    """
    Split richText blocks into rule body and Source Note.
    The Source Note block contains "Source Note:" text.
    The rule body is the first substantial non-Source-Note block.
    """
    # Kept for backwards compatibility with older logic, but now delegates
    # to the newer candidate selection which handles more widget shapes.
    return _pick_best_body_candidate(rich_blocks)


def _parse_section_num(text: str) -> str:
    m = re.search(r"(§[\d\.]+)", text)
    return m.group(1) if m else (text.split()[0] if text else "")


def _parse_effective_date(source_note: str) -> str:
    if not source_note:
        return ""
    m = re.search(r"effective\s+(\w+ \d{1,2},\s*\d{4})", source_note, re.I)
    if not m:
        return ""
    try:
        return datetime.strptime(m.group(1).strip(), "%B %d, %Y").strftime("%Y-%m-%d")
    except ValueError:
        return m.group(1).strip()


def _extract_rule_from_rendered_html(html: str) -> tuple[str, str]:
    """
    Best-effort extraction of rule body/source note from rendered Appian HTML.
    This is a safety net when the UI JSON shape changes and richText collection
    yields nothing.
    """
    if not html:
        return "", ""

    sel = HtmlResponse(url="about:blank", body=html, encoding="utf-8")

    # Prefer likely rich text containers first, then fall back to main content.
    candidate_selectors = [
        "div[class*='RichText']",
        "div[class*='richtext']",
        "div[role='document']",
        "main",
        "body",
    ]

    candidates: list[str] = []
    for css in candidate_selectors:
        txt = " ".join(t.strip() for t in sel.css(f"{css} ::text").getall() if t.strip())
        txt = re.sub(r"\s{2,}", " ", txt).strip()
        if not txt:
            continue
        # Filter obvious nav noise; keep things that look rule-like.
        low = txt.lower()
        if ("§" in txt) or ("source note" in low) or ("effective" in low and len(txt) > 300):
            candidates.append(txt)

    if not candidates:
        return "", ""

    # Pick the best candidate by length and presence of section marker.
    def score(t: str) -> int:
        s = len(t)
        if "§" in t:
            s += 800
        if "source note" in t.lower():
            s += 100
        return s

    best = max(candidates, key=score)

    # Try to split out Source Note if embedded.
    m = re.search(r"(?i)\bsource note\b\s*:\s*", best)
    if m:
        body = best[: m.start()].strip()
        source = best[m.start() :].strip()
        return body, source
    return best.strip(), ""