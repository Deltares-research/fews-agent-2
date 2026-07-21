"""Validated slot-patch operations — the trust boundary of the LLM-first turn.

The single-call architecture (``llm_turn.py``) asks the model for ONE JSON
response per user message: a reply plus a PATCH — a list of operations on the
project slots. This module owns that op vocabulary. Each op is validated
against the catalog deterministically and applied through the EXISTING slot
machinery (``apply_extracted_fields`` / ``apply_removal`` / ``set_variable`` /
``set_grid_geometry`` / ``module_focus.set_focus``); invalid ops are dropped
LOUDLY into ``PatchResult.dropped``, never applied silently — the same
philosophy as the filter drafter and ``extractor.validate_fields``.

The vocabulary is deliberately small and stable (CRUD on slots), NOT a
per-domain tool API: adding a new pattern to the library requires no change
here — ``add_capability`` validates against the catalog, and the model learns
what exists from the catalog digest in its prompt.

No LLM, no I/O — pure functions over (state, catalog). Deterministic tests in
``tests/test_patch_ops.py``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fews_agent.agent import module_focus
from fews_agent.agent.extractor import (
    ExtractedOperation,
    _canonical_adapter,
    _canonical_import,
    validate_fields,
)
from fews_agent.agent.modules import normalize_module
from fews_agent.agent.project_chat import set_grid_geometry
from fews_agent.agent.project_intents import (
    _DATA_TYPE_TO_PARAMETER,
    capability_required_variables,
)


@dataclass
class PatchResult:
    """Outcome of applying one patch (a batch of ops) to project state."""

    notes: list[str] = field(default_factory=list)      # applied — grey channel
    dropped: list[str] = field(default_factory=list)    # rejected — loud
    new_patterns: list[str] = field(default_factory=list)
    wants_build: bool = False
    build_scope: str | None = None
    wants_assemble: bool = False
    coordinates_for: str | None = None   # "" = all grids, name = one, None = no


# The op names the model may emit. Anything else is dropped loudly.
OP_NAMES = (
    "add_import", "add_basin", "add_capability", "set_variables",
    "remove", "set_focus", "open_coordinates", "build", "assemble", "none",
)


def _apply_fields(state: dict, fields: dict, catalog, action: str = "add"):
    """Route validated fields through the existing additive slot-fill."""
    from fews_agent.agent.turn_engine import apply_extracted_fields

    op = ExtractedOperation(action=action, fields=fields)
    return apply_extracted_fields(state, op, catalog)


def _op_add_import(state: dict, args: dict, catalog, res: PatchResult) -> None:
    name = _canonical_import(str(args.get("name") or ""))
    if name is None:
        res.dropped.append(f"add_import: unknown import {args.get('name')!r}")
        return
    fields: dict[str, Any] = {"imports": [name]}
    raw_dts = args.get("data_types") or []
    if raw_dts:
        clean, dts_dropped = validate_fields({"data_types": list(raw_dts)})
        fields.update(clean)
        res.dropped.extend(f"add_import: {d}" for d in dts_dropped)
    note, new = _apply_fields(state, fields, catalog)
    res.notes.append(note)
    res.new_patterns.extend(new)
    # Per-import scalars ride the override channel so two imports can differ.
    values = {
        k: args[k] for k in ("grid_resolution", "forecast_horizon_hours")
        if args.get(k) is not None
    }
    if values:
        _op_set_variables(
            state, {"target": name, "values": values}, catalog, res,
        )


def _op_add_basin(state: dict, args: dict, catalog, res: PatchResult) -> None:
    basin = str(args.get("basin_name") or "").strip()
    if not basin:
        res.dropped.append("add_basin: basin_name is required")
        return
    adapter = _canonical_adapter(str(args.get("model_adapter") or ""))
    if adapter is None:
        # The Rhine rule: never guess an adapter. The prompt instructs the
        # model to ASK instead of emitting this op without one; if it emits a
        # bogus adapter anyway, it lands here — loudly.
        res.dropped.append(
            f"add_basin: unknown model_adapter "
            f"{args.get('model_adapter')!r} (known: raven, wflow, hbv96)"
        )
        return
    note, new = _apply_fields(
        state,
        {"basins": [{"basin_name": basin, "model_adapter": adapter}]},
        catalog,
    )
    res.notes.append(note)
    res.new_patterns.extend(new)


def _resolve_capability_path(token: str, catalog) -> str | None:
    """Accept a full path or a bare pattern name from the catalog."""
    tok = str(token or "").strip()
    if not tok:
        return None
    paths = {getattr(e, "path", "") for e in (catalog or [])}
    if tok in paths:
        return tok
    for e in catalog or []:
        if getattr(e, "name", "") == tok or e.path.rsplit("/", 1)[-1] == tok:
            return e.path
    return None


def _op_add_capability(state: dict, args: dict, catalog, res: PatchResult) -> None:
    path = _resolve_capability_path(args.get("pattern"), catalog)
    if path is None:
        res.dropped.append(
            f"add_capability: {args.get('pattern')!r} is not in the pattern "
            f"library"
        )
        return
    required = capability_required_variables(path, catalog)
    if required:
        res.dropped.append(
            f"add_capability: {path.rsplit('/', 1)[-1]} needs "
            f"{', '.join(required)} before it can be added"
        )
        return
    note, new = _apply_fields(state, {"extra_patterns": [path]}, catalog)
    res.notes.append(note)
    res.new_patterns.extend(new)


def _op_set_variables(state: dict, args: dict, catalog, res: PatchResult) -> None:
    from fews_agent.agent.turn_engine import (
        _SET_VAR_CANON,
        _normalise_set_value,
        resolve_patterns,
    )
    from fews_agent.agent.project_chat import set_variable

    target = str(args.get("target") or "").strip()
    values = args.get("values") or {}
    if not isinstance(values, dict) or not values:
        res.dropped.append("set_variables: values{} is required")
        return
    for raw_var, raw_val in values.items():
        var_key = str(raw_var).strip().lower()
        # Weather variables are DATA TYPES (additive list, catalog-checked),
        # not a per-import scalar — routing them through set_variable stored
        # parameter-row dicts into the data_types slot and broke the resolver.
        if var_key in ("data_type", "data_types", "parameter", "parameters",
                       "weather_variable", "weather_variables"):
            vals = raw_val if isinstance(raw_val, list) else [raw_val]
            clean, dts_dropped = validate_fields(
                {"data_types": [str(v) for v in vals]}
            )
            res.dropped.extend(f"set_variables: {d}" for d in dts_dropped)
            if clean.get("data_types"):
                note, _ = _apply_fields(state, clean, catalog)
                res.notes.append(note)
            continue
        if var_key in ("grid_geometry", "coordinates"):
            g = raw_val if isinstance(raw_val, dict) else {}
            try:
                res.notes.append(set_grid_geometry(
                    state, target,
                    first_x=float(g["first_x"]), first_y=float(g["first_y"]),
                    columns=int(g["columns"]), rows=int(g["rows"]),
                ))
            except (KeyError, TypeError, ValueError):
                res.dropped.append(
                    "set_variables: grid_geometry needs "
                    "{first_x, first_y, columns, rows}"
                )
            continue
        variable = _SET_VAR_CANON.get(var_key) or (
            var_key if var_key in ("grid_resolution",
                                   "forecast_horizon_hours") else None
        )
        if variable is None:
            res.dropped.append(f"set_variables: unknown variable {raw_var!r}")
            continue
        value = _normalise_set_value(variable, raw_val)
        if value is None:
            res.dropped.append(
                f"set_variables: couldn't parse {raw_val!r} for {variable}"
            )
            continue
        res.notes.append(set_variable(state, target, variable, value))
    resolve_patterns(state, catalog)


def _op_remove(state: dict, args: dict, catalog, res: PatchResult) -> None:
    from fews_agent.agent.turn_engine import apply_removal, resolve_patterns

    token = str(args.get("target") or "").strip()
    if not token:
        res.dropped.append("remove: target is required")
        return
    slots = state.get("slots") or {}

    imp = _canonical_import(token)
    if imp and imp in (slots.get("imports") or []):
        note, _ = apply_removal(
            state, ExtractedOperation(action="remove",
                                      fields={"imports": [imp]}), catalog,
        )
        res.notes.append(note)
        return
    for b in slots.get("basins") or []:
        if str(b.get("basin_name", "")).lower() == token.lower():
            note, _ = apply_removal(
                state, ExtractedOperation(
                    action="remove",
                    fields={"basins": [{"basin_name": b["basin_name"]}]},
                ), catalog,
            )
            res.notes.append(note)
            return
    if token.lower() in _DATA_TYPE_TO_PARAMETER:
        note, _ = apply_removal(
            state, ExtractedOperation(action="remove",
                                      fields={"data_types": [token.lower()]}),
            catalog,
        )
        res.notes.append(note)
        return
    cap = _resolve_capability_path(token, catalog)
    extra = slots.get("extra_patterns") or []
    if cap and cap in extra:
        slots["extra_patterns"] = [p for p in extra if p != cap]
        resolve_patterns(state, catalog)
        res.notes.append(f"Removed capability {cap.rsplit('/', 1)[-1]}.")
        return
    res.dropped.append(f"remove: nothing in the project matches {token!r}")


def _op_set_focus(state: dict, args: dict, catalog, res: PatchResult) -> None:
    key = normalize_module(str(args.get("module") or ""))
    if key is None:
        res.dropped.append(f"set_focus: unknown module {args.get('module')!r}")
        return
    module_focus.set_focus(state, key)
    res.notes.append(f"Focused the {key} module.")


def apply_patch(state: dict, ops: list, catalog) -> PatchResult:
    """Validate + apply a patch (list of ``{"op": name, ...args}`` dicts).

    Valid ops apply through the existing slot machinery (each re-resolves, so
    partial application is consistent); invalid ops land in ``dropped`` with a
    reason the model can read back next turn. Build/assemble/coordinates are
    SIGNALS for the driving shell, not state mutations.
    """
    res = PatchResult()
    for raw in ops or []:
        if not isinstance(raw, dict):
            res.dropped.append(f"not an op object: {raw!r}")
            continue
        name = str(raw.get("op") or "").strip()
        args = {k: v for k, v in raw.items() if k != "op"}
        if name == "add_import":
            _op_add_import(state, args, catalog, res)
        elif name == "add_basin":
            _op_add_basin(state, args, catalog, res)
        elif name == "add_capability":
            _op_add_capability(state, args, catalog, res)
        elif name == "set_variables":
            _op_set_variables(state, args, catalog, res)
        elif name == "remove":
            _op_remove(state, args, catalog, res)
        elif name == "set_focus":
            _op_set_focus(state, args, catalog, res)
        elif name == "open_coordinates":
            res.coordinates_for = str(args.get("name") or "")
        elif name == "build":
            res.wants_build = True
            res.build_scope = (str(args["scope"]).strip()
                               if args.get("scope") else None)
        elif name == "assemble":
            res.wants_assemble = True
        elif name == "none":
            pass
        else:
            res.dropped.append(f"unknown op {name!r}")

    # Drop the no-op notes ("Noted — nothing new to change.") — a patch either
    # changed something (real notes) or it didn't (empty grey channel).
    from fews_agent.agent.turn_engine import _NOOP_NOTE
    res.notes = [n for n in res.notes if n != _NOOP_NOTE]
    return res
