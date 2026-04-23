"""System-prompt builder for the chat side of the agent.

The prompt is regenerated every turn so the model sees the current
project state, the checklist for the active spec, and the tool surface
— no stale context.

Kept under ~2KB by design:
  - Role + hard rules
  - Compact tool summary (names + one-line each)
  - Current project snapshot (pretty JSON, truncated)
  - Checklist slice: required vs optional, with enums/refs inlined
  - Style rules (ask one thing at a time, route coords through wizard)
"""
from __future__ import annotations

import json
from typing import Any

from .. import checklist as _checklist
from ..tools import TOOLS

_SNAPSHOT_BUDGET = 2000  # chars in the JSON snapshot


def _short_snapshot(data: dict[str, Any]) -> str:
    text = json.dumps(data, indent=2, ensure_ascii=False, default=str)
    if len(text) > _SNAPSHOT_BUDGET:
        return text[:_SNAPSHOT_BUDGET] + "\n... (truncated)"
    return text


def _render_checklist(spec_name: str) -> str:
    entries = _checklist.checklist_for(spec_name)
    if not entries:
        return "(no checklist available for this spec)"
    required = []
    optional = []
    for e in entries:
        if e.get("kind") == "static":
            continue
        line = f"- {e['path']} [{e.get('kind', 'scalar')}]"
        if e.get("allowed_values"):
            line += f" allowed={e['allowed_values']}"
        if e.get("ref"):
            line += f" ref={e['ref']}"
        if e.get("declares"):
            line += f" declares={e['declares']}"
        (required if e.get("required") else optional).append(line)
    lines = ["Required:"] + (required or ["  (none)"])
    if optional:
        lines += ["Optional:"] + optional
    return "\n".join(lines)


def _tool_summary() -> str:
    return "\n".join(f"- {t.name}: {t.description.splitlines()[0]}" for t in TOOLS)


def build_system_prompt(spec_name: str, project_data: dict[str, Any]) -> str:
    return (
        "You are a FEWS configuration assistant. You help a user author "
        "Delft-FEWS XML configs by asking focused questions, calling the "
        "provided tools to persist state and produce XML, and validating "
        "the result. You NEVER write XML yourself — always call the "
        "`generate` tool.\n"
        "\n"
        "Hard rules:\n"
        "  1. Ask one focused question at a time.\n"
        "  2. For coordinates (x, y, z), pass them as STRINGS to preserve "
        "digits. Suggest the side-panel wizard for bulk entry.\n"
        "  3. After params validate, call `generate` — do not print XML "
        "as prose. Report xsd_ok and a short summary from the tool result.\n"
        "  4. On `validation_errors`, read the errors and correct your "
        "args; do not invent fields.\n"
        "\n"
        "Available tools:\n"
        f"{_tool_summary()}\n"
        "\n"
        f"Active spec: {spec_name}\n"
        "\n"
        "Checklist for this spec:\n"
        f"{_render_checklist(spec_name)}\n"
        "\n"
        "Current project state (live; reload each turn):\n"
        f"{_short_snapshot(project_data)}\n"
    )


__all__ = ["build_system_prompt"]
