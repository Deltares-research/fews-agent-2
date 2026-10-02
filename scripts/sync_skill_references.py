"""Copy canonical skill references into each .cursor/skills/*/references/.

Canonical bodies live in doc/skill_references/. Duplication into each
skill is intentional (Cursor loads one skill at a time). CI fails if a
copy drifts — run this script to refresh.

    uv run python scripts/sync_skill_references.py
    uv run python scripts/sync_skill_references.py --check
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CANONICAL = REPO / "doc" / "skill_references"
SKILLS_ROOT = REPO / ".cursor" / "skills"
SHARED = (
    "generation_ladder.md",
    "the_weld.md",
    "file_set_map.md",
    "id_conventions.md",
    "conform_rules.md",
    "gotchas.md",
)


def _skill_dirs() -> list[Path]:
    if not SKILLS_ROOT.is_dir():
        return []
    return sorted(p for p in SKILLS_ROOT.iterdir() if p.is_dir() and (p / "SKILL.md").is_file())


def sync(*, check: bool = False) -> int:
    if not CANONICAL.is_dir():
        print(f"missing canonical dir: {CANONICAL}", file=sys.stderr)
        return 2
    errors = 0
    for skill in _skill_dirs():
        dest_dir = skill / "references"
        dest_dir.mkdir(parents=True, exist_ok=True)
        for name in SHARED:
            src = CANONICAL / name
            if not src.is_file():
                print(f"missing canonical {name}", file=sys.stderr)
                errors += 1
                continue
            dest = dest_dir / name
            body = src.read_bytes()
            if check:
                if not dest.is_file() or dest.read_bytes() != body:
                    print(f"drift: {dest.relative_to(REPO)}", file=sys.stderr)
                    errors += 1
                continue
            dest.write_bytes(body)
    return 1 if errors else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if any skill copy differs from canonical",
    )
    args = parser.parse_args()
    return sync(check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
