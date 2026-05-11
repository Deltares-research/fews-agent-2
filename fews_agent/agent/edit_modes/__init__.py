"""Per-yaml interactive edit handlers for the chat agent.

The chat agent's `/edit <file.yaml>` command routes to a handler module
in this package. Each handler is a turn-based state machine: it stores
its progress in `state["_editing"]` between chat turns and advances
one stage per user message.

Why per-file handlers (not a generic walker yet): the candidate yamls
(modifierTypes, modifierDisplay, locationIcons, thresholdValueSets)
each have very different schemas and elicitation needs. Hand-rolling
2-3 of them first surfaces the real common pattern; extracting a
generic walker before that risks designing for shapes that don't show
up.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import (
    export_raven,
    forecaster_notes_display,
    location_icons,
    manual_forecast_display,
    modifier_display,
    modifier_types,
    module_instance_sets,
    permissions,
    raven_parameters,
    threshold_value_sets,
    thresholds,
    user_groups,
    validation_rule_sets,
)

if TYPE_CHECKING:
    pass


# filename → handler module. Add entries here when supporting a new yaml.
REGISTRY: dict[str, Any] = {
    "exportRaven.yaml": export_raven,
    "forecasterNotesDisplay.yaml": forecaster_notes_display,
    "locationIcons.yaml": location_icons,
    "manualForecastDisplay.yaml": manual_forecast_display,
    "modifierDisplay.yaml": modifier_display,
    "modifierTypes.yaml": modifier_types,
    "moduleInstanceSets.yaml": module_instance_sets,
    "permissions.yaml": permissions,
    "ravenParameters.yaml": raven_parameters,
    "thresholdValueSets.yaml": threshold_value_sets,
    "thresholds.yaml": thresholds,
    "userGroups.yaml": user_groups,
    "validationRuleSets.yaml": validation_rule_sets,
}


def supported_files() -> list[str]:
    return sorted(REGISTRY)


def start(
    state: dict[str, Any],
    file: str,
    project_dir: Path,
) -> tuple[str, bool]:
    """Begin an edit session for ``file``. Initialises ``state['_editing']``
    and returns the handler's first prompt.

    Returns ``(reply, done)`` where ``done`` is True only if start failed
    so the caller knows whether to clear ``_editing``.
    """
    handler = REGISTRY.get(file)
    if handler is None:
        return (
            f"No edit handler registered for {file}. "
            f"Supported: {', '.join(supported_files())}",
            True,
        )
    state["_editing"] = {
        "file": file,
        "stage": "_start",
        "draft": {},
        "current": {},
    }
    return advance_turn(state, "", project_dir)


def advance_turn(
    state: dict[str, Any],
    user_message: str,
    project_dir: Path,
) -> tuple[str, bool]:
    """Advance the active edit session by one turn.

    Returns ``(reply, done)``. When ``done`` is True the caller should
    clear ``state['_editing']`` (the handler has either written the
    file or the session was cancelled).
    """
    edit = state.get("_editing")
    if edit is None:
        return ("(not in edit mode)", True)
    handler = REGISTRY.get(edit["file"])
    if handler is None:
        return (f"Lost handler for {edit['file']}", True)
    return handler.advance(state, user_message, project_dir)


__all__ = ["REGISTRY", "supported_files", "start", "advance_turn"]
