"""Validate a PatternSpec by re-rendering it against the input instances.

Three layers, ALL must pass for `ok`:

  1. **Round-trip equivalence.** Render every output with each
     instance's variable values; resulting dict must equal the source
     dict.
  2. **Schema preservation.** ``spec.outputs[i].schema_class`` must
     match the instances' ``schema_class``. A common LLM failure is
     silently rewriting ``Workflow`` to ``TimeSeriesImportRun`` when
     abstracting the data dict.
  3. **Variable hygiene.** No dead variables (declared but
     unreferenced in templates), no redundant variables (two vars
     with identical per-instance values are functionally one). Both
     are vacuous-pass enablers — the LLM can satisfy round-trip by
     binding 9 variables to the same string and substituting any of
     them; we reject that as a non-abstraction.

We do NOT re-validate via Pydantic + XSD here. That's a second-line
check the build pipeline applies; for farming, dict equality against
the source plus structural hygiene is the tighter signal.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from jinja2 import Environment, StrictUndefined

from .ir import InstanceInput, PatternSpec


_JINJA_VAR_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)")
# Anything other than a plain `{{ name[.attr|filter] }}` or `{{ name }}` is
# disallowed. Block conditionals (`{% ... %}`) and inline expressions
# (`{{ x if y else z }}`, `{{ a + b }}`, etc.) which models reach for
# to encode numeric divergences instead of declaring a variable.
_JINJA_BLOCK_RE = re.compile(r"\{%")
_JINJA_EXPR_RE = re.compile(
    r"\{\{[^}]*(\s(if|else|and|or|not)\s|[+\-*/%]|\?)"
)


@dataclass
class OutputDiff:
    output_index: int
    instance_label: str
    paths: list[str] = field(default_factory=list)  # diverging dotted paths
    expected: dict[str, Any] = field(default_factory=dict)
    actual: dict[str, Any] = field(default_factory=dict)

    def is_empty(self) -> bool:
        return not self.paths


@dataclass
class SchemaMismatch:
    output_index: int
    expected: str
    actual: str


@dataclass
class ValidationReport:
    diffs: list[OutputDiff] = field(default_factory=list)
    schema_mismatches: list[SchemaMismatch] = field(default_factory=list)
    dead_variables: list[str] = field(default_factory=list)
    redundant_variables: list[tuple[str, str]] = field(default_factory=list)
    forbidden_jinja: list[tuple[int, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return (
            all(d.is_empty() for d in self.diffs)
            and not self.schema_mismatches
            and not self.dead_variables
            and not self.redundant_variables
            and not self.forbidden_jinja
        )

    def summary(self) -> str:
        if self.ok:
            return "all instances round-trip exactly; schema/variables clean"
        lines = []
        for d in self.diffs:
            if d.is_empty():
                continue
            lines.append(
                f"output#{d.output_index} instance {d.instance_label!r}: "
                f"{len(d.paths)} divergent path(s)"
            )
            for p in d.paths[:8]:
                lines.append(
                    f"  {p}: expected={_at_path(d.expected, p)!r} "
                    f"actual={_at_path(d.actual, p)!r}"
                )
            if len(d.paths) > 8:
                lines.append(f"  ... +{len(d.paths) - 8} more")
        for sm in self.schema_mismatches:
            lines.append(
                f"output#{sm.output_index}: schema mismatch — "
                f"expected {sm.expected!r}, got {sm.actual!r}"
            )
        for out_idx, expr in self.forbidden_jinja:
            lines.append(
                f"output#{out_idx}: forbidden Jinja construct: {expr!r} "
                f"(use a named variable instead)"
            )
        if self.dead_variables:
            lines.append(
                f"dead variables (declared but unreferenced): "
                f"{', '.join(self.dead_variables)}"
            )
        for a, b in self.redundant_variables:
            lines.append(
                f"redundant variables: {a!r} and {b!r} have identical "
                f"per-instance values"
            )
        return "\n".join(lines)


def validate(spec: PatternSpec, instances: list[InstanceInput]) -> ValidationReport:
    """Render spec; diff vs. source; check schema preservation + var hygiene."""
    env = Environment(undefined=StrictUndefined, keep_trailing_newline=True)
    report = ValidationReport()

    # 1. Round-trip equivalence per (instance, output).
    for inst in instances:
        for out_idx, out_spec in enumerate(spec.outputs):
            vars_for_instance = dict(inst.variable_hints)
            try:
                rendered_path = env.from_string(out_spec.output).render(**vars_for_instance)
                rendered_data = _render_tree(out_spec.data, env, vars_for_instance)
            except Exception as exc:  # noqa: BLE001
                report.diffs.append(
                    OutputDiff(
                        output_index=out_idx,
                        instance_label=inst.label,
                        paths=[f"<render-failed:{exc}>"],
                        expected=inst.outputs[out_idx].data,
                        actual={},
                    )
                )
                continue

            expected = inst.outputs[out_idx]
            diff = OutputDiff(
                output_index=out_idx,
                instance_label=inst.label,
                expected=expected.data,
                actual=rendered_data,
            )
            if rendered_path != expected.output:
                diff.paths.append("__output_path__")
            _diff_trees(expected.data, rendered_data, "", diff.paths)
            report.diffs.append(diff)

    # 2. Schema preservation — every output's schema_class must match
    # the source instances' schema_class for that output index.
    if instances:
        for out_idx, out_spec in enumerate(spec.outputs):
            expected_schemas = {
                inst.outputs[out_idx].schema_class for inst in instances
            }
            if len(expected_schemas) > 1:
                # Source disagrees — the farmer can't reconcile; pick first
                # and flag.
                expected_schema = sorted(expected_schemas)[0]
            else:
                expected_schema = next(iter(expected_schemas))
            if out_spec.schema_class != expected_schema:
                report.schema_mismatches.append(
                    SchemaMismatch(
                        output_index=out_idx,
                        expected=expected_schema,
                        actual=out_spec.schema_class,
                    )
                )

    # 3. Forbidden Jinja constructs — anything beyond `{{ var }}`.
    for out_idx, out_spec in enumerate(spec.outputs):
        for expr in _forbidden_jinja_in(out_spec):
            report.forbidden_jinja.append((out_idx, expr))

    # 4. Variable hygiene — dead + redundant.
    referenced = _referenced_variables(spec)
    declared = set(spec.variables)
    report.dead_variables = sorted(declared - referenced)

    # Redundant: any pair of referenced variables whose per-instance
    # values (from variable_hints) are identical across ALL instances.
    referenced_list = sorted(referenced & declared)
    for i, a in enumerate(referenced_list):
        for b in referenced_list[i + 1:]:
            values_a = tuple(inst.variable_hints.get(a) for inst in instances)
            values_b = tuple(inst.variable_hints.get(b) for inst in instances)
            if values_a == values_b and None not in values_a:
                report.redundant_variables.append((a, b))

    return report


def _forbidden_jinja_in(out_spec: Any) -> list[str]:
    """Return a list of offending Jinja substrings found in this output."""
    found: list[str] = []

    def scan(s: str) -> None:
        for m in _JINJA_BLOCK_RE.finditer(s):
            # Capture a short snippet
            start = m.start()
            end = min(len(s), start + 40)
            found.append(s[start:end])
        for m in _JINJA_EXPR_RE.finditer(s):
            start = m.start()
            end = min(len(s), start + 40)
            found.append(s[start:end])

    def walk(node: Any) -> None:
        if isinstance(node, str):
            scan(node)
        elif isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    scan(out_spec.output)
    walk(out_spec.data)
    return found


def _referenced_variables(spec: PatternSpec) -> set[str]:
    """Walk every output's path + data, return the set of `{{ name }}`s."""
    found: set[str] = set()

    def scan(s: str) -> None:
        for m in _JINJA_VAR_RE.finditer(s):
            found.add(m.group(1))

    def walk(node: Any) -> None:
        if isinstance(node, str):
            scan(node)
        elif isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    for out in spec.outputs:
        scan(out.output)
        walk(out.data)
    return found


def _render_tree(obj: Any, env: Environment, vars: dict[str, Any]) -> Any:
    if isinstance(obj, str):
        rendered = env.from_string(obj).render(**vars)
        # Preserve original type when Jinja yields a number-looking string
        # in a slot that was originally numeric. We keep strings as
        # strings here — the diff comparison uses _equiv() which is
        # numeric-string tolerant.
        return rendered
    if isinstance(obj, dict):
        return {k: _render_tree(v, env, vars) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_render_tree(v, env, vars) for v in obj]
    return obj


def _diff_trees(
    expected: Any, actual: Any, path: str, out: list[str],
) -> None:
    if isinstance(expected, dict) and isinstance(actual, dict):
        keys = set(expected) | set(actual)
        for k in keys:
            _diff_trees(
                expected.get(k, _MISSING),
                actual.get(k, _MISSING),
                f"{path}.{k}" if path else k,
                out,
            )
        return
    if isinstance(expected, list) and isinstance(actual, list):
        for i in range(max(len(expected), len(actual))):
            e = expected[i] if i < len(expected) else _MISSING
            a = actual[i] if i < len(actual) else _MISSING
            _diff_trees(e, a, f"{path}[{i}]", out)
        return
    if not _equiv(expected, actual):
        out.append(path or "<root>")


_MISSING = object()


def _equiv(a: Any, b: Any) -> bool:
    if a is _MISSING or b is _MISSING:
        return a is b
    if a == b:
        return True
    # Numeric-string vs numeric tolerance: Jinja produces "1"/"3" for
    # int substitutions; the source might be int 1/3. Normalise.
    try:
        if isinstance(a, str) and isinstance(b, (int, float)):
            return type(b)(a) == b
        if isinstance(b, str) and isinstance(a, (int, float)):
            return type(a)(b) == a
        if isinstance(a, str) and isinstance(b, str):
            # Both strings, just != — return False (already checked equality)
            return False
    except (ValueError, TypeError):
        pass
    return False


def _at_path(obj: Any, path: str) -> Any:
    if path == "<root>" or path == "":
        return obj
    cur = obj
    parts: list[str] = []
    buf = ""
    i = 0
    while i < len(path):
        c = path[i]
        if c == ".":
            if buf:
                parts.append(buf)
                buf = ""
        elif c == "[":
            if buf:
                parts.append(buf)
                buf = ""
            j = path.index("]", i)
            parts.append(path[i + 1 : j])
            i = j
        else:
            buf += c
        i += 1
    if buf:
        parts.append(buf)
    for p in parts:
        try:
            if p.isdigit():
                cur = cur[int(p)]
            else:
                cur = cur[p]
        except (KeyError, IndexError, TypeError):
            return _MISSING
    return cur
