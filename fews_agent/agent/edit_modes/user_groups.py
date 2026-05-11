"""Interactive elicitation handler for ``inputs/userGroups.yaml``.

A FEWS ``userGroup`` registers a named group of users that
``Permissions.xml`` references. The minimal entry is just an id; in
practice configurators populate the ``user`` list with named members.

POC scope: id + user list (`<user id="..."/>` wrappers). Other choice
members (`userGroup`, `systemUserGroup`) are skipped — they're rarely
used and the configurator can hand-edit the yaml later.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fews_agent.schema import UserGroup, UserGroups

from . import _generic as G


SPEC = G.HandlerSpec(
    item_model=UserGroup,
    list_field_on_root=("userGroup", UserGroups),
    output_filename="userGroups.yaml",
    intro_text=(
        "Entering edit mode for userGroups.yaml. Each group has an id "
        "(referenced from Permissions.xml) and a list of user ids. "
        "Type /cancel-edit to abort."
    ),
    add_more_prompt="Add another group? (y/n)",
    labels={
        "id": "Group id (e.g. Forecasters, Admins)",
        "user": "User ids in this group (comma-separated)",
    },
    force_ask={"user"},
    skip_fields={"name", "userGroup", "systemUserGroup"},
)


def advance(
    state: dict[str, Any],
    user_message: str,
    project_dir: Path,
) -> tuple[str, bool]:
    return G.advance_via_walker(state, user_message, project_dir, SPEC)


__all__ = ["advance"]
