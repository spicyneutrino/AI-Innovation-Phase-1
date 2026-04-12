from __future__ import annotations

import os

from sos_crawler.paths import cache_dir, logs_dir

BOT_NAME = "sos_crawler"
SPIDER_MODULES = ["sos_crawler.spiders"]
NEWSPIDER_MODULE = "sos_crawler.spiders"

# Polite crawling — respect robots.txt & rate limits
ROBOTSTXT_OBEY = True
DOWNLOAD_DELAY = 1.0
RANDOMIZE_DOWNLOAD_DELAY = True
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 1.0
AUTOTHROTTLE_MAX_DELAY = 10.0
CONCURRENT_REQUESTS = 32
CONCURRENT_REQUESTS_PER_DOMAIN = 8

# Cache HTTP responses to avoid re-downloading unchanged files
HTTPCACHE_ENABLED = True
HTTPCACHE_EXPIRATION_SECS = 86400  # 24 hours
HTTPCACHE_DIR = str((cache_dir() / "scrapy_httpcache").resolve())

# Item pipeline
ITEM_PIPELINES = {
    "sos_crawler.pipelines.AgencyScopePipeline": 200,
    "sos_crawler.pipelines.NormalizePipeline": 250,
    "sos_crawler.pipelines.DocumentSavePipeline": 300,
    "sos_crawler.pipelines.ChangeTrackingPipeline": 350,
    "sos_crawler.pipelines.ManifestPipeline": 400,
}

# Logging
LOG_LEVEL = "INFO"
LOG_FILE = str((logs_dir() / "scrapy.log").resolve())

USER_AGENT = "SoS-Regulatory-Crawler/1.0 (+contact@youragency.gov)"

# Avoid opening local telnet port in restricted environments.
TELNETCONSOLE_ENABLED = False

# Playwright support for JS-rendered sources
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
DOWNLOAD_HANDLERS = {
    "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
    "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
}
PLAYWRIGHT_BROWSER_TYPE = "chromium"
PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT = 90_000
PLAYWRIGHT_LAUNCH_OPTIONS = {
    "headless": os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() in ("1", "true", "yes"),
}

DOWNLOAD_TIMEOUT = 120
RETRY_TIMES = 3
RETRY_HTTP_CODES = [500, 502, 503, 504, 408, 429]

