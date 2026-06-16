"""Pattern-farming orchestrator.

Three LLM calls + a deterministic validate-repair loop. The LLM is
NEVER asked to invent structure — only to fill the rigid IR using
the pre-computed diff as guidance.

Order:
  1. ``propose_variables`` — given the diff, name and type the
     variables. Cross-checks instance_hints (the user-provided
     mapping) and prefers those when conflict.
  2. ``abstract_output`` — for each output index, given that
     output's per-instance materialisation, emit the Jinja-templated
     dict.
  3. ``validate`` — re-render the proposed spec against every
     instance. If exact: done. If not: ``repair_output`` per failing
     output, up to ``max_retries`` per output.

The provider is injected so the same orchestrator works against
Ollama, HF (via LiteLLM), or any other backend.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from .diff_finder import DiffReport, TokenGroup, find_diffs
from .ir import (
    InstanceInput,
    OutputSpec,
    PatternSpec,
    VariableSpec,
)
from .prompts import (
    ABSTRACT_SCHEMA,
    ABSTRACT_SYSTEM,
    REPAIR_SYSTEM,
    VARIABLES_SCHEMA,
    VARIABLES_SYSTEM,
    abstract_user_prompt,
    repair_user_prompt,
    variables_user_prompt,
)
from .validator import ValidationReport, validate

_logger = logging.getLogger(__name__)


@dataclass
class FarmResult:
    spec: PatternSpec
    validation: ValidationReport
    retries_per_output: dict[int, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.validation.ok


def farm(
    instances: list[InstanceInput],
    name: str,
    provider: Any,
    description: str = "",
    max_repair_retries: int = 3,
    log: Callable[[str], None] | None = None,
) -> FarmResult:
    """Farm a PatternSpec from N concrete instances.

    The provider must implement ``generate_json(system, user, schema)``
    returning a ``StructuredResponse`` (data dict + usage).
    """
    if log is None:
        log = _logger.info

    if len(instances) < 1:
        raise ValueError("need at least 1 instance to farm a pattern")
    if not all(len(i.outputs) == len(instances[0].outputs) for i in instances):
        raise ValueError("instances must have identical output counts")

    diff = find_diffs(instances)
    log(f"diff: {len(diff.divergences)} divergent leaves, "
        f"{len(diff.atomic_groups)} atomic + "
        f"{len(diff.derived_groups)} derived token-groups")

    variables = _propose_variables(provider, instances, diff, log)
    log(f"proposed variables: {sorted(variables)}")

    # Deterministic fallback: ensure every atomic group has a variable.
    # The LLM reliably names string atomic groups but routinely skips
    # numeric/bool ones, then encodes the difference as a forbidden
    # Jinja conditional. Auto-add a variable for every uncovered
    # atomic group, named from its first divergence's path.
    added = _ensure_atomic_coverage(variables, diff, log)
    if added:
        log(f"auto-added atomic-coverage variables: {sorted(added)}")

    instance_var_lookup = _build_instance_lookup(instances, variables)

    # Resolve derived-group rewrite rules now that we know variable
    # names. Each derived group has a parent token-group; the parent's
    # value-set should correspond to one of the proposed variables.
    rewrite_rules = _build_rewrite_rules(diff, instance_var_lookup)
    log(f"rewrite rules: {len(rewrite_rules)}")

    n_outputs = len(instances[0].outputs)
    outputs: list[OutputSpec] = []
    for out_idx in range(n_outputs):
        spec = _abstract_output(
            provider, out_idx, instances, variables, rewrite_rules, log,
        )
        outputs.append(spec)

    pattern_spec = PatternSpec(
        name=name,
        description=description,
        variables=variables,
        outputs=outputs,
    )

    # Prune dead variables — declared but never referenced in any
    # template. Lossless by definition: a variable that doesn't appear
    # in the output dict cannot contribute to the abstraction.
    pruned = _prune_dead_variables(pattern_spec, log)
    log(f"pruned {len(pruned)} dead variable(s): {sorted(pruned)}")

    # Inject variable_hints into instances if missing — derive from
    # the LLM's value_per_instance mapping so the validator can render.
    for inst in instances:
        for var_name, lookup in instance_var_lookup.items():
            if var_name not in inst.variable_hints and inst.label in lookup:
                inst.variable_hints[var_name] = lookup[inst.label]

    result = FarmResult(spec=pattern_spec, validation=validate(pattern_spec, instances))
    if result.ok:
        log("validate: all instances round-trip exactly")
        return result

    # Repair loop — per output, capped retries.
    for out_idx in range(n_outputs):
        retries = 0
        while retries < max_repair_retries:
            report = validate(pattern_spec, instances)
            if report.ok:
                break
            failing = [d for d in report.diffs if d.output_index == out_idx and not d.is_empty()]
            if not failing:
                break  # this output is fine; another one is failing
            retries += 1
            log(f"repair output#{out_idx} attempt {retries}/{max_repair_retries}")
            try:
                repaired = _repair_output(
                    provider, out_idx, pattern_spec.outputs[out_idx],
                    instances, report, log,
                )
                pattern_spec.outputs[out_idx] = repaired
            except Exception as exc:  # noqa: BLE001
                result.notes.append(
                    f"repair output#{out_idx} attempt {retries} crashed: {exc}"
                )
                continue
        result.retries_per_output[out_idx] = retries

    result.validation = validate(pattern_spec, instances)
    return result


# --- internal helpers --------------------------------------------------

def _propose_variables(
    provider: Any,
    instances: list[InstanceInput],
    diff: DiffReport,
    log: Callable[[str], None],
) -> dict[str, VariableSpec]:
    user = variables_user_prompt(instances, diff)
    resp = provider.generate_json(VARIABLES_SYSTEM, user, VARIABLES_SCHEMA)
    raw = resp.data or {}
    vars_decl = raw.get("variables") or []
    out: dict[str, VariableSpec] = {}
    for v in vars_decl:
        try:
            name = v["name"]
            typ = v.get("type", "str")
            out[name] = VariableSpec(type=typ, required=True)
        except Exception:  # noqa: BLE001
            continue
    # Stash the value_per_instance mapping on a side dict so the
    # caller can wire variable_hints. We do this by re-walking raw.
    _propose_variables.last_lookup = {  # type: ignore[attr-defined]
        v["name"]: v.get("value_per_instance") or {}
        for v in vars_decl
        if "name" in v
    }
    if not out:
        log("warning: LLM proposed no variables; fallback to single str slot")
        out["instance_name"] = VariableSpec(type="str", required=True)
        _propose_variables.last_lookup = {  # type: ignore[attr-defined]
            "instance_name": {i.label: i.label for i in instances}
        }
    return out


def _build_instance_lookup(
    instances: list[InstanceInput],
    variables: dict[str, VariableSpec],
) -> dict[str, dict[str, Any]]:
    """variable_name → {instance_label → value}."""
    lookup = getattr(_propose_variables, "last_lookup", {})
    out: dict[str, dict[str, Any]] = {}
    for var_name in variables:
        out[var_name] = dict(lookup.get(var_name, {}))
    return out


def _abstract_output(
    provider: Any,
    out_idx: int,
    instances: list[InstanceInput],
    variables: dict[str, VariableSpec],
    rewrite_rules: list[dict[str, Any]],
    log: Callable[[str], None],
) -> OutputSpec:
    output_specs = [
        {
            "schema": inst.outputs[out_idx].schema_class,
            "output": inst.outputs[out_idx].output,
            "data": inst.outputs[out_idx].data,
        }
        for inst in instances
    ]
    labels = [inst.label for inst in instances]
    vars_payload = [
        {
            "name": name,
            "type": var.type,
            "value_per_instance": _build_instance_lookup(instances, variables).get(name, {}),
        }
        for name, var in variables.items()
    ]
    user = abstract_user_prompt(
        out_idx, output_specs, labels, vars_payload, rewrite_rules,
    )
    resp = provider.generate_json(ABSTRACT_SYSTEM, user, ABSTRACT_SCHEMA)
    data = resp.data or {}
    # Schema is NOT the LLM's call — pin it to the source instance to
    # block hallucinations like Workflow → TimeSeriesImportRun.
    return OutputSpec(
        schema=instances[0].outputs[out_idx].schema_class,
        output=data.get("output", instances[0].outputs[out_idx].output),
        data=data.get("data", {}),
    )


def _ensure_atomic_coverage(
    variables: dict[str, VariableSpec],
    diff: DiffReport,
    log: Callable[[str], None],
) -> list[str]:
    """Add a variable for every atomic group the LLM didn't cover.

    Coverage = the variable's value_per_instance (from
    ``_propose_variables.last_lookup``) equals the atomic group's
    ``values_by_label``. Uncovered groups get a deterministic name
    from the last segment of their first divergence's dotted path
    (e.g., ``timeStep.multiplier`` → ``multiplier``). Collisions
    suffix with the atomic-group index.

    Type is inferred from the values: bool → ``bool``, int → ``int``,
    float → ``float``, else ``str``.
    """
    lookup = getattr(_propose_variables, "last_lookup", {})
    covered_value_sets = {
        _frozen_dict(vals) for vals in lookup.values() if vals
    }
    added: list[str] = []
    used_names = set(variables)
    for atomic_idx, g in enumerate(diff.atomic_groups):
        key = _frozen_dict(g.values_by_label)
        if key in covered_value_sets:
            continue
        # Skip path-only atomic groups — those are templated inline by
        # the abstract step from the content variables (e.g.
        # 'Import{{ nwp_name }}.xml'). Lifting them into named
        # variables would block that.
        paths = {diff.divergences[i].path for i in g.divergence_indices}
        if paths == {"__output_path__"}:
            continue
        # Need a new variable for this atomic group
        path = diff.divergences[g.divergence_indices[0]].path
        base = _name_from_path(path) or f"var_{atomic_idx}"
        name = base
        i = 1
        while name in used_names:
            name = f"{base}_{i}"
            i += 1
        used_names.add(name)
        # Type inference
        sample = next(iter(g.values_by_label.values()))
        typ = (
            "bool" if isinstance(sample, bool)
            else "int" if isinstance(sample, int)
            else "float" if isinstance(sample, float)
            else "str"
        )
        variables[name] = VariableSpec(type=typ, required=True)
        # Wire the lookup so downstream variable_hints + rewrite-rule
        # detection sees this variable.
        lookup[name] = dict(g.values_by_label)
        added.append(name)
    _propose_variables.last_lookup = lookup  # type: ignore[attr-defined]
    return added


def _frozen_dict(d: dict[str, Any]) -> frozenset:
    """Make a dict hashable for set membership."""
    return frozenset((k, _hashable_val(v)) for k, v in d.items())


def _hashable_val(v: Any) -> Any:
    if isinstance(v, (list, dict)):
        return repr(v)
    return v


def _name_from_path(path: str) -> str:
    """Derive a snake_case variable name from a dotted path.

    'import[0].timeSeriesSet[0].timeStep.multiplier' → 'multiplier'
    '__output_path__' → 'output_path'
    """
    if path == "__output_path__":
        return "output_path"
    # Last segment after splitting on '.' or ']'
    import re
    segments = re.split(r"[\.\[\]]+", path)
    segments = [s for s in segments if s and not s.isdigit()]
    if not segments:
        return ""
    last = segments[-1]
    # camelCase → snake_case
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", last).lower()


def _prune_dead_variables(
    spec: PatternSpec, log: Callable[[str], None],
) -> list[str]:
    """Remove declared variables never referenced in any output template.

    Returns the list of pruned names. Mutates ``spec.variables`` in place.
    """
    import re
    pattern = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)")
    referenced: set[str] = set()

    def scan(node: Any) -> None:
        if isinstance(node, str):
            for m in pattern.finditer(node):
                referenced.add(m.group(1))
        elif isinstance(node, dict):
            for v in node.values():
                scan(v)
        elif isinstance(node, list):
            for v in node:
                scan(v)

    for out in spec.outputs:
        scan(out.output)
        scan(out.data)

    dead = sorted(set(spec.variables) - referenced)
    for name in dead:
        del spec.variables[name]
    return dead


def _build_rewrite_rules(
    diff: DiffReport,
    instance_var_lookup: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Translate derived token-groups into explicit LLM rewrite rules.

    For each derived group, find which variable matches the parent's
    value-set (by comparing per-instance value mappings). Construct a
    rule entry the abstract prompt can apply verbatim.
    """
    rules: list[dict[str, Any]] = []
    for derived in diff.derived_groups:
        parent = diff.token_groups[derived.derived_from]
        # Find the variable whose per-instance values match the parent's.
        matched_var = None
        for var_name, vals in instance_var_lookup.items():
            if vals == parent.values_by_label:
                matched_var = var_name
                break
        if matched_var is None:
            continue  # LLM didn't propose a variable for this atomic group
        rules.append({
            "literals": list(derived.value_set),
            "template": f"{derived.prefix}{{{{ {matched_var} }}}}",
            "sites": len(derived.divergence_indices),
        })
    return rules


def _repair_output(
    provider: Any,
    out_idx: int,
    failing_spec: OutputSpec,
    instances: list[InstanceInput],
    report: ValidationReport,
    log: Callable[[str], None],
) -> OutputSpec:
    expected = [
        {"output": inst.outputs[out_idx].output, "data": inst.outputs[out_idx].data}
        for inst in instances
    ]
    labels = [inst.label for inst in instances]
    diff_details_lines = []
    for d in report.diffs:
        if d.output_index != out_idx or d.is_empty():
            continue
        diff_details_lines.append(f"instance {d.instance_label}:")
        for p in d.paths[:10]:
            diff_details_lines.append(f"  {p}")
    diff_details = "\n".join(diff_details_lines)
    user = repair_user_prompt(
        out_idx,
        {
            "schema": failing_spec.schema_class,
            "output": failing_spec.output,
            "data": failing_spec.data,
        },
        labels, expected, diff_details,
    )
    resp = provider.generate_json(REPAIR_SYSTEM, user, ABSTRACT_SCHEMA)
    data = resp.data or {}
    # Schema is NOT touched by repair either — pin to source.
    return OutputSpec(
        schema=instances[0].outputs[out_idx].schema_class,
        output=data.get("output", failing_spec.output),
        data=data.get("data", failing_spec.data),
    )
