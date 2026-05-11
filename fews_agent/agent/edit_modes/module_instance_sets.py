"""Interactive elicitation handler for ``inputs/moduleInstanceSets.yaml``.

A ``moduleInstanceSet`` is a named bundle of moduleInstanceIds that
workflows and maintenance jobs can target as a group. The schema is
shallow: each set has an id and a list of moduleInstanceIds.

This handler is the first one driven by the generic walker
(``_generic.advance_via_walker``); the per-yaml override is
~30 lines of HandlerSpec configuration.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fews_agent.schema import ModuleInstanceSet, ModuleInstanceSets

from . import _generic as G


SPEC = G.HandlerSpec(
    item_model=ModuleInstanceSet,
    list_field_on_root=("moduleInstanceSet", ModuleInstanceSets),
    output_filename="moduleInstanceSets.yaml",
    intro_text=(
        "Entering edit mode for moduleInstanceSets.yaml. Each set is a "
        "named bundle of moduleInstanceIds — workflows and maintenance "
        "jobs target sets instead of listing each module by name. Type "
        "/cancel-edit to abort."
    ),
    add_more_prompt="Add another set? (y/n)",
    labels={
        "id": "Set id (e.g. AllImports, ECCCImports)",
        "moduleInstanceId": "moduleInstanceIds in this set (comma-separated)",
    },
    hints={"moduleInstanceId": "moduleInstanceIds"},
    # moduleInstanceId has default_factory=list so Pydantic considers it
    # optional, but it's the whole point of the yaml — force-ask it.
    force_ask={"moduleInstanceId"},
    # `name`/`description`/`moduleInstanceIdPattern` are optional — walker
    # skips by default. Configurator can edit the yaml manually for those.
)


def advance(
    state: dict[str, Any],
    user_message: str,
    project_dir: Path,
) -> tuple[str, bool]:
    return G.advance_via_walker(state, user_message, project_dir, SPEC)


__all__ = ["advance"]
