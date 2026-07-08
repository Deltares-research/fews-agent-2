"""Centralised LLM prompts + the tool-wizard system-prompt builder.

**Standing rule for this codebase:** every LLM prompt (system + user) lives
as a ``.txt`` file in THIS folder, and Python only supplies substitution
values. Prompts are what researchers/configurators iterate on most, so they
must be editable without touching logic. Load them with :func:`load`::

    from fews_agent.agent import prompts

    system = prompts.load("classify_intent.system")            # static
    user = prompts.load("classify_intent.user", prose=repr(p),  # templated
                        intent_descriptions=descs)

Templating is Jinja2 with **square-bracket delimiters** (``[[ var ]]``,
``[% if %]``) instead of curly braces, because prompt text is full of
literal ``{`` / ``}`` (JSON schemas, examples) and ``$`` (FEWS placeholders
like ``$MODELNAME1$``) — square brackets collide with neither.
``StrictUndefined`` makes a missing variable fail loudly instead of
rendering an empty string into a prompt. File naming: ``<job>.<role>.txt``
(role = ``system`` | ``user``).

This module ALSO hosts the legacy tool-wizard :func:`build_system_prompt`
(regenerated each turn for the tool-calling chat path); its text is being
migrated to ``.txt`` alongside the rest.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .. import checklist as _checklist
from ..tools import TOOLS

# ---------------------------------------------------------------------------
# Prompt loader (the standing-rule API)
# ---------------------------------------------------------------------------

_PROMPTS_DIR = Path(__file__).parent

_env = Environment(
    loader=FileSystemLoader(str(_PROMPTS_DIR)),
    variable_start_string="[[",
    variable_end_string="]]",
    block_start_string="[%",
    block_end_string="%]",
    comment_start_string="[#",
    comment_end_string="#]",
    keep_trailing_newline=True,
    autoescape=False,
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


@lru_cache(maxsize=None)
def _template(filename: str):
    return _env.get_template(filename)


def load(name: str, /, **variables) -> str:
    """Render prompt ``name`` (``.txt`` suffix optional) with ``variables``.

    Static prompts render verbatim when called with no variables; templated
    prompts substitute ``[[ var ]]`` placeholders. Raises if the file is
    missing or a referenced variable isn't supplied (StrictUndefined).
    """
    filename = name if name.endswith(".txt") else f"{name}.txt"
    return _template(filename).render(**variables)


# ---------------------------------------------------------------------------
# Legacy tool-wizard system-prompt builder
# ---------------------------------------------------------------------------

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
    return load(
        "wizard_system",
        tool_summary=_tool_summary(),
        spec_name=spec_name,
        checklist=_render_checklist(spec_name),
        snapshot=_short_snapshot(project_data),
    )


__all__ = ["load", "build_system_prompt"]
