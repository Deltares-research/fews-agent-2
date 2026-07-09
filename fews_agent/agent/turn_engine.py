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

from dataclasses import dataclass, field

from fews_agent.agent import module_focus
from fews_agent.agent.project_chat import (
    add_module,
    remove_module,
    set_variable,
)
from fews_agent.agent.project_intents import (
    ENGLISH_WORD_BLOCKLIST,
    INTENTS,
    classify_intent,
    compose_reply,
    compute_input_status,
    detect_edit_action,
    detect_forecast_horizon_hours,
    detect_grid_resolution,
    detect_model_adapter,
    extract_skills,
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
    state["patterns"] = intent.resolver(state.get("slots", {}), catalog_paths)


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

    # If no intent yet, infer one so the resolver has a template set.
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
    note = "Applied: " + "; ".join(applied) if applied else (
        "Noted — nothing new to change."
    )
    return note, new


def apply_operation(state: dict, op, catalog) -> tuple[str, list[str]]:
    """Route one ExtractedOperation's effect; return (reply, new_patterns).

    Handles add/set (merge fields + resolve), remove (removal edits), and
    select_module (switch focus). ``build``/``list`` are the DRIVER's
    responsibility (they do console/build I/O), so they're not routed here.
    Shared by the fresh-extract path and the pending-confirmation path so
    "apply now" and "apply after you confirm" can't diverge.
    """
    if op.action == "select_module":
        module, card = module_focus.set_focus(state, op.module)
        return card, []
    if op.action == "remove":
        notes: list[str] = []
        # Whole items (imports/basins) — each re-resolves via apply_edit_action.
        for e in extracted_removal_edits(op):
            notes.append(apply_edit_action(state, e, catalog))
        # Field values (a data_type, a scalar/bool setting).
        field_notes = apply_field_removals(state, op.fields or {})
        if field_notes:
            notes.extend(field_notes)
            if not state.get("intent"):
                inferred = heuristic_intent_from_slots(state.get("slots", {}))
                if inferred:
                    state["intent"] = inferred
            resolve_patterns(state, catalog)  # propagate dropped values
        if not notes:
            return "Nothing recognised to remove.", []
        return "\n".join(notes), []
    # add / set / none
    return apply_extracted_fields(state, op, catalog)


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
    skill_results: dict,
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
    if skill_results:
        for k, v in skill_results.items():
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
    skill_results = extract_skills(message)

    # Phase 2: intent classification (only if no intent yet).
    notes: list[str] = []
    llm_picked: str | None = None
    llm_entities: dict | None = None
    chosen_intent: str | None = state.get("intent")

    if state.get("intent") is None:
        try:
            cls = classify_intent(message, skill_results, provider=provider)
            llm_picked = cls.get("intent")
            llm_entities = cls.get("entities", {}) or {}
            # Merge LLM-supplied entities into skill results (skills win).
            # Empty-list slots (data_types) are treated as missing so the
            # LLM extraction isn't shadowed by a zero-result regex pass.
            for k, v in llm_entities.items():
                existing = skill_results.get(k)
                if (k not in skill_results or existing is None
                        or (isinstance(existing, list) and not existing)):
                    skill_results[k] = v
                    notes.append(f"LLM filled {k}={v}")
        except Exception as exc:  # noqa: BLE001
            notes.append(f"intent classify failed: {str(exc)[:60]}")

        chosen_intent = (
            llm_picked if llm_picked in INTENTS
            else heuristic_intent_from_slots(skill_results)
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
    # targets are stripped from skill_results so the additive merge below
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
            if isinstance(skill_results.get("imports"), list):
                skill_results["imports"] = [
                    x for x in skill_results["imports"]
                    if str(x).lower() not in ri
                ]
        if edit_action.get("removed_basins"):
            rb = {x.lower() for x in edit_action["removed_basins"]}
            if isinstance(skill_results.get("basins"), list):
                skill_results["basins"] = [
                    b for b in skill_results["basins"]
                    if not (
                        isinstance(b, dict)
                        and str(b.get("basin_name", "")).lower() in rb
                    )
                ]
            if (
                isinstance(skill_results.get("basin_name"), str)
                and skill_results["basin_name"].lower() in rb
            ):
                skill_results["basin_name"] = None
        recent_edit_note = "; ".join(applied_notes)

    # Phase 3: slot filling — additive, no overwrites.
    slots = state.setdefault("slots", {})
    for k, v in skill_results.items():
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
        skill_results=skill_results,
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
