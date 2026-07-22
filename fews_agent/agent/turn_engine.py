"""Shared chat turn-engine: the pipeline both drivers run.

The CLI driver (``runners/agent/chat_step.py::main``) and the Streamlit
driver (``app/chatter.py::ChatSession._send_inner``) used to each carry a
hand-maintained copy of the same per-turn pipeline (skills → classify →
NL edits → slot-fill → disambiguation gate → resolve → warnings →
input-scan → compose-reply). They drifted. This module is the single
source of that pipeline plus the helpers it needs; the drivers keep only
their genuinely-different shells (command sets, I/O, persistence, provider
resolution, app-only meta-intents).

`fews_agent` must not import `runners`, so every pipeline helper lives
here (not in chat_step), and the drivers import *from* here. The module
does **no** history/log/save/print I/O — it mutates ``state`` (passed by
reference) and returns data; each driver owns its own persistence and
output rendering.

The LLM seams ``classify_intent`` / ``compose_reply`` are imported into
this module's namespace so tests patch ``turn_engine.classify_intent`` /
``turn_engine.compose_reply`` once, regardless of which driver runs.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from fews_agent.agent import module_focus
from fews_agent.agent.phases import phase_plan
from fews_agent.agent.project_chat import (
    add_module,
    remove_module,
    set_variable,
)
from fews_agent.agent.project_intents import (
    detect_capabilities,
    split_addable_capabilities,
    ENGLISH_WORD_BLOCKLIST,
    INTENTS,
    classify_intent,
    compose_reply,
    compute_input_status,
    detect_edit_action,
    detect_forecast_horizon_hours,
    detect_grid_resolution,
    detect_model_adapter,
    filter_prose,
    heuristic_intent_from_slots,
    intent_disambiguation_needed,
    intent_disambiguation_question,
    is_intent_ready,
    next_unfilled_question,
    parse_intent_disambiguation_answer,
    scan_inputs,
    unrecognised_data_types,
)

# Instance-variable keys that label an import (reused by the unmapped-import
# warning scan in the pipeline). basin_name labels a model and is handled
# separately, so it's not in this group.
_IMPORT_LABEL_KEYS = (
    "nwp_name", "source_name", "wsc_variant", "snow_source", "template_name",
)

# Instance-variable keys that give a human label to a resolved pattern
# instance in the module listing — imports plus a basin's name.
_LABEL_VAR_KEYS = _IMPORT_LABEL_KEYS + ("basin_name",)

# Synonyms → canonical settable variable name for the /set command and NL
# edits. The canonical set is enforced by project_chat.set_variable.
_SET_VAR_CANON = {
    "grid_resolution": "grid_resolution",
    "resolution": "grid_resolution",
    "res": "grid_resolution",
    "forecast_horizon_hours": "forecast_horizon_hours",
    "horizon": "forecast_horizon_hours",
    "forecast_length": "forecast_horizon_hours",
    "length": "forecast_horizon_hours",
    "parameter": "data_types",
    "parameters": "data_types",
    "param": "data_types",
    "data_type": "data_types",
    "data_types": "data_types",
    "variable": "data_types",
    "adapter": "model_adapter",
    "model": "model_adapter",
    "model_adapter": "model_adapter",
}

# Question text for a focused module's own variables. When a module is in
# focus, the reply asks about THIS module's next gap using these, instead of
# the whole project's intent slots. Falls back to the intent's slot_questions
# for any variable not listed here.
_MODULE_VAR_QUESTIONS: dict[str, str] = {
    "imports": "Which data source(s) should this module import? "
               "(e.g. HRDPS, GFS, GEFS, IMERG, ERA5, ...)",
    "basins": "Which basin(s) and what model adapter does each use? "
              "(e.g. 'Liard uses raven')",
    "basin_name": "What basin is this model for? (e.g. Liard)",
    "model_adapter": "Which model adapter? (raven, wflow, hbv96, sfincs, "
                     "hurrywave, delft3d)",
    "data_types": "Which physical quantities / parameters? "
                  "(precipitation, temperature, wind speed, ...)",
    "geoDatum": "What geographic datum do the locations use? "
                "(default: WGS 1984)",
    "region": "Which geographic region? (e.g. Gulf of Guinea, North Sea, "
              "Mediterranean, ...)",
    "wants_visualization": "Should the imported grids be shown in the "
                           "Spatial Display?",
    "wants_interpolation": "Interpolate the grids to station locations for "
                           "the Data Viewer?",
    "grid_resolution": "Which grid resolution? (0p25 / 0p50 / 1p00)",
    "forecast_horizon_hours": "What forecast horizon? (e.g. 7 days)",
    "locations_source": "How are the locations provided? (csv / yaml)",
    "custom_bbox": "What bounding box? (e.g. '8N to -5N, -10E to 10E')",
}


def _module_focus_question(
    state: dict, intent, fallback: str | None,
) -> tuple[str | None, str | None]:
    """When a module is in focus, scope elicitation to its next gap.

    Returns ``(next_question, module_prompt)``. When no module is in focus,
    returns ``(fallback, None)`` so the intent-driven flow is unchanged.
    """
    focus = module_focus.get_focus(state)
    if focus is None:
        return fallback, None
    var = module_focus.next_unfilled_variable(state, focus)
    q = fallback
    if var is not None:
        q = _MODULE_VAR_QUESTIONS.get(var)
        if q is None and intent is not None:
            q = (intent.slot_questions or {}).get(var)
        if q is None:
            q = f"What is the {var} for the {focus.label} module?"
    return q, focus.prompt


# Strong, explicit intent-naming phrases. When one appears, it is
# AUTHORITATIVE over the LLM/heuristic intent pick (see
# forced_intent_override). Whole-phrase substring match so casual mentions
# don't flip-flop the intent. Kept in lockstep with project_intents'
# _NARROWING_PHRASES so turn-1 demotion and this override agree.
_INTENT_OVERRIDE_PHRASES = {
    "build_data_import_only": (
        "data import only", "import only", "imports only",
        "no basin model", "no basin", "no model",
        "without a basin", "without a model", "just imports",
    ),
    "build_basin_model_only": (
        "model only", "basin model only", "no imports",
        "without imports", "just the model",
        "no data import", "without data import",
    ),
}


def forced_intent_override(
    message: str, current_intent: str | None,
) -> str | None:
    """Return an intent to force from an explicit phrase, or None.

    Deterministic and turn-agnostic. An explicit forecasting request
    ('forecasting', 'full forecast') blocks any narrowing — so a greedy
    phrase like 'no model' inside 'no model preference' can't silently
    narrow a full-build request. Otherwise the first matching
    narrower-intent phrase wins. Returns None when no override applies or
    the matched intent equals ``current_intent`` (nothing to change).
    """
    lower = (message or "").lower()
    if "forecasting" in lower or "full forecast" in lower:
        return None
    for target, phrases in _INTENT_OVERRIDE_PHRASES.items():
        if any(p in lower for p in phrases) and current_intent != target:
            return target
    return None


def resolve_patterns(state: dict, catalog) -> None:
    """Refresh state['patterns'] from the resolver, using current slots.

    Resolver runs deterministically. Fully replaces ``state["patterns"]``
    (intent-driven assembly) — so all mid-chat edits must mutate ``slots``,
    never ``patterns``, since this wipes patterns every call.
    """
    intent = INTENTS.get(state.get("intent"))
    if not intent:
        return
    catalog_paths = {p.path for p in catalog}
    resolved = intent.resolver(state.get("slots", {}), catalog_paths)

    # Capabilities the slot-driven resolvers don't model (coastal models, ocean
    # grids, cyclone tracks, station CSV, ...). The three intent resolvers map
    # imports/basins/visualisation onto patterns; everything else in the library
    # was unreachable by conversation. `extra_patterns` is the generic escape
    # hatch — the user names a capability, we append it here, and it survives
    # the full rebuild that `resolve_patterns` does on every turn.
    already = {p.get("pattern") for p in resolved}
    for path in (state.get("slots", {}) or {}).get("extra_patterns") or []:
        if path in catalog_paths and path not in already:
            resolved.append({"pattern": path, "instances": [{}]})
            already.add(path)
    state["patterns"] = resolved


def _normalise_set_value(variable: str, raw):
    """Parse a /set value into the canonical form the slot expects."""
    if raw is None:
        return None
    text = str(raw).strip()
    if variable == "grid_resolution":
        return detect_grid_resolution(text) or (
            text if text in {"0p25", "0p50", "1p00"} else None
        )
    if variable == "forecast_horizon_hours":
        parsed = detect_forecast_horizon_hours(text)
        if parsed is not None:
            return parsed
        try:
            return int(text)
        except ValueError:
            return None
    if variable == "model_adapter":
        return detect_model_adapter(text) or text
    if variable == "data_types":
        return text
    return text


def apply_edit_action(state: dict, edit: dict, catalog) -> str:
    """Apply one add/remove/set edit to slots, then re-resolve patterns.

    Shared entry point for slash commands (Slice 1) and NL edits (later).
    Returns a human-readable note. Normalises /set variable synonyms and
    parses values to canonical form before delegating to the mutators.
    """
    op = edit.get("op")
    note: str
    if op == "add":
        note = add_module(state, edit["target"], edit["target_kind"])
    elif op == "remove":
        target = edit["target"]
        name = (
            target.get("basin_name") if isinstance(target, dict) else target
        )
        note = remove_module(state, name, edit["target_kind"])
    elif op == "set":
        variable = _SET_VAR_CANON.get(
            str(edit.get("variable", "")).strip().lower()
        )
        if variable is None:
            return (
                f"Don't recognise variable {edit.get('variable')!r}. "
                f"Try: resolution, horizon, parameter, adapter."
            )
        value = _normalise_set_value(variable, edit.get("value"))
        if value is None:
            return (
                f"Couldn't parse value {edit.get('value')!r} for "
                f"{variable}."
            )
        # NL edits ("make it half-degree") may carry no named module —
        # pass "" so set_variable applies the project-wide scalar cleanly.
        note = set_variable(state, edit.get("target") or "", variable, value)
    else:
        return f"Unknown edit op {op!r}."

    # Re-derive the resolver-selecting intent from the slots each edit (same
    # as the prose path's _sync_module_intent) — without this, "/add Liard
    # uses raven" after an import kept the import-only resolver active and the
    # basin never resolved into patterns.
    _sync_module_intent(state)
    if not state.get("intent"):
        inferred = heuristic_intent_from_slots(state.get("slots", {}))
        if inferred:
            state["intent"] = inferred
    resolve_patterns(state, catalog)
    return note


def extracted_removal_edits(op) -> list[dict]:
    """Translate a `remove` op's imports/basins into whole-item edit dicts."""
    edits: list[dict] = []
    for name in op.fields.get("imports") or []:
        edits.append({"op": "remove", "target": name, "target_kind": "import"})
    for b in op.fields.get("basins") or []:
        if isinstance(b, dict) and b.get("basin_name"):
            edits.append({
                "op": "remove",
                "target": {"basin_name": b["basin_name"]},
                "target_kind": "basin",
            })
    return edits


# Scalar / boolean slots a `remove` can unset (imports/basins are removed as
# whole items by extracted_removal_edits; data_types is subtracted below).
_REMOVABLE_SCALAR_FIELDS = (
    "grid_resolution", "forecast_horizon_hours", "region", "geoDatum",
)
_REMOVABLE_BOOL_FIELDS = ("wants_interpolation", "wants_visualization")


def apply_field_removals(state: dict, fields: dict) -> list[str]:
    """Remove field VALUES from slots (a data_type, a scalar/bool setting).

    Complements :func:`extracted_removal_edits` (whole imports/basins):
    subtracts the named entries from the ``data_types`` list and unsets any
    scalar/boolean setting the user asked to drop. Returns human notes; the
    caller re-resolves.
    """
    slots = state.setdefault("slots", {})
    notes: list[str] = []

    # data_types (list) — subtract the named phrases, case-insensitively.
    want = fields.get("data_types")
    if want and isinstance(slots.get("data_types"), list):
        drop = {str(v).strip().lower() for v in want}
        before = list(slots["data_types"])
        slots["data_types"] = [
            x for x in before if str(x).strip().lower() not in drop
        ]
        removed = [x for x in before if x not in slots["data_types"]]
        if removed:
            notes.append(f"Removed data_types: {removed}")

    # scalars — unset when the user named them.
    for f in _REMOVABLE_SCALAR_FIELDS:
        if f in fields and slots.get(f) not in (None, "", []):
            old = slots.pop(f, None)
            notes.append(f"Cleared {f} (was {old})")
            if f in ("region", "geoDatum"):
                seed = (state.get("singleton_seeds") or {}).get("Locations")
                if isinstance(seed, dict):
                    seed.pop(f, None)

    # booleans — turn off.
    for f in _REMOVABLE_BOOL_FIELDS:
        if f in fields and slots.get(f):
            slots.pop(f, None)
            notes.append(f"Turned off {f}")

    return notes


def apply_extracted_fields(state: dict, op, catalog) -> tuple[str, list[str]]:
    """Apply an add/set/none ExtractedOperation's fields to slots, then resolve.

    Mirrors the pipeline's additive slot-fill (Phase 3) + resolve (Phase 4),
    but honours the operation's explicit ``action``: a ``set`` OVERRIDES a
    scalar the user is changing ("make it half-degree"), whereas ``add`` /
    ``none`` only fill an empty scalar (never clobber an earlier value).
    List fields (imports, basins, data_types) always merge additively.

    Returns ``(human_note, new_pattern_paths)``.
    """
    slots = state.setdefault("slots", {})
    applied: list[str] = []
    for k, v in (op.fields or {}).items():
        if isinstance(v, list):
            merged = list(slots.get(k) or [])
            for item in v:
                if item not in merged:
                    merged.append(item)
            if merged != (slots.get(k) or []):
                slots[k] = merged
                applied.append(f"{k}={merged}")
        else:
            if op.action == "set" or slots.get(k) in (None, "", []):
                if slots.get(k) != v:
                    slots[k] = v
                    applied.append(f"{k}={v}")

    # Mirror the pipeline's geo → Locations singleton sync.
    for key, seed_key in (("geoDatum", "geoDatum"), ("region", "region")):
        if slots.get(key):
            state.setdefault("singleton_seeds", {}).setdefault(
                "Locations", {}
            )[seed_key] = slots[key]

    # Cross-turn basin promotion (same as the pipeline).
    if (
        not slots.get("basins")
        and slots.get("basin_name")
        and slots.get("model_adapter")
    ):
        slots["basins"] = [{
            "basin_name": slots["basin_name"],
            "model_adapter": slots["model_adapter"],
        }]

    _sync_module_intent(state)
    if not state.get("intent"):
        inferred = heuristic_intent_from_slots(slots)
        if inferred:
            state["intent"] = inferred

    before = {p["pattern"] for p in state.get("patterns", [])}
    resolve_patterns(state, catalog)
    new = [
        p["pattern"] for p in state.get("patterns", [])
        if p["pattern"] not in before
    ]
    note = "Applied: " + "; ".join(applied) if applied else _NOOP_NOTE
    return note, new


# The note apply_* returns when a turn changed NOTHING. Such a turn is not an
# edit — it's a question, a greeting, or prose we couldn't act on — so the
# shells must NOT show it as a grey "what changed" fact, and the reply should
# ANSWER the user instead of acknowledging a non-existent edit.
_NOOP_NOTE = "Noted — nothing new to change."


def _sync_module_intent(state: dict) -> None:
    """In module-mode there is NO user-facing whole-project intent; ``intent``
    is only an internal resolver-selector. Re-derive it from the current slots
    each turn (when a module is focused) so it tracks content — imports-only →
    ``build_data_import_only`` (no basin required for /done), imports+basins →
    ``build_forecasting_project``. The whole-project chat flow keeps whatever
    intent it explicitly classified (no ``current_module`` set)."""
    if state.get("current_module"):
        inferred = heuristic_intent_from_slots(state.get("slots") or {})
        if inferred:
            state["intent"] = inferred


def apply_removal(state: dict, op, catalog) -> tuple[str, list[str]]:
    """The `remove` skill handler: remove whole imports/basins + field values.

    (Registered as the ``remove`` skill in ``skills.py``.)
    """
    notes: list[str] = []
    # Whole items (imports/basins) — each re-resolves via apply_edit_action.
    for e in extracted_removal_edits(op):
        notes.append(apply_edit_action(state, e, catalog))
    # Field values (a data_type, a scalar/bool setting).
    field_notes = apply_field_removals(state, op.fields or {})
    if field_notes:
        notes.extend(field_notes)
    _sync_module_intent(state)
    if not state.get("intent"):
        inferred = heuristic_intent_from_slots(state.get("slots", {}))
        if inferred:
            state["intent"] = inferred
    resolve_patterns(state, catalog)  # propagate dropped values / derived intent
    if not notes:
        return "Nothing recognised to remove.", []
    return "\n".join(notes), []


def _current_intent(state: dict) -> str | None:
    """The intent a module-op turn is operating under: the focused module's
    build-intent, falling back to the whole-project intent."""
    cm = state.get("current_module")
    if cm:
        return f"build_{cm}"
    return state.get("intent")


def apply_operation(state: dict, op, catalog) -> tuple[str, list[str]]:
    """Route one operation's effect through the SKILL registry.

    ``select_module`` (focus change) and ``none`` (fill any fields) are handled
    directly. Every state-mutating action (add/set/remove) is dispatched to the
    skill registered for ``(current intent, action)`` — so which actions an
    intent supports, and how they're handled, is data in ``skills.py`` rather
    than an inline if-ladder. ``build``/``list`` are DRIVER-executed (I/O), not
    skills. Shared by the fresh-extract and pending-confirmation paths.
    """
    if op.action == "select_module":
        module, card = module_focus.set_focus(state, op.module)
        return card, []
    if op.action == "none":
        return apply_extracted_fields(state, op, catalog)

    from .skills import find_skill

    intent = _current_intent(state)
    skill = find_skill(intent, op.action)
    if skill is None:
        focus = module_focus.get_focus(state)
        label = focus.label if focus else "this module"
        avail = ", ".join(focus.operations) if focus else "(none)"
        return (
            f"The {label} doesn't support '{op.action}'. "
            f"Available here: {avail}."
        ), []
    return skill.handler(state, op, catalog)


_AFFIRM = frozenset({
    "yes", "y", "ok", "okay", "confirm", "sure", "yep", "yeah", "do it",
    "correct", "right",
})
_DENY = frozenset({"no", "n", "cancel", "nope", "stop", "nevermind", "never mind"})


def resolve_pending_operation(message: str) -> str | None:
    """Map a confirmation answer to 'apply' | 'discard' | None (unclear)."""
    low = (message or "").strip().lower().rstrip("!.")
    if low in _AFFIRM:
        return "apply"
    if low in _DENY:
        return "discard"
    return None


def _module_list_text(state: dict, catalog) -> str:
    """Instance-level listing of the project, grouped by phase.

    Finer than ``/phases`` (which is phase-level): shows each module
    instance, its built status, and its editable variables so the user
    knows exactly what they can /set or /remove. Lives here (not in a
    driver) so all three shells render the listing identically.
    """
    resolve_patterns(state, catalog)
    plan = phase_plan(state.get("patterns") or [])
    if not plan:
        return (
            "No modules yet. Add one with e.g.  /add GFS  (import) or "
            "/add Liard uses raven  (basin), then  /build <name>."
        )
    built = set(state.get("built_modules") or [])
    built_phases = set(state.get("built_phases") or [])
    # Markdown so it renders as a real bulleted list in the app (single-\n
    # space-indented lines collapse into one blob); blank lines separate each
    # phase block, and every instance is its own `- ` bullet.
    lines = ["**Modules in this project**"]
    for entry in plan:
        ph = entry["phase"]
        lines.append("")
        lines.append(f"**{ph}** — {entry['label']}")
        for p in entry["patterns"]:
            pat = p["pattern"]
            short = pat.rsplit("/", 1)[-1]
            for inst in p.get("instances") or [{}]:
                label = next(
                    (str(inst[k]) for k in _LABEL_VAR_KEYS if inst.get(k)),
                    short,
                )
                is_built = (
                    f"{pat}::{label}" in built or ph in built_phases
                )
                mark = "built" if is_built else "ready"
                extras = []
                for vk in ("grid_resolution", "forecast_horizon_hours",
                           "model_adapter"):
                    if inst.get(vk):
                        extras.append(f"{vk}={inst[vk]}")
                if inst.get("parameters"):
                    n = len(inst["parameters"])
                    extras.append(f"{n} param" + ("s" if n != 1 else ""))
                extra_txt = f" — {', '.join(extras)}" if extras else ""
                lines.append(f"- **{label}** · `{short}` · {mark}{extra_txt}")
    lines.append("")
    lines.append(
        "_Just say what you want — e.g. \"what can I change on "
        f"{_first_instance_label(state) or 'GFS'}?\", \"add HRDPS\", "
        "\"remove it\", or \"build it\". (`/help` lists the commands.)_"
    )
    return "\n".join(lines)


# --- /vars: what can I actually tune? -------------------------------------
#
# Across the library only ~45 of ~336 pattern variables are REQUIRED; the other
# ~291 carry an explicit default (blueprint._apply_defaults: instance value →
# default → loud error if a required one is missing). So the agent rightly asks
# for very little — but that left every optional knob undiscoverable: `/set`
# existed with no way to learn which <var> names were valid, what they're
# currently set to, or whether that value came from you or from the default.
# This renders exactly that, straight from the catalog's `variables` block, so
# it can never drift from what the pattern actually accepts.


def _first_instance_label(state: dict) -> str:
    """The first instance label in the project (for a concrete example)."""
    for p in state.get("patterns") or []:
        short = str(p.get("pattern", "")).rsplit("/", 1)[-1]
        for inst in p.get("instances") or [{}]:
            return next(
                (str(inst[k]) for k in _LABEL_VAR_KEYS if inst.get(k)), short
            )
    return ""


def _catalog_variables(catalog, pattern_path: str) -> dict:
    """The declared ``variables`` block for a pattern path, from the catalog."""
    for entry in catalog or []:
        if getattr(entry, "path", None) == pattern_path:
            return dict(getattr(entry, "variables", {}) or {})
    return {}


def _instances_matching(state: dict, target: str | None) -> list[tuple[str, str, dict]]:
    """``(pattern_path, label, instance)`` for instances whose label matches.

    ``target`` None/empty matches everything; otherwise matches the instance
    label (e.g. "GFS") or the short pattern name, case-insensitively.
    """
    want = (target or "").strip().lower()
    out: list[tuple[str, str, dict]] = []
    for p in state.get("patterns") or []:
        pat = str(p.get("pattern", ""))
        short = pat.rsplit("/", 1)[-1]
        for inst in p.get("instances") or [{}]:
            label = next(
                (str(inst[k]) for k in _LABEL_VAR_KEYS if inst.get(k)), short
            )
            if not want or want in (label.lower(), short.lower()):
                out.append((pat, label, inst))
    return out


def _fmt_var_value(value) -> str:
    """Render a variable value compactly for the /vars table."""
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                parts.append(str(
                    item.get("id") or item.get("basin_name")
                    or next(iter(item.values()), "?")
                ))
            else:
                parts.append(str(item))
        return ", ".join(parts) if parts else "—"
    if isinstance(value, dict):
        return ", ".join(f"{k}={v}" for k, v in value.items()) or "—"
    return str(value)


def module_vars_text(state: dict, catalog, target: str | None = None) -> str:
    """What you can tune — the whole project, or one instance's variables.

    No ``target`` → the instance overview (what ``/list`` showed) plus a pointer
    to the detail view. With a ``target`` → every variable the pattern declares,
    its effective value, and whether that came from YOU or from the default.
    Deterministic: pure catalog + blueprint data, no LLM.
    """
    matches = _instances_matching(state, target)

    if not target:
        # The overview's own footer already points at `/vars <name>` — don't
        # repeat it here.
        return _module_list_text(state, catalog)

    if not matches:
        known = [lbl for _, lbl, _ in _instances_matching(state, None)]
        avail = ", ".join(f"`{k}`" for k in known) if known else "_(nothing yet)_"
        return (
            f"I don't have anything called **{target}** in this project. "
            f"Currently here: {avail}."
        )

    blocks: list[str] = []
    for pat, label, inst in matches:
        declared = _catalog_variables(catalog, pat)
        short = pat.rsplit("/", 1)[-1]
        rows: list[str] = [f"**{label}** · `{short}`", ""]
        if not declared:
            rows.append("_This pattern declares no tunable variables._")
            blocks.append("\n".join(rows))
            continue
        for name, spec in declared.items():
            spec = spec if isinstance(spec, dict) else {}
            if name in inst:
                value, source = inst[name], "you set this"
            elif "default" in spec:
                value, source = spec["default"], "default"
            elif spec.get("required"):
                value, source = None, "**required — not set**"
            else:
                value, source = None, "default"
            rows.append(
                f"- `{name}` — {_fmt_var_value(value)} _({source})_"
            )
        rows.append("")
        rows.append(
            f"_To change one, just say it — e.g. \"make {label} "
            f"half-degree\" or \"set {label}'s map area\"._"
        )
        blocks.append("\n".join(rows))
    return "\n\n".join(blocks)


@dataclass
class ModuleTurnResult:
    """The outcome of one module-mode prose turn — driver-agnostic.

    ``reply`` is the user-facing text (the LLM-composed guidance); ``note`` the
    transcript/log tag; ``confirmation`` the mechanical "what changed" fact,
    which shells render MUTED (grey) above/around the reply so the model's
    guidance reads as the main voice. ``kind`` distinguishes a plain reply from
    a state edit. ``wants_build`` is set when the extracted operation was
    ``build`` — the shells execute their own scoped build (console table /
    TurnResult / JSON) because the build I/O legitimately differs; everything
    else is fully shared.
    """

    reply: str
    note: str
    kind: str = "reply"          # "reply" | "edit"
    action: str = "none"
    new_patterns: list[str] = field(default_factory=list)
    wants_build: bool = False
    confirmation: str = ""       # muted "what changed" fact (grey in the UI)
    # Signals from the LLM-first patch turn (llm_turn.run_llm_turn):
    build_scope: str | None = None       # phase/module name for wants_build
    wants_assemble: bool = False         # the `done` path
    coordinates_for: str | None = None   # ""=all grids, name=one, None=no
    input_files_written: list[str] = field(default_factory=list)
    wants_undo: bool = False             # prose "undo that" — shell rolls back


def _next_step_hint(state: dict, focus) -> str:
    """The single, focused follow-up QUESTION for the module's current state —
    so the agent guides one step at a time ("GFS added. Which weather
    variables?") instead of dumping the whole option menu every turn.

    Progress-aware and deterministic (control-flow guidance must not drift),
    plain text so it reads the same in console / app / API JSON. Returns "" when
    there's nothing sensible to ask.

    PLAIN LANGUAGE ONLY — no slash commands. Every action reachable from here
    is reachable by just saying it ("build it", "set GFS's map area", "add
    HRDPS"), so the agent describes the action instead of teaching syntax. The
    command list lives in ``/help``, which is where a user who wants it looks.
    """
    if focus is None:
        return ""
    slots = state.get("slots") or {}
    key = getattr(focus, "key", None)

    if key == "processing":
        imports = [str(i) for i in (slots.get("imports") or [])]
        has_basin = bool(slots.get("basins") or slots.get("basin_name"))
        if not imports and not has_basin:
            return ("What would you like to import? (e.g. GFS, HRDPS) — or say "
                    "'Liard uses raven' to add a model.")
        if imports and not slots.get("data_types"):
            return (f"Which weather variables should {imports[-1]} carry? "
                    "(e.g. precipitation, temperature)")
        target = imports[-1] if imports else "the model"
        return (f"Want to set {target}'s map area, add another source, or "
                f"build what you have so far?")

    if key == "display":
        # Display plots the grids the session already imported (shared read),
        # so guide: nothing to plot → which source → over what window → build.
        imports = [str(i) for i in (slots.get("imports") or [])]
        if not imports:
            return ("Nothing to visualize yet — add a gridded source first "
                    "(e.g. say 'add GFS'), then come back here to plot it.")
        if not slots.get("wants_visualization"):
            joined = ", ".join(imports)
            return (f"Which source's grids should I visualize — {joined}? "
                    "(name one, or say 'all of them')")
        if not slots.get("forecast_horizon_hours"):
            return ("Over what forecast window should the plots run? "
                    "(e.g. '7 days') — or say you're ready to build.")
        return "The display is set up — want me to build it?"

    if key == "locations":
        # The station list itself is a locations.csv input; the one variable
        # worth eliciting is the datum. Guide toward both.
        if not module_focus.read_var(state, "geoDatum"):
            return ("What geographic datum are your station coordinates in? "
                    "(e.g. WGS 1984) — the stations themselves come from a "
                    "locations.csv you drop in inputs/.")
        return ("Datum's set. Add your stations as inputs/locations.csv "
                "(id, name, lat/lon, attributes) if you haven't yet — then "
                "tell me when you'd like to build.")

    if getattr(focus, "supports", lambda _op: False)("set"):
        var = module_focus.next_unfilled_variable(state, focus)
        if var:
            return f"What should {var} be?"
        return "That's everything this module needs — want me to build it?"

    # Assembly-generated module (Filters, Topology, IdMapFiles, System, Root):
    # nothing is configured here by hand and it is NOT built on its own — the
    # old "this module is ready — want me to build it?" was a template lie on
    # an empty project. Say what the folder is and where its files come from.
    short = (getattr(focus, "label", "") or "").split(" (")[0].strip() or \
        getattr(focus, "key", "this")
    what = getattr(focus, "description", "") or ""
    if state.get("full_build_ok"):
        return (f"{short} was generated at the last assembly and refreshes "
                f"automatically whenever you assemble again. {what}")
    return (f"{short} is generated automatically at final assembly — "
            f"there's nothing to configure here by hand. {what} Keep working "
            f"in the content modules and tell me when you're ready to "
            f"assemble the project.")


def module_edit_reply(note: str, state: dict) -> str:
    """A concise edit reply: the confirmation + the ONE focused follow-up
    question — no full module list / command menu (that's what /list is for).
    Shared by every shell's edit paths so replies stay short and identical.

    This is the DETERMINISTIC fallback. The live path composes the guiding
    reply with the LLM (:func:`compose_module_reply`) and shows ``note`` as a
    separate muted confirmation; this template is what renders when no provider
    is available or the LLM call fails."""
    q = _next_step_hint(state, module_focus.get_focus(state))
    return note + (f"\n\n{q}" if q else "")


# Slots that count as "done" for a module's checklist but read nicer with a
# friendly label than the raw slot key.
_CHECKLIST_LABELS = {
    "imports": "imports",
    "basins": "basin model(s)",
    "data_types": "weather variables",
    "grid_resolution": "grid resolution",
    "forecast_horizon_hours": "forecast horizon",
    "region": "map region",
    "custom_bbox": "map area",
    "grid_geometry": "grid coordinates",
    "geoDatum": "geo datum",
}


def _module_progress(state: dict, focus, catalog) -> dict:
    """A structured completion checklist for the focused module.

    Splits the module's variables into done/todo (via
    :func:`module_focus.module_slot_status`), decides whether the module has
    enough to build, and carries the deterministic next-step hint as the anchor
    the LLM should guide toward. Pure — no LLM, no I/O — so the guidance can't
    drift on WHICH step is next, only on how it's phrased.
    """
    slots = state.get("slots") or {}
    status = module_focus.module_slot_status(state, focus) if focus else {
        "filled": [], "unfilled": []
    }

    def _label(k: str) -> str:
        return _CHECKLIST_LABELS.get(k, k)

    done = []
    for k in status.get("filled", []):
        val = slots.get(k)
        if isinstance(val, list) and val:
            done.append(f"{_label(k)}: {', '.join(str(v) for v in val)}")
        elif val not in (None, "", [], {}):
            done.append(f"{_label(k)}: {val}")
        else:
            done.append(_label(k))
    todo = [_label(k) for k in status.get("unfilled", [])]

    key = getattr(focus, "key", None)
    if key == "processing":
        ready = bool(slots.get("imports") or slots.get("basins")
                     or slots.get("basin_name"))
    elif focus is not None and getattr(focus, "supports", lambda _o: False)("set"):
        ready = module_focus.next_unfilled_variable(state, focus) is None
    else:
        ready = True  # view-only modules are always buildable

    # CONFIGURED is not BUILT. ``done``/``todo`` describe slots the user has
    # filled in; these describe what has actually been rendered + XSD-validated.
    # Without them the reply can only ever talk about configuration, so it can't
    # answer "what's already built?" — it would call a never-built module done.
    built_phases = set(state.get("built_phases") or [])
    built_instances = [
        str(m).split("::")[-1] for m in (state.get("built_modules") or [])
    ]
    mod_phases = list(getattr(focus, "phases", ()) or ())
    built_here = [p for p in mod_phases if p in built_phases]
    unbuilt_here = [p for p in mod_phases if p not in built_phases]

    return {
        "done": done,
        "todo": todo,
        "ready": ready,
        "built": built_here,
        "unbuilt": unbuilt_here,
        "built_instances": built_instances,
        "suggested_next": _next_step_hint(state, focus),
    }


def agentic_guidance_enabled() -> bool:
    """Whether the model may CHOOSE the next step instead of narrating ours.

    Off by default: ``suggested_next`` is an instruction, so control-flow
    guidance is deterministic and cannot drift. Set
    ``FEWS_AGENT_AGENTIC_GUIDANCE=1`` to hand the model the full picture and let
    it decide — more agentic, less predictable. Kept as a flag so the two can be
    compared side by side on the same project.
    """
    import os
    return (os.environ.get("FEWS_AGENT_AGENTIC_GUIDANCE") or "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _history_text(history: list | None, limit: int = 6) -> str:
    """The last few turns, oldest→newest, for the composer prompt.

    Without this the model sees only a state snapshot and the latest message —
    it has no memory of what it just said, which is why two different questions
    in a row produced near-identical replies. Truncated per message so a long
    build panel can't crowd out the conversation.
    """
    if not history:
        return "(this is the first thing they've said)"
    lines: list[str] = []
    for entry in list(history)[-limit:]:
        role = "User" if entry.get("role") == "user" else "You"
        msg = " ".join(str(entry.get("message", "")).split())
        if len(msg) > 300:
            msg = msg[:300] + "…"
        if msg:
            lines.append(f"{role}: {msg}")
    return "\n".join(lines) or "(this is the first thing they've said)"


def compose_module_reply(
    state: dict, focus, changed_note: str, catalog, *, provider,
    model: str = "qwen2.5:7b-instruct", help_mode: bool = False,
    history: list | None = None,
) -> str:
    """LLM-composed guiding reply for a module-mode turn.

    The engine has already applied the edit; this phrases a warm, natural reply
    that acknowledges ``changed_note`` and guides toward completing the module,
    using the deterministic checklist (:func:`_module_progress`) as the anchor.
    Falls back to just the deterministic next-step question when no provider is
    wired or the call fails, so the turn never breaks. The mechanical "what
    changed" fact is shown separately (muted) by the shells — this reply is the
    guidance, NOT the confirmation, so the fallback is the QUESTION ALONE (never
    the note again: that would double-print "Applied: …" once grey, once here).

    Uses the plain ``chat`` (free text) interface, NOT ``generate_json`` — this
    is a phrasing task, not a structured-output one, so forcing
    ``response_format=json_object`` is both unnecessary and fragile (some Azure
    deployments / api-versions reject it, which silently fell back to the
    robotic template). ``chat`` is the universal Provider method every backend
    implements."""
    from . import prompts
    from .providers.base import Message

    def _fallback() -> str:
        hint = _next_step_hint(state, focus) or "This module is ready to /build."
        if help_mode:
            # A question deserves an answer even with no LLM: say what this
            # module does, then the concrete next step.
            what = getattr(focus, "description", "") or getattr(focus, "label", "")
            return (
                f"You're in the {getattr(focus, 'label', 'current')} module — "
                f"{what} You can add or change things in plain language "
                f"(e.g. 'add HRDPS', 'remove temperature'), see what's here "
                f"with /list, or /build to generate and validate. {hint}"
            )
        return hint

    if provider is None:
        return _fallback()

    prog = _module_progress(state, focus, catalog)
    label = getattr(focus, "label", "this")
    job = getattr(focus, "prompt", "") or getattr(focus, "description", "") or ""

    system = prompts.load("module_reply.system")
    user = prompts.load(
        "module_reply.user",
        module_label=label,
        module_job=job,
        turn_kind=(
            "question/help — the user asked something; NOTHING changed. "
            "Answer and teach; do not report a non-edit."
            if help_mode else
            "edit — the engine applied the change below"
        ),
        user_message=repr(state.get("_last_user_message", "")),
        changed=changed_note or "(nothing new)",
        done_text="; ".join(prog["done"]) or "(nothing yet)",
        todo_text="; ".join(prog["todo"]) or "(nothing left)",
        ready="yes" if prog["ready"] else "not yet",
        built_text=(
            ", ".join(prog["built"]) if prog["built"]
            else "nothing built yet — everything here is still only configured"
        ),
        unbuilt_text=", ".join(prog["unbuilt"]) or "(nothing pending)",
        history_text=_history_text(history),
        guidance_mode=(
            "a SUGGESTION — you may follow it or choose a better next step "
            "yourself, using your judgement about what this user needs"
            if agentic_guidance_enabled() else
            "the step to guide toward — follow it"
        ),
        suggested_next=prog["suggested_next"] or "(module is complete)",
    )
    try:
        resp = provider.chat(
            system, [Message(role="user", content=user)], tools=[],
        )
        text = (resp.text or "").strip().strip('"')
        if text:
            return text
    except Exception as exc:  # noqa: BLE001
        # Don't fail the turn, but don't hide WHY the model reply was skipped —
        # a silent fallback reads to the user as "the LLM did nothing".
        logging.getLogger(__name__).warning(
            "compose_module_reply fell back to the deterministic question: "
            "%s: %s", type(exc).__name__, exc,
        )
    return _fallback()


def module_welcome(state: dict, module) -> str:
    """The main reply for a freshly-entered module: just the ONE focused
    question ("What would you like to import?"), or — for the
    assembly-generated folders — an honest statement of where their files come
    from. The discrete grey status line ("Focused on <FEWS folder>.") is
    carried SEPARATELY as the muted confirmation (``module_focus.focus_card``)
    by every entry path — cold entry, the ``select_module`` switch, and each
    shell's ``/module`` handler."""
    return _next_step_hint(state, module)


def module_vars_reply(state: dict, catalog, target: str | None = None) -> str:
    """``/vars`` — what's in the project, or what you can tune on one instance,
    plus the proactive next-step nudge.

    ONE command for both questions: bare ``/vars`` answers "what's in my
    project?" (the old ``/list``), ``/vars GFS`` answers "what can I change on
    GFS?". ``list``/``show`` are aliases of the bare form, so there is no second
    overlapping concept to learn.

    The next-step hint is appended only when the focused module is a CONTENT
    module — with an assembly-generated module in focus (Filters, Root...),
    its whole "generated at final assembly" paragraph got glued under the
    variables table, which is entry text, not a next step."""
    text = module_vars_text(state, catalog, target)
    focus = module_focus.get_focus(state)
    is_content = focus is not None and (
        getattr(focus, "phases", ()) or focus.supports("set")
    )
    hint = _next_step_hint(state, focus) if is_content else ""
    return text + (f"\n\n{hint}" if hint else "")


def module_list_reply(state: dict, catalog) -> str:
    """Back-compat alias for the bare ``/vars`` overview (the prose-``list``
    path and older call sites still use this name)."""
    return module_vars_reply(state, catalog, None)


def run_module_turn(
    state: dict, message: str, catalog, focus, *, provider,
    just_entered: bool = False, history: list | None = None,
) -> ModuleTurnResult:
    """Module-mode prose turn — the ONE shared implementation all shells call.

    When a module is in focus, a free-form message is exactly ONE operation
    on it. Resolve a pending confirmation first; otherwise extract the
    operation (LLM), validate it against the catalog, and route it:
    ``build``/``list`` → the driver's handlers; a low-confidence effectful op
    → stash + ask to confirm; otherwise apply and reply. Catalog-dropped
    values are surfaced loudly, never applied silently. Mutates ``state`` in
    place; does no history/log/print I/O (the shells own that).

    Previously duplicated verbatim in ``chat_step._run_module_operation`` and
    ``chatter._run_module_operation`` — unifying here is what lets the HTTP
    API get module-mode without a third copy (and stops the two from
    drifting, which is how the API missed module-mode in the first place).
    """
    from .extractor import (
        describe_operation, extract_operation, needs_confirmation,
        op_from_dict, op_to_dict,
    )

    state["_last_user_message"] = message  # read by compose_module_reply

    # A low-confidence op from a prior turn is awaiting a yes/no.
    pending = state.get("_pending_operation")
    if pending:
        decision = resolve_pending_operation(message)
        if decision is not None:
            state["_pending_operation"] = None
            if decision == "discard":
                return ModuleTurnResult(
                    "Okay — cancelled, nothing applied.",
                    "module op: cancelled",
                )
            changed, new_patterns = apply_operation(
                state, op_from_dict(pending), catalog
            )
            guidance = compose_module_reply(
                state, focus, changed, catalog, provider=provider,
                history=history,
            )
            return ModuleTurnResult(
                guidance, "module op: confirmed", kind="edit",
                new_patterns=new_patterns, confirmation=changed,
            )
        # Unclear answer → drop the stale pending op, process this fresh.
        state["_pending_operation"] = None

    op = extract_operation(message, focus_module=focus, provider=provider,
                           catalog=catalog)

    # build / list are DRIVER-executed (I/O differs per shell).
    if op.action == "build":
        return ModuleTurnResult(
            "", "module op: build", action="build", wants_build=True,
        )
    if op.action == "list":
        return ModuleTurnResult(module_list_reply(state, catalog), "module op: list")

    # Uncertain AND effectful → confirm instead of applying silently.
    if needs_confirmation(op):
        state["_pending_operation"] = op_to_dict(op)
        reply = (
            f"Just to confirm — did you want to {describe_operation(op)}? "
            f"(yes / no)"
        )
        return ModuleTurnResult(reply, "module op: confirm?")

    changed, new_patterns = apply_operation(state, op, catalog)

    # Pure cold entry ("configure locations") with no operation to apply:
    # the focused question as the reply, the discrete grey status as the
    # muted confirmation — no verbose welcome pile.
    is_card = just_entered and op.action == "none" and not op.fields
    if is_card:
        return ModuleTurnResult(
            module_welcome(state, focus), f"module op: {op.action}",
            kind="edit", action=op.action, new_patterns=new_patterns,
            confirmation=module_focus.focus_card(state, focus),
        )

    # A module switch: same shape for the module now in focus.
    if op.action == "select_module":
        new_focus = module_focus.get_focus(state)
        return ModuleTurnResult(
            module_welcome(state, new_focus),
            f"module op: {op.action}", kind="edit", action=op.action,
            new_patterns=new_patterns,
            confirmation=module_focus.focus_card(state, new_focus),
        )

    # An edit (add / set / remove / none-with-fields): the LLM composes the
    # guiding reply from the module checklist; the mechanical "what changed"
    # note rides along as the muted confirmation (grey in the UI). Falls back
    # to the deterministic template inside compose_module_reply if the LLM is
    # unavailable. Catalog-dropped values stay LOUD — appended to the main
    # reply, never buried in the grey confirmation.
    # A turn that changed NOTHING is not an edit — it's a question ("help me
    # out", "what is GFS?") or prose we couldn't act on. Showing "Noted —
    # nothing new to change." as a grey what-changed fact is noise, and asking
    # the model to acknowledge a non-existent edit produced the useless
    # "Noted … / here's your state again" reply. Answer the user instead.
    _is_noop = changed == _NOOP_NOTE

    # A capability we HAVE but can't instantiate without values we'd be
    # guessing at — derived from the pattern's own required variables, not a
    # hand-maintained list.
    _, _needs_input = split_addable_capabilities(
        detect_capabilities(message, catalog), catalog,
    )

    if _needs_input and _is_noop:
        # We know EXACTLY what they asked for and exactly what it still needs,
        # so answer deterministically. Letting the model improvise here made it
        # invent instructions that don't apply ("say 'add archive import for
        # GFS'") — a confidently wrong explanation over a correct fact.
        lines = [
            f"I can set up **{path.rsplit('/', 1)[-1]}**, but it needs "
            f"{', '.join(needed)} first — tell me those and I'll add it."
            for path, needed in _needs_input
        ]
        return ModuleTurnResult(
            "\n\n".join(lines), f"module op: {op.action}", kind="edit",
            action=op.action, new_patterns=new_patterns,
        )

    guidance = compose_module_reply(
        state, focus, "" if _is_noop else changed, catalog, provider=provider,
        help_mode=_is_noop, history=history,
    )
    if _is_noop:
        changed = ""  # nothing changed → no grey confirmation
    if op.dropped:
        guidance += (
            "\n\n[!] Ignored (not in the catalog, so not applied): "
            + ", ".join(op.dropped)
            + ". Rephrase with a known name if you meant something valid."
        )
    for path, needed in _needs_input:
        guidance += (
            f"\n\n[!] I can set up `{path.rsplit('/', 1)[-1]}`, but it needs "
            f"{', '.join(needed)} first — tell me those and I'll add it."
        )
    return ModuleTurnResult(
        guidance, f"module op: {op.action}", kind="edit", action=op.action,
        new_patterns=new_patterns, confirmation=changed,
    )


def apply_disambiguation_answer(state: dict, message: str) -> None:
    """Consume a pending intent-disambiguation answer, if one is awaited.

    A prior turn asked "imports only or a full forecasting project?" and
    set ``awaiting_intent_disambiguation``. This turn's message is that
    answer: an 'a'/'b' shorthand, a natural phrasing, or an explicit
    intent-naming override. On a clear choice, commit the intent and latch
    ``intent_disambiguated`` so the Phase 3.5 gate never re-asks; otherwise
    just clear the flag so the gate re-evaluates against this turn's slots.
    Drivers call this after appending the user message, before command
    dispatch (so a bare 'a'/'b' isn't swallowed by a command). No-op when
    nothing is awaited.
    """
    if not state.get("awaiting_intent_disambiguation"):
        return
    ans = parse_intent_disambiguation_answer(message)
    if ans is None:
        ans = forced_intent_override(message, None)
    state["awaiting_intent_disambiguation"] = False
    if ans:
        state["intent"] = ans
        state["intent_disambiguated"] = True
        state["patterns"] = []  # resolver rebuilds from slots


def _format_internals(
    prose_facts: dict,
    llm_intent: str | None,
    llm_entities: dict | None,
    chosen_intent: str | None,
    notes: list[str],
    state: dict,
    new_patterns: list[str],
    ready: bool,
    next_q: str | None,
    input_status: dict | None = None,
    warnings: list[str] | None = None,
) -> str:
    """Render skill / intent / slot / pattern diagnostics as markdown."""
    lines: list[str] = []

    lines.append("**1. Skills (deterministic regex pass)**")
    if prose_facts:
        for k, v in prose_facts.items():
            if v in (None, [], {}):
                continue
            lines.append(f"- `{k}` = {v!r}")
    else:
        lines.append("- (no skill output)")
    lines.append("")

    if llm_intent is not None or llm_entities is not None:
        lines.append("**2. LLM intent classification (qwen2.5)**")
        lines.append(f"- picked: `{llm_intent}`")
        if llm_entities:
            for k, v in llm_entities.items():
                lines.append(f"- entity `{k}` = {v!r}")
        lines.append(f"- final intent: `{chosen_intent}`")
        lines.append("")

    slot_notes = [n for n in notes if n.startswith("slot ") or n.startswith("derived ")]
    if slot_notes:
        lines.append("**3. Slot-fill events**")
        for n in slot_notes:
            lines.append(f"- {n}")
        lines.append("")

    if new_patterns:
        lines.append("**4. Pattern resolution**")
        lines.append(f"- {len(new_patterns)} new pattern(s) added:")
        for p in new_patterns:
            lines.append(f"  - `{p}`")
        lines.append("")

    if input_status:
        lines.append("**5. Input scan (`inputs/` vs intent expectations)**")
        present = input_status.get("csvs_present") or []
        req_missing = input_status.get("csvs_required_missing") or []
        rec_missing = input_status.get("csvs_recommended_missing") or []
        ypc = input_status.get("yamls_present_count") or 0
        rec_yamls = input_status.get("recommended_yamls") or input_status.get(
            "yamls_recommended_examples"
        ) or []
        auto_yamls = input_status.get("auto_generated_yamls") or []
        lines.append(f"- CSVs present: {present or '(none)'}")
        lines.append(f"- CSVs required & missing: {req_missing or '(none)'}")
        lines.append(f"- CSVs recommended & missing: {rec_missing or '(none)'}")
        lines.append(f"- yamls present count: {ypc}")
        if rec_yamls:
            lines.append(f"- recommended yamls (configurator-authored): {rec_yamls}")
        if auto_yamls:
            lines.append(f"- auto-generated yamls (no need to author): {auto_yamls}")
        lines.append("")

    if warnings:
        lines.append("**6. ⚠ Warnings (loud failures — surfaced to user)**")
        for w in warnings:
            lines.append(f"- {w}")
        lines.append("")

    lines.append("**7. State snapshot**")
    lines.append(f"- intent: `{state.get('intent')}`")
    slots = state.get("slots") or {}
    lines.append(f"- slots filled: {sum(1 for v in slots.values() if v)}/{len(slots)}")
    lines.append(f"- patterns: {len(state.get('patterns') or [])}")
    lines.append(f"- ready: `{ready}`")
    if next_q:
        lines.append(f"- next unfilled question: {next_q!r}")
    lines.append("")

    other_notes = [
        n for n in notes
        if not n.startswith("slot ") and not n.startswith("derived ")
    ]
    if other_notes:
        lines.append("**8. Other notes**")
        for n in other_notes:
            lines.append(f"- {n}")
        lines.append("")

    return "\n".join(lines).rstrip()


@dataclass
class PipelineResult:
    """Structured outcome of one turn's Phase 1–5 pipeline.

    ``run_turn_pipeline`` does no I/O — the driver renders this. When
    ``short_circuit`` is True the disambiguation gate asked a question
    (``agent_message`` is the question, ``log_note`` labels the turn) and
    nothing was resolved/composed. Otherwise ``agent_message`` is the
    composed reply and the remaining fields carry the turn's diagnostics.
    """
    short_circuit: bool
    agent_message: str
    log_note: str | None = None
    internals: str | None = None
    warnings: list[str] = field(default_factory=list)
    ready: bool = False
    next_question: str | None = None
    new_patterns: list[str] = field(default_factory=list)
    recent_edit: str | None = None


def run_turn_pipeline(
    state: dict,
    message: str,
    catalog,
    *,
    provider,
    inputs_dir,
    nag_suppression: bool = False,
) -> PipelineResult:
    """Run one turn's deterministic + LLM pipeline (Phases 1–5).

    Single source of truth shared by both drivers. Mutates ``state`` in
    place (intent, slots, patterns, warnings, disambiguation flags) and
    returns a :class:`PipelineResult`. Does NO history/log/save/print I/O
    and resolves no provider — the driver passes ``provider`` (its own
    resolution) and ``inputs_dir`` (CLI: project_dir/inputs; app:
    session_dir/inputs), and owns persistence + output rendering.

    ``nag_suppression`` (app passes True) blanks already-surfaced
    missing-CSV lists on repeat turns via ``state["_inputs_nagged"]``; the
    CLI passes False and the suppression state is never touched.
    """
    # Phase 1: skills.
    prose_facts = filter_prose(message)

    # Phase 2: intent classification (only if no intent yet).
    notes: list[str] = []
    llm_picked: str | None = None
    llm_entities: dict | None = None
    chosen_intent: str | None = state.get("intent")

    if state.get("intent") is None:
        try:
            cls = classify_intent(message, prose_facts, provider=provider)
            llm_picked = cls.get("intent")
            llm_entities = cls.get("entities", {}) or {}
            # Merge LLM-supplied entities into skill results (skills win).
            # Empty-list slots (data_types) are treated as missing so the
            # LLM extraction isn't shadowed by a zero-result regex pass.
            for k, v in llm_entities.items():
                existing = prose_facts.get(k)
                if (k not in prose_facts or existing is None
                        or (isinstance(existing, list) and not existing)):
                    prose_facts[k] = v
                    notes.append(f"LLM filled {k}={v}")
        except Exception as exc:  # noqa: BLE001
            notes.append(f"intent classify failed: {str(exc)[:60]}")

        chosen_intent = (
            llm_picked if llm_picked in INTENTS
            else heuristic_intent_from_slots(prose_facts)
        )
        state["intent"] = chosen_intent
        if chosen_intent:
            notes.append(
                f"intent: {chosen_intent}"
                + ("" if llm_picked == chosen_intent else " (heuristic)")
            )
        else:
            notes.append("no intent classified")

    # Deterministic intent override — runs on EVERY turn, AFTER
    # classification. An explicit intent-naming phrase forces the intent over
    # the LLM/heuristic pick, so "no basin model" yields build_data_import_only
    # on turn 1 rather than relying on the 7B model. On a later turn this is
    # the mid-conversation re-classification that recovers from an early miss.
    _forced = forced_intent_override(message, state.get("intent"))
    if _forced:
        notes.append(f"intent override: {state.get('intent')} → {_forced}")
        state["intent"] = _forced
        state["patterns"] = []  # resolver will rebuild from slots
        chosen_intent = _forced

    # Phase 2.5: natural-language edits (remove a module / override a scalar).
    # Verb-gated and target-required, so descriptive prose never parses as an
    # edit. Runs AFTER intent + LLM-entity merge but BEFORE the additive
    # merge: applied edits mutate slots immediately, then the just-removed
    # targets are stripped from prose_facts so the additive merge below
    # cannot re-add them on the same turn.
    recent_edit_note: str | None = None  # per-turn; stale notes must not leak
    edit_action = detect_edit_action(message)
    if edit_action and edit_action.get("edits"):
        applied_notes: list[str] = []
        for e in edit_action["edits"]:
            note = apply_edit_action(state, e, catalog)
            notes.append(f"edit: {note}")
            applied_notes.append(note)
        if edit_action.get("removed_imports"):
            ri = {x.lower() for x in edit_action["removed_imports"]}
            if isinstance(prose_facts.get("imports"), list):
                prose_facts["imports"] = [
                    x for x in prose_facts["imports"]
                    if str(x).lower() not in ri
                ]
        if edit_action.get("removed_basins"):
            rb = {x.lower() for x in edit_action["removed_basins"]}
            if isinstance(prose_facts.get("basins"), list):
                prose_facts["basins"] = [
                    b for b in prose_facts["basins"]
                    if not (
                        isinstance(b, dict)
                        and str(b.get("basin_name", "")).lower() in rb
                    )
                ]
            if (
                isinstance(prose_facts.get("basin_name"), str)
                and prose_facts["basin_name"].lower() in rb
            ):
                prose_facts["basin_name"] = None
        recent_edit_note = "; ".join(applied_notes)

    # Phase 3: slot filling — additive, no overwrites.
    slots = state.setdefault("slots", {})
    for k, v in prose_facts.items():
        if v is None or v == []:
            continue
        existing = slots.get(k)
        if isinstance(v, list):
            merged = list(existing or [])
            for item in v:
                if isinstance(item, dict):
                    key = tuple(sorted(item.items()))
                    existing_keys = {
                        tuple(sorted(d.items())) for d in merged
                        if isinstance(d, dict)
                    }
                    if key not in existing_keys:
                        merged.append(item)
                else:
                    if item not in merged:
                        merged.append(item)
            if merged != existing:
                slots[k] = merged
                notes.append(f"slot {k}={merged}")
        else:
            if existing is None:
                slots[k] = v
                notes.append(f"slot {k}={v}")

    # Sync settings: geoDatum / region / custom_bbox → Locations singleton.
    if slots.get("geoDatum"):
        state.setdefault("singleton_seeds", {}).setdefault(
            "Locations", {}
        )["geoDatum"] = slots["geoDatum"]
    if slots.get("region"):
        state.setdefault("singleton_seeds", {}).setdefault(
            "Locations", {}
        )["region"] = slots["region"]
    if slots.get("custom_bbox"):
        state.setdefault("singleton_seeds", {}).setdefault(
            "Locations", {}
        )["regionBbox"] = list(slots["custom_bbox"])

    # Cross-turn promotion: singular basin_name + model_adapter filled on
    # different turns → synthesise the canonical `basins` pair.
    if (
        not slots.get("basins")
        and slots.get("basin_name")
        and slots.get("model_adapter")
    ):
        slots["basins"] = [{
            "basin_name": slots["basin_name"],
            "model_adapter": slots["model_adapter"],
        }]
        notes.append(f"derived basins={slots['basins']}")

    if slots.get("locations_source") == "csv":
        if "locations.csv" not in state.get("missing_data", []):
            state.setdefault("missing_data", []).append("locations.csv")

    # Phase 3.5: intent disambiguation gate. One half (imports XOR basin) with
    # no explicit narrowing/forecasting signal → ASK rather than silently
    # defaulting to forecasting. Deterministic question; the turn
    # short-circuits until answered. Re-asks capped, then forecasting default.
    if not state.get("intent_disambiguated"):
        _which = intent_disambiguation_needed(message, slots)
        if _which:
            _asks = state.get("intent_disambiguation_asks", 0)
            if _asks >= 2:
                state["intent"] = "build_forecasting_project"
                state["intent_disambiguated"] = True
                state["patterns"] = []
                notes.append(
                    "intent disambiguation unanswered → forecasting default"
                )
            else:
                state["intent_disambiguation_asks"] = _asks + 1
                state["intent_disambiguation_which"] = _which
                state["awaiting_intent_disambiguation"] = True
                return PipelineResult(
                    short_circuit=True,
                    agent_message=intent_disambiguation_question(_which),
                    log_note="intent disambiguation",
                )

    # Phase 4: resolve patterns from slots.
    patterns_before = {p["pattern"] for p in state.get("patterns", [])}
    resolve_patterns(state, catalog)
    new_patterns = [
        p["pattern"] for p in state.get("patterns", [])
        if p["pattern"] not in patterns_before
    ]

    # Phase 4.25: warn loudly when a mentioned input has no pattern mapping.
    warnings: list[str] = []
    mentioned_imports: set[str] = set()
    if llm_entities and isinstance(llm_entities.get("imports"), list):
        mentioned_imports.update(str(x) for x in llm_entities["imports"])
    if isinstance(slots.get("imports"), list):
        mentioned_imports.update(str(x) for x in slots["imports"])
    mapped_imports: set[str] = set()
    pattern_names_lower: set[str] = set()
    for p in state.get("patterns", []):
        pname = str(p.get("pattern", ""))
        pattern_names_lower.add(pname.lower())
        for inst in p.get("instances") or []:
            if not isinstance(inst, dict):
                continue
            for k in _IMPORT_LABEL_KEYS:
                v = inst.get(k)
                if isinstance(v, str):
                    mapped_imports.add(v)
    unmapped_imports = sorted(
        m for m in mentioned_imports - mapped_imports
        if not any(m.lower() in pn for pn in pattern_names_lower)
    )
    if unmapped_imports:
        warnings.append(
            "No pattern in the library for: "
            + ", ".join(unmapped_imports)
            + ". These would be silently skipped. Add a pattern under "
              "patterns/auto/, or remove them from the request."
        )

    if isinstance(slots.get("basins"), list):
        suspicious = [
            b for b in slots["basins"]
            if isinstance(b, dict) and b.get("basin_name") in ENGLISH_WORD_BLOCKLIST
        ]
        if suspicious:
            names = ", ".join(b["basin_name"] for b in suspicious)
            warnings.append(
                f"Detected '{names}' as a basin name, which looks like an "
                f"English word, not a basin. Likely a regex false positive — "
                f"confirm or correct before continuing."
            )

    if isinstance(slots.get("data_types"), list):
        unmapped_dt = unrecognised_data_types(slots["data_types"])
        if unmapped_dt:
            warnings.append(
                "No FEWS parameterId mapping for: "
                + ", ".join(unmapped_dt)
                + ". These will be skipped — the import will use the "
                  "pattern's default parameter list. Edit the pattern's "
                  "`parameters` variable or rename to a recognised phrase."
            )

    state["warnings"] = warnings

    # Phase 4.5: scan the inputs/ directory and compute presence/missing.
    input_scan = scan_inputs(inputs_dir)
    input_status = compute_input_status(state.get("intent"), input_scan, slots)

    # Optional (app) nag suppression: once a given missing-CSV/yaml set has
    # been surfaced, blank it on later turns so the LLM stops re-asking.
    if nag_suppression and input_status:
        missing_now = sorted(
            set(input_status.get("csvs_required_missing") or [])
            | set(input_status.get("csvs_recommended_missing") or [])
        )
        already_raised = sorted(state.get("_inputs_nagged") or [])
        if missing_now and missing_now == already_raised:
            input_status = dict(input_status)
            input_status["csvs_required_missing"] = []
            input_status["csvs_recommended_missing"] = []
        elif missing_now:
            state["_inputs_nagged"] = missing_now

    # Phase 5: LLM composes the user-facing reply.
    intent = INTENTS.get(state.get("intent") or "")
    next_q = next_unfilled_question(intent, slots) if intent else None
    ready = bool(intent) and is_intent_ready(intent, slots)
    # Module focus (module-mode): scope the elicitation to the focused
    # module's own next gap and steer the reply with its prompt. A no-op
    # when nothing is in focus, so the intent-driven flow is unchanged.
    next_q, module_prompt = _module_focus_question(state, intent, next_q)
    agent_msg = compose_reply(
        user_message=message,
        state=state,
        intent=intent,
        slots=slots,
        notes=notes,
        next_question=next_q,
        is_ready=ready,
        new_patterns=new_patterns,
        input_status=input_status,
        warnings=warnings,
        recent_edit=recent_edit_note,
        provider=provider,
        module_focus_prompt=module_prompt,
    )

    internals = _format_internals(
        prose_facts=prose_facts,
        llm_intent=llm_picked,
        llm_entities=llm_entities,
        chosen_intent=chosen_intent,
        notes=notes,
        state=state,
        new_patterns=new_patterns,
        ready=ready,
        next_q=next_q,
        input_status=input_status,
        warnings=warnings,
    )

    return PipelineResult(
        short_circuit=False,
        agent_message=agent_msg,
        internals=internals,
        warnings=warnings,
        ready=ready,
        next_question=next_q,
        new_patterns=new_patterns,
        recent_edit=recent_edit_note,
    )
