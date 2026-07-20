"""LLM-backed natural-language parser for wizard group answers.

The wizard owns the *flow* (which fields, what order, when to ask "add
another"). The parser owns the *interpretation*: given a single user
utterance and a description of the fields the wizard wants, return a
``{path: value}`` dict. The wizard then validates each value against
its declared kind (decimal, enum, ref) using its existing helpers.

Key design choice: per-step scope. The parser sees only one bulk prompt
and one user reply; it has no conversation history, no tool registry,
no ability to wander. That keeps the LLM call cheap and reliable even
on small models.

Provider contract: anything that exposes ``generate_json(system, user,
schema) -> StructuredResponse`` works (see ``providers/base.py`` for
the dataclass). The parser threads ``StructuredResponse.usage`` onto
``ParseResult.usage`` so the replay runner can sum tokens across
many small parse calls.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .providers.base import StructuredOutputProvider, StructuredResponse

_logger = logging.getLogger(__name__)


@dataclass
class ParseResult:
    """Outcome of one parse call.

    ``values`` maps field paths (the wizard's ``WizardField.path``) to
    raw string values. ``error`` is set when the provider call failed
    or the response couldn't be parsed; the wizard should fall back to
    field-by-field prompting in that case. ``usage`` carries token
    counts from the underlying provider call when reported.
    """

    values: dict[str, str]
    error: str | None = None
    raw_response: dict[str, Any] | None = None
    usage: dict[str, int] | None = None


def _schema_for_fields(fields: list[Any]) -> dict[str, Any]:
    """Build a JSON schema describing the parser's expected output.

    Every field is optional in the schema even when wizard-required —
    the wizard handles required-but-missing via field-by-field
    fallback. This way the parser can return only what the user
    actually said without inventing values.
    """
    properties: dict[str, Any] = {}
    scalar_descriptions = {
        "scalar": "string value, exactly as the user wrote it",
        "decimal": "numeric string preserving source digits (e.g. '0', '-180', '-142.8968')",
        "enum": "one of the allowed values",
        "ref": "id from another spec",
        "bool": "'true' or 'false'",
    }
    for f in fields:
        kind = getattr(f, "kind", "scalar")
        if kind == "list_str":
            prop: dict[str, Any] = {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    f"{getattr(f, 'prompt', f.path)} — list of strings "
                    f"the user provided (e.g. ['a', 'b', 'c'])."
                ),
            }
        elif kind == "list_decimal":
            prop = {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    f"{getattr(f, 'prompt', f.path)} — list of numeric "
                    f"strings preserving source digits."
                ),
            }
        else:
            prop = {
                "type": "string",
                "description": (
                    f"{getattr(f, 'prompt', f.path)} — "
                    f"{scalar_descriptions.get(kind, 'string value')}"
                ),
            }
            allowed = getattr(f, "allowed_values", None)
            if allowed:
                prop["enum"] = list(allowed)
        properties[f.path] = prop
    return {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }


def _system_prompt() -> str:
    from fews_agent.agent import prompts
    return prompts.load("nl_parser_extract.system")


def _user_prompt(text: str, group_label: str | None) -> str:
    from fews_agent.agent import prompts
    return prompts.load(
        "nl_parser_extract.user",
        text=text.strip(), group_label=group_label or "",
    )


def parse_group(
    text: str,
    fields: list[Any],
    provider: StructuredOutputProvider,
    group_label: str | None = None,
) -> ParseResult:
    """Extract field values from one user utterance.

    `fields` is a list of ``WizardField``-like objects (anything with
    ``path``, ``prompt``, ``kind``, optional ``allowed_values``). The
    return value's ``values`` dict will only contain fields the user
    actually mentioned — empty if the parser couldn't extract anything.
    """
    if not text.strip():
        return ParseResult(values={})

    schema = _schema_for_fields(fields)
    try:
        resp = provider.generate_json(
            system=_system_prompt(),
            user=_user_prompt(text, group_label),
            schema=schema,
        )
    except Exception as exc:  # noqa: BLE001 — providers raise various
        _logger.warning("nl_parser: provider call failed (%s)", exc)
        return ParseResult(values={}, error=f"{type(exc).__name__}: {exc}")

    raw = resp.data if isinstance(resp, StructuredResponse) else resp
    usage = resp.usage if isinstance(resp, StructuredResponse) else None

    if not isinstance(raw, dict):
        return ParseResult(
            values={},
            error=f"provider returned non-dict: {type(raw).__name__}",
            usage=usage,
        )

    valid_paths = {f.path for f in fields}
    list_kinds = {f.path for f in fields if getattr(f, "kind", "") in {"list_str", "list_decimal"}}
    values: dict[str, Any] = {}
    for k, v in raw.items():
        if k not in valid_paths:
            continue
        if v is None:
            continue
        if k in list_kinds:
            # Keep lists as lists. Coerce items to stripped strings.
            if isinstance(v, list):
                cleaned = [
                    str(x).strip() for x in v
                    if x is not None and str(x).strip()
                ]
                if cleaned:
                    values[k] = cleaned
            elif isinstance(v, str) and v.strip():
                # Some models return a comma-separated string; fall
                # back to splitting.
                cleaned = [x.strip() for x in v.split(",") if x.strip()]
                if cleaned:
                    values[k] = cleaned
            continue
        # Scalar — coerce to a stripped string.
        sval = str(v).strip()
        if not sval:
            continue
        values[k] = sval

    return ParseResult(values=values, raw_response=raw, usage=usage)


def _list_schema_for_fields(fields: list[Any]) -> dict[str, Any]:
    """Build a JSON schema for ``{"items": array of <item schema>}``.

    Wrapping in an outer object plays nicer with the structured-output
    fallback (which scavenges the first balanced ``{...}`` from the
    completion). Bare top-level arrays are awkward for that scavenger.
    """
    item_schema = _schema_for_fields(fields)
    return {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": item_schema,
            }
        },
        "required": ["items"],
        "additionalProperties": False,
    }


def _list_user_prompt(text: str, group_label: str | None) -> str:
    from fews_agent.agent import prompts
    return prompts.load(
        "nl_parser_extract_list.user",
        text=text.strip(), group_label=group_label or "",
    )


def parse_group_list(
    text: str,
    fields: list[Any],
    provider: StructuredOutputProvider,
    group_label: str | None = None,
) -> ParseResult:
    """Extract a list of items from one user utterance.

    Tolerates the model returning the array under various shapes:
      - ``{"items": [...]}`` (the schema we asked for)
      - bare ``[...]`` (model ignored the wrapper)
      - bare ``{...}`` (single item; wrapped in a list)

    ``ParseResult.values`` carries the list under the conventional key
    ``"_items"`` so callers can distinguish from a single-dict parse.
    """
    if not text.strip():
        return ParseResult(values={})

    schema = _list_schema_for_fields(fields)
    try:
        resp = provider.generate_json(
            system=_system_prompt(),
            user=_list_user_prompt(text, group_label),
            schema=schema,
        )
    except Exception as exc:  # noqa: BLE001
        _logger.warning("nl_parser(list): provider call failed (%s)", exc)
        return ParseResult(values={}, error=f"{type(exc).__name__}: {exc}")

    raw = resp.data if isinstance(resp, StructuredResponse) else resp
    usage = resp.usage if isinstance(resp, StructuredResponse) else None

    # Normalise the response into ``items`` (list of dicts).
    items: list[Any] | None = None
    if isinstance(raw, dict):
        if "items" in raw and isinstance(raw["items"], list):
            items = raw["items"]
        else:
            # Bare single dict — wrap.
            items = [raw]
    elif isinstance(raw, list):
        items = raw
    if not items:
        return ParseResult(
            values={},
            error="parser returned no items",
            raw_response=raw if isinstance(raw, dict) else None,
            usage=usage,
        )

    valid_paths = {f.path for f in fields}
    list_kinds = {f.path for f in fields if getattr(f, "kind", "") in {"list_str", "list_decimal"}}
    cleaned_items: list[dict[str, Any]] = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        cleaned: dict[str, Any] = {}
        for k, v in entry.items():
            if k not in valid_paths:
                continue
            if v is None:
                continue
            if k in list_kinds:
                if isinstance(v, list):
                    arr = [str(x).strip() for x in v if x is not None and str(x).strip()]
                    if arr:
                        cleaned[k] = arr
                elif isinstance(v, str) and v.strip():
                    arr = [x.strip() for x in v.split(",") if x.strip()]
                    if arr:
                        cleaned[k] = arr
                continue
            sval = str(v).strip()
            if not sval:
                continue
            cleaned[k] = sval
        if cleaned:
            cleaned_items.append(cleaned)

    return ParseResult(
        values={"_items": cleaned_items},
        raw_response=raw if isinstance(raw, dict) else None,
        usage=usage,
    )


__all__ = ["ParseResult", "parse_group", "parse_group_list"]
