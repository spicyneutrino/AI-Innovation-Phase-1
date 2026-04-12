from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    # This file lives at <repo>/src/sos_crawler/paths.py
    return Path(__file__).resolve().parents[2]


def runtime_dir() -> Path:
    """
    Directory where the crawler writes artifacts (logs/output/downloads/cache).

    Override with SOS_CRAWLER_RUNTIME_DIR to move all generated files.
    """
    override = os.getenv("SOS_CRAWLER_RUNTIME_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    # AWS Lambda has a read-only filesystem except for /tmp
    if os.getenv("AWS_LAMBDA_FUNCTION_NAME", "").strip():
        return Path("/tmp/sos_crawler").resolve()
    return (repo_root() / "var" / "sos_crawler").resolve()


def ensure_runtime_subdir(name: str) -> Path:
    p = runtime_dir() / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def logs_dir() -> Path:
    return ensure_runtime_subdir("logs")


def output_dir() -> Path:
    return ensure_runtime_subdir("output")


def downloads_dir() -> Path:
    return ensure_runtime_subdir("downloads")


def cache_dir() -> Path:
    return ensure_runtime_subdir("cache")


def tldextract_cache_dir() -> Path:
    p = cache_dir() / "tldextract"
    p.mkdir(parents=True, exist_ok=True)
    return p


def config_dir_override() -> Path | None:
    override = os.getenv("SOS_CRAWLER_CONFIG_DIR", "").strip()
    if not override:
        return None
    return Path(override).expanduser().resolve()

