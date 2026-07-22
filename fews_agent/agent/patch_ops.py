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
    vars_for: str | None = None          # "" = overview, name = one instance
    preview_for: str | None = None       # /show target — file preview
    # write_input_file ops that passed validation: (filename, clean_rows).
    # patch_ops stays pure — llm_turn performs the disk write.
    input_writes: list = field(default_factory=list)


# The op names the model may emit. Anything else is dropped loudly.
OP_NAMES = (
    "add_import", "add_basin", "add_capability", "set_variables",
    "remove", "set_focus", "open_coordinates", "show_variables",
    "preview_file", "write_input_file",
    "build", "assemble", "none",
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


# Patterns owned by a resolver FLAG, not by extra_patterns: the resolvers emit
# one instance per eligible import (with the right parameters/timeStep), so
# adding them directly would either fail (required vars) or bypass that logic.
# Redirect the op to the flag — any route the model picks then works.
_FLAG_OWNED_PATTERNS = {
    "auto/spatial_display_grid": "wants_visualization",
    "auto/wf_interpolate_nwp_to_stations": "wants_interpolation",
}


def _op_add_capability(state: dict, args: dict, catalog, res: PatchResult) -> None:
    path = _resolve_capability_path(args.get("pattern"), catalog)
    if path is None:
        res.dropped.append(
            f"add_capability: {args.get('pattern')!r} is not in the pattern "
            f"library"
        )
        return
    flag = _FLAG_OWNED_PATTERNS.get(path)
    if flag:
        note, _ = _apply_fields(state, {flag: True}, catalog)
        res.notes.append(note)
        return
    # An IMPORT-owned pattern (the model picked the pattern route for a known
    # source, e.g. add_capability nwp_grid_eccc_HRDPS): redirect to add_import
    # so the import route fills nwp_name/companions — any route works.
    from fews_agent.agent.project_intents import _IMPORT_PATTERN_MAP
    for imp_name, (imp_path, _var) in _IMPORT_PATTERN_MAP.items():
        if imp_path == path:
            _op_add_import(state, {"name": imp_name, **args}, catalog, res)
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


def _declared_variables(target: str, catalog) -> tuple[str | None, dict]:
    """(canonical import name, declared pattern variables) for a target.

    This is what makes ``set_variables`` CATALOG-driven: any variable the
    target's pattern declares (the same set the /vars table shows) is
    settable — not just a hand-maintained scalar whitelist. Returns
    ``(None, {})`` when the target isn't a known import.
    """
    from fews_agent.agent.project_intents import _IMPORT_PATTERN_MAP

    imp = _canonical_import(str(target or ""))
    if imp is None or imp not in _IMPORT_PATTERN_MAP:
        return None, {}
    path = _IMPORT_PATTERN_MAP[imp][0]
    for entry in catalog or []:
        if getattr(entry, "path", "") == path:
            variables = getattr(entry, "variables", {}) or {}
            return imp, {k: v for k, v in variables.items()
                         if isinstance(v, dict)}
    return imp, {}


def _coerce_declared(value, spec: dict):
    """Coerce a raw value to the declared variable's shape (default's type).

    Returns the coerced value, or ``None`` when it can't be read as that
    type — the caller drops the op loudly.
    """
    default = spec.get("default")
    if isinstance(default, bool):
        if isinstance(value, bool):
            return value
        token = str(value).strip().lower()
        if token in ("true", "yes", "y", "on", "1"):
            return True
        if token in ("false", "no", "n", "off", "0"):
            return False
        return None
    if isinstance(default, int) and not isinstance(default, bool):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    if isinstance(default, float):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    if isinstance(default, (list, dict)):
        return value if isinstance(value, type(default)) else None
    return str(value)


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
        # Project-wide geo context: datum + named region. Applied through
        # _apply_fields so the geo → Locations-singleton sync fires (the build
        # reads region/geoDatum off the singleton seed).
        if var_key in ("geodatum", "geo_datum", "datum"):
            note, _ = _apply_fields(
                state, {"geoDatum": str(raw_val)}, catalog, action="set",
            )
            res.notes.append(note)
            continue
        if var_key == "region":
            note, _ = _apply_fields(
                state, {"region": str(raw_val)}, catalog, action="set",
            )
            res.notes.append(note)
            continue
        # Project-wide feature flags: "visualize the grids" / "interpolate to
        # my stations". These ride the slots the resolvers already understand
        # (spatial_display_grid / wf_interpolate_nwp_to_stations per import).
        if var_key in ("wants_visualization", "visualization", "visualize",
                       "wants_interpolation", "interpolation", "interpolate"):
            flag = ("wants_visualization" if "vis" in var_key
                    else "wants_interpolation")
            if raw_val in (True, "true", "True", "yes", 1):
                note, _ = _apply_fields(state, {flag: True}, catalog)
                res.notes.append(note)
            else:
                from fews_agent.agent.turn_engine import apply_field_removals
                res.notes.extend(apply_field_removals(state, {flag: None}))
            continue
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
            # CATALOG-driven fallback: any variable the target's pattern
            # declares (exactly what the /vars table advertises) is settable
            # via the per-import override channel; the resolver stamps it
            # onto the instance. Fixes "the table lists contribute_parameters
            # but set_variables calls it unknown".
            imp, declared = _declared_variables(target, catalog)
            spec = declared.get(str(raw_var).strip())
            if imp is not None and spec is not None:
                coerced = _coerce_declared(raw_val, spec)
                if coerced is None:
                    res.dropped.append(
                        f"set_variables: couldn't parse {raw_val!r} "
                        f"for {raw_var}"
                    )
                    continue
                overrides = state.setdefault("slots", {}).setdefault(
                    "import_overrides", {})
                overrides.setdefault(imp, {})[str(raw_var).strip()] = coerced
                res.notes.append(
                    f"Set {raw_var} to {coerced} for {imp}."
                )
                continue
            hint = (f" {imp} has: {', '.join(sorted(declared))}."
                    if imp and declared else "")
            res.dropped.append(
                f"set_variables: unknown variable {raw_var!r}.{hint}"
            )
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
    from fews_agent.agent.turn_engine import (
        _SET_VAR_CANON,
        apply_field_removals,
        apply_removal,
        resolve_patterns,
    )

    token = str(args.get("target") or "").strip()
    if not token:
        res.dropped.append("remove: target is required")
        return
    slots = state.get("slots") or {}

    # Unset a VARIABLE ("remove the forecast horizon"): either scoped to one
    # import ({target: "GFS", variable: "horizon"}) or project-wide when the
    # target itself names a variable. Clearing an import's override falls back
    # to the project default; clearing project-wide also sweeps overrides.
    var_token = str(args.get("variable") or "").strip().lower()

    # When `variable` is present it is AUTHORITATIVE: handle it fully or drop
    # the op. Falling through with the variable silently ignored turned
    # `remove {target:"GFS", variable:"temperature"}` into deleting the whole
    # GFS import — a destructive mis-apply found in live testing.
    if var_token:
        if var_token in _DATA_TYPE_TO_PARAMETER:
            note, _ = apply_removal(
                state, ExtractedOperation(
                    action="remove", fields={"data_types": [var_token]},
                ), catalog,
            )
            res.notes.append(note)
            return
        canon = _SET_VAR_CANON.get(var_token) or (
            "geoDatum" if var_token in ("geodatum", "geo_datum", "datum")
            else var_token if var_token in
            ("grid_resolution", "forecast_horizon_hours", "region",
             "wants_visualization", "wants_interpolation") else None
        )
        overrides = slots.get("import_overrides") or {}
        imp = _canonical_import(token)
        if canon is None:
            # A catalog-declared variable set via the override channel
            # ("remove GFS's contribute_parameters") clears the same way.
            _imp2, declared = _declared_variables(token, catalog)
            for name in declared:
                if name.lower() == var_token:
                    if imp and name in (overrides.get(imp) or {}):
                        overrides[imp].pop(name, None)
                        resolve_patterns(state, catalog)
                        res.notes.append(
                            f"Cleared {name} for {imp} (back to default)."
                        )
                    else:
                        res.dropped.append(
                            f"remove: {token!r} has no {name} override to "
                            f"clear"
                        )
                    return
            res.dropped.append(f"remove: unknown variable {var_token!r}")
            return
        if imp and imp in overrides and canon in overrides[imp]:
            overrides[imp].pop(canon, None)
            resolve_patterns(state, catalog)
            res.notes.append(f"Cleared {canon} for {imp} (back to default).")
        else:
            res.dropped.append(
                f"remove: {token!r} has no {canon} override to clear"
            )
        return

    # No `variable`: the target itself may name a project-wide variable to
    # unset ("remove the grid_resolution").
    canon = _SET_VAR_CANON.get(token.lower().replace(" ", "_")) or (
        token.lower() if token.lower() in
        ("grid_resolution", "forecast_horizon_hours", "region", "geodatum",
         "wants_visualization", "wants_interpolation") else None
    )
    if canon and canon != "data_types":   # data types remove as list items below
        canon = "geoDatum" if canon == "geodatum" else canon
        cleared = list(apply_field_removals(state, {canon: None}))
        for name, ov in (slots.get("import_overrides") or {}).items():
            if canon in ov:
                ov.pop(canon, None)
                cleared.append(f"Cleared {canon} for {name}.")
        if cleared:
            resolve_patterns(state, catalog)
            res.notes.extend(cleared)
            return

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
    module, _card = module_focus.set_focus(state, key)
    # Speak the FEWS folder label, never the internal key ("filters").
    short = (module.label.split(" (")[0].strip() if module else key)
    res.notes.append(f"Focused on {short}.")


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
        elif name == "show_variables":
            res.vars_for = str(args.get("target") or "")
        elif name == "preview_file":
            res.preview_for = str(args.get("target") or "")
        elif name == "write_input_file":
            from fews_agent.agent.input_files import (
                SUPPORTED_FILES,
                validate_rows,
            )
            fname = str(args.get("file") or "").strip()
            delete_ids = [str(x).strip() for x in (args.get("delete_ids")
                          or []) if str(x).strip()]
            rows = args.get("rows") or []
            if delete_ids and not rows:
                # Pure deletion: no rows to validate, just a known file.
                if fname in SUPPORTED_FILES:
                    res.input_writes.append((fname, [], delete_ids))
                else:
                    res.dropped.append(
                        f"write_input_file: unsupported input file {fname!r}"
                    )
            else:
                clean, errors = validate_rows(fname, rows)
                if errors:
                    res.dropped.extend(
                        f"write_input_file {fname or '?'}: {e}"
                        for e in errors
                    )
                else:
                    res.input_writes.append((fname, clean, delete_ids))
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
