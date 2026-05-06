"""Derive a pattern.yaml from N tutorial instances of one cluster.

Given a cluster (e.g. all 6 ECCCGrids importers, each contributing
Import<NWP>.xml + Import<NWP>Grids.xml), this tool:

  1. Parses each XML → routes through the matching Pydantic schema
     → dumps a canonical dict.
  2. Walks all instance-dicts of the same output position in parallel,
     leaf-by-leaf, classifying paths as:
       - constant: all instances share the same value → bake into pattern
       - variable: values differ → declare as a pattern variable
       - structural divergence: present in some, absent in others →
         flag for human review (deferred — needs `workflow_shape`-style
         discriminator handling).
  3. Computes the output_path template by string-diffing each
     instance's file path against instance 0; varying chunks become
     ``{{ instance_label }}`` placeholders.
  4. Emits a draft ``pattern.yaml`` with mechanical variable names
     (e.g. ``import_0_general_relativeViewPeriod_start``). LLM polish
     to rename + add descriptions is a follow-up step, not part of
     this deterministic backbone.

Round-trip self-check: render the derived pattern with each
instance's variable values and diff against the original XML. If
non-equivalent, the deriver missed something.

Usage::

    python scripts/derive_pattern.py            # built-in nwp_grid demo
    python scripts/derive_pattern.py --cluster <path-to-cluster.yaml>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml
from lxml import etree

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from fews_agent.agent.blueprint import schema_class_for  # noqa: E402
from fews_agent.generators.base import canonicalize, render as render_template  # noqa: E402

TUTORIAL = REPO_ROOT / "examples" / "config-tutorial"


# ---------------------------------------------------------------------------
# Source data: tutorial input JSON
# ---------------------------------------------------------------------------

# The tutorial config-tutorial-input.json holds the canonical
# Pydantic-shape dicts the existing generators consume. Reading from
# there lets the deriver work in the same dict shape patterns produce —
# no XML parsing heuristics needed.

_TUTORIAL_INPUT_JSON: dict[str, Any] | None = None


def _tutorial_data(input_key: str) -> dict[str, Any]:
    """Load the tutorial's canonical input dict for one SPEC by key."""
    global _TUTORIAL_INPUT_JSON
    if _TUTORIAL_INPUT_JSON is None:
        path = REPO_ROOT / "examples" / "config-tutorial-input.json"
        _TUTORIAL_INPUT_JSON = json.loads(path.read_text(encoding="utf-8"))
    if input_key not in _TUTORIAL_INPUT_JSON:
        raise KeyError(f"input_key {input_key!r} missing from tutorial input")
    return _TUTORIAL_INPUT_JSON[input_key]


# ---------------------------------------------------------------------------
# Parallel-walk diff
# ---------------------------------------------------------------------------

def diff_dicts(
    dicts: list[Any], path: tuple = ()
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Walk a list of parallel structures; return (varying_leaves, structural_divergences)."""
    varying: list[dict[str, Any]] = []
    divergent: list[dict[str, Any]] = []

    if all(isinstance(d, dict) for d in dicts):
        keys: list[str] = []
        for d in dicts:
            for k in d.keys():
                if k not in keys:
                    keys.append(k)
        for k in keys:
            present = [k in d for d in dicts]
            if not all(present):
                divergent.append(
                    {"path": path + (k,), "presence": present}
                )
                continue
            sub_v, sub_d = diff_dicts(
                [d[k] for d in dicts], path + (k,)
            )
            varying.extend(sub_v)
            divergent.extend(sub_d)
        return varying, divergent

    if all(isinstance(d, list) for d in dicts):
        lens = {len(d) for d in dicts}
        if len(lens) > 1:
            divergent.append(
                {"path": path, "lengths": [len(d) for d in dicts]}
            )
            return varying, divergent
        for i in range(len(dicts[0])):
            sub_v, sub_d = diff_dicts(
                [d[i] for d in dicts], path + (i,)
            )
            varying.extend(sub_v)
            divergent.extend(sub_d)
        return varying, divergent

    # Leaf — compare reprs. Differing types or values → varying.
    reprs = {repr(d) for d in dicts}
    if len(reprs) == 1:
        return varying, divergent
    varying.append({"path": path, "values": list(dicts)})
    return varying, divergent


# ---------------------------------------------------------------------------
# Pattern emission
# ---------------------------------------------------------------------------

def _var_name(path: tuple) -> str:
    """Mechanical variable name from leaf path."""
    parts = [str(p).replace("@", "") for p in path]
    # Drop integer indices that just denote list position 0 — not
    # informative.
    pretty = [p for p in parts if not (p.isdigit() and int(p) == 0)]
    name = "_".join(pretty) or "var"
    return name


def _set_at_path(d: Any, path: tuple, value: Any) -> Any:
    """Return a copy of d with value placed at path."""
    if not path:
        return value
    head, *tail = path
    if isinstance(d, list):
        new = list(d)
        new[head] = _set_at_path(new[head] if head < len(new) else {}, tuple(tail), value)
        return new
    if isinstance(d, dict):
        new = dict(d)
        new[head] = _set_at_path(new.get(head, {}), tuple(tail), value)
        return new
    return value


def _output_path_template(
    paths: list[str], labels: list[str], label_var_name: str
) -> str:
    """Compute an output template by replacing each label occurrence with a placeholder."""
    if not paths:
        return ""
    template = paths[0]
    label_0 = labels[0]
    if label_0 in template:
        template = template.replace(
            label_0, "{{ " + label_var_name + " }}"
        )
    return template


def derive_pattern(
    cluster_name: str,
    output_specs: list[dict[str, Any]],
    instances: list[dict[str, Any]],
    label_var_name: str = "nwp_name",
) -> tuple[dict[str, Any], dict[str, list[Any]]]:
    """Derive a pattern.yaml-shaped dict from N parallel instances.

    Args:
      cluster_name: e.g. "nwp_grid".
      output_specs: [{"role": "import_file", "schema": "TimeSeriesImportRun",
                      "files": ["ImportHRDPS.xml", "ImportGDPS.xml", ...]}, ...]
      instances: [{"label": "HRDPS", "vars": {...optional known}}, ...]
    """
    pattern: dict[str, Any] = {
        "name": cluster_name,
        "description": f"Auto-derived pattern from tutorial instances: "
                       f"{', '.join(i['label'] for i in instances)}.",
        "variables": {
            label_var_name: {"type": "str", "required": True},
        },
        "outputs": [],
        "contributions": [],
    }
    discovered_vars: dict[tuple, str] = {}
    # Per-instance value map: {var_name: [value_for_each_instance]}.
    # Used by round_trip_check to feed the derived pattern with correct
    # values for each instance and verify byte-equivalence.
    var_values_per_instance: dict[str, list[Any]] = {
        label_var_name: [inst["label"] for inst in instances],
    }

    for spec in output_specs:
        # Pull all instance dicts from the tutorial input JSON.
        dicts = [dict(_tutorial_data(k)) for k in spec["input_keys"]]

        varying, divergent = diff_dicts(dicts)

        # Build the data shape: take instance 0's dict, replace each
        # varying path with a Jinja placeholder.
        data = dicts[0]
        for v in varying:
            path = v["path"]
            name = _var_name(path)
            # Disambiguate against existing var names.
            base = name
            i = 1
            existing_paths = {p for p in discovered_vars}
            while name in {discovered_vars.get(p) for p in existing_paths if p != path}:
                name = f"{base}_{i}"
                i += 1
            discovered_vars[path] = name
            placeholder = "{{ " + name + " }}"
            data = _set_at_path(data, path, placeholder)
            if name not in pattern["variables"]:
                pattern["variables"][name] = {
                    "type": _infer_type(v["values"]),
                    "default": v["values"][0],
                }
            var_values_per_instance[name] = list(v["values"])

        pattern["outputs"].append({
            "schema": spec["schema"],
            "output": _output_path_template(
                spec["output_paths"],
                [i["label"] for i in instances],
                label_var_name,
            ),
            "data": data,
        })

        if divergent:
            pattern.setdefault("_review", []).extend(
                [{"output_role": spec.get("role", "?"), **d} for d in divergent]
            )

    return pattern, var_values_per_instance


def _infer_type(values: list[Any]) -> str:
    if all(isinstance(v, bool) for v in values):
        return "bool"
    if all(isinstance(v, int) for v in values):
        return "int"
    if all(isinstance(v, (int, float)) for v in values):
        return "float"
    return "str"


# ---------------------------------------------------------------------------
# Cluster splitting (shape fingerprinting)
# ---------------------------------------------------------------------------

def _fingerprint_instance(
    output_specs: list[dict[str, Any]], instance_idx: int
) -> set[tuple]:
    """Compact shape fingerprint for one instance — the set of leaf
    paths in its dicts, with list indices collapsed to ``*``.

    Two instances of the same pattern have nearly identical
    fingerprints; instances of different patterns (lumped together by
    naive directory-mining) have very different fingerprints.
    """
    paths: set[tuple] = set()
    for spec in output_specs:
        try:
            d = _tutorial_data(spec["input_keys"][instance_idx])
        except KeyError:
            continue
        paths.update(_collect_paths(d, ()))
    return paths


def _collect_paths(obj: Any, prefix: tuple) -> set[tuple]:
    if isinstance(obj, dict):
        out: set[tuple] = set()
        for k, v in obj.items():
            out.update(_collect_paths(v, prefix + (str(k),)))
        return out
    if isinstance(obj, list):
        out = set()
        for item in obj:
            out.update(_collect_paths(item, prefix + ("*",)))
        return out
    return {prefix}


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


def detect_splits(
    output_specs: list[dict[str, Any]],
    instances: list[dict[str, Any]],
    threshold: float = 0.85,
    recursive: bool = True,
) -> list[tuple[str, list[int]]]:
    """Group instances into homogeneous sub-clusters by shape fingerprint.

    Returns a list of ``(sub_cluster_label, [instance_indices])`` tuples.
    If only one group emerges, the cluster is homogeneous; if more,
    splitting is recommended.
    """
    fingerprints = [
        _fingerprint_instance(output_specs, i) for i in range(len(instances))
    ]
    n = len(instances)
    assigned = [False] * n
    groups: list[list[int]] = []
    for i in range(n):
        if assigned[i]:
            continue
        group = [i]
        assigned[i] = True
        for j in range(i + 1, n):
            if assigned[j]:
                continue
            # Average similarity of j to existing members of group.
            avg_sim = sum(
                _jaccard(fingerprints[k], fingerprints[j]) for k in group
            ) / len(group)
            if avg_sim >= threshold:
                group.append(j)
                assigned[j] = True
        groups.append(group)

    out: list[tuple[str, list[int]]] = []
    for group in groups:
        label = "_".join(instances[k]["label"] for k in group)
        # If recursive: try the deriver on this sub-group; if it has
        # any structural divergences, split further by raising the
        # similarity threshold until the divergences disappear or the
        # group reaches a single instance.
        if recursive and len(group) > 1:
            sub_specs, sub_instances = slice_cluster(
                output_specs, instances, group
            )
            try:
                sub_derived, _ = derive_pattern(
                    "test", sub_specs, sub_instances, "instance_label"
                )
                if sub_derived.get("_review"):
                    # Try a tighter threshold to break this group.
                    sub_groups = _split_with_higher_threshold(
                        sub_specs, sub_instances, threshold
                    )
                    if len(sub_groups) > 1:
                        # Map sub-group indices back to the original
                        # instance indices.
                        for sub_label, sub_indices in sub_groups:
                            mapped = [group[i] for i in sub_indices]
                            mapped_label = "_".join(
                                instances[k]["label"] for k in mapped
                            )
                            out.append((mapped_label, mapped))
                        continue
            except Exception:
                # If anything goes wrong, fall through to non-recursive.
                pass
        out.append((label, group))
    return out


def _split_with_higher_threshold(
    output_specs: list[dict[str, Any]],
    instances: list[dict[str, Any]],
    base_threshold: float,
) -> list[tuple[str, list[int]]]:
    """Try increasingly strict thresholds until the cluster splits into
    homogeneous sub-clusters (each producing 0 ``_review`` items)."""
    for thr in [base_threshold + 0.05, base_threshold + 0.10, 0.99]:
        groups = detect_splits(
            output_specs, instances, threshold=thr, recursive=False,
        )
        if len(groups) > 1:
            # Verify each sub-group is now divergence-free; if not,
            # recurse further by re-splitting the divergent sub-groups.
            final: list[tuple[str, list[int]]] = []
            all_clean = True
            for label, indices in groups:
                if len(indices) <= 1:
                    final.append((label, indices))
                    continue
                sub_specs, sub_instances = slice_cluster(
                    output_specs, instances, indices
                )
                sub_derived, _ = derive_pattern(
                    "test", sub_specs, sub_instances, "instance_label"
                )
                if sub_derived.get("_review"):
                    all_clean = False
                    # Recurse on this sub-group.
                    rec = _split_with_higher_threshold(
                        sub_specs, sub_instances, thr
                    )
                    for sub_label, sub_indices in rec:
                        mapped = [indices[i] for i in sub_indices]
                        mapped_label = "_".join(
                            instances[k]["label"] for k in mapped
                        )
                        final.append((mapped_label, mapped))
                else:
                    final.append((label, indices))
            return final
    # Couldn't split any further — fall back to one-instance-per-group.
    return [
        (instances[i]["label"], [i]) for i in range(len(instances))
    ]


def slice_cluster(
    output_specs: list[dict[str, Any]],
    instances: list[dict[str, Any]],
    indices: list[int],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build a sub-cluster's output_specs + instances from selected indices."""
    sub_specs = [
        {
            **spec,
            "input_keys": [spec["input_keys"][i] for i in indices],
            "output_paths": [spec["output_paths"][i] for i in indices],
        }
        for spec in output_specs
    ]
    sub_instances = [instances[i] for i in indices]
    return sub_specs, sub_instances


# ---------------------------------------------------------------------------
# Variable coupling (deterministic)
# ---------------------------------------------------------------------------

def couple_variables(
    pattern: dict[str, Any],
    var_values_per_instance: dict[str, list[Any]],
    label_var_name: str = "nwp_name",
) -> tuple[dict[str, Any], dict[str, list[Any]]]:
    """Collapse mechanical variables that share the same per-instance values.

    If 5 mechanical variables (e.g. ``import_timeSeriesSet_locationId``,
    ``import_timeSeriesSet_moduleInstanceId``, ...) all take values
    ``[HRDPS, GDPS, RDPS]`` across instances, they are guaranteed to be
    the same semantic variable — coalesce into one. The canonical name
    is the first mechanical name in the group (LLM polish renames it
    later).

    String/int variants of the same value (e.g. ``1`` vs ``"1"``) are
    coupled by comparing string-coerced values; the canonical type
    follows the first member.

    Returns ``(updated_pattern, updated_var_values)``.
    """
    # Bucket variables by their string-normalised value tuple.
    buckets: dict[tuple, list[str]] = {}
    for name, values in var_values_per_instance.items():
        key = tuple(str(v) for v in values)
        buckets.setdefault(key, []).append(name)

    # Build rename map: each bucket member → canonical name (first member).
    # The label_var_name always wins its bucket if present.
    rename: dict[str, str] = {}
    for members in buckets.values():
        canonical = label_var_name if label_var_name in members else members[0]
        for m in members:
            rename[m] = canonical

    # Skip if no coalescing possible.
    if all(canonical == name for name, canonical in rename.items()):
        return pattern, var_values_per_instance

    # Rewrite the variables block: keep only canonicals; drop coalesced.
    new_variables: dict[str, Any] = {}
    seen_canonicals: set[str] = set()
    for name, spec in pattern["variables"].items():
        canonical = rename.get(name, name)
        if canonical in seen_canonicals:
            continue
        if canonical == name:
            new_variables[name] = spec
            seen_canonicals.add(canonical)
        else:
            # Use the canonical's spec instead.
            canonical_spec = pattern["variables"].get(canonical, spec)
            if canonical not in seen_canonicals:
                new_variables[canonical] = canonical_spec
                seen_canonicals.add(canonical)
    pattern["variables"] = new_variables

    # Rewrite the data blocks: replace {{ old_name }} with {{ canonical }}.
    for output in pattern["outputs"]:
        output["data"] = _rename_placeholders(output["data"], rename)
        output["output"] = _rename_placeholders_str(output["output"], rename)

    # Updated var values (one entry per canonical).
    new_var_values: dict[str, list[Any]] = {}
    for name, values in var_values_per_instance.items():
        canonical = rename.get(name, name)
        if canonical not in new_var_values:
            new_var_values[canonical] = values

    return pattern, new_var_values


def _rename_placeholders(obj: Any, rename: dict[str, str]) -> Any:
    if isinstance(obj, str):
        return _rename_placeholders_str(obj, rename)
    if isinstance(obj, dict):
        return {k: _rename_placeholders(v, rename) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_rename_placeholders(v, rename) for v in obj]
    return obj


def _rename_placeholders_str(s: str, rename: dict[str, str]) -> str:
    """Replace ``{{ old_name }}`` (with optional whitespace) with ``{{ new_name }}``."""
    import re
    out = s
    for old, new in rename.items():
        if old == new:
            continue
        # Match {{ old }} or {{ old}} or {{old}} etc.
        pattern = re.compile(
            r"\{\{\s*" + re.escape(old) + r"\s*\}\}"
        )
        out = pattern.sub("{{ " + new + " }}", out)
    return out


# ---------------------------------------------------------------------------
# Round-trip self-check
# ---------------------------------------------------------------------------

def round_trip_check(
    output_specs: list[dict[str, Any]],
    instances: list[dict[str, Any]],
    derived: dict[str, Any],
    var_values_per_instance: dict[str, list[Any]],
    label_var_name: str = "nwp_name",
    yaml_text: str | None = None,
) -> dict[str, Any]:
    """Render the derived pattern with each instance's vars; diff vs tutorial.

    This exercises the **derived pattern**, not the source dict — so a
    drift here means the deriver missed a varying path or mishandled
    a structural divergence. ``ok`` means the derived pattern faithfully
    reproduces the tutorial XML for that instance.

    Per-instance status:
      - ``ok``: byte-equivalent.
      - ``drift``: rendered + valid but bytes differ (deriver bug).
      - ``error``: render or model_validate raised.
      - ``no_tutorial_xml``: tutorial file missing on disk.
    """
    from jinja2 import Environment, StrictUndefined

    from fews_agent.agent.blueprint import template_for_schema

    raw_text = yaml_text if yaml_text is not None else yaml.safe_dump(
        derived, sort_keys=False
    )
    env = Environment(undefined=StrictUndefined, keep_trailing_newline=True)

    summary = {"per_instance": []}
    for i, inst in enumerate(instances):
        # Build the var dict for this instance from the deriver's
        # recorded per-instance values.
        vars_for_inst: dict[str, Any] = {}
        for var_name, values in var_values_per_instance.items():
            vars_for_inst[var_name] = values[i]

        results: list[dict[str, Any]] = []
        try:
            rendered_yaml_text = env.from_string(raw_text).render(**vars_for_inst)
            spec = yaml.safe_load(rendered_yaml_text)
        except Exception as exc:  # noqa: BLE001
            results.append({
                "file": "(yaml render)",
                "status": "error",
                "msg": f"{type(exc).__name__}: {exc}",
            })
            summary["per_instance"].append(
                {"label": inst["label"], "results": results}
            )
            continue

        for spec_idx, output_spec in enumerate(output_specs):
            output_decl = spec["outputs"][spec_idx]
            tutorial_relpath = output_spec["output_paths"][i]
            try:
                cls = schema_class_for(output_decl["schema"])
                model = cls.model_validate(output_decl["data"])
                xml = render_template(template_for_schema(cls), model)
                tutorial_path = TUTORIAL / tutorial_relpath
                if not tutorial_path.is_file():
                    results.append({
                        "file": tutorial_relpath, "status": "no_tutorial_xml",
                    })
                    continue
                eq = canonicalize(xml.encode("utf-8")) == canonicalize(
                    tutorial_path.read_bytes()
                )
                results.append({
                    "file": tutorial_relpath,
                    "status": "ok" if eq else "drift",
                })
            except Exception as exc:  # noqa: BLE001
                results.append({
                    "file": tutorial_relpath,
                    "status": "error",
                    "msg": f"{type(exc).__name__}: {exc}",
                })

        summary["per_instance"].append(
            {"label": inst["label"], "results": results}
        )

    total = sum(len(p["results"]) for p in summary["per_instance"])
    ok = sum(
        1 for p in summary["per_instance"] for r in p["results"]
        if r["status"] == "ok"
    )
    summary["aggregate"] = {"ok": ok, "total": total}
    return summary


# ---------------------------------------------------------------------------
# Demo: derive nwp_grid from tutorial
# ---------------------------------------------------------------------------

def demo_nwp_grid_specs() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (output_specs, instances) for the nwp_grid demo cluster."""
    nwps = ["HRDPS", "GDPS", "RDPS"]
    output_specs = [
        {
            "role": "import_file",
            "schema": "TimeSeriesImportRun",
            "input_keys": [f"import{n}" for n in nwps],
            "output_paths": [
                f"ModuleConfigFiles/Import/ECCCGrids/Import{n}.xml" for n in nwps
            ],
        },
        {
            "role": "workflow_file",
            "schema": "Workflow",
            "input_keys": [f"import{n}GridsWorkflow" for n in nwps],
            "output_paths": [
                f"WorkflowFiles/Import/ECCCGrids/Import{n}Grids.xml" for n in nwps
            ],
        },
    ]
    instances = [{"label": n} for n in nwps]
    return output_specs, instances


def load_cluster_config(
    config_path: Path,
) -> tuple[
    str, str, list[dict[str, Any]], list[dict[str, Any]]
]:
    """Read a cluster config YAML; return (name, label_var, output_specs, instances).

    Cluster YAML shape::

        name: snow_grid
        label_var: snow_source
        instances: [GLOBSNOW, SNODAS]
        outputs:
          - role: import_file
            schema: TimeSeriesImportRun
            input_key_template: "import{label}"
            output_path_template: "ModuleConfigFiles/Import/Snow/Import{label}.xml"
    """
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    name = cfg["name"]
    label_var = cfg.get("label_var", "instance_label")
    labels = cfg["instances"]
    instances = [{"label": label} for label in labels]

    output_specs: list[dict[str, Any]] = []
    for out in cfg["outputs"]:
        output_specs.append({
            "role": out["role"],
            "schema": out["schema"],
            "input_keys": [
                _format_label(out["input_key_template"], label) for label in labels
            ],
            "output_paths": [
                _format_label(out["output_path_template"], label) for label in labels
            ],
        })
    return name, label_var, output_specs, instances


def _format_label(template: str, label: str) -> str:
    """Substitute ``{label}``, ``{label_lower}``, ``{label_upper}``, ``{label_title}``.

    Tutorial input keys mix casings: ``liardForecastTemplate`` (start)
    vs ``runLiardHistoricWorkflow`` (mid-string). The cluster YAML
    chooses the right placeholder per output.
    """
    return template.format(
        label=label,
        label_lower=label.lower(),
        label_upper=label.upper(),
        label_title=label[:1].upper() + label[1:] if label else label,
    )


def process_cluster(
    cluster_name: str,
    label_var: str,
    output_specs: list[dict[str, Any]],
    instances: list[dict[str, Any]],
    *,
    polish: bool,
    polish_model: str,
) -> tuple[dict[str, Any], dict[str, list[Any]], str, dict[str, Any]]:
    """One cluster end-to-end: derive → couple → (optional polish) → round-trip."""
    derived, var_values = derive_pattern(
        cluster_name=cluster_name,
        output_specs=output_specs,
        instances=instances,
        label_var_name=label_var,
    )
    derived, var_values = couple_variables(derived, var_values, label_var)
    out_text: str | None = None

    if polish:
        from fews_agent.agent.pattern_polish import (
            identify_discriminators, inject_jinja_conditionals,
            polish_variable_names,
        )
        schema_names = sorted({o["schema"] for o in derived["outputs"]})
        derived, var_values = polish_variable_names(
            pattern=derived,
            var_values_per_instance=var_values,
            label_var_name=label_var,
            schema_names=schema_names,
            model=polish_model,
        )
        review = derived.get("_review", [])
        if review:
            per_output = [
                [_tutorial_data(k) for k in spec["input_keys"]]
                for spec in output_specs
            ]
            derived, var_values = identify_discriminators(
                pattern=derived,
                instances=instances,
                review_items=review,
                per_instance_source_data=per_output,
                schema_names=schema_names,
                var_values_per_instance=var_values,
                model=polish_model,
            )
            out_text = inject_jinja_conditionals(
                pattern=derived,
                review_items=review,
                per_instance_source_data=per_output,
                instances=instances,
                var_values_per_instance=var_values,
            )

    if out_text is None:
        out_text = yaml.safe_dump(derived, sort_keys=False, width=200)

    rt = round_trip_check(
        output_specs, instances, derived, var_values, label_var,
        yaml_text=out_text,
    )
    return derived, var_values, out_text, rt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=None, help="Where to write the derived pattern.yaml")
    parser.add_argument(
        "--cluster", default=None,
        help="Path to a cluster config YAML. Defaults to built-in nwp_grid demo.",
    )
    parser.add_argument("--no-round-trip", action="store_true")
    parser.add_argument(
        "--auto-split", action="store_true",
        help=(
            "Detect heterogeneous clusters and split into homogeneous "
            "sub-clusters before deriving. Each sub-cluster yields its "
            "own pattern.yaml."
        ),
    )
    parser.add_argument(
        "--polish", action="store_true",
        help="Apply qwen2.5:7b LLM polish to suggest semantic variable names.",
    )
    parser.add_argument(
        "--polish-model", default="qwen2.5:7b-instruct",
        help="Ollama model id for the polish step.",
    )
    args = parser.parse_args()

    if args.cluster:
        cluster_name, label_var, output_specs, instances = load_cluster_config(
            Path(args.cluster)
        )
    else:
        output_specs, instances = demo_nwp_grid_specs()
        cluster_name = "nwp_grid_derived"
        label_var = "nwp_name"

    # Auto-split: detect heterogeneous clusters and process each
    # sub-cluster as its own pattern.
    if args.auto_split:
        splits = detect_splits(output_specs, instances)
        if len(splits) > 1:
            print(f"Cluster split into {len(splits)} homogeneous sub-clusters:")
            for label, indices in splits:
                members = [instances[i]["label"] for i in indices]
                print(f"  {label}: {members}")
            print()
        clusters_to_process = [
            (
                cluster_name if len(splits) == 1
                else f"{cluster_name}_{label}",
                indices,
            )
            for label, indices in splits
        ]
    else:
        clusters_to_process = [(cluster_name, list(range(len(instances))))]

    grand_ok = grand_total = 0
    for sub_name, indices in clusters_to_process:
        sub_specs, sub_instances = slice_cluster(
            output_specs, instances, indices
        )
        derived, var_values, out_text, rt = process_cluster(
            cluster_name=sub_name,
            label_var=label_var,
            output_specs=sub_specs,
            instances=sub_instances,
            polish=args.polish,
            polish_model=args.polish_model,
        )

        out_path = Path(args.out) if args.out else (
            REPO_ROOT / "data" / "patterns" / f"derived_{sub_name}.yaml"
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(out_text, encoding="utf-8")

        agg = rt["aggregate"]
        grand_ok += agg["ok"]
        grand_total += agg["total"]
        print(f"  [{sub_name}] vars={len(derived.get('variables', {}))} "
              f"outputs={len(derived.get('outputs', []))} "
              f"round-trip={agg['ok']}/{agg['total']} "
              f"({out_path.name})")
        if not args.no_round_trip:
            for p in rt["per_instance"]:
                badges = [
                    {"ok": "[OK]", "drift": "[DRIFT]",
                     "error": "[ERR]", "no_tutorial_xml": "[-]"}.get(
                        r["status"], "[?]"
                    ) + " " + r["file"]
                    for r in p["results"]
                ]
                print(f"      {p['label']}: " + ", ".join(badges))

    if len(clusters_to_process) > 1:
        print(f"\nGrand total round-trip: {grand_ok}/{grand_total} byte-equivalent")
