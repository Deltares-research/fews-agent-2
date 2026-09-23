"""Compare gauntlet tiers on a config folder (opt-in, not default pytest).

    python -m runners.agent.calibrate_gauntlet --config examples/config-tutorial

Writes a markdown table to stdout (and optionally --out PATH).
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from fews_agent.validation.gauntlet import DEFAULT_TIERS, validate_config


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", required=True, type=Path)
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args(argv)

    report = validate_config(args.config)
    counts = Counter((d.tier, d.severity) for d in report.diagnostics)
    lines = [
        f"# Gauntlet calibration — `{args.config}`",
        "",
        f"files_checked: {report.files_checked}",
        f"ok (no errors): {report.ok}",
        f"tiers: {', '.join(report.tiers_run or DEFAULT_TIERS)}",
        "",
        "| tier | severity | count |",
        "| --- | --- | ---: |",
    ]
    for (tier, sev), n in sorted(counts.items()):
        lines.append(f"| {tier} | {sev} | {n} |")
    if not counts:
        lines.append("| — | — | 0 |")
    lines.extend(["", "## First 20 diagnostics", ""])
    for d in report.diagnostics[:20]:
        lines.append(
            f"- `{d.rule_id}` [{d.severity}] {d.file}: {d.message}"
        )
    text = "\n".join(lines) + "\n"
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
