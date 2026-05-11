"""Interactive elicitation handler for ``inputs/permissions.yaml``.

A FEWS ``permission`` ties a permission id to the userGroups that hold
it. Each entry is shallow: an id plus a list of userGroup id-wrappers.
The walker detects the ``list[UserGroupRef]`` shape (single-field
``id`` wrapper) and parses comma-separated ids accordingly.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fews_agent.schema import Permission, Permissions

from . import _generic as G


SPEC = G.HandlerSpec(
    item_model=Permission,
    list_field_on_root=("permission", Permissions),
    output_filename="permissions.yaml",
    intro_text=(
        "Entering edit mode for permissions.yaml. Each permission is "
        "an id (referenced from FEWS configs) plus the userGroups that "
        "hold it. Type /cancel-edit to abort."
    ),
    add_more_prompt="Add another permission? (y/n)",
    labels={
        "id": "Permission id (e.g. F12_DEVELOPMENT, F13_DATA_PRIVACY)",
        "userGroup": "userGroups that hold this permission (comma-separated ids)",
    },
    force_ask={"userGroup"},  # Pydantic-optional but the whole point.
    skip_fields={"enabled"},  # rarely set; configurator can edit yaml later
)


def advance(
    state: dict[str, Any],
    user_message: str,
    project_dir: Path,
) -> tuple[str, bool]:
    return G.advance_via_walker(state, user_message, project_dir, SPEC)


__all__ = ["advance"]
