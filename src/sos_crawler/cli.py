from __future__ import annotations

import argparse
import sys

from sos_crawler.orchestrator import crawl_from_cli
from sos_crawler.tools.enrich import enrich_from_cli
from sos_crawler.tools.qa import qa_from_cli


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sos-crawler", description="SoS Regulatory Crawler")
    sub = p.add_subparsers(dest="cmd", required=True)

    crawl = sub.add_parser("crawl", help="Run one or more state spiders")
    crawl.add_argument("--states", nargs="+", help="Limit to state IDs (e.g. MS TX)")
    crawl.add_argument("--mode", choices=["full", "designated"], default="full")
    crawl.add_argument("--max-retries", type=int, default=1)
    crawl.add_argument(
        "--max-workers",
        type=int,
        default=4,
        help="Max parallel state workers (local only). Disabled automatically on AWS Lambda.",
    )
    crawl.add_argument("--run-qa", action="store_true")
    crawl.add_argument("--run-enrichment", action="store_true")
    crawl.add_argument(
        "--runtime-dir",
        help="Override runtime directory (logs/output/downloads/cache). Also via SOS_CRAWLER_RUNTIME_DIR.",
    )
    crawl.add_argument(
        "--config-dir",
        help="Override config directory (sources.yaml, agency_allowlists.yaml). Also via SOS_CRAWLER_CONFIG_DIR.",
    )

    qa = sub.add_parser("qa", help="Run QA checks on latest crawl outputs")
    qa.add_argument("--runtime-dir", help="Override runtime directory (also via SOS_CRAWLER_RUNTIME_DIR).")

    enrich = sub.add_parser("enrich", help="Generate knowledge package JSONL from manifests")
    enrich.add_argument("--runtime-dir", help="Override runtime directory (also via SOS_CRAWLER_RUNTIME_DIR).")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "crawl":
        return crawl_from_cli(args)
    if args.cmd == "qa":
        return qa_from_cli(args)
    if args.cmd == "enrich":
        return enrich_from_cli(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

