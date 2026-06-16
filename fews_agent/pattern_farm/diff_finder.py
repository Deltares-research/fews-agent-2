"""Deterministic variable-candidate finder.

Walk N InstanceInputs in parallel; at every position that varies
across instances, record the path + per-instance values.

Output shape (DiffReport):

  - ``divergences`` — one entry per leaf position that varies.
  - ``token_groups`` — list[TokenGroup]. A TokenGroup collapses all
    divergences with the same per-instance value set. Each carries
    the value-set, the label→value mapping, and a list of divergence
    indices that share it.
  - ``derived_token_groups`` — set of indices into ``token_groups``
    that are derivable from another (atomic) token-group via a
    constant prefix. E.g., ``{"ImportHRDPS", "ImportGFS"}`` is
    derivable from ``{"HRDPS", "GFS"}`` with prefix ``"Import"``.
    Captured deterministically so the LLM never sees them as
    candidate variables — they're rewrite rules instead.

The atomic-vs-derived split is the key insight: even strong LLMs
over-decompose ``HRDPS`` and ``ImportHRDPS`` into two variables.
Surfacing the prefix relationship in code eliminates that failure
mode upstream of the LLM.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from .ir import InstanceInput


@dataclass
class Divergence:
    """One position that varies across instances."""

    output_index: int
    # Dotted/indexed path: "import[0].timeSeriesSet[0].locationId"
    path: str
    # Map instance label → value found at this path
    values: dict[str, Any] = field(default_factory=dict)

    @property
    def is_string_only(self) -> bool:
        return all(isinstance(v, str) for v in self.values.values())

    @property
    def value_set(self) -> tuple[Any, ...]:
        return tuple(sorted(set(self.values.values()), key=repr))


@dataclass
class TokenGroup:
    """Divergences that share the same per-instance value set."""

    value_set: tuple[Any, ...]            # sorted distinct values
    values_by_label: dict[str, Any]       # label → value
    divergence_indices: list[int]
    # Set when this group is derivable from another (atomic) group.
    derived_from: int | None = None       # index into DiffReport.token_groups
    prefix: str = ""                       # e.g. "Import" for derived="HRDPS"

    @property
    def is_atomic(self) -> bool:
        return self.derived_from is None


@dataclass
class DiffReport:
    divergences: list[Divergence] = field(default_factory=list)
    token_groups: list[TokenGroup] = field(default_factory=list)

    @property
    def atomic_groups(self) -> list[TokenGroup]:
        return [g for g in self.token_groups if g.is_atomic]

    @property
    def derived_groups(self) -> list[TokenGroup]:
        return [g for g in self.token_groups if not g.is_atomic]

    def summary(self, limit: int = 20) -> str:
        lines = [f"divergences: {len(self.divergences)}"]
        for d in self.divergences[:limit]:
            vs = ", ".join(f"{k}={v!r}" for k, v in d.values.items())
            lines.append(f"  out#{d.output_index} {d.path}: {vs}")
        if len(self.divergences) > limit:
            lines.append(f"  ... +{len(self.divergences) - limit} more")
        lines.append(f"atomic token-groups: {len(self.atomic_groups)}")
        for g in self.atomic_groups[:limit]:
            lines.append(
                f"  {g.value_set}: at {len(g.divergence_indices)} site(s)"
            )
        if self.derived_groups:
            lines.append(f"derived token-groups: {len(self.derived_groups)}")
            for g in self.derived_groups:
                parent = self.token_groups[g.derived_from]
                lines.append(
                    f"  {g.value_set} = {g.prefix!r}+{parent.value_set} "
                    f"at {len(g.divergence_indices)} site(s)"
                )
        return "\n".join(lines)


def find_diffs(instances: list[InstanceInput]) -> DiffReport:
    """Walk every output position, collect cross-instance divergences."""
    if len(instances) < 2:
        return DiffReport()

    n_outputs = len(instances[0].outputs)
    for inst in instances[1:]:
        if len(inst.outputs) != n_outputs:
            raise ValueError(
                f"instance {inst.label!r}: {len(inst.outputs)} outputs, "
                f"expected {n_outputs} (instances must align)"
            )

    report = DiffReport()
    for out_idx in range(n_outputs):
        path_values = {
            inst.label: inst.outputs[out_idx].output for inst in instances
        }
        if len(set(path_values.values())) > 1:
            report.divergences.append(
                Divergence(
                    output_index=out_idx,
                    path="__output_path__",
                    values=dict(path_values),
                )
            )
        data_trees = [inst.outputs[out_idx].data for inst in instances]
        labels = [inst.label for inst in instances]
        _walk(data_trees, labels, out_idx, "", report)

    _build_token_groups(report)
    _detect_prefix_derivations(report)
    return report


def _walk(
    nodes: list[Any], labels: list[str], out_idx: int,
    path: str, report: DiffReport,
) -> None:
    """Walk N parallel trees in lockstep, record per-leaf divergences."""
    if all(isinstance(n, dict) for n in nodes):
        keys: list[str] = []
        seen: set[str] = set()
        for n in nodes:
            for k in n:
                if k not in seen:
                    seen.add(k)
                    keys.append(k)
        for k in keys:
            children = [n.get(k) for n in nodes]
            _walk(children, labels, out_idx, f"{path}.{k}" if path else k, report)
        return
    if all(isinstance(n, list) for n in nodes):
        max_len = max(len(n) for n in nodes)
        for i in range(max_len):
            children = [n[i] if i < len(n) else None for n in nodes]
            _walk(children, labels, out_idx, f"{path}[{i}]", report)
        return
    if len({_hashable(n) for n in nodes}) > 1:
        report.divergences.append(
            Divergence(
                output_index=out_idx,
                path=path or "<root>",
                values=dict(zip(labels, nodes)),
            )
        )


def _hashable(v: Any) -> Any:
    if isinstance(v, (list, dict)):
        return repr(v)
    return v


def _build_token_groups(report: DiffReport) -> None:
    """Group scalar divergences by their value-set tuple.

    Scalar = str, int, float, bool. Numeric and boolean divergences
    surface as candidate atomic variables too; only nested-structure
    divergences (dict/list differences) are skipped — those reflect a
    schema-shape mismatch between instances, not a variable.
    """
    by_value_set: dict[tuple[Any, ...], list[int]] = defaultdict(list)
    for i, d in enumerate(report.divergences):
        if not all(_is_scalar(v) for v in d.values.values()):
            continue
        by_value_set[d.value_set].append(i)

    for value_set, idxs in by_value_set.items():
        # All divergences in the group should share the same
        # label→value mapping; pick the first as canonical.
        canonical = dict(report.divergences[idxs[0]].values)
        report.token_groups.append(
            TokenGroup(
                value_set=value_set,
                values_by_label=canonical,
                divergence_indices=idxs,
            )
        )


def _is_scalar(v: Any) -> bool:
    """Anything Jinja can render and YAML can round-trip as a leaf."""
    return v is None or isinstance(v, (str, int, float, bool))


def _detect_prefix_derivations(report: DiffReport) -> None:
    """Mark token-groups derivable from another via constant prefix/suffix.

    Algorithm: for every ordered pair (A, B) of string-only token-groups
    with the same label set, check whether for every label L,
    B.values_by_label[L] == prefix + A.values_by_label[L] for a single
    constant prefix. If so, B is derived from A with that prefix.

    Suffix derivation is symmetric.

    When a group could derive from multiple parents, pick the one with
    the shortest values (most atomic). This avoids chains where C
    derives from B which derives from A — we want C ← A directly.
    """
    groups = report.token_groups
    if len(groups) < 2:
        return

    # Score by "atomicity": shorter strings = more atomic.
    def atomicity(g: TokenGroup) -> int:
        return -max(len(str(v)) for v in g.values_by_label.values())

    # Sort indices by atomicity (descending), so the most-atomic
    # candidates are considered as parents first.
    candidate_parents = sorted(range(len(groups)), key=lambda i: atomicity(groups[i]), reverse=True)

    for child_idx, child in enumerate(groups):
        if not all(isinstance(v, str) for v in child.values_by_label.values()):
            continue
        for parent_idx in candidate_parents:
            if parent_idx == child_idx:
                continue
            parent = groups[parent_idx]
            if not all(isinstance(v, str) for v in parent.values_by_label.values()):
                continue
            if set(parent.values_by_label) != set(child.values_by_label):
                continue
            prefix = _common_prefix(parent.values_by_label, child.values_by_label)
            if prefix:
                child.derived_from = parent_idx
                child.prefix = prefix
                break
            suffix = _common_suffix(parent.values_by_label, child.values_by_label)
            if suffix:
                # Encode suffix derivation as prefix="" + suffix marker.
                # We currently only template prefixes; suffix-derived
                # groups stay atomic. (Could extend later.)
                continue


def _common_prefix(
    parent: dict[str, str], child: dict[str, str],
) -> str | None:
    """Return prefix p such that ∀L, child[L] == p + parent[L]. None if none."""
    prefixes: set[str] = set()
    for label, parent_val in parent.items():
        child_val = child[label]
        if not child_val.endswith(parent_val):
            return None
        prefixes.add(child_val[: len(child_val) - len(parent_val)])
        if len(prefixes) > 1:
            return None
    p = next(iter(prefixes))
    return p if p else None


def _common_suffix(
    parent: dict[str, str], child: dict[str, str],
) -> str | None:
    """Return suffix s such that ∀L, child[L] == parent[L] + s. None if none."""
    suffixes: set[str] = set()
    for label, parent_val in parent.items():
        child_val = child[label]
        if not child_val.startswith(parent_val):
            return None
        suffixes.add(child_val[len(parent_val):])
        if len(suffixes) > 1:
            return None
    s = next(iter(suffixes))
    return s if s else None
