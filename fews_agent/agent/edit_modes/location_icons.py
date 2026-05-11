"""Interactive elicitation handler for ``inputs/locationIcons.yaml``.

A LocationIcon ties an iconId to either a single locationSet OR a list
of locationIds (XSD choice). The walker's ``choices`` mechanism handles
the pick.

POC scope: required iconId + the choice between locationSetId /
locationId list. Optional ``description`` is skipped (configurator can
hand-edit yaml).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fews_agent.schema import LocationIcon, LocationIcons

from . import _generic as G


SPEC = G.HandlerSpec(
    item_model=LocationIcon,
    list_field_on_root=("locationIcon", LocationIcons),
    output_filename="locationIcons.yaml",
    intro_text=(
        "Entering edit mode for locationIcons.yaml. Each entry maps an "
        "icon (image file id) to a locationSet OR to a list of "
        "locationIds. Type /cancel-edit to abort."
    ),
    add_more_prompt="Add another icon mapping? (y/n)",
    labels={
        "iconId": "Icon id (filename in icons folder, e.g. station.png)",
        "locationSetId": "locationSetId this icon applies to",
        "locationId": "locationIds this icon applies to (comma-separated)",
    },
    hints={
        "locationSetId": "locationSetIds",
        "locationId": "locationIds",
    },
    skip_fields={"description"},
    # XSD choice: locationSetId XOR locationId[]. Walker prompts user
    # to pick one branch then asks only that.
    choices=[(
        "Apply this icon by location set or by individual locations?",
        [("locationSetId", "str"), ("locationId", "list_str")],
    )],
)


def advance(
    state: dict[str, Any],
    user_message: str,
    project_dir: Path,
) -> tuple[str, bool]:
    return G.advance_via_walker(state, user_message, project_dir, SPEC)


__all__ = ["advance"]
