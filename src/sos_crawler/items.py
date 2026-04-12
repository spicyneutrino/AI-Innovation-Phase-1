import scrapy


class RegDocItem(scrapy.Item):
    state = scrapy.Field()  # e.g. "MS"
    state_name = scrapy.Field()  # e.g. "Mississippi"
    source_url = scrapy.Field()  # page where link was found
    doc_url = scrapy.Field()  # direct URL of the document
    filename = scrapy.Field()  # saved filename
    doc_type = scrapy.Field()  # "proposed", "final", "emergency", "code"
    agency = scrapy.Field()  # agency name if extractable
    title = scrapy.Field()  # document title from link text or metadata
    fetched_at = scrapy.Field()  # ISO timestamp
    hash_md5 = scrapy.Field()  # content hash for change detection
    size_bytes = scrapy.Field()
    content_type = scrapy.Field()
    http_status = scrapy.Field()
    response_headers_subset = scrapy.Field()
    is_new = scrapy.Field()  # True if not seen in previous run

    # Phase 2 extraction and compliance metadata
    agency_type = scrapy.Field()
    agency_id = scrapy.Field()
    rule_status = scrapy.Field()
    effective_date = scrapy.Field()
    statutory_authority = scrapy.Field()
    citation = scrapy.Field()
    citation_normalized = scrapy.Field()
    source_system = scrapy.Field()
    source_portal = scrapy.Field()
    source_state_url = scrapy.Field()
    extracted_text = scrapy.Field()
    topics = scrapy.Field()
    first_seen = scrapy.Field()
    last_seen = scrapy.Field()
    last_changed_at = scrapy.Field()
    previous_hash = scrapy.Field()
    _body = scrapy.Field()

