from __future__ import annotations

"""
Mississippi Secretary of State — Administrative Rules Spider
SoS URL  : https://www.sos.ms.gov/regulation-enforcement/administrative-code
Code URL : https://www.sos.ms.gov/adminsearch/default.aspx
Bulletin : https://www.sos.ms.gov/ACPublic/Default.aspx
Coverage  : ~150 state agencies; updated within 2 business days of rule changes

Discovery uses Playwright to read the agency dropdown inside the adminsearch iframe, then
calls the same CodeSearch JSON endpoint the UI uses. Session cookies from the portal are
required for non-empty results (see AdminSearchService CodeSearch).

The published AdminSearchService.asmx/js contract exposes no paging parameters for
CodeSearch; each call returns the full matching row set for that agency in one payload.
"""

import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime

import scrapy

from sos_crawler.config import load_config
from sos_crawler.items import RegDocItem


class MississippiSpider(scrapy.Spider):
    name = "mississippi"
    state = "MS"
    state_name = "Mississippi"
    allowed_domains = ["sos.ms.gov"]
    agency_selectors = ["select#cAgencySearch", "select[name='cAgencySearch']"]
    code_search_endpoint = "https://www.sos.ms.gov/adminsearch/AdminSearchService.asmx/CodeSearch"
    session_referer = "https://www.sos.ms.gov/adminsearch/default.aspx"

    start_urls = [
        "https://www.sos.ms.gov/regulation-enforcement/administrative-code",
    ]
    seen_doc_urls = set()

    custom_settings = {
        "DOWNLOAD_TIMEOUT": 120,
        "RETRY_TIMES": 3,
        "RETRY_HTTP_CODES": [500, 502, 503, 504, 408, 429],
        "CONCURRENT_REQUESTS_PER_DOMAIN": 4,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._codesearch_max_retries = int(os.getenv("MS_CODESEARCH_RETRIES", "4"))

    @staticmethod
    def _agency_option_ok(opt: dict) -> bool:
        label = (opt.get("label") or "").strip().lower()
        value = (opt.get("value") or "").strip()
        if not value or not label:
            return False
        if value in {"0", "00"}:
            return False
        if "select" in label and "agency" in label:
            return False
        if label in {"choose", "all", "none"}:
            return False
        return True

    def start_requests(self):
        cfg = load_config("sources.yaml")
        state_cfg = (cfg.get("states", {}) or {}).get(self.state, {})
        urls = state_cfg.get("entrypoints") or self.start_urls
        for url in urls:
            if "administrative-code" not in url:
                continue
            yield scrapy.Request(
                url,
                callback=self.parse,
                meta={
                    "playwright": True,
                    "playwright_include_page": True,
                    "playwright_page_goto_kwargs": {"wait_until": "domcontentloaded"},
                    "dont_cache": True,
                },
                errback=self.errback_close_page,
            )

    async def parse(self, response):
        page = response.meta.get("playwright_page")
        if page is None:
            self.logger.warning("Playwright page missing for Mississippi bootstrap request")
            return
        try:
            await page.wait_for_load_state("domcontentloaded")
            try:
                await page.wait_for_selector(
                    "iframe[src*='adminsearch'], iframe[src*='AdminSearch']",
                    timeout=90_000,
                )
            except Exception:
                self.logger.warning("adminsearch iframe selector not found (continuing)")
            frame = await self._find_admin_frame(page)
            if frame is None:
                self.logger.warning("No adminsearch iframe found on Mississippi page")
                return

            agency_selector = await self._first_visible_selector(frame, self.agency_selectors)
            if not agency_selector:
                self.logger.warning("No agency dropdown found on Mississippi page")
                return

            options = await frame.eval_on_selector_all(
                f"{agency_selector} option",
                "els => els.map(e => ({value: e.value || '', label: (e.textContent || '').trim()}))",
            )
            agencies = [opt for opt in options if self._agency_option_ok(opt)]

            cookie_dict = {}
            for c in await page.context.cookies():
                dom = (c.get("domain") or "").lower()
                if "sos.ms" in dom:
                    cookie_dict[c["name"]] = c["value"]

            if not cookie_dict:
                self.logger.warning("No sos.ms.gov cookies from Playwright; CodeSearch may return empty rows")

            for agency in agencies:
                agency_name = agency["label"].strip()
                agency_value = agency["value"].strip()
                payload = {
                    "tmpSubject": "",
                    "tmpAgency": f"{agency_value} ",
                    "tmpPartRange1": "",
                    "tmpPartRange2": "",
                    "tmpRuleSum": "",
                    "tmpOrder": "PartNo",
                    "tmpOrderDirec": "Ascending",
                    "tmpSearchDate1": "",
                    "tmpSearchDate2": "",
                    "tmpDateType": "0",
                }
                yield scrapy.Request(
                    url=self.code_search_endpoint,
                    method="POST",
                    body=json.dumps(payload),
                    cookies=cookie_dict,
                    headers={
                        "Content-Type": "application/json; charset=UTF-8",
                        "X-Requested-With": "XMLHttpRequest",
                        "Referer": self.session_referer,
                    },
                    callback=self.parse_codesearch_results,
                    errback=self.errback_codesearch,
                    meta={
                        "agency": agency_name,
                        "source_url": response.url,
                        "cookie_dict": cookie_dict,
                        "codesearch_retry": 0,
                        "dont_cache": True,
                        "download_timeout": 120,
                    },
                    dont_filter=True,
                )
        finally:
            await page.close()

    async def errback_close_page(self, failure):
        page = failure.request.meta.get("playwright_page")
        if page:
            await page.close()

    def errback_codesearch(self, failure):
        request = failure.request
        retries = request.meta.get("codesearch_retry", 0)
        if retries < self._codesearch_max_retries:
            self.logger.warning(
                "CodeSearch errback (attempt %s/%s) agency=%s: %s",
                retries + 1,
                self._codesearch_max_retries,
                request.meta.get("agency", ""),
                failure.value,
            )
            retry = request.copy()
            retry.meta["codesearch_retry"] = retries + 1
            retry.dont_filter = True
            yield retry
            return
        self.logger.error(
            "CodeSearch failed after %s retries for agency=%s: %s",
            self._codesearch_max_retries,
            request.meta.get("agency", ""),
            failure.value,
        )

    def parse_codesearch_results(self, response):
        agency = response.meta.get("agency", "")
        source_url = response.meta.get("source_url", response.url)
        if response.status != 200:
            self.logger.warning("CodeSearch HTTP %s for agency=%s", response.status, agency)
            return

        try:
            payload = json.loads(response.text)
        except json.JSONDecodeError:
            self.logger.warning("Invalid JSON for agency=%s", agency)
            return

        rows_blob = payload.get("d", "")
        if not rows_blob or rows_blob.strip() in {"|0", "|"}:
            return

        for row in rows_blob.split("^"):
            parts = row.split("~")
            if len(parts) < 8:
                continue
            agency_name = parts[0].strip() or agency
            part_no = parts[1].strip()
            last_amended = parts[2].strip()
            title = "~".join(parts[4:-3]).strip() if len(parts) > 8 else parts[4].strip()
            pdf_file = parts[-1].strip().split("|", 1)[0].strip()
            if not pdf_file:
                continue

            doc_url = response.urljoin(f"/adminsearch/ACCode/{pdf_file}")
            if doc_url in self.seen_doc_urls:
                continue
            self.seen_doc_urls.add(doc_url)
            composed_title = f"Part {part_no} - {title}" if part_no and title else title or agency_name
            yield scrapy.Request(
                doc_url,
                callback=self.handle_document,
                meta={
                    "agency": agency_name,
                    "title": composed_title,
                    "source_url": source_url,
                    "doc_type": self._classify(doc_url, composed_title),
                    "effective_date": last_amended,
                },
            )

    async def _first_visible_selector(self, page_or_frame, selectors):
        for selector in selectors:
            try:
                await page_or_frame.wait_for_selector(selector, timeout=15_000)
                count = await page_or_frame.locator(selector).count()
                if count > 0:
                    return selector
            except Exception:
                continue
        return None

    async def _find_admin_frame(self, page):
        for _ in range(60):
            for frame in page.frames:
                if "adminsearch/default.aspx" in frame.url.lower():
                    return frame
            await asyncio.sleep(0.5)
        return None

    def handle_document(self, response):
        ct = response.headers.get("Content-Type", b"").decode().lower()
        if "html" in ct and not any(response.url.lower().endswith(ext) for ext in (".pdf", ".doc", ".docx")):
            return
        body = response.body
        doc_type = response.meta.get("doc_type", "unknown")
        yield RegDocItem(
            state=self.state,
            state_name=self.state_name,
            agency=response.meta.get("agency", ""),
            source_url=response.meta["source_url"],
            doc_url=response.url,
            filename=response.url.split("/")[-1],
            doc_type=doc_type,
            rule_status=doc_type,
            effective_date=response.meta.get("effective_date", ""),
            title=response.meta.get("title", ""),
            fetched_at=datetime.now(UTC).isoformat(),
            hash_md5=hashlib.md5(body).hexdigest(),
            size_bytes=len(body),
            content_type=response.headers.get("Content-Type", b"").decode(),
            _body=body,
        )

    def _classify(self, href, label):
        href_l, label_l = href.lower(), label.lower()
        if "proposed" in href_l or "proposed" in label_l:
            return "proposed"
        if "emergency" in href_l or "emergency" in label_l:
            return "emergency"
        if "adopted" in href_l or "final" in label_l:
            return "final"
        return "code"

