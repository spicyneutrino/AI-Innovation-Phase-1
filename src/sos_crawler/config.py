from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import importlib.resources as resources

from sos_crawler.paths import config_dir_override

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None


def _parse_scalar(value: str):
    value = value.strip()
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    return value


def _simple_yaml_load(text: str) -> dict[str, Any]:
    """Minimal YAML loader for nested dict/list structures used in config files."""
    root: dict[str, Any] = {}
    stack: list[tuple[int, Any]] = [(-1, root)]
    last_key_for_indent: dict[int, str] = {}

    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()

        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]

        if stripped.startswith("- "):
            value = _parse_scalar(stripped[2:])
            if not isinstance(parent, list):
                key = last_key_for_indent.get(stack[-1][0], None)
                if key is None:
                    continue
                parent[key] = []
                parent = parent[key]
                stack.append((indent - 1, parent))
            parent.append(value)
            continue

        if ":" in stripped:
            key, rhs = stripped.split(":", 1)
            key = key.strip()
            rhs = rhs.strip()
            if rhs:
                parent[key] = _parse_scalar(rhs)
            else:
                parent[key] = {}
                stack.append((indent, parent[key]))
            last_key_for_indent[indent] = key
    return root


def _load_text(text: str, suffix: str) -> dict[str, Any]:
    suffix = (suffix or "").lower()
    if suffix == ".json" or text.lstrip().startswith("{") or text.lstrip().startswith("["):
        return json.loads(text)
    if yaml is None:
        return _simple_yaml_load(text)
    return yaml.safe_load(text) or {}


def read_config_text(filename: str) -> tuple[str, str]:
    """
    Read config text either from SOS_CRAWLER_CONFIG_DIR override or from packaged defaults.

    Returns (text, suffix).
    """
    override_dir = config_dir_override()
    if override_dir is not None:
        p = (override_dir / filename).resolve()
        if p.exists():
            return p.read_text(encoding="utf-8"), p.suffix

    pkg = "sos_crawler.config_data"
    with resources.files(pkg).joinpath(filename).open("r", encoding="utf-8") as f:
        return f.read(), Path(filename).suffix


def load_config(filename_or_path: str | Path) -> dict[str, Any]:
    """
    Load config from a path or a known config filename.

    - If given an existing filesystem path, it will be read directly.
    - Otherwise, it is treated as a config filename and resolved via read_config_text().
    """
    p = Path(filename_or_path)
    if p.exists():
        text = p.read_text(encoding="utf-8")
        return _load_text(text, p.suffix)

    text, suffix = read_config_text(str(filename_or_path))
    return _load_text(text, suffix)

