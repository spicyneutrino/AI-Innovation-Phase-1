from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sos_crawler.config import load_config, read_config_text
from sos_crawler.paths import repo_root, tldextract_cache_dir


STATE_SPIDERS: dict[str, str] = {
    "MS": "mississippi",
    "AL": "alabama",
    "LA": "louisiana",
    "TN": "tennessee",
    "AR": "arkansas",
    "GA": "georgia",
    "TX": "texas",
}


def _resolve_runtime_dir(runtime_dir_arg: str | None) -> Path:
    if runtime_dir_arg:
        os.environ["SOS_CRAWLER_RUNTIME_DIR"] = runtime_dir_arg
    from sos_crawler.paths import runtime_dir  # late bind after env set

    return runtime_dir()


def _resolve_config_dir(config_dir_arg: str | None) -> None:
    if config_dir_arg:
        os.environ["SOS_CRAWLER_CONFIG_DIR"] = config_dir_arg


def _targets_from_sources(states_filter: list[str] | None) -> list[str]:
    cfg = load_config("sources.yaml")
    configured_states = (cfg.get("states") or {}).keys()
    configured = [s.upper() for s in configured_states if isinstance(s, str)]
    if states_filter:
        want = [s.upper() for s in states_filter]
        return [s for s in want if s in STATE_SPIDERS]
    return [s for s in configured if s in STATE_SPIDERS]


def _setup_logging(log_file: Path) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(log_file)],
    )


def _is_lambda_env() -> bool:
    return bool(os.getenv("AWS_LAMBDA_FUNCTION_NAME", "").strip())


def _pool_entrypoint(kwargs: dict) -> dict:
    """
    multiprocessing Pool worker entrypoint.
    Use a top-level function for picklability under spawn.
    """
    return run_spider(**kwargs)


def _agent_debug_log(*, hypothesis_id: str, location: str, message: str, data: dict) -> None:
    # #region agent log
    try:
        ts_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        payload = {
            "sessionId": "d63066",
            "runId": os.getenv("SOS_DEBUG_RUN_ID") or "pre-fix",
            "hypothesisId": hypothesis_id,
            "id": f"log_{ts_ms}_{uuid.uuid4().hex[:8]}",
            "timestamp": ts_ms,
            "location": location,
            "message": message,
            "data": data,
        }
        Path("/var/home/oak/work/AI-Innovation-Phase-1/.cursor/debug-d63066.log").open("a", encoding="utf-8").write(
            json.dumps(payload, ensure_ascii=False) + "\n"
        )
    except Exception:
        pass
    # #endregion


def run_spiders(states: list[str]) -> dict:
    """
    Programmatic entrypoint (e.g. AWS Lambda) to run one or more state spiders.
    """
    _agent_debug_log(
        hypothesis_id="H1",
        location="src/sos_crawler/orchestrator.py:run_spiders",
        message="run_spiders invoked",
        data={"states": states},
    )

    runtime = _resolve_runtime_dir(os.getenv("SOS_CRAWLER_RUNTIME_DIR"))
    _resolve_config_dir(os.getenv("SOS_CRAWLER_CONFIG_DIR"))

    logs = runtime / "logs"
    out = runtime / "output"
    dl = runtime / "downloads"
    logs.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    dl.mkdir(parents=True, exist_ok=True)

    _setup_logging(logs / "run.log")

    mode = (os.getenv("CRAWLER_MODE") or "full").strip() or "full"
    max_retries = int(os.getenv("MAX_RETRIES") or "1")

    allowlist_filename = "agency_allowlists.yaml"
    runtime_config_dir = runtime / "config"
    runtime_config_dir.mkdir(parents=True, exist_ok=True)
    allowlist_abs = runtime_config_dir / allowlist_filename
    text, _suffix = read_config_text(allowlist_filename)
    allowlist_abs.write_text(text, encoding="utf-8")

    targets = _targets_from_sources(states)
    _agent_debug_log(
        hypothesis_id="H2",
        location="src/sos_crawler/orchestrator.py:run_spiders",
        message="resolved targets",
        data={"input_states": states, "targets": targets, "mode": mode, "runtime_dir": str(runtime)},
    )

    results: list[dict] = []
    for state in targets:
        results.append(
            run_spider(
                state=state,
                spider=STATE_SPIDERS[state],
                runtime=runtime,
                max_retries=max_retries,
                mode=mode,
                allowlist_file=str(allowlist_abs),
            )
        )

    ok_count = sum(1 for r in results if r["ok"])
    summary = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "total": len(results),
        "ok": ok_count,
        "failed": len(results) - ok_count,
        "mode": mode,
        "states": results,
        "runtime_dir": str(runtime),
    }
    (out / "last_run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    _agent_debug_log(
        hypothesis_id="H3",
        location="src/sos_crawler/orchestrator.py:run_spiders",
        message="run complete",
        data={"ok": ok_count, "total": len(results)},
    )
    return summary


def run_spider(
    *,
    state: str,
    spider: str,
    runtime: Path,
    max_retries: int,
    mode: str,
    allowlist_file: str,
) -> dict:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    out_rel = Path("output") / f"{state}_{ts}.jsonl"
    log_rel = Path("logs") / f"{state}_{ts}.log"

    # State-specific combined log (Scrapy log + subprocess stdout/stderr).
    combined_log_rel = Path("logs") / f"{state}_{ts}.log"

    cmd = [
        sys.executable,
        "-m",
        "scrapy",
        "crawl",
        spider,
        "-o",
        str(runtime / out_rel),
        "--logfile",
        str(runtime / combined_log_rel),
    ]

    env = os.environ.copy()
    env["CRAWLER_MODE"] = mode
    env["AGENCY_ALLOWLIST_FILE"] = allowlist_file
    env["TLDEXTRACT_CACHE"] = str(tldextract_cache_dir().resolve())
    # Ensure `src/` package imports work even if project isn't installed.
    src_dir = str((repo_root() / "src").resolve())
    env["PYTHONPATH"] = src_dir + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

    logging.info("▶ Starting %s (%s)", spider, state)
    t0 = datetime.now(timezone.utc)
    result = None
    for attempt in range(1, max_retries + 2):
        combined_log_path = runtime / combined_log_rel
        combined_log_path.parent.mkdir(parents=True, exist_ok=True)
        with combined_log_path.open("a", encoding="utf-8") as lf:
            lf.write(f"\n── {datetime.now(timezone.utc).isoformat()}Z attempt {attempt}/{max_retries + 1} ──\n")
            lf.flush()
            result = subprocess.run(
                cmd,
                stdout=lf,
                stderr=lf,
                text=True,
                cwd=str(repo_root()),
                env=env,
            )
        if result.returncode == 0:
            break
        logging.warning("Retry %s/%s failed for %s", attempt, max_retries + 1, state)

    elapsed = int((datetime.now(timezone.utc) - t0).total_seconds())
    ok = bool(result and result.returncode == 0)
    if ok:
        logging.info("✓ %s done in %ss → %s", state, elapsed, runtime / out_rel)
    else:
        logging.error("✗ %s FAILED (%ss). See logs: %s", state, elapsed, runtime / combined_log_rel)

    return {
        "state": state,
        "ok": ok,
        "elapsed_s": elapsed,
        "output": str(out_rel),
        "logfile": str(combined_log_rel),
        "mode": mode,
    }


def crawl_from_cli(args: argparse.Namespace) -> int:
    _resolve_config_dir(getattr(args, "config_dir", None))
    runtime = _resolve_runtime_dir(getattr(args, "runtime_dir", None))

    logs = runtime / "logs"
    out = runtime / "output"
    dl = runtime / "downloads"
    logs.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    dl.mkdir(parents=True, exist_ok=True)

    _setup_logging(logs / "run.log")

    # AgencyScopePipeline expects a readable file path from AGENCY_ALLOWLIST_FILE.
    # We always materialize the active config into runtime/config for stability.
    allowlist_filename = "agency_allowlists.yaml"
    runtime_config_dir = runtime / "config"
    runtime_config_dir.mkdir(parents=True, exist_ok=True)
    allowlist_abs = runtime_config_dir / allowlist_filename
    text, _suffix = read_config_text(allowlist_filename)
    allowlist_abs.write_text(text, encoding="utf-8")

    targets = _targets_from_sources(getattr(args, "states", None))
    results = []

    max_workers = int(getattr(args, "max_workers", 4) or 4)
    if max_workers < 1:
        max_workers = 1

    if _is_lambda_env():
        logging.info("AWS Lambda detected; disabling multiprocessing.")
        max_workers = 1

    job_kwargs = []
    for state in targets:
        spider = STATE_SPIDERS[state]
        job_kwargs.append(
            dict(
                state=state,
                spider=spider,
                runtime=runtime,
                max_retries=int(getattr(args, "max_retries", 1)),
                mode=str(getattr(args, "mode", "full")),
                allowlist_file=str(allowlist_abs),
            )
        )

    if max_workers == 1 or len(job_kwargs) <= 1:
        for kw in job_kwargs:
            results.append(run_spider(**kw))
    else:
        workers = min(max_workers, len(job_kwargs))
        logging.info("Running %d states with %d workers (popen)", len(job_kwargs), workers)
        results = _run_parallel_popen(job_kwargs, max_workers=workers)

    ok_count = sum(1 for r in results if r["ok"])
    summary = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "total": len(results),
        "ok": ok_count,
        "failed": len(results) - ok_count,
        "mode": getattr(args, "mode", "full"),
        "states": results,
        "runtime_dir": str(runtime),
    }
    (out / "last_run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    logging.info("── Run complete: %s/%s spiders succeeded ──", ok_count, len(results))

    exit_code = 0 if ok_count == len(results) else 1

    if getattr(args, "run_qa", False):
        from sos_crawler.tools.qa import run_qa

        exit_code = max(exit_code, run_qa(runtime))
    if getattr(args, "run_enrichment", False):
        from sos_crawler.tools.enrich import run_enrich

        exit_code = max(exit_code, run_enrich(runtime))

    return exit_code


def _build_spider_cmd(*, spider: str, runtime: Path, state: str, ts: str) -> tuple[list[str], Path, Path]:
    out_rel = Path("output") / f"{state}_{ts}.jsonl"
    log_rel = Path("logs") / f"{state}_{ts}.log"
    cmd = [
        sys.executable,
        "-m",
        "scrapy",
        "crawl",
        spider,
        "-o",
        str(runtime / out_rel),
        "--logfile",
        str(runtime / log_rel),
    ]
    return cmd, out_rel, log_rel


def _run_parallel_popen(job_kwargs: list[dict], *, max_workers: int) -> list[dict]:
    """
    Run multiple state spiders concurrently using subprocess.Popen.
    Each state spider remains isolated in its own OS process.
    """
    crawl_ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")

    # Prepare jobs with attempts and pre-built env/cmd to avoid recomputing in the loop.
    pending: list[dict] = []
    for kw in job_kwargs:
        state = kw["state"]
        spider = kw["spider"]
        runtime: Path = kw["runtime"]
        cmd, out_rel, log_rel = _build_spider_cmd(spider=spider, runtime=runtime, state=state, ts=crawl_ts)

        env = os.environ.copy()
        env["CRAWLER_MODE"] = kw["mode"]
        env["AGENCY_ALLOWLIST_FILE"] = kw["allowlist_file"]
        env["TLDEXTRACT_CACHE"] = str(tldextract_cache_dir().resolve())
        src_dir = str((repo_root() / "src").resolve())
        env["PYTHONPATH"] = src_dir + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

        pending.append(
            {
                "state": state,
                "spider": spider,
                "runtime": runtime,
                "cmd": cmd,
                "env": env,
                "out_rel": out_rel,
                "log_rel": log_rel,
                "max_retries": int(kw.get("max_retries", 1)),
                "attempt": 0,
            }
        )

    running: dict[int, dict] = {}
    finished: list[dict] = []

    def start_job(job: dict) -> None:
        job["attempt"] += 1
        state = job["state"]
        spider = job["spider"]
        runtime: Path = job["runtime"]
        log_path = runtime / job["log_rel"]
        log_path.parent.mkdir(parents=True, exist_ok=True)
        # Append marker for retry attempts
        with log_path.open("a", encoding="utf-8") as lf:
            lf.write(f"\n── {datetime.now(timezone.utc).isoformat()}Z attempt {job['attempt']}/{job['max_retries'] + 1} ──\n")
            lf.flush()
            logging.info("▶ Dispatching %s (%s) attempt %d", spider, state, job["attempt"])
            p = subprocess.Popen(
                job["cmd"],
                stdout=lf,
                stderr=lf,
                text=True,
                cwd=str(repo_root()),
                env=job["env"],
            )
        job["t0"] = datetime.now(timezone.utc)
        job["pid"] = p.pid
        running[p.pid] = {"proc": p, "job": job}

    # Start initial batch
    while pending and len(running) < max_workers:
        start_job(pending.pop(0))

    # Poll loop
    while running:
        done_pids = []
        for pid, entry in list(running.items()):
            p: subprocess.Popen = entry["proc"]
            rc = p.poll()
            if rc is None:
                continue
            done_pids.append(pid)
            job = entry["job"]
            elapsed = int((datetime.now(timezone.utc) - job["t0"]).total_seconds())
            ok = rc == 0
            state = job["state"]
            if ok:
                logging.info("✓ %s done in %ss → %s", state, elapsed, job["runtime"] / job["out_rel"])
                finished.append(
                    {
                        "state": state,
                        "ok": True,
                        "elapsed_s": elapsed,
                        "output": str(job["out_rel"]),
                        "logfile": str(job["log_rel"]),
                        "mode": job["env"].get("CRAWLER_MODE", ""),
                    }
                )
            else:
                if job["attempt"] <= job["max_retries"]:
                    logging.warning("Retry %d/%d failed for %s (rc=%s); re-queueing", job["attempt"], job["max_retries"] + 1, state, rc)
                    pending.append(job)
                else:
                    logging.error("✗ %s FAILED (%ss). See logs: %s", state, elapsed, job["runtime"] / job["log_rel"])
                    finished.append(
                        {
                            "state": state,
                            "ok": False,
                            "elapsed_s": elapsed,
                            "output": str(job["out_rel"]),
                            "logfile": str(job["log_rel"]),
                            "mode": job["env"].get("CRAWLER_MODE", ""),
                        }
                    )

        for pid in done_pids:
            running.pop(pid, None)

        # Start more jobs if slots freed
        while pending and len(running) < max_workers:
            start_job(pending.pop(0))

        if running:
            # brief sleep without importing time at module top
            import time

            time.sleep(0.5)

    # If any jobs were queued for retries at the end, they should have been run; finished includes all states.
    # Preserve original ordering by the input job list.
    by_state = {r["state"]: r for r in finished}
    ordered = []
    for kw in job_kwargs:
        st = kw["state"]
        if st in by_state:
            ordered.append(by_state[st])
    return ordered

