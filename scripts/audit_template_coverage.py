"""Report Pydantic model fields never referenced in their Jinja template.

Diagnostic, not a CI gate. Templates were farmed from the tutorial, so
some silently omit optionals the model wants to set.

    uv run python scripts/audit_template_coverage.py
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TEMPLATES = REPO / "fews_agent" / "generators" / "templates"


def _model_fields(cls: type) -> list[str]:
    fields = getattr(cls, "model_fields", None)
    if not fields:
        return []
    return list(fields.keys())


def main() -> int:
    sys.path.insert(0, str(REPO))
    from fews_agent.generators import SPECS

    seen: dict[str, tuple[type, str]] = {}
    for spec in SPECS:
        key = spec.model_class.__name__
        if key in seen:
            continue
        seen[key] = (spec.model_class, spec.template_name)

    ranked: list[tuple[int, str, list[str], str]] = []
    for name, (cls, template_name) in sorted(seen.items()):
        path = TEMPLATES / template_name
        if not path.is_file():
            ranked.append((999, name, ["<template missing>"], template_name))
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        missing = [f for f in _model_fields(cls) if f not in text]
        if missing:
            ranked.append((len(missing), name, missing, template_name))

    ranked.sort(reverse=True)
    print(f"{len(ranked)} specs with unreferenced model fields "
          f"(of {len(seen)} unique model classes)\n")
    for count, name, missing, template_name in ranked[:40]:
        preview = ", ".join(missing[:12])
        extra = "" if len(missing) <= 12 else f" … +{len(missing) - 12}"
        print(f"{count:3d}  {name:40s}  {template_name}")
        print(f"     {preview}{extra}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
