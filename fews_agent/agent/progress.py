"""Derived project progress — "what's still missing?"

Walks the spec's checklist and compares each required `path` to the
current `project_data`. Produces a structured `ProjectProgress` used by
the TUI's state view and by the wizard's resume logic.

The path language in `file_to_variables.json`:
  - `geoDatum` — top-level field under the spec's input key
  - `location[].id` — field inside each repeating_group item
  - `location[].attribute[]` — nested repeating, treated as a whole
  - `A|B` — user supplies exactly one (first-match is required)

Everything here is spec-agnostic. Adding new specs to the coverage
doesn't touch this file — just the `file_to_variables.json` entry.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .checklist import checklist_for, file_type_for


@dataclass
class ItemProgress:
    """One entry of a repeating group (e.g. one `<location>`)."""

    index: int
    id: str | None
    missing: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.missing


@dataclass
class ProjectProgress:
    spec_name: str
    file_type: str | None
    file_level_missing: list[str] = field(default_factory=list)
    per_item: list[ItemProgress] = field(default_factory=list)
    item_count: int = 0

    @property
    def fully_complete(self) -> bool:
        if self.file_level_missing:
            return False
        if not self.per_item:
            # Some specs have no repeating group (e.g. Permissions roots
            # that use only a flat `permission[]` list which we treat as
            # the item itself). For Locations we do require at least one
            # location — callers should enforce that separately if
            # relevant. Default: file-level OK is enough.
            return True
        return all(i.complete for i in self.per_item)


def _split_path(path: str) -> list[str]:
    """'location[].id' → ['location', '[]', 'id']; 'geoDatum' → ['geoDatum']."""
    parts: list[str] = []
    for seg in path.split("."):
        if "[]" in seg:
            name, _ = seg.split("[]", 1)
            if name:
                parts.append(name)
            parts.append("[]")
        else:
            parts.append(seg)
    return parts


def _is_filled(value: Any) -> bool:
    """Empty string / None / [] / {} count as missing; 0 and False do not."""
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, (list, dict)):
        return len(value) > 0
    return True


def _item_display_id(item: dict[str, Any]) -> str | None:
    for key in ("id", "validationRuleSetId", "workflowId", "moduleInstanceId"):
        if item.get(key):
            return str(item[key])
    return None


def compute_progress(spec_name: str, project_data: dict[str, Any]) -> ProjectProgress:
    """Walk the spec's checklist against current data and report gaps."""
    file_type = file_type_for(spec_name)
    report = ProjectProgress(spec_name=spec_name, file_type=file_type)

    entries = checklist_for(spec_name)
    if not entries:
        return report  # no known checklist → assume complete; TUI warns

    # Pick the spec's input block. Use the generator registry to find the
    # canonical input_key; fall back to the spec name itself.
    from fews_agent.generators import SPECS

    spec = next((s for s in SPECS if s.name == spec_name), None)
    input_key = spec.input_key if spec else spec_name
    block = project_data.get(input_key, {})

    # Split required entries into file-level (no repeating_group) vs per-item.
    file_level: list[dict[str, Any]] = []
    per_item_required: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        if entry.get("kind") == "static" or not entry.get("required"):
            continue
        group = entry.get("repeating_group")
        if group:
            per_item_required.setdefault(group, []).append(entry)
        else:
            file_level.append(entry)

    # File-level check: each entry's `path` is a dotted lookup in the block.
    for entry in file_level:
        parts = _split_path(entry["path"])
        val: Any = block
        for p in parts:
            if p == "[]":
                # unexpected on file-level; treat as missing.
                val = None
                break
            if isinstance(val, dict):
                val = val.get(p)
            else:
                val = None
                break
        if not _is_filled(val):
            report.file_level_missing.append(entry["path"])

    # Per-item check: walk each repeating group and test required leaves.
    for group_name, required_entries in per_item_required.items():
        # Support single-level grouping (e.g. "location"); nested groups
        # like "parameterGroup.parameter" come in as a dotted name — the
        # first token is the outer array on the block.
        top = group_name.split(".", 1)[0]
        items = block.get(top, []) if isinstance(block, dict) else []
        if not isinstance(items, list):
            items = []
        if group_name == top:
            # flat group
            for i, item in enumerate(items):
                missing = []
                for entry in required_entries:
                    leaf = entry["path"].split("].", 1)[-1]  # strip "group[]."
                    if not _is_filled(item.get(leaf)):
                        missing.append(leaf)
                report.per_item.append(
                    ItemProgress(index=i, id=_item_display_id(item), missing=missing)
                )
            report.item_count = len(items)
        # nested handling can come later when we cover specs with that shape.

    return report
