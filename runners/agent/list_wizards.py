"""List wizard registrations.

Prints every spec known to ``fews_agent.agent.wizard.WIZARD_SPECS`` with
its source (manual hand-authored vs auto-derived from a Pydantic model),
the file-level setter count, the item field, and the item field count.
Helpful when you want to know which specs you can drive via the wizard
runner today.

Usage::

    python -m runners.agent.list_wizards
    python -m runners.agent.list_wizards --skipped     # also show specs the auto path couldn't derive
    python -m runners.agent.list_wizards --filter time # substring filter on spec name
"""
from __future__ import annotations

import argparse
import sys
from typing import Any


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--skipped",
        action="store_true",
        help="Also list specs that couldn't be auto-derived (with reasons).",
    )
    parser.add_argument(
        "--filter",
        default="",
        help="Substring filter on spec name (case-insensitive).",
    )
    args = parser.parse_args(argv)

    from fews_agent.agent.wizard import (
        AUTO_REGISTRATION_STATUS,
        WIZARD_SPECS,
    )

    needle = args.filter.lower().strip()

    rows: list[tuple[str, str, str, str, int, int]] = []
    for name in sorted(AUTO_REGISTRATION_STATUS):
        if needle and needle not in name.lower():
            continue
        outcome = AUTO_REGISTRATION_STATUS[name]
        spec = WIZARD_SPECS.get(name)
        if spec is None:
            if not args.skipped:
                continue
            rows.append((name, outcome, "—", "—", 0, 0))
            continue
        # Show item-field summary across all sections for this spec.
        section_summary = (
            ", ".join(s.item_field for s in spec.sections)
            if spec.sections
            else "(no items)"
        )
        total_item_fields = sum(
            len(g.fields)
            for s in spec.sections
            for g in s.item_groups
        )
        rows.append(
            (
                name,
                outcome,
                spec.input_key,
                section_summary,
                len(spec.file_level),
                total_item_fields,
            )
        )

    print(f"{'spec':<45} {'src':<7} {'input_key':<35} {'item':<25} {'fl':>3} {'fld':>4}")
    print("-" * 124)
    for name, outcome, input_key, item_field, n_fl, n_item in rows:
        print(f"{name[:44]:<45} {outcome[:6]:<7} {input_key[:34]:<35} {item_field[:24]:<25} {n_fl:>3} {n_item:>4}")
    print("-" * 124)

    # Global counts always reflect the full registry — even if rows
    # were filtered, the bottom line is what matters.
    g_manual = sum(1 for v in AUTO_REGISTRATION_STATUS.values() if v == "manual")
    g_auto = sum(1 for v in AUTO_REGISTRATION_STATUS.values() if v == "auto")
    g_skipped = sum(1 for v in AUTO_REGISTRATION_STATUS.values() if v.startswith("skipped"))
    g_total = len(AUTO_REGISTRATION_STATUS)
    print(
        f"showing {len(rows)} of {g_total} — "
        f"{g_manual} manual + {g_auto} auto + {g_skipped} skipped (full registry)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
