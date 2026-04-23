"""Project-state tools: upsert/remove items, list/save projects.

`upsert_location` is the shared hook between the LLM chat (via tool
call) and the Rich wizard (direct invocation). Both paths end up in the
same `project_data["locations"]["location"]` array and the same
`input.json` on disk — cache-authoritative state, no divergence.

All mutating operations persist synchronously via `ctx.store.save` so
an aborted session leaves the disk consistent with the last completed
turn.
"""
from __future__ import annotations

from typing import Any

from ..providers.base import ToolSpec


def _ensure_locations(ctx: Any) -> dict[str, Any]:
    """Return `project_data['locations']`, creating empty scaffold if absent."""
    locations = ctx.project_data.setdefault(
        "locations", {"geoDatum": "", "location": []}
    )
    locations.setdefault("location", [])
    return locations


def upsert_location(location: dict[str, Any], ctx: Any) -> dict[str, Any]:
    """Insert or update a location entry (keyed by `id`). Persists."""
    if "id" not in location or not str(location["id"]).strip():
        return {"error": "location.id is required"}
    locations = _ensure_locations(ctx)
    items = locations["location"]
    target_id = location["id"]
    for i, existing in enumerate(items):
        if existing.get("id") == target_id:
            items[i] = {**existing, **location}
            ctx.store.save(ctx.project_name, ctx.project_data)
            return {"action": "updated", "id": target_id, "count": len(items)}
    items.append(location)
    ctx.store.save(ctx.project_name, ctx.project_data)
    return {"action": "inserted", "id": target_id, "count": len(items)}


def remove_location(id: str, ctx: Any) -> dict[str, Any]:
    """Remove a location by id. No-op if absent."""
    locations = _ensure_locations(ctx)
    items = locations["location"]
    before = len(items)
    locations["location"] = [l for l in items if l.get("id") != id]
    after = len(locations["location"])
    ctx.store.save(ctx.project_name, ctx.project_data)
    return {
        "action": "removed" if after < before else "noop",
        "id": id,
        "count": after,
    }


def list_projects(ctx: Any) -> dict[str, Any]:
    return {"projects": ctx.store.list(), "current": ctx.project_name}


def save_project(ctx: Any) -> dict[str, Any]:
    """Explicit save (in practice a no-op since every mutation persists)."""
    ctx.store.save(ctx.project_name, ctx.project_data)
    return {"saved": ctx.project_name, "path": str(ctx.store.input_path(ctx.project_name))}


UPSERT_LOCATION_TOOL = ToolSpec(
    name="upsert_location",
    description=(
        "Add a new location or update an existing one by id. Writes "
        "directly to project_data['locations']['location']. Use strings "
        "for x/y/z to preserve exact coordinate digits."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "location": {
                "type": "object",
                "description": "Location fields; `id` and `name` are required.",
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "x": {"type": "string"},
                    "y": {"type": "string"},
                    "z": {"type": "string"},
                    "shortName": {"type": "string"},
                    "description": {"type": "string"},
                    "parentLocationId": {"type": "string"},
                    "relation": {"type": "string"},
                },
                "required": ["id", "name"],
                "additionalProperties": True,
            }
        },
        "required": ["location"],
        "additionalProperties": False,
    },
)

REMOVE_LOCATION_TOOL = ToolSpec(
    name="remove_location",
    description="Remove a location by id. No-op if not present.",
    input_schema={
        "type": "object",
        "properties": {"id": {"type": "string"}},
        "required": ["id"],
        "additionalProperties": False,
    },
)

LIST_PROJECTS_TOOL = ToolSpec(
    name="list_projects",
    description="Return existing project names and the one currently loaded.",
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
)

SAVE_PROJECT_TOOL = ToolSpec(
    name="save_project",
    description=(
        "Explicitly persist project state. Normally unnecessary since "
        "every mutating tool persists synchronously."
    ),
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
)
