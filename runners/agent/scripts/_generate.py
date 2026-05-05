"""Auto-generate wizard answer queues from the tutorial input JSON.

The wizard architecture is driven by ``WizardSpec`` entries that
declare file-level setters and one-or-more sections of repeating
typed items. The tutorial JSON
(``examples/config-tutorial-input.json``) carries the same data as a
flat dict: every spec's input lives at ``data[<input_key>]``.

This module mechanically translates each tutorial entry into the
sequence of natural-language replies the wizard expects, so a single
project-level script can drive every wizard-supported spec at once.

Per-spec output:

  1. file-level setters in declaration order — one reply per setter
     whose value is present in the JSON (skipped if absent).
  2. for each section in declaration order:
       - one bulk-ask reply per item formatted as
         ``key="value", key="value"`` (dotted paths flattened from any
         nested Pydantic; lists rendered as JSON arrays of strings).
       - a "no" reply if the section's items support attributes (we
         never auto-add attributes — they're a wizard convenience).
       - "yes" / "no" replies driving the "Add another?" loop.
       - "skip" sentinel if the section has zero items (exits the
         section without trying to insert one).

Intentionally bland format. The point of this generator is regression
coverage at scale, not naturalistic prose.
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from fews_agent.agent.wizard import (
    WIZARD_SPECS,
    WizardField,
    WizardSection,
    WizardSpec,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
TUTORIAL_JSON = REPO_ROOT / "examples" / "config-tutorial-input.json"


# ---------------------------------------------------------------------------
# JSON loading
# ---------------------------------------------------------------------------


def load_tutorial(path: Path | None = None) -> dict[str, Any]:
    """Load the tutorial input JSON with parse_float=Decimal so coord
    digits round-trip exactly through string formatting (matches
    runners/generation/run_generation.py)."""
    p = path or TUTORIAL_JSON
    with p.open("r", encoding="utf-8") as f:
        return json.load(f, parse_float=Decimal)


# ---------------------------------------------------------------------------
# Value formatting
# ---------------------------------------------------------------------------


def _format_scalar(v: Any) -> str:
    """Format a JSON value as a string for prompt-side use.

    - bool → "true" / "false"
    - Decimal/int/float → str() (preserves digits via Decimal)
    - str → as-is
    - None → empty
    - list → JSON array of stringified items
    - dict → str(dict) (rare; should usually have been flattened)
    """
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (Decimal, int, float)):
        return str(v)
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        return json.dumps([str(x) for x in v], ensure_ascii=False)
    return str(v)


def _lookup_dotted(data: dict[str, Any], path: str) -> Any:
    """Resolve a dotted path inside a (potentially nested) dict.

    Returns ``...`` (Ellipsis) when the path doesn't exist — distinct
    from None values that are present in the JSON.
    """
    cur: Any = data
    for part in path.split("."):
        if not isinstance(cur, dict):
            return ...
        if part not in cur:
            return ...
        cur = cur[part]
    return cur


def _flatten_item(item: dict[str, Any], wanted_paths: list[str]) -> dict[str, Any]:
    """Pull only the wanted dotted-path keys out of a possibly-nested item.

    Skips paths the JSON doesn't have so we don't fabricate values.
    """
    out: dict[str, Any] = {}
    for path in wanted_paths:
        v = _lookup_dotted(item, path)
        if v is ...:
            continue
        if v is None:
            continue
        out[path] = v
    return out


def _format_bulk_reply(item: dict[str, Any], fields: list[WizardField]) -> str:
    """Render a flat dict as ``key="value", ...`` prose for the bulk parser.

    Lists become JSON arrays so the parser's list-extraction path picks
    them up. Strings are double-quoted to keep the LLM from chopping
    on whitespace.
    """
    flat = _flatten_item(item, [f.path for f in fields])
    parts: list[str] = []
    for path, value in flat.items():
        if isinstance(value, list):
            arr = json.dumps([str(x) for x in value], ensure_ascii=False)
            parts.append(f"{path}={arr}")
        elif isinstance(value, bool):
            parts.append(f'{path}="{_format_scalar(value)}"')
        elif isinstance(value, (Decimal, int, float)):
            # Quote numerics so digits survive; Pydantic accepts the string.
            parts.append(f'{path}="{_format_scalar(value)}"')
        else:
            parts.append(f'{path}="{value}"')
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# Phase building
# ---------------------------------------------------------------------------


def build_phase_answers(
    spec: WizardSpec,
    data: dict[str, Any],
    *,
    cross_phase_seen: dict[str, str] | None = None,
) -> list[str]:
    """Build the answer queue for one wizard run on one spec.

    ``data`` is the spec-level entry pulled from the tutorial JSON
    (i.e. ``tutorial[spec.input_key]``). May be None / missing — in
    that case the answer queue triggers nothing meaningful.

    ``cross_phase_seen`` is a name→value mapping of file-level
    setters set by *earlier* phases. The wizard's
    ``run_file_level_wizard`` auto-fills those without prompting, so
    we MUST suppress the corresponding answers here to keep the
    replay queue in sync.
    """
    seen = cross_phase_seen or {}
    answers: list[str] = []

    # File-level setters: in declaration order. Resolve via dotted lookup.
    if isinstance(data, dict):
        for setter in spec.file_level:
            if setter.field in seen:
                # Wizard skips the prompt; emit nothing.
                continue
            v = _lookup_dotted(data, setter.field)
            if v is ...:
                # Nothing in tutorial — let the wizard skip / use default.
                # We still need an answer queued (Prompt.ask consumes one).
                answers.append(setter.default or "")
            else:
                answers.append(_format_scalar(v))

    # Each section: one bulk reply containing ALL items, separated by
    # newlines. The wizard's section-level bulk-ask parses the list in
    # one (or more, if >8) LLM calls and upserts each. The wizard no
    # longer asks "Add more X?" after a bulk reply (the ask itself
    # promises one-or-many in one go), so we don't emit a trailing
    # confirm answer here.
    for section in spec.sections:
        items: list[Any] = []
        if isinstance(data, dict):
            raw_items = data.get(section.item_field) or []
            if isinstance(raw_items, list):
                items = raw_items

        if not items:
            answers.append("skip")
            continue

        # Build one big multi-item reply. Each item on its own line
        # with a leading "- " bullet so the parser can split the list.
        lines: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            line = _format_bulk_reply(item, section.bulk_fields)
            if line:
                lines.append(f"- {line}")
        if not lines:
            answers.append("skip")
            continue
        answers.append("\n".join(lines))

    return answers


def build_phases(
    *,
    only: set[str] | None = None,
    skip: set[str] | None = None,
    json_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Walk the tutorial JSON and return one phase per spec with data.

    A spec gets a phase iff:
      - it's registered in WIZARD_SPECS, AND
      - the tutorial JSON has data under its input_key.

    ``only`` / ``skip`` are optional name filters on the spec's
    registered name (``WizardSpec.name``).

    Tracks file-level setter values across phases — when a later
    spec's setter has the same name as an earlier phase's, the answer
    is suppressed because the wizard auto-fills from project state.
    """
    data = load_tutorial(json_path)
    phases: list[dict[str, Any]] = []
    cross_phase_seen: dict[str, str] = {}
    for name, spec in WIZARD_SPECS.items():
        if only is not None and name not in only:
            continue
        if skip is not None and name in skip:
            continue
        if spec.input_key not in data:
            continue
        entry = data[spec.input_key]
        # Skip explicit nulls — nothing to elicit.
        if entry is None:
            continue
        answers = build_phase_answers(
            spec, entry, cross_phase_seen=cross_phase_seen
        )
        if not answers:
            continue
        phases.append(
            {
                "spec_name": name,
                "label": name,
                "answers": answers,
            }
        )
        # Update the seen-set with this phase's file-level setter
        # values (whether we emitted them or they were inherited).
        if isinstance(entry, dict):
            for setter in spec.file_level:
                if setter.field in cross_phase_seen:
                    continue
                v = _lookup_dotted(entry, setter.field)
                if v is ... or v is None:
                    continue
                if isinstance(v, (dict, list)) and not v:
                    continue
                cross_phase_seen[setter.field] = _format_scalar(v)
    return phases


__all__ = [
    "build_phase_answers",
    "build_phases",
    "load_tutorial",
]
