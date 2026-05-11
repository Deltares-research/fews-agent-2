"""Hand-rolled handler for ``inputs/thresholds.yaml``.

ThresholdGroups XSD shape:

  thresholdGroup [list, min 1]
    id, name?
    defaultThreshold (required by XSD sequence, before levelThreshold)
      shortName
    levelThreshold [list, min 1]
      id, upWarningLevelId, name?, shortName?

The walker doesn't yet handle nested-typed-list, so this handler is
hand-rolled with an inner loop for levelThreshold entries. POC asks
the minimum XSD-required fields per entry.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml as _yaml

from fews_agent.schema import ThresholdGroups


def advance(
    state: dict[str, Any],
    user_message: str,
    project_dir: Path,
) -> tuple[str, bool]:
    edit = state["_editing"]
    stage = edit.get("stage", "_start")
    msg = (user_message or "").strip()
    edit.setdefault("draft", {})
    edit["draft"].setdefault("thresholdGroup", [])
    edit.setdefault("current", {})
    edit.setdefault("levels", [])

    if stage == "_start":
        edit["stage"] = "ask_add"
        return (
            "Entering edit mode for thresholds.yaml. Each thresholdGroup "
            "bundles related warning levels (e.g. flood-stage levels). "
            "Type /cancel-edit to abort.\nAdd a thresholdGroup? (y/n)",
            False,
        )

    if stage == "ask_add":
        if msg.lower() in {"y", "yes"}:
            edit["current"] = {}
            edit["levels"] = []
            edit["stage"] = "group_id"
            return ("Threshold group id (e.g. TG_Flood):", False)
        if msg.lower() in {"n", "no"}:
            if not edit["draft"]["thresholdGroup"]:
                return (
                    "thresholds.yaml needs at least one thresholdGroup. "
                    "Add one? (y/n)",
                    False,
                )
            edit["stage"] = "review"
            return (_summary(edit["draft"]), False)
        return ("Please answer y or n.", False)

    if stage == "group_id":
        if not msg:
            return ("Group id can't be empty:", False)
        edit["current"]["id"] = msg
        edit["stage"] = "default_short"
        return (
            "Default threshold shortName (matches one of the levels' "
            "shortName, e.g. Flood):",
            False,
        )

    if stage == "default_short":
        if not msg:
            return ("Default shortName can't be empty:", False)
        edit["current"]["defaultThreshold"] = {"shortName": msg}
        edit["stage"] = "lvl_id"
        return ("Level id (e.g. L1_Flood):", False)

    if stage == "lvl_id":
        if not msg:
            return ("Level id can't be empty:", False)
        edit["_lvl"] = {"id": msg}
        edit["stage"] = "lvl_warning"
        return (
            "upWarningLevelId for this level (matches an id in "
            "thresholdWarningLevels.csv, e.g. WL_Flood):",
            False,
        )

    if stage == "lvl_warning":
        if not msg:
            return ("upWarningLevelId can't be empty:", False)
        edit["_lvl"]["upWarningLevelId"] = msg
        edit["stage"] = "lvl_short"
        return (
            "Short name for this level (or blank to skip; the "
            "defaultThreshold should match one of these):",
            False,
        )

    if stage == "lvl_short":
        if msg:
            edit["_lvl"]["shortName"] = msg
        edit["levels"].append(edit["_lvl"])
        edit["_lvl"] = {}
        edit["stage"] = "ask_more_lvl"
        return (
            f"Added level (total in this group: {len(edit['levels'])}). "
            "Add another level to this group? (y/n)",
            False,
        )

    if stage == "ask_more_lvl":
        if msg.lower() in {"y", "yes"}:
            edit["stage"] = "lvl_id"
            return ("Level id:", False)
        if msg.lower() in {"n", "no"}:
            edit["current"]["levelThreshold"] = edit["levels"]
            edit["draft"]["thresholdGroup"].append(edit["current"])
            gid = edit["current"]["id"]
            edit["current"] = {}
            edit["levels"] = []
            edit["stage"] = "ask_add"
            n = len(edit["draft"]["thresholdGroup"])
            return (
                f"Added group '{gid}' (total groups: {n}). "
                "Add another thresholdGroup? (y/n)",
                False,
            )
        return ("Please answer y or n.", False)

    if stage == "review":
        if msg.lower() in {"y", "yes"}:
            return _validate_and_write(edit["draft"], project_dir)
        if msg.lower() in {"n", "no"}:
            return ("Cancelled. /edit thresholds.yaml again to retry.", True)
        return ("Please answer y or n.", False)

    return (f"(unknown stage {stage!r}; aborting)", True)


def _summary(draft: dict[str, Any]) -> str:
    lines = [
        f"Ready to write thresholds.yaml with "
        f"{len(draft['thresholdGroup'])} group(s):"
    ]
    for g in draft["thresholdGroup"]:
        levels = ", ".join(l["id"] for l in g.get("levelThreshold", []))
        lines.append(f"  - {g['id']}: levels [{levels}]")
    lines.append("Confirm? (y/n)")
    return "\n".join(lines)


def _validate_and_write(draft, project_dir):
    try:
        ThresholdGroups.model_validate(draft)
    except Exception as exc:  # noqa: BLE001
        return (
            f"Validation failed: {type(exc).__name__}: "
            f"{str(exc)[:200]}\nAborted.",
            True,
        )
    inputs_dir = project_dir / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    path = inputs_dir / "thresholds.yaml"
    path.write_text(
        _yaml.safe_dump(draft, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    return (f"Wrote {path}.", True)


__all__ = ["advance"]
