"""Run the deriver on every cluster YAML in data/patterns/clusters/.

Aggregates per-cluster round-trip results into one table — the
tracking dashboard for "how close are we to full tutorial reproduction
without LLM polish?".
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.derive_pattern import (  # noqa: E402
    derive_pattern, load_cluster_config, round_trip_check,
)

CLUSTERS_DIR = REPO_ROOT / "data" / "patterns" / "clusters"


def main() -> int:
    rows = []
    grand_total = grand_ok = 0
    for cluster_path in sorted(CLUSTERS_DIR.glob("*.yaml")):
        try:
            name, label_var, output_specs, instances = load_cluster_config(
                cluster_path
            )
            derived, var_values = derive_pattern(
                cluster_name=name,
                output_specs=output_specs,
                instances=instances,
                label_var_name=label_var,
            )
            rt = round_trip_check(
                output_specs, instances, derived, var_values, label_var
            )
            agg = rt["aggregate"]
            review_count = len(derived.get("_review", []))
            rows.append({
                "cluster": name,
                "instances": len(instances),
                "ok": agg["ok"],
                "total": agg["total"],
                "review": review_count,
            })
            grand_total += agg["total"]
            grand_ok += agg["ok"]
        except Exception as exc:  # noqa: BLE001
            rows.append({
                "cluster": cluster_path.stem,
                "error": f"{type(exc).__name__}: {exc}",
            })

    # Pretty-print.
    print(f"\n{'cluster':30}  {'inst':>5}  {'ok/tot':>8}  {'review':>7}")
    print("-" * 60)
    for r in rows:
        if "error" in r:
            print(f"{r['cluster']:30}  ERROR: {r['error'][:40]}")
            continue
        print(
            f"{r['cluster']:30}  {r['instances']:>5}  "
            f"{r['ok']}/{r['total']:>3}      {r['review']:>4}"
        )
    print("-" * 60)
    print(f"{'TOTAL':30}  {'':>5}  {grand_ok}/{grand_total} byte-equivalent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
