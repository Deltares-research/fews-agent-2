"""Shared variable declarations across a pattern family.

A "family" is a parent folder grouping sibling pattern.yaml files (e.g.
``patterns/auto/gfs/``, holding ``deterministic/``, ``gribfilter/``,
``ensemble/``). Trivial variable declarations like ``nwp_name`` were getting
copy-pasted identically across siblings with nothing to keep them in sync
structurally -- not a correctness bug (nothing drifts when every copy is
identical), but real duplication worth centralizing.

Two independent call sites read a pattern's raw spec dict today --
``project_chat.build_pattern_catalog()`` (the LLM-facing catalog) and
``blueprint.expand()`` (the real per-instance render). Both route through
``merge_family_variables`` so the catalog and the actual render can never
disagree about what a pattern's variables are.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

_COMMENT_RE = re.compile(r"#.*$", re.MULTILINE)


def _references(raw_text: str, name: str) -> bool:
    """Whether ``name`` is actually used as a Jinja variable somewhere in
    ``raw_text`` (outside comments) -- e.g. ``{{ nwp_name }}`` or
    ``{% if nwp_name %}``. A plain substring/word match would also fire on
    an unrelated comment mentioning the name; stripping comments first
    keeps this a real usage check."""
    stripped = _COMMENT_RE.sub("", raw_text)
    return re.search(rf"\b{re.escape(name)}\b", stripped) is not None


def merge_family_variables(
    spec: dict[str, Any], pat_yaml_path: Path, raw_text: str | None = None,
) -> dict[str, Any]:
    """Merge a family-level ``variables.yaml`` (if present) under ``spec``'s
    own ``variables:`` -- but only the shared names this specific pattern
    actually uses.

    The family folder is ``pat_yaml_path``'s grandparent -- e.g. for
    ``patterns/auto/gfs/deterministic/pattern.yaml`` that's
    ``patterns/auto/gfs/``. Every pattern under a family folder sees the
    same shared file, but a sibling that never references a given shared
    variable (e.g. ``auto/gfs/ensemble`` doesn't use ``nwp_name``) must not
    inherit it -- a ``required: true`` shared variable an unrelated sibling
    never sets would otherwise break that sibling's build. The pattern's own
    declarations always win on a name collision, so a pattern can still
    override or add its own.
    """
    family_yaml = pat_yaml_path.parent.parent / "variables.yaml"
    if not family_yaml.is_file():
        return spec
    try:
        shared = yaml.safe_load(family_yaml.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return spec
    shared_vars = shared.get("variables") or {}
    if not shared_vars:
        return spec
    if raw_text is None:
        raw_text = pat_yaml_path.read_text(encoding="utf-8")
    applicable = {
        name: value for name, value in shared_vars.items()
        if name in (spec.get("variables") or {}) or _references(raw_text, name)
    }
    if not applicable:
        return spec
    merged = dict(spec)
    merged["variables"] = {**applicable, **(spec.get("variables") or {})}
    return merged
