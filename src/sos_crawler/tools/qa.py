from __future__ import annotations

import argparse
import json
from pathlib import Path

from sos_crawler.paths import output_dir, runtime_dir


def run_qa(runtime: Path | None = None) -> int:
    rt = runtime or runtime_dir()
    out = rt / "output"
    if not out.exists():
        raise SystemExit("[QA] FAIL: output directory missing")

    summary_path = out / "last_run_summary.json"
    if not summary_path.exists():
        raise SystemExit("[QA] FAIL: last_run_summary.json missing")

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("total", 0) <= 0:
        raise SystemExit("[QA] FAIL: no states executed")

    manifests = list(out.glob("manifest_*.jsonl"))
    if not manifests:
        raise SystemExit("[QA] FAIL: no manifest files produced")

    required_fields = {"state", "doc_url", "fetched_at", "rule_status", "citation_normalized"}
    for mf in manifests:
        for line in mf.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            obj = json.loads(line)
            missing = [k for k in required_fields if k not in obj]
            if missing:
                raise SystemExit(f"[QA] FAIL: manifest {mf.name} missing fields: {missing}")

    print("[QA] PASS")
    return 0


def qa_from_cli(args: argparse.Namespace) -> int:
    if getattr(args, "runtime_dir", None):
        import os

        os.environ["SOS_CRAWLER_RUNTIME_DIR"] = args.runtime_dir
    return run_qa(runtime_dir())

