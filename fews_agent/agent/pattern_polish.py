"""LLM polish for derived patterns — semantic naming via qwen.

Phase 1 (this module): take a deterministically-derived pattern with
mechanical variable names and call a local LLM (qwen2.5:7b-instruct
via Ollama) to suggest semantic names + descriptions. The LLM output
is constrained to JSON schema, so it can only rename — it can't
invent new variables, change values, or alter pattern shape.

Phase 2 (deferred): discriminator detection for structural
divergences. Not in this module yet.

Round-trip safety: after polish, the derived pattern's *behavior*
must be identical to before — only variable names + descriptions
change. The polish step renames placeholders consistently across
the pattern.yaml + var_values map. If round-trip fails after polish,
that's a bug in the rename pass, not a bug in the LLM.
"""
from __future__ import annotations

import re
from typing import Any

from .providers.ollama_provider import OllamaProvider


def polish_variable_names(
    pattern: dict[str, Any],
    var_values_per_instance: dict[str, list[Any]],
    label_var_name: str,
    schema_names: list[str],
    provider: OllamaProvider | None = None,
    model: str = "qwen2.5:7b-instruct",
) -> tuple[dict[str, Any], dict[str, list[Any]]]:
    """Ask the LLM to rename mechanical variables to semantic names.

    Inputs:
      - pattern: derived pattern dict (from derive_pattern + couple_variables).
      - var_values_per_instance: {var_name: [values per instance]}.
      - label_var_name: the cluster's label variable; preserved as-is.
      - schema_names: Pydantic class names the pattern targets (for context).
      - provider: optional pre-built OllamaProvider; one is created if None.

    Returns ``(polished_pattern, polished_var_values)`` with the same
    behavior but semantic names.
    """
    if provider is None:
        provider = OllamaProvider(model=model)

    # Build the LLM input: list of mechanical vars with their values.
    mechanical_vars = [
        {
            "mechanical_name": name,
            "type": pattern["variables"][name].get("type", "str"),
            "default": pattern["variables"][name].get("default"),
            "values_per_instance": var_values_per_instance.get(name, []),
        }
        for name in pattern["variables"]
        if name != label_var_name
    ]
    if not mechanical_vars:
        return pattern, var_values_per_instance

    system = (
        "You rename auto-generated FEWS pattern variables. The mechanical "
        "names like `import_general_relativeViewPeriod_end` are paths through "
        "the FEWS XML schema. Your job is to suggest a short, snake_case "
        "semantic name that reflects what the variable represents at the "
        "FEWS level (e.g. `forecast_horizon_hours`). Do NOT invent new "
        "variables. Do NOT change defaults or types. Output ONLY the JSON "
        "object the schema asks for."
    )
    user = (
        f"Cluster name: {pattern.get('name', '?')}\n"
        f"Pydantic schemas this pattern emits: {', '.join(schema_names)}\n"
        f"Label variable (already named): {label_var_name}\n\n"
        f"Mechanical variables to rename:\n"
        f"{_format_vars_for_llm(mechanical_vars)}\n\n"
        f"For each mechanical name, propose a semantic_name (lower_snake_case, "
        f"<=30 chars) and a one-line description."
    )
    schema = {
        "type": "object",
        "properties": {
            "renames": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "mechanical_name": {"type": "string"},
                        "semantic_name": {"type": "string"},
                        "description": {"type": "string"},
                    },
                    "required": ["mechanical_name", "semantic_name", "description"],
                },
            },
        },
        "required": ["renames"],
    }

    resp = provider.generate_json(system=system, user=user, schema=schema)
    if not resp.data or "renames" not in resp.data:
        # LLM returned nothing usable — leave pattern as-is.
        return pattern, var_values_per_instance

    return _apply_renames(
        pattern, var_values_per_instance, resp.data["renames"], label_var_name
    )


# ---------------------------------------------------------------------------
# LLM input formatting
# ---------------------------------------------------------------------------

def _format_vars_for_llm(mechanical_vars: list[dict[str, Any]]) -> str:
    lines = []
    for v in mechanical_vars:
        values = v.get("values_per_instance") or []
        # Show at most 4 values to keep prompt small.
        sample = values[:4]
        lines.append(
            f"  - {v['mechanical_name']} (type={v['type']}, "
            f"default={v.get('default')!r}, values={sample!r})"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Apply renames to the pattern
# ---------------------------------------------------------------------------

def _apply_renames(
    pattern: dict[str, Any],
    var_values: dict[str, list[Any]],
    renames: list[dict[str, str]],
    label_var_name: str,
) -> tuple[dict[str, Any], dict[str, list[Any]]]:
    """Rewrite the pattern with the LLM's suggested names + descriptions."""
    rename_map: dict[str, str] = {}
    descriptions: dict[str, str] = {}
    seen_semantic: set[str] = set()
    for r in renames:
        old = r.get("mechanical_name")
        new = r.get("semantic_name", "").strip()
        desc = r.get("description", "").strip()
        if not old or not new:
            continue
        if old not in pattern["variables"]:
            continue  # LLM hallucinated a name not in the input
        if new == label_var_name or new in rename_map.values() or new in seen_semantic:
            # Conflict — fall back to mechanical name.
            new = old
        # snake_case sanitisation.
        new = re.sub(r"[^a-zA-Z0-9_]", "_", new).lower()
        if not new[0].isalpha() and new[0] != "_":
            new = f"v_{new}"
        rename_map[old] = new
        descriptions[new] = desc
        seen_semantic.add(new)

    # Rebuild variables block in original order.
    new_variables: dict[str, Any] = {}
    for old_name, spec in pattern["variables"].items():
        new_name = rename_map.get(old_name, old_name)
        new_spec = dict(spec)
        if new_name in descriptions:
            new_spec["description"] = descriptions[new_name]
        new_variables[new_name] = new_spec
    pattern["variables"] = new_variables

    # Rewrite placeholders in outputs + contributions.
    pattern["outputs"] = [
        _rename_placeholders_recursive(out, rename_map) for out in pattern["outputs"]
    ]

    new_var_values: dict[str, list[Any]] = {}
    for old, values in var_values.items():
        new_var_values[rename_map.get(old, old)] = values

    return pattern, new_var_values


def _rename_placeholders_recursive(obj: Any, rename: dict[str, str]) -> Any:
    if isinstance(obj, str):
        return _rename_placeholders_str(obj, rename)
    if isinstance(obj, dict):
        return {k: _rename_placeholders_recursive(v, rename) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_rename_placeholders_recursive(v, rename) for v in obj]
    return obj


def _rename_placeholders_str(s: str, rename: dict[str, str]) -> str:
    out = s
    for old, new in rename.items():
        if old == new:
            continue
        pattern = re.compile(r"\{\{\s*" + re.escape(old) + r"\s*\}\}")
        out = pattern.sub("{{ " + new + " }}", out)
    return out


# ---------------------------------------------------------------------------
# Phase 2: discriminator identification
# ---------------------------------------------------------------------------

def identify_discriminators(
    pattern: dict[str, Any],
    instances: list[dict[str, Any]],
    review_items: list[dict[str, Any]],
    per_instance_source_data: list[list[dict[str, Any]]],
    schema_names: list[str],
    var_values_per_instance: dict[str, list[Any]] | None = None,
    provider: OllamaProvider | None = None,
    model: str = "qwen2.5:7b-instruct",
) -> tuple[dict[str, Any], dict[str, list[Any]]]:
    """Group structural divergences under discriminator variables (LLM).

    For each ``_review`` divergence (presence-based or list-length-based),
    the LLM proposes:
      - which divergences cluster under one discriminator (often
        multiple review items share a semantic discriminator like
        ``workflow_shape``);
      - the discriminator's name + values per instance + description.

    This function only IDENTIFIES discriminators and adds them to the
    pattern's variables block. It does NOT inject the Jinja
    conditionals into the data section — that's a follow-up
    (manual/automated) step. The discriminator proposal is also
    written to the pattern as ``_discriminator_proposals`` so the next
    step can act on it.
    """
    if var_values_per_instance is None:
        var_values_per_instance = {}
    if not review_items:
        return pattern, var_values_per_instance

    if provider is None:
        provider = OllamaProvider(model=model)

    # Format the review items with per-instance content at each path.
    # We scan all outputs to find the one whose dicts have content at
    # the divergent path; that's the right output to pull from.
    review_summary = []
    for idx, ri in enumerate(review_items):
        path = ri.get("path", ())
        # Find the output whose dicts are non-empty at this path.
        output_idx = 0
        for cand_idx, output_dicts in enumerate(per_instance_source_data):
            # length-based divergence: pick the output whose first dict
            # has a list at this path.
            sample = _safely_get_at_path(output_dicts[0], path) if output_dicts else None
            if "lengths" in ri and isinstance(sample, list):
                output_idx = cand_idx
                break
            # presence-based: pick the output where ANY instance has
            # content at this path.
            if "presence" in ri and any(
                _safely_get_at_path(d, path) is not None for d in output_dicts
            ):
                output_idx = cand_idx
                break

        per_inst_at_path = []
        if output_idx < len(per_instance_source_data):
            for inst_idx, d in enumerate(per_instance_source_data[output_idx]):
                content = _safely_get_at_path(d, path)
                if "lengths" in ri and isinstance(content, list):
                    summary = (
                        f"list of {len(content)} item(s); "
                        f"first item: {_summarise_for_llm(content[0] if content else None, 80)}"
                    )
                else:
                    summary = _summarise_for_llm(content)
                per_inst_at_path.append({
                    "instance": instances[inst_idx]["label"],
                    "content_summary": summary,
                })
        review_summary.append({
            "review_index": idx,
            "path": "/".join(str(p) for p in path),
            "kind": "lengths" if "lengths" in ri else "presence",
            "details_str": (
                f"lengths={ri['lengths']}" if "lengths" in ri
                else f"presence={ri.get('presence')}"
            ),
            "per_instance_content": per_inst_at_path,
        })

    instance_labels = [inst["label"] for inst in instances]
    system = (
        "You analyse FEWS pattern structural divergences. Each divergence "
        "describes how the FEWS XML structure differs across instances of "
        "the same pattern. Your job: group divergences into one or more "
        "DISCRIMINATOR variables that classify each instance's structural "
        "variant.\n\n"
        "RULES:\n"
        "- `values_per_instance` keys MUST be the exact instance labels "
        "given in the prompt (e.g. HRDPS, GDPS, RDPS) — not synthetic keys.\n"
        "- `values_per_instance` values are short snake_case literals "
        "(e.g. 'inline', 'delegated', 'bool', 'string').\n"
        "- One discriminator can group MULTIPLE related review indices.\n"
        "- Cover EVERY review index — every divergence must be assigned "
        "to some discriminator.\n"
        "- Pick semantic names — `workflow_shape`, `properties_kind` — not "
        "`nwp_shape_a` or path-based names.\n\n"
        "EXAMPLE:\n"
        "Given divergences where instances HRDPS, GDPS, RDPS differ in:\n"
        "  [0] activity list lengths: [4, 3, 3]\n"
        "  [1] properties.bool present: [True, False, True]\n"
        "  [2] properties.string present: [False, True, False]\n"
        "Good output:\n"
        '  {\n'
        '    \"discriminators\": [\n'
        '      {\n'
        '        \"name\": \"workflow_shape\",\n'
        '        \"description\": \"how the workflow handles preprocessing\",\n'
        '        \"values_per_instance\": {\"HRDPS\": \"inline\", \"GDPS\": \"delegated\", \"RDPS\": \"delegated\"},\n'
        '        \"review_indices_handled\": [0]\n'
        '      },\n'
        '      {\n'
        '        \"name\": \"properties_kind\",\n'
        '        \"description\": \"property element type\",\n'
        '        \"values_per_instance\": {\"HRDPS\": \"bool\", \"GDPS\": \"string\", \"RDPS\": \"bool\"},\n'
        '        \"review_indices_handled\": [1, 2]\n'
        '      }\n'
        '    ]\n'
        '  }\n\n'
        "Output ONLY the JSON object the schema asks for, nothing else."
    )
    user = (
        f"Cluster: {pattern.get('name', '?')}\n"
        f"Schemas: {', '.join(schema_names)}\n"
        f"Instance labels (use these EXACT labels in `values_per_instance` keys): "
        f"{instance_labels}\n\n"
        f"Structural divergences ({len(review_summary)} items, each must be "
        f"assigned to a discriminator):\n"
        f"{_format_review_for_llm(review_summary)}\n\n"
        f"Propose discriminators that classify each instance's variant."
    )
    schema = {
        "type": "object",
        "properties": {
            "discriminators": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "values_per_instance": {
                            "type": "object",
                            "additionalProperties": {"type": "string"},
                        },
                        "review_indices_handled": {
                            "type": "array",
                            "items": {"type": "integer"},
                        },
                    },
                    "required": [
                        "name", "description",
                        "values_per_instance", "review_indices_handled",
                    ],
                },
            },
        },
        "required": ["discriminators"],
    }

    resp = provider.generate_json(system=system, user=user, schema=schema)
    if not resp.data or "discriminators" not in resp.data:
        return pattern, var_values_per_instance

    discriminators = resp.data["discriminators"]
    instance_labels = [inst["label"] for inst in instances]
    # Add discriminators to the variables block + per-instance value map.
    for d in discriminators:
        name = d.get("name", "").strip()
        if not name:
            continue
        name = re.sub(r"[^a-zA-Z0-9_]", "_", name).lower()
        if name in pattern["variables"]:
            continue
        values_map = d.get("values_per_instance", {})
        # Type is str (discriminators are categorical literals).
        pattern["variables"][name] = {
            "type": "str",
            "description": d.get("description", ""),
            "default": next(iter(values_map.values()), ""),
        }
        # Build the per-instance values list in instance order.
        var_values_per_instance[name] = [
            values_map.get(label, "") for label in instance_labels
        ]

    pattern["_discriminator_proposals"] = discriminators
    return pattern, var_values_per_instance


def _safely_get_at_path(d: Any, path: tuple) -> Any:
    """Walk ``d`` along ``path``; return None if any step fails."""
    cur = d
    for p in path:
        try:
            cur = cur[p]
        except (KeyError, IndexError, TypeError):
            return None
    return cur


def _summarise_for_llm(content: Any, max_chars: int = 200) -> str:
    """Produce a compact prose summary of structured content."""
    if content is None:
        return "(absent)"
    s = repr(content)
    if len(s) > max_chars:
        s = s[: max_chars - 3] + "..."
    return s


def _format_review_for_llm(review_summary: list[dict[str, Any]]) -> str:
    lines = []
    for r in review_summary:
        lines.append(
            f"  [{r['review_index']}] path={r['path']!r} kind={r['kind']}"
        )
        for inst in r["per_instance_content"]:
            lines.append(
                f"        {inst['instance']}: {inst['content_summary']}"
            )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Phase 2.5: inject Jinja conditionals from discriminator proposals
# ---------------------------------------------------------------------------

import yaml as _yaml


def inject_jinja_conditionals(
    pattern: dict[str, Any],
    review_items: list[dict[str, Any]],
    per_instance_source_data: list[list[dict[str, Any]]],
    instances: list[dict[str, Any]],
    var_values_per_instance: dict[str, list[Any]] | None = None,
) -> str:
    """Serialise pattern as YAML with Jinja conditional blocks injected.

    Each discriminator in ``pattern['_discriminator_proposals']`` covers
    one or more divergent paths. This function:

      1. Finds the lowest common ancestor of all paths a discriminator
         handles (usually they're the same path or sibling paths).
      2. Replaces the value at that path with a placeholder string.
      3. After ``yaml.safe_dump``, locates the placeholder in the
         output text, computes its indentation, and replaces it with
         a multi-line ``{% if disc == 'A' %}content_A{% elif disc == 'B' %}content_B{% endif %}``
         block. Per-instance content is pulled from
         ``per_instance_source_data``.

    Returns YAML text with Jinja blocks ready for the existing expander
    (which renders pattern.yaml as Jinja before YAML-parsing).
    """
    proposals = pattern.get("_discriminator_proposals", [])
    if not proposals:
        return _yaml.safe_dump(pattern, sort_keys=False, width=200)

    placeholders: dict[str, dict[str, Any]] = {}

    for prop in proposals:
        disc_name = re.sub(r"[^a-zA-Z0-9_]", "_", prop.get("name", "")).lower()
        if not disc_name:
            continue
        handled = prop.get("review_indices_handled", [])
        if not handled:
            continue
        paths = [
            tuple(review_items[i].get("path", ()))
            for i in handled if i < len(review_items)
        ]
        paths = [p for p in paths if p]
        if not paths:
            continue

        # Common ancestor: walk paths together; stop where they diverge.
        common = paths[0]
        for p in paths[1:]:
            new_common = []
            for a, b in zip(common, p):
                if a == b:
                    new_common.append(a)
                else:
                    break
            common = tuple(new_common)
        if not common:
            continue

        # For each unique discriminator value, find an instance that
        # has it and pull its content at `common`. Also remember which
        # instance index was the "anchor" (the one we pulled content
        # from) — Phase 2.6 uses this to parameterise inner content
        # against that instance's variable values.
        values_per_inst = prop.get("values_per_instance", {})
        value_to_content: dict[str, Any] = {}
        value_to_anchor_idx: dict[str, int] = {}
        chosen_output_idx: int | None = None
        for inst_idx, inst in enumerate(instances):
            label = inst["label"]
            value = values_per_inst.get(label)
            if value is None or str(value) in value_to_content:
                continue
            for output_idx, output_dicts in enumerate(per_instance_source_data):
                if inst_idx >= len(output_dicts):
                    continue
                content = _safely_get_at_path(output_dicts[inst_idx], common)
                if content is not None:
                    value_to_content[str(value)] = content
                    value_to_anchor_idx[str(value)] = inst_idx
                    if chosen_output_idx is None:
                        chosen_output_idx = output_idx
                    break

        # Phase 2.6: parameterise inner content against the anchor
        # instance's variable values. Where the anchor's content
        # contains a literal string equal to one of the anchor's
        # variable values, replace with {{ var_name }} so the
        # rendered output uses each rendering instance's own value.
        if var_values_per_instance:
            value_to_content = {
                v: _parameterise_inner_content(
                    c, var_values_per_instance, value_to_anchor_idx[v]
                )
                for v, c in value_to_content.items()
            }

        if len(value_to_content) < 2 or chosen_output_idx is None:
            continue

        # Set the value at `common` in the pattern's chosen output to a
        # unique placeholder string.
        marker = f"__JINJA_BLOCK_{disc_name}__"
        if chosen_output_idx >= len(pattern["outputs"]):
            continue
        _set_dict_path(
            pattern["outputs"][chosen_output_idx]["data"], common, marker,
        )
        placeholders[marker] = {
            "discriminator": disc_name,
            "value_to_content": value_to_content,
        }

    yaml_text = _yaml.safe_dump(pattern, sort_keys=False, width=200)

    for marker, info in placeholders.items():
        yaml_text = _replace_marker_with_jinja(
            yaml_text, marker, info["discriminator"], info["value_to_content"]
        )
    return yaml_text


def _parameterise_inner_content(
    content: Any,
    var_values_per_instance: dict[str, list[Any]],
    anchor_idx: int,
) -> Any:
    """Replace literal strings in content with ``{{ var }}`` placeholders.

    For each variable, look up ``values[anchor_idx]`` and substitute
    every occurrence of that string in the content with the variable's
    Jinja placeholder. Longer values are substituted first to avoid
    partial overlaps (e.g. ``ImportHRDPS`` should match before
    ``HRDPS``).
    """
    # Build longest-first sub list so that ImportHRDPS replaces before HRDPS.
    subs: list[tuple[str, str]] = []
    for var_name, values in var_values_per_instance.items():
        if anchor_idx >= len(values):
            continue
        val = values[anchor_idx]
        if not isinstance(val, str) or not val:
            continue
        subs.append((val, "{{ " + var_name + " }}"))
    subs.sort(key=lambda x: -len(x[0]))

    def _walk(obj: Any) -> Any:
        if isinstance(obj, str):
            out = obj
            for old, new in subs:
                # Avoid replacing inside an already-substituted Jinja expr.
                if new in out:
                    continue
                out = out.replace(old, new)
            return out
        if isinstance(obj, dict):
            return {k: _walk(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_walk(v) for v in obj]
        return obj

    return _walk(content)


def _set_dict_path(d: Any, path: tuple, value: Any) -> bool:
    """In-place set d[path] = value. Returns True on success, False if
    a parent step couldn't be traversed (e.g. a previous injection
    already replaced the parent with a placeholder string)."""
    if not path:
        return False
    cur = d
    for p in path[:-1]:
        try:
            cur = cur[p]
        except (KeyError, IndexError, TypeError):
            return False
        if not isinstance(cur, (dict, list)):
            return False
    try:
        cur[path[-1]] = value
        return True
    except (KeyError, IndexError, TypeError):
        return False


def _replace_marker_with_jinja(
    yaml_text: str,
    marker: str,
    disc_name: str,
    value_to_content: dict[str, Any],
) -> str:
    """Replace ``key: <marker>`` with a Jinja-conditional block."""
    lines = yaml_text.split("\n")
    out_lines = []
    for line in lines:
        if marker not in line:
            out_lines.append(line)
            continue
        # Identify the indent level + the dict key on this line.
        indent_len = len(line) - len(line.lstrip(" "))
        indent = " " * indent_len
        # Strip the trailing ``: <marker>`` (with optional quotes)
        # to get the key portion.
        # YAML may have rendered it as ``key: __MARKER__`` or
        # ``key: '__MARKER__'`` depending on safe_dump quirks.
        before, _, _ = line.rpartition(":")
        key_part = before  # e.g. "    activity"
        out_lines.append(f"{key_part}:")
        block_indent = indent + "  "  # one level deeper for list / dict children
        first = True
        for value, content in value_to_content.items():
            if_kw = "if" if first else "elif"
            first = False
            out_lines.append(
                f"{block_indent}{{% {if_kw} {disc_name} == '{value}' %}}"
            )
            content_yaml = _yaml.safe_dump(
                content, sort_keys=False, width=200
            ).rstrip("\n")
            for cl in content_yaml.split("\n"):
                out_lines.append(f"{block_indent}{cl}")
        out_lines.append(f"{block_indent}{{% endif %}}")
    return "\n".join(out_lines)


__all__ = [
    "polish_variable_names",
    "identify_discriminators",
    "inject_jinja_conditionals",
]
