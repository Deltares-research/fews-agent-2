"""Walker-driven handler for ``inputs/exportRaven.yaml``.

UnitConversions table for the Raven model adapter. Each entry maps a
FEWS-side unit string to the model-side unit string with an optional
numeric multiplier (e.g. FEWS ``mm/day`` → Raven ``mm/s`` with
multiplier ``1.157407407E-5``).

Walker handles the flat shape directly:
  unitConversion: list[UnitConversion]
    inputUnitType: str (required)
    outputUnitType: str (required)
    multiplier: str (optional but conceptually required — force-asked)
    incrementer: str (optional — skipped; configurator hand-edits)
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fews_agent.schema import UnitConversion, UnitConversions

from . import _generic as G


SPEC = G.HandlerSpec(
    item_model=UnitConversion,
    list_field_on_root=("unitConversion", UnitConversions),
    output_filename="exportRaven.yaml",
    intro_text=(
        "Entering edit mode for exportRaven.yaml. Each entry maps a "
        "FEWS unit to a Raven-side unit with an optional numeric "
        "multiplier (e.g. mm/day → mm/s with multiplier "
        "1.157407407E-5). Type /cancel-edit to abort."
    ),
    add_more_prompt="Add another conversion? (y/n)",
    labels={
        "inputUnitType": "FEWS-side unit (e.g. mm/day, m3/s, K)",
        "outputUnitType": "Raven-side unit (e.g. mm/s, m3/d, °C)",
        "multiplier": (
            "Multiplier (numeric or blank for 1; e.g. 86400 for /day → /s)"
        ),
    },
    # multiplier has type `str | None = None`; force-ask so the
    # configurator can choose to leave it blank for unit-relabel-only.
    force_ask={"multiplier"},
    skip_fields={"incrementer"},
)


def advance(
    state: dict[str, Any],
    user_message: str,
    project_dir: Path,
) -> tuple[str, bool]:
    return G.advance_via_walker(state, user_message, project_dir, SPEC)


__all__ = ["advance"]
