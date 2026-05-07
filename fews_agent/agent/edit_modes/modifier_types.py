"""Interactive elicitation handler for ``inputs/modifierTypes.yaml``.

ModifierTypes declares the manual interventions operators are allowed
to perform on time series. The XSD admits ~25 modifier kinds with
40-100 fields each — far too many to ask cold. The POC focuses on the
single most common kind, ``timeSeriesModifier``, which alone covers
the operational use case (override values for a (module, parameter,
location) target).

A configurator typically wants several modifiers (one per
parameter/location combination they expect to override). The handler
loops: add modifier? → fields → add another? → ... → review → write.

State machine in ``state['_editing']``:

  stage='_start'    setup; advance immediately to 'ask_add'
  stage='ask_add'   prompt for "add a modifier? (y/n)"
  stage='ts_id'     ask modifier id
  stage='ts_name'   ask human-readable name (defaults to id if blank)
  stage='ts_module' ask moduleInstanceId (with project IDs as hints)
  stage='ts_param'  ask parameterId
  stage='ts_locset' ask locationSetId
  stage='review'    final confirmation, then write file
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml as _yaml
from lxml import etree


def advance(
    state: dict[str, Any],
    user_message: str,
    project_dir: Path,
) -> tuple[str, bool]:
    """Advance one turn. Returns ``(reply_text, done)``.

    ``done=True`` signals the caller to clear ``state['_editing']``.
    """
    edit = state["_editing"]
    stage = edit.get("stage", "_start")
    msg = (user_message or "").strip()

    if stage == "_start":
        edit["draft"] = {"timeSeriesModifier": []}
        edit["current"] = {}
        edit["stage"] = "ask_add"
        intro = (
            "Entering edit mode for modifierTypes.yaml. This file declares "
            "what manual interventions operators can make on time series. "
            "The POC supports timeSeriesModifier — the most common kind "
            "(override values for a specific module/parameter/location). "
            "Type /cancel-edit to abort.\n\n"
            "Add a timeSeriesModifier? (y/n)"
        )
        return (intro, False)

    if stage == "ask_add":
        if _is_yes(msg):
            edit["current"] = {}
            edit["stage"] = "ts_id"
            return (
                "Modifier id (e.g. ChangeQObserved, AdjustPC, "
                "MarkMissingData):",
                False,
            )
        if _is_no(msg):
            if not edit["draft"]["timeSeriesModifier"]:
                return (
                    "modifierTypes.yaml needs at least one modifier. "
                    "Add a timeSeriesModifier? (y/n)",
                    False,
                )
            edit["stage"] = "review"
            return (_review_summary(edit["draft"]), False)
        return ("Please answer y or n. Add a timeSeriesModifier? (y/n)", False)

    if stage == "ts_id":
        if not msg:
            return ("Modifier id can't be empty:", False)
        edit["current"]["id"] = msg
        edit["stage"] = "ts_name"
        return (
            f"Human-readable name for this modifier? "
            f"(blank = use id '{msg}'):",
            False,
        )

    if stage == "ts_name":
        # XSD requires the `name` attribute; default to id when blank.
        edit["current"]["name"] = msg or edit["current"]["id"]
        edit["stage"] = "ts_module"
        ids = _collect_ids(project_dir)
        return (_ask_with_hints("Module instance id", ids["moduleInstanceIds"]), False)

    if stage == "ts_module":
        if not msg:
            return ("Module instance id can't be empty:", False)
        edit["current"]["timeSeries"] = {"moduleInstanceId": msg}
        edit["stage"] = "ts_param"
        ids = _collect_ids(project_dir)
        return (_ask_with_hints("Parameter id", ids["parameterIds"]), False)

    if stage == "ts_param":
        if not msg:
            return ("Parameter id can't be empty:", False)
        edit["current"]["timeSeries"]["parameterId"] = msg
        # valueType is required; default 'scalar' covers most cases.
        edit["current"]["timeSeries"]["valueType"] = "scalar"
        edit["stage"] = "ts_locset"
        ids = _collect_ids(project_dir)
        return (_ask_with_hints("Location set id", ids["locationSetIds"]), False)

    if stage == "ts_locset":
        if not msg:
            return ("Location set id can't be empty:", False)
        edit["current"]["timeSeries"]["locationSetId"] = msg
        # XSD-required policy bools (Pydantic treats these as optional
        # but XSD does not). Defaulting to false is conservative; the
        # configurator can edit the yaml later for non-default behaviour.
        edit["current"]["resolveInWorkflow"] = False
        edit["current"]["resolveInPlots"] = False
        edit["draft"]["timeSeriesModifier"].append(edit["current"])
        added_id = edit["current"]["id"]
        edit["current"] = {}
        edit["stage"] = "ask_add"
        n = len(edit["draft"]["timeSeriesModifier"])
        return (
            f"Added '{added_id}' (total: {n}). Add another "
            f"timeSeriesModifier? (y/n)",
            False,
        )

    if stage == "review":
        if _is_yes(msg):
            return _validate_and_write(edit["draft"], project_dir)
        if _is_no(msg):
            return (
                "Cancelled. Run '/edit modifierTypes.yaml' again to retry.",
                True,
            )
        return ("Please answer y or n. Confirm write? (y/n)", False)

    return (f"(unknown stage {stage!r}; aborting)", True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_yes(msg: str) -> bool:
    return msg.lower() in {"y", "yes", "confirm", "ok"}


def _is_no(msg: str) -> bool:
    return msg.lower() in {"n", "no", "cancel", "skip"}


def _ask_with_hints(label: str, hints: list[str]) -> str:
    """Format an elicitation prompt with up to 8 hint values."""
    if not hints:
        return f"{label}:"
    shown = hints[:8]
    suffix = f" (project has {len(hints)} total)" if len(hints) > 8 else ""
    return f"{label} (existing: {', '.join(shown)}){suffix}:"


def _review_summary(draft: dict[str, Any]) -> str:
    lines = [
        f"Ready to write modifierTypes.yaml with "
        f"{len(draft['timeSeriesModifier'])} modifier(s):"
    ]
    for m in draft["timeSeriesModifier"]:
        ts = m.get("timeSeries", {})
        target = (
            f"{ts.get('moduleInstanceId', '?')}/"
            f"{ts.get('parameterId', '?')}/"
            f"{ts.get('locationSetId', '?')}"
        )
        lines.append(f"  - {m['id']} → {target}")
    lines.append("Confirm? (y/n)")
    return "\n".join(lines)


def _validate_and_write(
    draft: dict[str, Any],
    project_dir: Path,
) -> tuple[str, bool]:
    """Validate against Pydantic and write to inputs/modifierTypes.yaml."""
    try:
        from fews_agent.schema import ModifierTypes
        ModifierTypes.model_validate(draft)
    except Exception as exc:  # noqa: BLE001
        return (
            f"Validation failed: {type(exc).__name__}: "
            f"{str(exc)[:200]}\nEdit aborted; please /edit again.",
            True,
        )
    inputs_dir = project_dir / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    path = inputs_dir / "modifierTypes.yaml"
    path.write_text(
        _yaml.safe_dump(draft, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    return (
        f"Wrote {path}. Re-run build_from_blueprint to regenerate "
        f"the FEWS config with the new modifiers.",
        True,
    )


def _collect_ids(project_dir: Path) -> dict[str, list[str]]:
    """Find candidate moduleInstanceIds / parameterIds / locationSetIds.

    Walks the project's most recently-rendered XMLs under
    ``validation/<project>/generated`` (if any). Returns sorted lists,
    placeholders excluded. Empty lists if no rendered output yet — the
    handler degrades to free-text prompts in that case.
    """
    candidates: list[Path] = []
    repo_root = _find_repo_root(project_dir)
    if repo_root is not None:
        rendered_root = repo_root / "validation" / project_dir.name / "generated"
        if rendered_root.is_dir():
            candidates.append(rendered_root)

    out = {"moduleInstanceIds": [], "parameterIds": [], "locationSetIds": []}
    if not candidates:
        return out

    tag_to_key = {
        "moduleInstanceId": "moduleInstanceIds",
        "parameterId": "parameterIds",
        "locationSetId": "locationSetIds",
    }
    seen = {key: set() for key in tag_to_key.values()}
    for root in candidates:
        for p in root.rglob("*.xml"):
            try:
                tree = etree.fromstring(p.read_bytes())
            except etree.XMLSyntaxError:
                continue
            for tag, key in tag_to_key.items():
                for el in tree.iter("{*}" + tag):
                    text = (el.text or "").strip()
                    if text and "$" not in text:
                        seen[key].add(text)
    for key, values in seen.items():
        out[key] = sorted(values)
    return out


def _find_repo_root(start: Path) -> Path | None:
    """Walk up looking for a marker that identifies the repo root."""
    current = start.resolve()
    for parent in [current, *current.parents]:
        if (parent / "pyproject.toml").is_file() or (parent / "patterns").is_dir():
            return parent
    return None


__all__ = ["advance"]
