"""
Georgia Secretary of State — Administrative Rules Division Spider
Rules DB: https://rules.sos.ga.gov/gac/
Also captures explanatory law pages on georgia.gov when present.
"""
import hashlib
from datetime import UTC, datetime
from urllib.parse import urlparse

import scrapy

from sos_crawler.config import load_config
from sos_crawler.extractors import extract_html_text, extract_pdf_text
from sos_crawler.items import RegDocItem


class GeorgiaSpider(scrapy.Spider):
    name = "georgia"
    state = "GA"
    state_name = "Georgia"
    allowed_domains = ["sos.ga.gov", "rules.sos.ga.gov", "georgia.gov"]

    _default_start_urls = [
        "https://rules.sos.ga.gov/",
        "https://georgia.gov/life-law/",
    ]

    FOLLOW_KEYWORDS = (
        "gac",
        "chapter",
        "rule",
        "rules",
        "register",
        "law",
        "life-law",
        "article",
        "title",
    )
    
    custom_settings = {
        "DOWNLOAD_DELAY": 1.0,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
        "ROBOTSTXT_OBEY": False,
        "HTTPCACHE_ENABLED": False,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        cfg = load_config("sources.yaml")
        state_cfg = (cfg.get("states") or {}).get(self.state, {})
        
        self.start_urls = state_cfg.get("entrypoints") or self._default_start_urls

    def parse(self, response):
        html_item = self._build_html_item(response)
        if html_item:
            yield html_item

        for a in response.css("a[href]"):
            href = (a.attrib.get("href") or "").strip()
            label = " ".join(a.css("::text").getall()).strip()
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue

            href_lower = href.lower()
            if any(href_lower.endswith(ext) for ext in (".pdf", ".doc", ".docx")):
                yield response.follow(
                    href,
                    self.handle_document,
                    meta={
                        "title": label,
                        "source_url": response.url,
                        "doc_type": self._classify(href, label),
                    },
                )
            elif any(token in href_lower for token in self.FOLLOW_KEYWORDS):
                yield response.follow(href, self.parse)

    def handle_document(self, response):
        body = response.body
        content_type = (response.headers.get("Content-Type") or b"").decode("utf-8", errors="replace").lower()
        extracted_text = ""
        if "pdf" in content_type or response.url.lower().endswith(".pdf"):
            extracted_text = extract_pdf_text(body)

        doc_type = response.meta.get("doc_type", "code")
        yield RegDocItem(
            state=self.state,
            state_name=self.state_name,
            source_url=response.meta.get("source_url", ""),
            doc_url=response.url,
            filename=response.url.split("/")[-1] or "document",
            doc_type=doc_type,
            agency_type=doc_type,
            title=response.meta.get("title", ""),
            fetched_at=datetime.now(UTC).isoformat(),
            hash_md5=hashlib.md5(body).hexdigest(),
            size_bytes=len(body),
            content_type=content_type,
            http_status=response.status,
            extracted_text=extracted_text,
            response_headers_subset={
                "content-type": (response.headers.get("Content-Type") or b"").decode("utf-8", errors="replace"),
                "content-length": (response.headers.get("Content-Length") or b"").decode("utf-8", errors="replace"),
                "etag": (response.headers.get("ETag") or b"").decode("utf-8", errors="replace"),
                "last-modified": (response.headers.get("Last-Modified") or b"").decode("utf-8", errors="replace"),
                "cache-control": (response.headers.get("Cache-Control") or b"").decode("utf-8", errors="replace"),
                "content-disposition": (response.headers.get("Content-Disposition") or b"").decode("utf-8", errors="replace"),
            },
            _body=body,
        )

    def _build_html_item(self, response):
        content_type = (response.headers.get("Content-Type") or b"").decode("utf-8", errors="replace").lower()
        if "html" not in content_type:
            return None
        extracted_text = extract_html_text(response)
        if len(extracted_text) < 500:
            return None
        title = (response.css("title::text").get() or response.url).strip()
        url_path = urlparse(response.url).path.strip("/") or "index"
        filename = url_path.replace("/", "_") + ".html"
        body = response.body or extracted_text.encode("utf-8", errors="ignore")
        doc_type = self._classify(response.url, title)
        return RegDocItem(
            state=self.state,
            state_name=self.state_name,
            source_url=response.url,
            doc_url=response.url,
            filename=filename,
            doc_type=doc_type,
            agency_type=doc_type,
            title=title,
            fetched_at=datetime.now(UTC).isoformat(),
            hash_md5=hashlib.md5(extracted_text.encode("utf-8")).hexdigest(),
            size_bytes=len(body),
            content_type=content_type,
            http_status=response.status,
            extracted_text=extracted_text,
            response_headers_subset={
                "content-type": (response.headers.get("Content-Type") or b"").decode("utf-8", errors="replace"),
                "content-length": (response.headers.get("Content-Length") or b"").decode("utf-8", errors="replace"),
                "etag": (response.headers.get("ETag") or b"").decode("utf-8", errors="replace"),
                "last-modified": (response.headers.get("Last-Modified") or b"").decode("utf-8", errors="replace"),
                "cache-control": (response.headers.get("Cache-Control") or b"").decode("utf-8", errors="replace"),
                "content-disposition": (response.headers.get("Content-Disposition") or b"").decode("utf-8", errors="replace"),
            },
            _body=body,
        )

    def _classify(self, href, label):
        low = f"{href} {label}".lower()
        if "pending" in low or "proposed" in low:
            return "proposed"
        if "emergency" in low:
            return "emergency"
        if "bulletin" in low:
            return "bulletin"
        return "code"
