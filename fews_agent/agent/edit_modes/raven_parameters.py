"""Hand-rolled handler for ``inputs/ravenParameters.yaml``.

ModuleParameters file (also reused for wflow, mesh, sacsma, etc.).
Each entry is a parameter group; each group has a list of parameters
where each parameter has exactly one of bool/string/double/intValue
(XSD choice).

POC scope: one or more groups, each with parameters via per-parameter
value-type choice. Configurator can hand-edit yaml afterwards for
optional ``model`` / ``modifierType`` / ``version`` fields.
"""
from __future__ import annotations

from pathlib import Path

import yaml as _yaml

from fews_agent.schema import ModuleParameters

_VALUE_KINDS = ["stringValue", "doubleValue", "intValue", "boolValue"]


def advance(state, user_message, project_dir):
    edit = state["_editing"]
    stage = edit.get("stage", "_start")
    msg = (user_message or "").strip()
    edit.setdefault("draft", {})
    edit["draft"].setdefault("group", [])
    edit.setdefault("current", {})
    edit.setdefault("params", [])

    if stage == "_start":
        edit["stage"] = "ask_add"
        return (
            "Entering edit mode for ravenParameters.yaml. Each group "
            "bundles parameters for one model run; each parameter has "
            "an id and exactly one typed value. Type /cancel-edit to "
            "abort.\nAdd a parameter group? (y/n)",
            False,
        )

    if stage == "ask_add":
        if msg.lower() in {"y", "yes"}:
            edit["current"] = {}
            edit["params"] = []
            edit["stage"] = "group_id"
            return ("Group id (e.g. RavenLiard):", False)
        if msg.lower() in {"n", "no"}:
            if not edit["draft"]["group"]:
                return ("Need at least one group. Add one? (y/n)", False)
            edit["stage"] = "review"
            return (_summary(edit["draft"]), False)
        return ("y or n.", False)

    if stage == "group_id":
        if not msg:
            return ("Group id can't be empty:", False)
        edit["current"]["id"] = msg
        edit["stage"] = "param_id"
        return ("Parameter id (e.g. Block, ModelRoot):", False)

    if stage == "param_id":
        if not msg:
            return ("Parameter id can't be empty:", False)
        edit["_param"] = {"id": msg}
        edit["stage"] = "param_kind"
        return (
            "Value type for this parameter:\n"
            "  1. stringValue\n"
            "  2. doubleValue\n"
            "  3. intValue\n"
            "  4. boolValue\n"
            "Pick a number:",
            False,
        )

    if stage == "param_kind":
        try:
            picked = int(msg) - 1
            if not 0 <= picked < len(_VALUE_KINDS):
                raise ValueError
        except ValueError:
            return ("Pick a number 1-4:", False)
        edit["_param_kind"] = _VALUE_KINDS[picked]
        edit["stage"] = "param_value"
        return (f"{edit['_param_kind']} (e.g. true / 0.5 / 42 / hello):", False)

    if stage == "param_value":
        if not msg:
            return ("Value can't be empty:", False)
        # XSD models all 4 value variants as strings; FEWS coerces at
        # runtime. Pass through verbatim — supports placeholders too.
        edit["_param"][edit["_param_kind"]] = msg
        edit["params"].append(edit["_param"])
        edit["_param"] = {}
        edit["_param_kind"] = ""
        edit["stage"] = "more_param"
        return (
            f"Added parameter (total in this group: {len(edit['params'])}). "
            "Add another parameter? (y/n)",
            False,
        )

    if stage == "more_param":
        if msg.lower() in {"y", "yes"}:
            edit["stage"] = "param_id"
            return ("Parameter id:", False)
        if msg.lower() in {"n", "no"}:
            edit["current"]["parameter"] = edit["params"]
            edit["draft"]["group"].append(edit["current"])
            gid = edit["current"]["id"]
            edit["current"] = {}
            edit["params"] = []
            edit["stage"] = "ask_add"
            n = len(edit["draft"]["group"])
            return (
                f"Added group '{gid}' (total groups: {n}). "
                "Add another parameter group? (y/n)",
                False,
            )
        return ("y or n.", False)

    if stage == "review":
        if msg.lower() in {"y", "yes"}:
            return _validate_and_write(edit["draft"], project_dir)
        if msg.lower() in {"n", "no"}:
            return ("Cancelled.", True)
        return ("y or n.", False)

    return (f"(unknown stage {stage!r}; aborting)", True)


def _summary(draft):
    lines = [
        f"Ready to write ravenParameters.yaml with "
        f"{len(draft['group'])} group(s):"
    ]
    for g in draft["group"]:
        params = ", ".join(p["id"] for p in g.get("parameter", []))
        lines.append(f"  - {g['id']}: [{params}]")
    lines.append("Confirm? (y/n)")
    return "\n".join(lines)


def _validate_and_write(draft, project_dir):
    try:
        ModuleParameters.model_validate(draft)
    except Exception as exc:  # noqa: BLE001
        return (f"Validation failed: {type(exc).__name__}: {str(exc)[:200]}", True)
    inputs_dir = project_dir / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    path = inputs_dir / "ravenParameters.yaml"
    path.write_text(
        _yaml.safe_dump(draft, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    return (f"Wrote {path}.", True)


__all__ = ["advance"]
