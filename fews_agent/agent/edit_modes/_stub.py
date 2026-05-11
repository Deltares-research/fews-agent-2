"""Trivial 'write a minimal valid stub' handler.

For yamls whose Pydantic model accepts an empty input and produces
XSD-valid XML, the configurator just confirms they want a default
file. Useful for FEWS UI configs (modifierDisplay, manualForecastDisplay)
that have all-optional fields and FEWS sensible defaults.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml as _yaml


def make_advance(
    output_filename: str,
    intro_text: str,
    minimal_payload: dict[str, Any] | None = None,
):
    """Return an `advance(state, message, project_dir)` callable that
    writes ``minimal_payload`` (defaults to ``{}``) to
    ``inputs/<output_filename>`` after a y/n confirmation."""
    payload = minimal_payload or {}

    def advance(state, user_message, project_dir):
        edit = state["_editing"]
        stage = edit.get("stage", "_start")
        msg = (user_message or "").strip().lower()

        if stage == "_start":
            edit["stage"] = "confirm"
            return (
                intro_text + "\nWrite a minimal stub yaml (FEWS uses "
                "defaults for everything else)? (y/n)",
                False,
            )

        if stage == "confirm":
            if msg in {"y", "yes", "ok"}:
                inputs_dir = project_dir / "inputs"
                inputs_dir.mkdir(parents=True, exist_ok=True)
                path = inputs_dir / output_filename
                # Empty payload → write empty doc; FEWS templates
                # render a minimally-valid XML.
                if payload:
                    path.write_text(
                        _yaml.safe_dump(payload, sort_keys=False),
                        encoding="utf-8",
                    )
                else:
                    path.write_text("{}\n", encoding="utf-8")
                return (f"Wrote {path}.", True)
            if msg in {"n", "no", "cancel"}:
                return ("Cancelled. No file written.", True)
            return ("Please answer y or n.", False)

        return (f"(unknown stage {stage!r}; aborting)", True)

    return advance


__all__ = ["make_advance"]
