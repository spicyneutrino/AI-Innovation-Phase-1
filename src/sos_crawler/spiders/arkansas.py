from __future__ import annotations

"""
Arkansas Code of Arkansas Rules Spider
========================================
Source  : https://codeofarrules.arkansas.gov
Publisher: Arkansas Secretary of State

Targets 3 agencies (all Title 17 — Professions, Occupations, and Businesses):
  chapterID=84   →  Chapter XXI:   AR State Board of Dental Examiners  (dental)
  chapterID=173  →  Chapter XXIV:  AR State Medical Board              (medical-licensure)
  chapterID=258  →  Chapter XXXIX: AR Real Estate Commission           (real-estate)

HOW THE SITE WORKS (confirmed via HAR capture)
───────────────────────────────────────────────
The left-pane tree is JS-rendered — plain HTTP returns a shell with no links.
BUT the tree data comes from a clean JSON REST API (no auth required):

  GET /Home/GetRulesTreeViewData?levelType=SUBCHAPTER&titleID=17&chapterID=84&subchapterID=&partID=&subpartID=
  GET /Home/GetRulesTreeViewData?levelType=PART      &titleID=17&chapterID=84&subchapterID=109&partID=&subpartID=
  GET /Home/GetRulesTreeViewData?levelType=SUBPART   &titleID=17&chapterID=84&subchapterID=109&partID=418&subpartID=
  GET /Home/GetRulesTreeViewData?levelType=SECTION   &titleID=17&chapterID=84&subchapterID=109&partID=418&subpartID=3947

Each level returns a JSON array of nodes. Each node has:
  nodeID, nodeType, nodeCitation, nodeText, nodeTextFull, hasChildren,
  titleID, chapterID, subchapterID, partID, subpartID, sectionID, repealedDateTime

SECTION nodes give us all IDs needed to construct the section content page URL:
  GET /Rules/Rule?levelType=section&titleID=17&chapterID=84
                 &subChapterID=109&partID=418&subPartID=3947&sectionID=24303

That content page is server-rendered HTML (confirmed by curl).

No Playwright needed. This spider uses only plain scrapy.Request.
"""

import hashlib
import json
import re
from datetime import UTC, datetime
from urllib.parse import urlencode

import scrapy
from scrapy.http import Response

from sos_crawler.config import load_config
from sos_crawler.items import RegDocItem

_BASE      = "https://codeofarrules.arkansas.gov"
_API_BASE  = f"{_BASE}/Home/GetRulesTreeViewData"
_PAGE_BASE = f"{_BASE}/Rules/Rule"

# Target chapters — mirrors sources.yaml AR agencies block
_CHAPTERS: dict[str, dict] = {
    "84": {
        "agency_type":  "dental",
        "agency_name":  "Arkansas State Board of Dental Examiners",
        "chapter_num":  "XXI",
        "chapter_name": "Arkansas State Board of Dental Examiners, Department of Health",
        "title_id":     17,
    },
    "173": {
        "agency_type":  "medical-licensure",
        "agency_name":  "Arkansas State Medical Board",
        "chapter_num":  "XXIV",
        "chapter_name": "Arkansas State Medical Board, Department of Health",
        "title_id":     17,
    },
    "258": {
        "agency_type":  "real-estate",
        "agency_name":  "Arkansas Real Estate Commission",
        "chapter_num":  "XXXIX",
        "chapter_name": "Arkansas Real Estate Commission, Department of Labor and Licensing",
        "title_id":     17,
    },
}

_CONTENT_NOISE = frozenset({
    "previous", "next", "search", "home", "contact",
    "emergency rules", "administrative monthly",
    "agency proposed rules", "code of arkansas rules",
    "quick find",
})


def _api_url(level: str, title_id: int, chapter_id: str,
             subchapter_id: str = "", part_id: str = "",
             subpart_id: str = "") -> str:
    return f"{_API_BASE}?{urlencode({'levelType': level, 'titleID': title_id, 'chapterID': chapter_id, 'subchapterID': subchapter_id, 'partID': part_id, 'subpartID': subpart_id})}"


def _section_url(title_id: int, chapter_id: str, subchapter_id: str,
                 part_id: str, subpart_id: str, section_id: str) -> str:
    return f"{_PAGE_BASE}?{urlencode({'levelType': 'section', 'titleID': title_id, 'chapterID': chapter_id, 'subChapterID': subchapter_id, 'partID': part_id, 'subPartID': subpart_id, 'sectionID': section_id})}"


class ArkansasSpider(scrapy.Spider):
    name = "arkansas"
    state = "AR"
    state_name = "Arkansas"
    allowed_domains = ["codeofarrules.arkansas.gov"]

    custom_settings = {
        "DOWNLOAD_DELAY": 1.0,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 3,
        "ROBOTSTXT_OBEY": False,
        "HTTPCACHE_ENABLED": False,
    }

    # ── Entry: one SUBCHAPTER call per target chapter ──────────────────────────

    def start_requests(self):
        cfg = load_config("sources.yaml")
        state_cfg = (cfg.get("states") or {}).get(self.state, {})
        agencies_cfg = state_cfg.get("agencies") or {}

        chapter_ids = [
            str(v["chapter_id"])
            for v in agencies_cfg.values()
            if v.get("chapter_id")
        ] or list(_CHAPTERS.keys())

        for chapter_id in chapter_ids:
            info = _CHAPTERS.get(chapter_id)
            if not info:
                self.logger.warning("[AR] Unknown chapter_id=%s, skipping", chapter_id)
                continue
            yield scrapy.Request(
                _api_url("SUBCHAPTER", info["title_id"], chapter_id),
                callback=self.parse_subchapters,
                headers={"Accept": "application/json"},
                meta={"chapter_id": chapter_id, "info": info},
                errback=self.errback,
            )

    # ── JSON API traversal: SUBCHAPTER → PART → SUBPART → SECTION ─────────────

    def parse_subchapters(self, response: Response):
        nodes = _parse_json(response)
        if nodes is None:
            return
        info       = response.meta["info"]
        chapter_id = response.meta["chapter_id"]
        self.logger.info("[AR] %s: %d subchapter(s)", info["agency_name"], len(nodes))
        for node in nodes:
            yield scrapy.Request(
                _api_url("PART", info["title_id"], chapter_id,
                         subchapter_id=str(node["nodeID"])),
                callback=self.parse_parts,
                headers={"Accept": "application/json"},
                meta={**response.meta,
                      "subchapter_id":   str(node["nodeID"]),
                      "subchapter_text": node.get("nodeTextFull", node.get("nodeText", ""))},
                errback=self.errback,
            )

    def parse_parts(self, response: Response):
        nodes = _parse_json(response)
        if nodes is None:
            return
        info = response.meta["info"]
        for node in nodes:
            yield scrapy.Request(
                _api_url("SUBPART", info["title_id"], response.meta["chapter_id"],
                         subchapter_id=response.meta["subchapter_id"],
                         part_id=str(node["nodeID"])),
                callback=self.parse_subparts,
                headers={"Accept": "application/json"},
                meta={**response.meta,
                      "part_id":   str(node["nodeID"]),
                      "part_text": node.get("nodeTextFull", node.get("nodeText", ""))},
                errback=self.errback,
            )

    def parse_subparts(self, response: Response):
        nodes = _parse_json(response)
        if nodes is None:
            return
        info = response.meta["info"]
        for node in nodes:
            yield scrapy.Request(
                _api_url("SECTION", info["title_id"], response.meta["chapter_id"],
                         subchapter_id=response.meta["subchapter_id"],
                         part_id=response.meta["part_id"],
                         subpart_id=str(node["nodeID"])),
                callback=self.parse_sections,
                headers={"Accept": "application/json"},
                meta={**response.meta,
                      "subpart_id":   str(node["nodeID"]),
                      "subpart_text": node.get("nodeTextFull", node.get("nodeText", ""))},
                errback=self.errback,
            )

    def parse_sections(self, response: Response):
        nodes = _parse_json(response)
        if nodes is None:
            return
        info = response.meta["info"]
        for node in nodes:
            if node.get("repealedDateTime"):
                continue  # skip repealed rules
            section_id = str(node["sectionID"])
            yield scrapy.Request(
                _section_url(
                    info["title_id"],
                    response.meta["chapter_id"],
                    response.meta["subchapter_id"],
                    response.meta["part_id"],
                    response.meta["subpart_id"],
                    section_id,
                ),
                callback=self.parse_section_page,
                meta={**response.meta,
                      "section_id":      section_id,
                      "node_citation":   node.get("nodeCitation", ""),
                      "node_text":       node.get("nodeText", ""),
                      "node_text_full":  node.get("nodeTextFull", ""),
                      "source_url":      response.url},
                errback=self.errback,
            )

    # ── Section HTML page → extract content and yield item ────────────────────

    def parse_section_page(self, response: Response):
        info           = response.meta["info"]
        chapter_id     = response.meta["chapter_id"]
        node_citation  = response.meta["node_citation"]   # "17 CAR § 115-101"
        node_text      = response.meta["node_text"]       # "Office"
        node_text_full = response.meta["node_text_full"]  # "17 CAR § 115-101. Office"
        subchapter_text = response.meta.get("subchapter_text", "")
        part_text       = response.meta.get("part_text", "")
        subpart_text    = response.meta.get("subpart_text", "")
        source_url      = response.meta.get("source_url", "")

        content = _extract_content(response)
        if not content:
            self.logger.warning("[AR] Empty content at %s", response.url)
            return

        doc_lines = [
            f"STATE: Arkansas (AR)",
            f"AGENCY: {info['agency_name']}",
            f"TITLE: {info['title_id']} — Professions, Occupations, and Businesses",
            f"CHAPTER: {info['chapter_num']} — {info['chapter_name']}",
        ]
        if subchapter_text:
            doc_lines.append(f"SUBCHAPTER: {subchapter_text}")
        if part_text:
            doc_lines.append(f"PART: {part_text}")
        if subpart_text:
            doc_lines.append(f"SUBPART: {subpart_text}")
        doc_lines += [
            f"RULE: {node_citation} — {node_text}",
            f"SOURCE: {response.url}",
            "",
            content,
        ]
        doc_text = re.sub(r"\n{3,}", "\n\n", "\n".join(doc_lines)).strip()

        citation = (
            f"Arkansas | {info['agency_name']} | "
            f"Title {info['title_id']}, Chapter {info['chapter_num']} | "
            f"{node_citation}"
        )
        safe_cite = re.sub(r"[^\w\-]", "_", node_citation or "unknown")
        filename  = f"AR_{info['agency_type']}_ch{info['chapter_num']}_{safe_cite}.txt"

        body = doc_text.encode("utf-8")
        yield RegDocItem(
            state          = self.state,
            state_name     = self.state_name,
            agency         = info["agency_name"],
            agency_type    = info["agency_type"],
            agency_id      = chapter_id,
            source_url     = source_url,
            doc_url        = response.url,
            filename       = filename,
            doc_type       = "rule",
            rule_status    = "rule",
            title          = node_text_full or f"{node_citation} — {node_text}",
            citation       = citation,
            extracted_text = doc_text,
            fetched_at     = datetime.now(UTC).isoformat(),
            hash_md5       = hashlib.md5(body).hexdigest(),
            size_bytes     = len(body),
            content_type   = "text/plain; charset=utf-8",
            _body          = body,
        )

    def errback(self, failure):
        self.logger.error("[AR] Request failed: %s — %s", failure.request.url, failure.value)


# ── Module helpers ─────────────────────────────────────────────────────────────

def _parse_json(response: Response) -> list | None:
    try:
        data = json.loads(response.text)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, Exception) as exc:
        # Log the raw response for debugging
        spider_logger = getattr(response, "_logger", None)
        return None


def _extract_content(response: Response) -> str:
    """Extract rule text from the server-rendered section page."""
    for selector in [
        ".col-md-9", ".col-lg-9",
        "#rule-display", "#ContentPlaceHolder1_pnlContent",
        "#main-content", ".rule-content", "#content",
    ]:
        els = response.css(selector)
        if not els:
            continue
        texts = [t.strip() for t in els.css("*::text").getall() if t.strip()]
        lines = [t for t in texts if t.lower() not in _CONTENT_NOISE and len(t) > 2]
        result = "\n".join(lines).strip()
        if len(result) > 80:
            return result

    # Broadest fallback
    texts = []
    for el in response.css("p, td, li"):
        t = " ".join(el.css("::text").getall()).strip()
        if len(t) >= 5 and t.lower() not in _CONTENT_NOISE:
            texts.append(t)
    return "\n".join(texts)
