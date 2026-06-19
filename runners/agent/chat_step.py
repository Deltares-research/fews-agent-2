"""Single-turn chat driver — intent + skills + slot-filling.

Each invocation processes one user message and persists state to disk.
The flow per turn:

  1. Run deterministic SKILLS on the user's message — regex against
     known enum values for adapter, basin, imports, datum, etc.
  2. If state has no intent yet, call the LLM to classify the user's
     intent (which family of project) and to fill in entities the
     skills missed. Otherwise just merge new skill results.
  3. Apply skill outputs to the project's slots additively (no
     overwrites of explicitly-set values).
  4. If the active intent has unfilled required slots, ask one
     focused question. Otherwise resolve patterns deterministically
     from the filled slots and mark the project ready.

State persisted under ``projects/<project>/<project>_<datetime>/.chat_state.json``.

Special user messages handled deterministically:
  - ``done`` / ``quit``: finalise + write project.yaml.
  - ``yes`` / ``no``: confirm or cancel a proposed pattern removal.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from fews_agent.agent.project_chat import (
    add_module,
    apply_removal,
    build_pattern_catalog,
    initial_state,
    remove_module,
    set_variable,
    write_project,
)
from fews_agent.agent.project_intents import (
    ENGLISH_WORD_BLOCKLIST,
    INTENTS,
    classify_intent,
    compose_reply,
    compute_input_status,
    detect_basin,
    detect_basins_with_adapters,
    detect_edit_action,
    detect_forecast_horizon_hours,
    detect_grid_resolution,
    detect_imports,
    detect_model_adapter,
    extract_skills,
    fill_slots_from_text,
    heuristic_intent_from_slots,
    is_intent_ready,
    next_unfilled_question,
    scan_inputs,
    unrecognised_data_types,
)
from fews_agent.agent.phases import (
    PHASE_LABELS,
    PHASE_ORDER,
    next_unbuilt_phase,
    normalize_phase,
    phase_plan,
)
from fews_agent.agent.providers.ollama_provider import OllamaProvider

REPO_ROOT = Path(__file__).resolve().parents[2]
PATTERNS_ROOT = REPO_ROOT / "patterns"
OUTPUT_ROOT = REPO_ROOT / "projects"

# Instance-variable keys that name a module. The first group labels an
# import (reused by the unmapped-import warning scan); basin_name labels a
# model. ``_LABEL_VAR_KEYS`` is the full set used to resolve a user-typed
# module name (e.g. "GFS", "Liard") back to its pattern instance.
_IMPORT_LABEL_KEYS = (
    "nwp_name", "source_name", "wsc_variant", "snow_source", "template_name",
)
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


def _resolve_provider(model: str):
    """Pick the LLM provider for this turn.

    Honors ``FEWS_AGENT_PROVIDER`` (read by the factory) so a user can
    swap the chat-agent backend from Ollama to HF / Anthropic / Azure
    by setting one env var, without touching this file. Falls back to
    Ollama with the CLI ``--model`` arg when no env var is set — keeps
    the existing local-only workflow working unchanged.
    """
    from fews_agent.agent.providers.factory import get_provider_or_ollama
    return get_provider_or_ollama(model)


def _resolve_project_dir(project_name: str) -> Path:
    """Find or create the active datetime-stamped instance for a project.

    Layout: ``projects/<project_name>/<project_name>_<YYYY-MM-DD_HHMMSS>/``.
    Each chat session targets one instance — multiple instances over
    time form a history of project iterations.

    If any ``<project_name>_*`` instances exist, the lexicographically
    latest is returned (timestamp format sorts chronologically). If
    none exist, a fresh instance is created with the current timestamp.
    """
    parent = OUTPUT_ROOT / project_name
    parent.mkdir(parents=True, exist_ok=True)
    instances = sorted(d for d in parent.iterdir() if d.is_dir() and d.name.startswith(f"{project_name}_"))
    if instances:
        return instances[-1]
    from datetime import datetime
    dt = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    new_dir = parent / f"{project_name}_{dt}"
    new_dir.mkdir(parents=True, exist_ok=True)
    return new_dir


def _state_path(project_dir: Path) -> Path:
    return project_dir / ".chat_state.json"


def _history_path(project_dir: Path) -> Path:
    return project_dir / ".chat_history.json"


def _log_path(project_dir: Path) -> Path:
    return project_dir / "_conversation.md"


def _load_state(project_dir: Path, project_name: str) -> tuple[dict, list]:
    sp, hp = _state_path(project_dir), _history_path(project_dir)
    if sp.is_file() and hp.is_file():
        return (
            json.loads(sp.read_text(encoding="utf-8")),
            json.loads(hp.read_text(encoding="utf-8")),
        )
    state = initial_state(project_name)
    state.setdefault("intent", None)
    state.setdefault("slots", {})
    return state, []


def _save(project_dir: Path, state: dict, history: list) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    _state_path(project_dir).write_text(
        json.dumps(state, indent=2, default=str), encoding="utf-8"
    )
    _history_path(project_dir).write_text(
        json.dumps(history, indent=2, default=str), encoding="utf-8"
    )


def _record_build_result(
    project_dir: Path, history: list, turn: int, summary: dict, label: str,
) -> None:
    """Append a build's XSD result as an agent turn → history + transcript.

    Build commands (``/build``, ``/export``) print their XSD table to the
    console but, without this, leave no trace in ``_conversation.md``. This
    writes a one-line agent turn recording per-file XSD validity so the
    saved transcript is self-verifying.
    """
    n_ok = summary.get("files_xsd_ok", 0)
    n_xml = summary.get("files_xml", 0)
    files = summary.get("files", [])
    fails = [f for f in files if not f.get("xsd_ok")]
    # List every file when there are few; for large builds list only the
    # failures (or nothing, if all valid) to keep the transcript readable.
    if len(files) <= 8:
        per_file = ", ".join(
            f"{f['path'].rsplit('/', 1)[-1]}: "
            f"{'OK' if f.get('xsd_ok') else 'FAIL'}"
            for f in files
        )
    elif fails:
        per_file = "failed: " + ", ".join(
            f['path'].rsplit('/', 1)[-1] for f in fails
        )
    else:
        per_file = ""
    verdict = "all XSD-valid" if summary.get("ok") else "XSD VALIDATION FAILED"
    msg = (
        f"Built '{label}': {n_ok}/{n_xml} XSD-valid — {verdict}."
        + (f" [{per_file}]" if per_file else "")
    )
    history.append({"role": "agent", "message": msg})
    _append_log(project_dir, turn, "agent", msg, "build result")


def _append_log(
    project_dir: Path,
    turn: int,
    role: str,
    message: str,
    note: str | None,
    internals: str | None = None,
) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    log = _log_path(project_dir)
    if not log.is_file():
        log.write_text(
            f"# Conversation: {project_dir.name}\n"
            f"Created: {datetime.now().isoformat(timespec='seconds')}\n\n",
            encoding="utf-8",
        )
    block = [f"## Turn {turn} ({role})"]
    if note:
        block.append(f"_{note}_")
    block.append("")
    block.append(message)
    block.append("")
    if internals:
        block.append("<details><summary>Engine internals</summary>")
        block.append("")
        block.append(internals)
        block.append("</details>")
        block.append("")
    with log.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(block) + "\n")


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


def _resolve_patterns(state: dict, catalog) -> None:
    """Refresh state['patterns'] from the resolver, using current slots.

    Resolver runs deterministically. Existing patterns that were
    user-confirmed are preserved if not contradicted by current slots.
    """
    intent_name = state.get("intent")
    intent = INTENTS.get(intent_name)
    if not intent:
        return
    catalog_paths = {p.path for p in catalog}
    derived = intent.resolver(state.get("slots", {}), catalog_paths)
    # Drop patterns that aren't derivable from current slots — but only
    # if the user hasn't explicitly added them outside the intent flow.
    # For now, fully replace (intent-driven assembly).
    state["patterns"] = derived


def _phase_plan_text(state: dict, catalog) -> str:
    """Render the current module-by-module phase plan as a text block.

    Resolves patterns from current slots (without persisting), groups
    them into capability phases, and marks which have been built.
    """
    _resolve_patterns(state, catalog)
    plan = phase_plan(state.get("patterns") or [])
    built = set(state.get("built_phases") or [])
    if not plan:
        return (
            "No modules resolved yet — tell me what you want to import, "
            "model, or visualize and I'll line up the first phase."
        )
    lines = ["Module plan (built one phase at a time):"]
    for entry in plan:
        ph = entry["phase"]
        mark = "(built)" if ph in built else "(ready)"
        names = ", ".join(
            p["pattern"].rsplit("/", 1)[-1] for p in entry["patterns"]
        )
        lines.append(
            f"  {mark} {ph} — {entry['label']}\n"
            f"        {entry['instance_count']} instance(s): {names}"
        )
    nxt = next_unbuilt_phase(state.get("patterns") or [], list(built))
    if nxt:
        lines.append(
            f"\nNext: build the '{nxt}' phase with  /build {nxt}  "
            f"(or 'done' to assemble the whole project)."
        )
    else:
        lines.append(
            "\nAll phases built. Type 'done' to assemble the full "
            "project (singletons, derivers, cross-file validation)."
        )
    return "\n".join(lines)


def _run_phase_build(
    state: dict, project_dir: Path, phase: str, console: Console,
    history: list, turn: int,
) -> int:
    """Resolve current slots → write project.yaml → build one phase."""
    from runners.agent.build_from_blueprint import build_phase

    catalog = build_pattern_catalog(PATTERNS_ROOT)
    _resolve_patterns(state, catalog)
    plan = {e["phase"] for e in phase_plan(state.get("patterns") or [])}
    if phase not in plan:
        console.print(
            f"[yellow]No '{phase}' modules resolved yet.[/yellow] "
            f"Phases with content: {', '.join(sorted(plan)) or '(none)'}."
        )
        return 1
    project_path = write_project(state, project_dir)
    summary = build_phase(
        blueprint_path=Path(project_path),
        pattern_root=PATTERNS_ROOT,
        phase=phase,
        console=console,
    )
    _record_build_result(project_dir, history, turn, summary, f"phase {phase}")
    if summary.get("ok"):
        built = state.setdefault("built_phases", [])
        if phase not in built:
            built.append(phase)
        nxt = next_unbuilt_phase(
            state.get("patterns") or [], built,
        )
        if nxt:
            console.print(
                f"[green]Phase '{phase}' built and XSD-valid.[/green] "
                f"Next phase: [bold]{nxt}[/bold] — build it with "
                f"[bold]/build {nxt}[/bold], or 'done' to assemble."
            )
        else:
            console.print(
                f"[green]Phase '{phase}' built.[/green] All phases done — "
                f"type [bold]done[/bold] to assemble the full project."
            )
        return 0
    console.print(
        f"[yellow]Phase '{phase}' did not fully validate — "
        f"see the table above before moving on.[/yellow]"
    )
    return 1


def _resolve_module_target(
    state: dict, catalog, name: str,
) -> tuple[str, dict] | None:
    """Map a user-typed module name to ``(pattern_path, label_match)``.

    Walks the currently-resolved instances and matches ``name`` (case-
    insensitively) against any label variable (nwp_name, basin_name, ...).
    The returned ``label_match`` is a single-key dict suitable for
    :func:`build_from_blueprint.build_module`'s ``instance_match``.
    Returns None when no instance matches.
    """
    _resolve_patterns(state, catalog)
    name_l = name.strip().lower()
    for entry in state.get("patterns") or []:
        pat = entry.get("pattern", "")
        for inst in entry.get("instances") or []:
            if not isinstance(inst, dict):
                continue
            for k in _LABEL_VAR_KEYS:
                v = inst.get(k)
                if isinstance(v, str) and v.lower() == name_l:
                    return pat, {k: v}
    return None


def _module_list_text(state: dict, catalog) -> str:
    """Instance-level listing of the project, grouped by phase.

    Finer than ``/phases`` (which is phase-level): shows each module
    instance, its built status, and its editable variables so the user
    knows exactly what they can /set or /remove.
    """
    _resolve_patterns(state, catalog)
    plan = phase_plan(state.get("patterns") or [])
    if not plan:
        return (
            "No modules yet. Add one with e.g.  /add GFS  (import) or "
            "/add Liard uses raven  (basin), then  /build <name>."
        )
    built = set(state.get("built_modules") or [])
    built_phases = set(state.get("built_phases") or [])
    lines = ["Modules in this project (one per line):"]
    for entry in plan:
        ph = entry["phase"]
        lines.append(f"\n{ph} — {entry['label']}")
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
                mark = "(built)" if is_built else "(ready)"
                extras = []
                for vk in ("grid_resolution", "forecast_horizon_hours",
                           "model_adapter"):
                    if inst.get(vk):
                        extras.append(f"{vk}={inst[vk]}")
                if inst.get("parameters"):
                    extras.append(f"{len(inst['parameters'])} param(s)")
                extra_txt = f"  ({'; '.join(extras)})" if extras else ""
                lines.append(f"  {mark} {label}  ·{short}{extra_txt}")
    lines.append(
        "\nEdit: /add <name> · /remove <name> · /set <name> <var> <value>"
        "  ·  Build one: /build <name>"
    )
    return "\n".join(lines)


def _parse_slash_edit(op: str, rest: str) -> list[dict]:
    """Turn a slash-command tail into one or more edit dicts.

    ``op`` is add/remove/set. For add/remove, classify ``rest`` into
    import(s) or basin(s) by reusing the detector skills (with optional
    explicit ``import``/``basin`` prefixes). For set, split into
    target / variable / value.
    """
    rest = rest.strip()
    if op == "set":
        parts = rest.split(None, 2)
        if len(parts) < 3:
            return []
        target, variable, value = parts[0], parts[1], parts[2]
        return [{
            "op": "set", "target": target, "target_kind": "variable",
            "variable": variable, "value": value,
        }]

    # add / remove: allow an explicit kind prefix.
    forced_kind: str | None = None
    low = rest.lower()
    for prefix, kind in (("import ", "import"), ("imports ", "import"),
                         ("basin ", "basin"), ("basins ", "basin")):
        if low.startswith(prefix):
            forced_kind = kind
            rest = rest[len(prefix):].strip()
            break

    edits: list[dict] = []
    if forced_kind == "basin" or (forced_kind is None and
                                  detect_basins_with_adapters(rest)):
        pairs = detect_basins_with_adapters(rest)
        if pairs:
            for b in pairs:
                edits.append({"op": op, "target": b, "target_kind": "basin"})
            return edits
        # basin forced but no adapter parsed → bare basin name
        name = detect_basin(rest) or rest
        return [{"op": op, "target": {"basin_name": name},
                 "target_kind": "basin"}]

    imports = detect_imports(rest)
    if imports:
        for name in imports:
            edits.append({"op": op, "target": name, "target_kind": "import"})
        return edits

    # Fall back: treat each whitespace token as an import name. Unknown
    # names surface via the unmapped-import warning on resolve.
    for tok in rest.split():
        edits.append({"op": op, "target": tok, "target_kind": "import"})
    return edits


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
    _resolve_patterns(state, catalog)
    return note


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


def _run_module_build(
    state: dict, project_dir: Path, name: str, console: Console,
    history: list, turn: int,
) -> int:
    """Resolve a module name → write project.yaml → build just that module."""
    from runners.agent.build_from_blueprint import build_module

    catalog = build_pattern_catalog(PATTERNS_ROOT)
    target = _resolve_module_target(state, catalog, name)
    if target is None:
        console.print(
            f"[yellow]No module named '{name}' in the project.[/yellow]\n"
            + _module_list_text(state, catalog)
        )
        return 1
    pattern, match = target
    project_path = write_project(state, project_dir)
    summary = build_module(
        blueprint_path=Path(project_path),
        pattern_root=PATTERNS_ROOT,
        pattern=pattern,
        instance_match=match,
        console=console,
    )
    label = next(iter(match.values()))
    _record_build_result(project_dir, history, turn, summary, f"module {label}")
    if summary.get("ok"):
        built = state.setdefault("built_modules", [])
        key = f"{pattern}::{label}"
        if key not in built:
            built.append(key)
        console.print(
            f"[green]Module '{label}' built and XSD-valid.[/green] "
            f"Build another with [bold]/build <name>[/bold], or "
            f"[bold]/phases[/bold] to see the plan."
        )
        return 0
    console.print(
        f"[yellow]Module '{label}' did not fully validate — "
        f"see the table above.[/yellow]"
    )
    return 1


def _run_module_export(
    state: dict, project_dir: Path, name: str, console: Console,
    history: list, turn: int,
) -> int:
    """Export ONE module + only the files it depends on (closure walker).

    Builds the full project (so every declarer exists), identifies the
    module's own files, walks the dependency closure, and writes just
    that subset + a MANIFEST.md to ``generated/_export_<name>/``.
    """
    from runners.agent.build_from_blueprint import (
        build_from_blueprint, build_module,
    )
    from fews_agent.agent.module_export import (
        compute_closure, render_manifest, trim_dependency_files,
    )
    from fews_agent.validation.xsd import validate_xsd

    catalog = build_pattern_catalog(PATTERNS_ROOT)
    target = _resolve_module_target(state, catalog, name)
    if target is None:
        console.print(
            f"[yellow]No module named '{name}' in the project.[/yellow]\n"
            + _module_list_text(state, catalog)
        )
        return 1
    pattern, match = target
    project_path = Path(write_project(state, project_dir))

    # 1) Full build — produces every declarer (Parameters, Grids, idMaps...).
    console.print("[dim]Building full project to resolve dependencies…[/dim]")
    full = build_from_blueprint(
        blueprint_path=project_path, pattern_root=PATTERNS_ROOT, console=console,
    )
    output_root = Path(full["output_root"])
    _record_build_result(project_dir, history, turn, full, f"export {name} (full project)")

    # 2) Identify the module's own files (the closure seeds).
    mod = build_module(
        blueprint_path=project_path, pattern_root=PATTERNS_ROOT,
        pattern=pattern, instance_match=match, console=console,
    )
    seeds = [f["path"].replace("\\", "/") for f in mod.get("files", [])]

    # 3) Load the rendered tree + walk the closure.
    files: dict[str, str] = {}
    for p in output_root.rglob("*.xml"):
        rel = str(p.relative_to(output_root)).replace("\\", "/")
        if rel.startswith("_export_"):
            continue
        files[rel] = p.read_text(encoding="utf-8")
    result = compute_closure(files, seeds)

    # 3b) Trim each pulled-in dependency file to only the entries the module
    # references. An XSD safety net falls back to the full file if a trim
    # would produce invalid XML (never ship unvalidated output).
    trimmed = trim_dependency_files(files, result)
    for rel in list(trimmed):
        ok, msg = validate_xsd(trimmed[rel].encode("utf-8"))
        if not ok:
            console.print(
                f"[yellow]Trim of {rel} failed XSD ({msg}); "
                f"keeping the full file.[/yellow]"
            )
            del trimmed[rel]

    # 4) Write the subset + manifest.
    export_dir = output_root / f"_export_{name}"
    for rel in result.needed:
        dst = export_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(trimmed.get(rel, files[rel]), encoding="utf-8")
    (export_dir / "MANIFEST.md").write_text(
        render_manifest(result, name, trimmed=set(trimmed)), encoding="utf-8",
    )

    deps = [f for f in result.needed if f not in result.seeds]
    if result.external:
        ext_line = "".join(f"\n  - {e}" for e in result.external)
    else:
        ext_line = " (none — self-contained)"
    console.print(Panel(
        f"[bold]{len(result.needed)}[/bold] file(s) "
        f"= {len(result.seeds)} module + {len(deps)} dependency; "
        f"[bold]{len(result.chrome)}[/bold] chrome file(s) excluded.\n"
        f"External refs to satisfy in your target config: "
        f"[bold]{len(result.external)}[/bold]" + ext_line
        + f"\n[dim]Written to {export_dir} (+ MANIFEST.md)[/dim]",
        title=f"Module export: {name}", border_style="green",
    ))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--message", required=True)
    parser.add_argument("--finalize", action="store_true")
    parser.add_argument("--model", default="qwen2.5:7b-instruct")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Print engine state diagnostics under each reply.")
    args = parser.parse_args(argv)

    console = Console()
    project_dir = _resolve_project_dir(args.project_name)
    state, history = _load_state(project_dir, args.project_name)
    catalog = build_pattern_catalog(PATTERNS_ROOT)
    turn = len([h for h in history if h["role"] == "user"]) + 1

    history.append({"role": "user", "message": args.message})
    _append_log(project_dir, turn, "user", args.message, None)

    cmd = args.message.lower().strip()

    # Deterministic special commands.
    if cmd in {"done", "/done", "quit", "force-done", "/force-done"}:
        force = cmd in {"force-done", "/force-done"}
        intent = INTENTS.get(state.get("intent") or "")
        if intent and not is_intent_ready(intent, state.get("slots", {})):
            unfilled = next_unfilled_question(intent, state.get("slots", {}))
            console.print(
                f"[yellow]Project not ready:[/yellow] still need to "
                f"answer — {unfilled}"
            )
            if not args.finalize:
                _save(project_dir, state, history)
                return 1
        existing_warnings = list(state.get("warnings") or [])
        if existing_warnings and not force and not args.finalize:
            note = (
                f"{len(existing_warnings)} unresolved warning(s) — "
                f"refusing to write project.yaml.\n\n"
                + "\n".join(f"  - {w}" for w in existing_warnings)
                + "\n\nType 'force-done' to write anyway, or send another "
                  "message to address them."
            )
            console.print(f"[yellow]WARNING: {note}[/yellow]")
            history.append({"role": "agent", "message": note})
            _append_log(project_dir, turn, "agent", note, "done refused")
            _save(project_dir, state, history)
            return 2
        _resolve_patterns(state, catalog)
        project_path = write_project(state, project_dir)
        msg = f"Wrote {project_path}"
        if force and existing_warnings:
            msg += f"  (forced — {len(existing_warnings)} warning(s) ignored)"
        console.print(f"[green]{msg}[/green]")
        _save(project_dir, state, history)
        return 0

    # Module-by-module flow: show the phase plan.
    if cmd in {"/phases", "phases", "/plan", "plan", "/modules", "modules"}:
        reply = _phase_plan_text(state, catalog)
        history.append({"role": "agent", "message": reply})
        _append_log(project_dir, turn, "agent", reply, "phase plan")
        _save(project_dir, state, history)
        console.print(f"\n[bold magenta]agent[/bold magenta]: {reply}")
        return 0

    # Instance-level listing (finer than /phases).
    if cmd in {"/list", "list", "/show", "show"}:
        reply = _module_list_text(state, catalog)
        history.append({"role": "agent", "message": reply})
        _append_log(project_dir, turn, "agent", reply, "module list")
        _save(project_dir, state, history)
        console.print(f"\n[bold magenta]agent[/bold magenta]: {reply}")
        return 0

    # Explicit edits: /add, /remove (/drop), /set. Deterministic — mutate
    # slots then re-resolve. No LLM, no confirmation (the command IS the
    # confirmation; the engine-proposed yes/no flow stays for ambiguous
    # NL-driven removals only).
    if cmd.startswith(("/add ", "/remove ", "/drop ", "/set ")):
        verb = args.message.strip().split(None, 1)[0].lstrip("/").lower()
        op = "remove" if verb == "drop" else verb
        rest = args.message.strip().split(None, 1)[1].strip()
        edits = _parse_slash_edit(op, rest)
        if not edits:
            console.print(
                "[yellow]Couldn't parse that edit. Usage: "
                "/add <name> · /remove <name> · /set <name> <var> "
                "<value>[/yellow]"
            )
            _save(project_dir, state, history)
            return 1
        notes = [apply_edit_action(state, e, catalog) for e in edits]
        reply = "\n".join(notes)
        history.append({"role": "agent", "message": reply})
        _append_log(project_dir, turn, "agent", reply, f"edit:{op}")
        _save(project_dir, state, history)
        console.print(f"\n[bold magenta]agent[/bold magenta]: {reply}")
        console.print("\n" + _module_list_text(state, catalog))
        return 0

    # Module-by-module flow: build ONE capability group (phase).
    #   /build imports   /build model   /build visualize   (or /build-phase X)
    # Bare "/build" builds the next unbuilt phase.
    if cmd == "/build" or cmd.startswith(("/build ", "/build-phase ",
                                          "build phase ")):
        if cmd == "/build":
            _resolve_patterns(state, catalog)
            phase = next_unbuilt_phase(
                state.get("patterns") or [], state.get("built_phases"),
            )
            if phase is None:
                console.print(
                    "[yellow]No unbuilt phases — every resolved module is "
                    "built. Type 'done' to assemble the full project.[/yellow]"
                )
                _save(project_dir, state, history)
                return 0
        else:
            token = args.message.strip().split(None, 1)[1].strip()
            phase = normalize_phase(token)
            if phase is None:
                # Not a phase. For a bare "/build <token>" treat the token
                # as a single module name (e.g. /build GFS). The explicit
                # phase-only forms (/build-phase, "build phase") still error.
                if cmd.startswith("/build ") and "-phase" not in cmd:
                    rc = _run_module_build(
                        state, project_dir, token, console, history, turn,
                    )
                    _save(project_dir, state, history)
                    return rc
                console.print(
                    f"[yellow]Unknown phase '{token}'. Valid phases: "
                    f"{', '.join(PHASE_ORDER)}.[/yellow]"
                )
                _save(project_dir, state, history)
                return 1
        rc = _run_phase_build(
            state, project_dir, phase, console, history, turn,
        )
        _save(project_dir, state, history)
        return rc

    # Export ONE module + only its dependencies (closure walker), to
    # `generated/_export_<name>/` + a MANIFEST.md. For dropping a single
    # module into an existing config without the project chrome.
    if cmd.startswith("/export "):
        token = args.message.strip().split(None, 1)[1].strip()
        rc = _run_module_export(
            state, project_dir, token, console, history, turn,
        )
        _save(project_dir, state, history)
        return rc

    pending = state.get("_pending_removals") or []
    if pending and cmd in {"yes", "y", "confirm", "ok"}:
        for r in pending:
            apply_removal(state, r["pattern"])
        state["_pending_removals"] = []
        _save(project_dir, state, history)
        console.print(f"[green]Removed {len(pending)} pattern(s).[/green]")
        return 0
    if pending and cmd in {"no", "n", "cancel"}:
        state["_pending_removals"] = []
        _save(project_dir, state, history)
        console.print("[dim]Cancelled removal.[/dim]")
        return 0

    # /edit <file>: enter per-yaml interactive edit mode.
    if cmd.startswith("/edit "):
        from fews_agent.agent import edit_modes
        target_file = args.message.strip().split(None, 1)[1].strip()
        reply, done = edit_modes.start(state, target_file, project_dir)
        if done:
            state.pop("_editing", None)
        history.append({"role": "agent", "message": reply})
        _append_log(project_dir, turn, "agent", reply, "edit-mode start")
        _save(project_dir, state, history)
        console.print(f"\n[bold magenta]agent[/bold magenta]: {reply}")
        return 0

    # /cancel-edit: abort an active edit session without writing.
    if cmd in {"/cancel-edit", "cancel-edit", "/abort-edit"}:
        if state.get("_editing"):
            state.pop("_editing", None)
            console.print("[dim]Edit session cancelled.[/dim]")
        else:
            console.print("[dim]No active edit session.[/dim]")
        _save(project_dir, state, history)
        return 0

    # If an edit session is active, route this turn to its handler.
    if state.get("_editing"):
        from fews_agent.agent import edit_modes
        reply, done = edit_modes.advance_turn(state, args.message, project_dir)
        if done:
            state.pop("_editing", None)
        history.append({"role": "agent", "message": reply})
        _append_log(project_dir, turn, "agent", reply, "edit-mode")
        _save(project_dir, state, history)
        console.print(f"\n[bold magenta]agent[/bold magenta]: {reply}")
        return 0

    # Phase 1: skills.
    skill_results = extract_skills(args.message)

    # Phase 2: intent classification (only if no intent yet).
    notes: list[str] = []
    llm_picked: str | None = None
    llm_entities: dict | None = None
    chosen_intent: str | None = state.get("intent")

    if state.get("intent") is None:
        provider = _resolve_provider(args.model)
        try:
            cls = classify_intent(
                args.message, skill_results, provider=provider,
            )
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

        # Validate LLM pick against known intents; fall back to heuristic.
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

    # Deterministic intent override — runs on EVERY turn (turn 1 included),
    # AFTER classification. An explicit intent-naming phrase forces the
    # intent over whatever the LLM/heuristic picked, so "no basin model"
    # deterministically yields build_data_import_only on the first turn
    # rather than relying on a 7B model (and surviving classify_intent's
    # default-to-forecasting demotion). On a later turn this is the
    # mid-conversation re-classification that recovers from an early miss.
    _forced = forced_intent_override(args.message, state.get("intent"))
    if _forced:
        notes.append(f"intent override: {state.get('intent')} → {_forced}")
        state["intent"] = _forced
        state["patterns"] = []  # resolver will rebuild from slots
        chosen_intent = _forced

    # Phase 2.5: natural-language edits (remove a module / override a
    # scalar). Verb-gated and target-required, so descriptive prose never
    # parses as an edit. Runs AFTER intent + LLM-entity merge but BEFORE
    # the additive merge: applied edits mutate slots immediately, then the
    # just-removed targets are stripped from skill_results so the additive
    # merge below cannot re-add them on the same turn. Slash /add /remove
    # /set (handled earlier) stay the unambiguous fallback.
    recent_edit_note: str | None = None  # per-turn; stale notes must not leak
    edit_action = detect_edit_action(args.message)
    if edit_action and edit_action.get("edits"):
        applied_notes: list[str] = []
        for e in edit_action["edits"]:
            note = apply_edit_action(state, e, catalog)
            notes.append(f"edit: {note}")
            applied_notes.append(note)
        # Re-add suppression: drop removed targets from skill_results so the
        # additive merge doesn't immediately resurrect them.
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
        # Surface this turn's edits so the reply layer can acknowledge
        # them as already-done. Per-turn only — never persisted, so a
        # later non-edit turn can't re-acknowledge a stale edit.
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
                # Dict items dedup on equality of dict contents.
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

    # Sync settings: geoDatum slot → Locations.geoDatum.
    if slots.get("geoDatum"):
        state.setdefault("singleton_seeds", {}).setdefault(
            "Locations", {}
        )["geoDatum"] = slots["geoDatum"]

    # Sync settings: region slot → Locations.region. This populates the
    # REGION property in sa_global.Properties so FEWS resolves $REGION$
    # at startup, and lets the build path override the bundled
    # spatialDisplay defaultExtent if the region has a known bbox.
    if slots.get("region"):
        state.setdefault("singleton_seeds", {}).setdefault(
            "Locations", {}
        )["region"] = slots["region"]

    # Free-form bbox parsed from prose (e.g. "from 5N to 10S, 15W to
    # 5E") — stored as a 4-tuple so the runner can crop NWP grids and
    # rewrite the SpatialDisplay defaultExtent without needing a
    # gazetteer match. Stored as a list for yaml round-trip.
    if slots.get("custom_bbox"):
        bbox = list(slots["custom_bbox"])
        state.setdefault("singleton_seeds", {}).setdefault(
            "Locations", {}
        )["regionBbox"] = bbox

    # Cross-turn promotion: if singular basin_name + model_adapter were
    # filled in different turns, synthesise the canonical `basins` pair.
    # Without this, `is_intent_ready` blocks indefinitely because the
    # skill only emits `basins` when both appear in the SAME message.
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

    # Sync missing_data: locations_source=csv → reminder for locations.csv.
    if slots.get("locations_source") == "csv":
        if "locations.csv" not in state.get("missing_data", []):
            state.setdefault("missing_data", []).append("locations.csv")

    # Phase 4: resolve patterns from slots.
    patterns_before = {p["pattern"] for p in state.get("patterns", [])}
    _resolve_patterns(state, catalog)
    new_patterns = [
        p["pattern"] for p in state.get("patterns", [])
        if p["pattern"] not in patterns_before
    ]

    # Phase 4.25: warn loudly when a mentioned input has no pattern mapping.
    # The LLM often sees more than skills + resolver can map (e.g. it picks
    # up HARMONIE/ICON but the library only has patterns for ECCC + NOAA
    # NWPs). Surface the gap so the configurator isn't surprised by silent
    # drops downstream.
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

    # Suspicious basin names — single-token CAPITALISED words that are
    # actually English sentence starters ("We", "It", "The", ...).
    # The regex extractor in project_intents now filters these too, so
    # this branch only catches LLM entity-extraction leaks.
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

    # Mentioned data_types that the parameter mapper can't translate to a
    # FEWS parameterId. Without this, the resolver drops them silently
    # (stderr only) and the user gets the pattern's default subset (PC.nwp
    # + TA.nwp) — wrong output, no signal.
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
    inputs_dir = project_dir / "inputs"
    input_scan = scan_inputs(inputs_dir)
    input_status = compute_input_status(state.get("intent"), input_scan, slots)

    # Phase 5: LLM composes the user-facing reply.
    intent = INTENTS.get(state.get("intent") or "")
    next_q = next_unfilled_question(intent, slots) if intent else None
    ready = bool(intent) and is_intent_ready(intent, slots)
    provider = _resolve_provider(args.model)
    agent_msg = compose_reply(
        user_message=args.message,
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
    history.append({"role": "agent", "message": agent_msg})
    _append_log(project_dir, turn, "agent", agent_msg, None, internals=internals)
    _save(project_dir, state, history)

    console.print(f"\n[bold magenta]agent[/bold magenta]: {agent_msg}")

    # Module-by-module guidance. The system builds one capability group
    # (phase) at a time — imports → process → model → visualize — rather
    # than generating the whole project in one shot. After each turn,
    # point the user at the next phase to build. This is deterministic
    # (not LLM-composed) so the guidance never drifts.
    _plan = phase_plan(state.get("patterns") or [])
    if _plan:
        _built = state.get("built_phases") or []
        _nxt = next_unbuilt_phase(state.get("patterns") or [], _built)
        if _nxt:
            console.print(
                f"\n[cyan]Next module phase:[/cyan] [bold]{_nxt}[/bold] — "
                f"{PHASE_LABELS[_nxt]}.\n"
                f"[dim]Build just this phase now with[/dim] "
                f"[bold]/build {_nxt}[/bold][dim], or[/dim] "
                f"[bold]/phases[/bold] [dim]to see the full plan. "
                f"One capability at a time; 'done' assembles the whole "
                f"project at the end.[/dim]"
            )
        else:
            console.print(
                "\n[cyan]All resolved module phases are built.[/cyan] "
                "[dim]Type[/dim] [bold]done[/bold] [dim]to assemble the "
                "full project (singletons, derivers, cross-file "
                "validation).[/dim]"
            )
    if args.verbose:
        console.print(
            f"\n[dim]turn={turn}  intent={state.get('intent')}  "
            f"slots_filled={sum(1 for v in slots.values() if v)}  "
            f"patterns={len(state.get('patterns', []))}  ready={ready}[/dim]"
        )

    if args.finalize:
        project_path = write_project(state, project_dir)
        console.print(f"[green]Wrote {project_path}[/green]")

    return 0


if __name__ == "__main__":
    sys.exit(main())
