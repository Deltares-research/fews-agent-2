"""Hand-rolled handler for ``inputs/forecasterNotesDisplay.yaml``.

Minimal valid file: just ``title`` + at least one ``msgTemplate`` (id +
message). Forecaster notes are short templated messages operators can
post to a shared bulletin during a forecast cycle.

POC scope: title + one or more msgTemplate entries. Optional table
columns and message limits are skipped.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml as _yaml

from fews_agent.schema import ForecasterNotesDisplay


def advance(
    state: dict[str, Any],
    user_message: str,
    project_dir: Path,
) -> tuple[str, bool]:
    edit = state["_editing"]
    stage = edit.get("stage", "_start")
    msg = (user_message or "").strip()
    edit.setdefault("draft", {})
    edit["draft"].setdefault("msgTemplate", [])

    if stage == "_start":
        edit["stage"] = "title"
        return (
            "Entering edit mode for forecasterNotesDisplay.yaml. This "
            "config drives the Forecaster Notes panel — a templated "
            "bulletin board for shift handover. Type /cancel-edit to "
            "abort.\nPanel title (e.g. 'Forecast Notes'):",
            False,
        )

    if stage == "title":
        if not msg:
            return ("Title can't be empty:", False)
        edit["draft"]["title"] = msg
        edit["stage"] = "tpl_id"
        return ("Message template id (e.g. ShiftHandover):", False)

    if stage == "tpl_id":
        if not msg:
            return ("Template id can't be empty:", False)
        edit["_tpl"] = {"id": msg}
        edit["stage"] = "tpl_msg"
        return (
            "Template body text (the message operators see / edit; "
            "use \\n for newlines):",
            False,
        )

    if stage == "tpl_msg":
        if not msg:
            return ("Template body can't be empty:", False)
        edit["_tpl"]["message"] = msg.replace("\\n", "\n")
        edit["draft"]["msgTemplate"].append(edit["_tpl"])
        edit["_tpl"] = {}
        edit["stage"] = "ask_more"
        n = len(edit["draft"]["msgTemplate"])
        return (
            f"Added template (total: {n}). Add another? (y/n)",
            False,
        )

    if stage == "ask_more":
        if msg.lower() in {"y", "yes"}:
            edit["stage"] = "tpl_id"
            return ("Template id:", False)
        if msg.lower() in {"n", "no"}:
            edit["stage"] = "review"
            return (
                f"Ready to write forecasterNotesDisplay.yaml: title="
                f"{edit['draft']['title']!r}, "
                f"{len(edit['draft']['msgTemplate'])} template(s). "
                f"Confirm? (y/n)",
                False,
            )
        return ("Please answer y or n.", False)

    if stage == "review":
        if msg.lower() in {"y", "yes"}:
            try:
                ForecasterNotesDisplay.model_validate(edit["draft"])
            except Exception as exc:  # noqa: BLE001
                return (
                    f"Validation failed: {type(exc).__name__}: "
                    f"{str(exc)[:200]}\nAborted.",
                    True,
                )
            inputs_dir = project_dir / "inputs"
            inputs_dir.mkdir(parents=True, exist_ok=True)
            path = inputs_dir / "forecasterNotesDisplay.yaml"
            path.write_text(
                _yaml.safe_dump(
                    edit["draft"], sort_keys=False, default_flow_style=False,
                ),
                encoding="utf-8",
            )
            return (f"Wrote {path}.", True)
        if msg.lower() in {"n", "no"}:
            return ("Cancelled.", True)
        return ("Please answer y or n.", False)

    return (f"(unknown stage {stage!r}; aborting)", True)


__all__ = ["advance"]
