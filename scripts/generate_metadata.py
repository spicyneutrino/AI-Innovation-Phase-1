from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MS_ROOT = REPO_ROOT / "var" / "sos_crawler" / "downloads" / "MS"


def _safe_segment(s: str, *, fallback: str) -> str:
    s = (s or "").strip()
    if not s:
        return fallback
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r'[\\\\/:"*?<>|]+', "-", s)
    s = s.strip(" .-_")
    return s or fallback


def _parse_ms_title_folder(title_folder: str) -> tuple[str, str]:
    """
    From folder name: 'Title_{Number}-{Agency_Name}'
    Returns (title_num, agency_name).
    """
    s = (title_folder or "").strip()
    m = re.match(r"(?i)^title[_\s-]*0*(\d+)\s*[-—]\s*(.+)$", s)
    if m:
        return m.group(1).zfill(2), m.group(2).strip()
    # Fallbacks: treat whole folder as agency label.
    return "00", s or "Unknown"


def _parse_ms_part_folder(part_folder: str) -> tuple[str, str]:
    """
    From folder name: 'Part_{Number}-{Rule_Name}'
    Returns (part_num, part_name).
    """
    s = (part_folder or "").strip()
    m = re.match(r"(?i)^part[_\s-]*0*(\d+)\s*[-—]\s*(.+)$", s)
    if m:
        return m.group(1), m.group(2).strip()
    return "0", s or "Unknown"


def _remove_empty_dirs(root: Path) -> int:
    removed = 0
    # Bottom-up removal
    for p in sorted([d for d in root.rglob("*") if d.is_dir()], key=lambda x: len(x.parts), reverse=True):
        try:
            next(p.iterdir())
        except StopIteration:
            p.rmdir()
            removed += 1
        except Exception:
            continue
    return removed


def migrate_ms_from_data(*, data_ms_root: Path, downloads_ms_root: Path) -> int:
    """
    Move an existing `data/MS/**` tree into `var/sos_crawler/downloads/MS/**`,
    preserving relative paths. Moves `.pdf`, `.txt`, and existing `.metadata.json` sidecars.
    Removes empty `data/MS` directories after move.
    """
    if not data_ms_root.exists():
        return 0

    downloads_ms_root.mkdir(parents=True, exist_ok=True)

    moved = 0
    for src in sorted([p for p in data_ms_root.rglob("*") if p.is_file()]):
        rel = src.relative_to(data_ms_root)
        dst = downloads_ms_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        moved += 1

    _remove_empty_dirs(data_ms_root)
    try:
        next(data_ms_root.iterdir())
    except StopIteration:
        data_ms_root.rmdir()
    return moved


def generate_metadata(ms_root: Path) -> tuple[int, int]:
    """
    Create `{filename}.metadata.json` sidecars for every MS document under downloads/MS.
    Handles both `.pdf` and `.txt`.
    """
    count = 0
    missing_structure = 0

    for doc in sorted(ms_root.rglob("*")):
        if not doc.is_file():
            continue
        if doc.suffix.lower() not in {".pdf", ".txt"}:
            continue
        if doc.name.endswith(".metadata.json"):
            continue

        try:
            rel = doc.relative_to(ms_root)
        except Exception:
            continue

        parts = rel.parts
        # Expected depth: Title_folder / Part_folder / file
        if len(parts) < 3:
            missing_structure += 1
            title_folder = parts[0] if parts else "Title_00-Unknown"
            part_folder = parts[1] if len(parts) > 1 else "Part_0-Unknown"
        else:
            title_folder = parts[0]
            part_folder = parts[1]

        title_num, agency_name = _parse_ms_title_folder(title_folder)
        part_num, part_name = _parse_ms_part_folder(part_folder)

        title_value = str(title_folder)
        part_value = str(part_folder)
        citation = f"Miss. Admin. Code {title_num}-{part_num}"

        metadata = {
            "metadataAttributes": {
                "state": "MS",
                "title": str(title_value),
                "agency": str(agency_name),
                "part": str(part_value),
                "citation": str(citation),
                "is_primary": "true",
            }
        }

        meta_path = doc.parent / f"{doc.name}.metadata.json"
        meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        count += 1

    return count, missing_structure


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--ms-root",
        default=str(DEFAULT_MS_ROOT),
        help="Root directory for MS downloads (default: ./var/sos_crawler/downloads/MS)",
    )
    ap.add_argument(
        "--migrate-ms-from-data",
        action="store_true",
        help="Move existing ./data/MS into ./var/sos_crawler/downloads/MS (preserving nested folders).",
    )
    args = ap.parse_args()

    ms_root = Path(args.ms_root).expanduser().resolve()
    ms_root.mkdir(parents=True, exist_ok=True)

    if args.migrate_ms_from_data:
        data_ms = REPO_ROOT / "data" / "MS"
        moved = migrate_ms_from_data(data_ms_root=data_ms, downloads_ms_root=ms_root)
        print(f"[MS] Migrated {moved} files into {ms_root}")

    count, missing_structure = generate_metadata(ms_root)
    print(f"[MS] Wrote {count} metadata sidecars under {ms_root}")
    if missing_structure:
        print(f"[MS] Warning: {missing_structure} docs were not in expected Title/Part nesting")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())