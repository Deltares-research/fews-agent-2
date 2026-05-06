"""Full-tutorial reproduction via patterns + CSVs end-to-end.

For every cluster YAML in ``data/patterns/clusters/``:

  1. Run the deriver pipeline (mechanical extraction + recursive
     auto-split). Each sub-cluster yields one pattern + a map of
     ``{var_name: [values per instance]}``.
  2. Write the derived pattern.yaml under
     ``patterns/auto/<sub_cluster_name>/pattern.yaml`` so the runtime
     blueprint expander can find it.
  3. Append a `patterns:` entry to ``tutorial.project.yaml`` with the
     derived var_values as instance-level overrides.

Then writes CSV files for tabular singletons (Locations, Parameters,
Qualifiers, ThresholdWarningLevels) by extracting their tutorial
input dicts and converting back to tabular form.

Finally calls ``build_from_blueprint`` on the assembled project and
reports per-file byte-equivalent count vs the tutorial.

Usage::

    python scripts/build_tutorial_full.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.derive_pattern import (  # noqa: E402
    detect_splits, derive_pattern, couple_variables, load_cluster_config,
    slice_cluster, _tutorial_data,
)
from runners.agent.build_from_blueprint import build_from_blueprint  # noqa: E402

PATTERNS_DIR = REPO_ROOT / "patterns" / "auto"
TUTORIAL_PROJECT_DIR = REPO_ROOT / "examples" / "blueprints" / "tutorial-full"
TUTORIAL_DIR = REPO_ROOT / "examples" / "config-tutorial"


def derive_and_write_pattern(
    cluster_yaml_path: Path,
) -> list[tuple[str, dict[str, list[Any]], list[str]]]:
    """Run the deriver pipeline on one cluster YAML.

    Returns a list of ``(sub_cluster_name, var_values_per_instance,
    instance_labels)`` — one entry per derived pattern (auto-split may
    yield multiple sub-clusters from one input cluster).
    """
    name, label_var, output_specs, instances = load_cluster_config(
        cluster_yaml_path
    )
    splits = detect_splits(output_specs, instances)
    out: list[tuple[str, dict[str, list[Any]], list[str]]] = []

    for label, indices in splits:
        sub_specs, sub_instances = slice_cluster(
            output_specs, instances, indices
        )
        sub_name = name if len(splits) == 1 else f"{name}_{label}"
        derived, var_values = derive_pattern(
            cluster_name=sub_name,
            output_specs=sub_specs,
            instances=sub_instances,
            label_var_name=label_var,
        )
        derived, var_values = couple_variables(derived, var_values, label_var)

        # Write the derived pattern under patterns/auto/<sub_name>/.
        pat_dir = PATTERNS_DIR / sub_name
        pat_dir.mkdir(parents=True, exist_ok=True)
        (pat_dir / "pattern.yaml").write_text(
            yaml.safe_dump(derived, sort_keys=False, width=200),
            encoding="utf-8",
        )
        out.append((
            sub_name, var_values,
            [inst["label"] for inst in sub_instances],
        ))
    return out


def build_csv_inputs(inputs_dir: Path) -> None:
    """Write CSVs for tabular singletons from the tutorial input dict."""
    import json
    data = json.loads(
        (REPO_ROOT / "examples" / "config-tutorial-input.json")
        .read_text(encoding="utf-8")
    )
    inputs_dir.mkdir(parents=True, exist_ok=True)

    # Locations
    locations = data.get("locations", {}).get("location", [])
    if locations:
        rows = ["id,name,x,y,description"]
        for loc in locations:
            rows.append(
                f"{loc.get('id','')},{loc.get('name','')},"
                f"{loc.get('x','')},{loc.get('y','')},"
                f"{(loc.get('description') or '').replace(',', ';')}"
            )
        (inputs_dir / "locations.csv").write_text(
            "\n".join(rows) + "\n", encoding="utf-8"
        )

    # Parameters — flatten parameterGroups
    pg_list = data.get("parameters", {}).get("parameterGroup", [])
    if pg_list:
        rows = ["id,name,shortName,group,unit,parameterType"]
        for pg in pg_list:
            for p in pg.get("parameter", []):
                rows.append(
                    f"{p.get('id','')},{p.get('name') or ''},"
                    f"{p.get('shortName','')},"
                    f"{pg.get('id','')},{pg.get('unit','')},"
                    f"{pg.get('parameterType','')}"
                )
        (inputs_dir / "parameters.csv").write_text(
            "\n".join(rows) + "\n", encoding="utf-8"
        )

    # Qualifiers
    qualifiers = data.get("qualifiers", {}).get("qualifier", [])
    if qualifiers:
        rows = ["id,name,group"]
        for q in qualifiers:
            rows.append(
                f"{q.get('id','')},{q.get('name') or ''},{q.get('group','')}"
            )
        (inputs_dir / "qualifiers.csv").write_text(
            "\n".join(rows) + "\n", encoding="utf-8"
        )

    # ThresholdWarningLevels
    twl = data.get("thresholdWarningLevels", {}).get(
        "thresholdWarningLevel", []
    )
    if twl:
        rows = [
            "id,name,color,iconName,historicOverlayIconName,"
            "forecastOverlayIconName"
        ]
        for w in twl:
            rows.append(
                f"{w.get('id','')},{w.get('name') or ''},"
                f"{w.get('color','')},{w.get('iconName','')},"
                f"{w.get('historicOverlayIconName','')},"
                f"{w.get('forecastOverlayIconName','')}"
            )
        (inputs_dir / "thresholdWarningLevels.csv").write_text(
            "\n".join(rows) + "\n", encoding="utf-8"
        )


def build_project_yaml(
    pattern_records: list[tuple[str, dict[str, list[Any]], list[str]]],
    out_path: Path,
) -> None:
    """Compose the tutorial project.yaml referencing all derived patterns."""
    patterns_block: list[dict] = []
    for sub_name, var_values, labels in pattern_records:
        # Build instance dicts: each instance has var_name -> value at that index
        instances = []
        for i, label in enumerate(labels):
            inst: dict[str, Any] = {}
            for var_name, values in var_values.items():
                if i < len(values):
                    inst[var_name] = values[i]
            instances.append(inst)
        patterns_block.append({
            "pattern": f"auto/{sub_name}",
            "instances": instances,
        })

    # Compute which SPEC input_keys are NOT already covered by:
    #   (a) pattern outputs (already rendered)
    #   (b) the four CSV-driven specs
    # Everything left in tutorial-input.json gets rendered as a direct
    # singleton from JSON.
    import json
    tutorial_input_path = REPO_ROOT / "examples" / "config-tutorial-input.json"
    tutorial_input = json.loads(tutorial_input_path.read_text(encoding="utf-8"))

    from fews_agent.generators import SPECS
    pattern_input_keys: set[str] = set()
    for sub_name, var_values, labels in pattern_records:
        # Per pattern, look up the auto-derived pattern.yaml and find
        # the input_key it relies on (via output paths). Skip — too
        # fiddly to track precisely. Use a heuristic: if the cluster
        # YAML named input_key_template that resolves to a tutorial
        # entry, mark it as covered.
        pass

    # Rather than complex tracking, rebuild the covered set from the
    # cluster YAMLs directly:
    clusters_dir = REPO_ROOT / "data" / "patterns" / "clusters"
    for cluster_yaml in clusters_dir.glob("*.yaml"):
        cluster_data = yaml.safe_load(cluster_yaml.read_text(encoding="utf-8"))
        labels = cluster_data.get("instances", [])
        for out_spec in cluster_data.get("outputs", []):
            template = out_spec.get("input_key_template", "")
            for label in labels:
                key = template.format(
                    label=label, label_lower=label.lower(),
                    label_upper=label.upper(),
                    label_title=label[:1].upper() + label[1:] if label else label,
                )
                pattern_input_keys.add(key)

    # Pattern-covered keys are excluded from direct_singletons (would
    # produce duplicate output paths). CSV-covered keys ARE included,
    # because direct_singletons runs after the CSV path and overwrites
    # CSV-rendered files with the lossless JSON-derived version. CSVs
    # remain useful as base_data for the contribution merger.
    direct_specs: list[str] = []
    for s in SPECS:
        if s.input_key in tutorial_input and s.input_key not in pattern_input_keys:
            direct_specs.append(s.name)

    project = {
        "name": "tutorial-full",
        "output_root": "../../../validation/tutorial-full/generated",
        "patterns": patterns_block,
        "singleton_seeds": {
            # Locations gets a baseline geoDatum; CSV adds rows; pattern
            # contributions add NWP grids on top.
            "Locations": {
                "geoDatum": "WGS 1984",
            },
        },
        "direct_singletons": {
            "source": "../../config-tutorial-input.json",
            "specs": direct_specs,
        },
    }
    print(f"  direct singletons: {len(direct_specs)} specs not covered by "
          f"patterns/CSVs")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        yaml.safe_dump(project, sort_keys=False, width=200),
        encoding="utf-8",
    )


def main() -> int:
    clusters_dir = REPO_ROOT / "data" / "patterns" / "clusters"

    # Step 1: derive each cluster, write to patterns/auto/, collect records.
    pattern_records: list[tuple[str, dict[str, list[Any]], list[str]]] = []
    for cluster_yaml in sorted(clusters_dir.glob("*.yaml")):
        try:
            recs = derive_and_write_pattern(cluster_yaml)
            pattern_records.extend(recs)
        except Exception as exc:  # noqa: BLE001
            print(f"  ERR {cluster_yaml.name}: {exc}")
    print(f"Derived {len(pattern_records)} sub-cluster patterns")

    # Step 2: build CSVs.
    inputs_dir = TUTORIAL_PROJECT_DIR / "inputs"
    build_csv_inputs(inputs_dir)
    print(f"Wrote tabular CSVs to {inputs_dir}")

    # Step 3: build the project.yaml.
    project_yaml = TUTORIAL_PROJECT_DIR / "project.yaml"
    build_project_yaml(pattern_records, project_yaml)
    print(f"Wrote {project_yaml}")

    # Step 4: run the build, diff against tutorial.
    summary = build_from_blueprint(
        blueprint_path=project_yaml,
        pattern_root=REPO_ROOT / "patterns",
        inputs_dir=inputs_dir,
        diff_against=TUTORIAL_DIR,
    )

    print()
    print("=" * 60)
    print(f"Files generated:        {summary.get('files_total', 0)}")
    print(f"XSD-valid:              {summary.get('files_xsd_ok', 0)}")
    print(f"Byte-equivalent vs tutorial: "
          f"{summary.get('byte_equivalent_vs_tutorial', '—')}")
    print("=" * 60)
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
