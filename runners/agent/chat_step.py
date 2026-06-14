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

from fews_agent.agent.project_chat import (
    apply_removal,
    build_pattern_catalog,
    initial_state,
    write_project,
)
from fews_agent.agent.project_intents import (
    ENGLISH_WORD_BLOCKLIST,
    INTENTS,
    classify_intent,
    compose_reply,
    compute_input_status,
    extract_skills,
    fill_slots_from_text,
    heuristic_intent_from_slots,
    is_intent_ready,
    next_unfilled_question,
    scan_inputs,
)
from fews_agent.agent.providers.ollama_provider import OllamaProvider

REPO_ROOT = Path(__file__).resolve().parents[2]
PATTERNS_ROOT = REPO_ROOT / "patterns"
OUTPUT_ROOT = REPO_ROOT / "projects"


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
            for k, v in llm_entities.items():
                if k not in skill_results or skill_results[k] is None:
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
            for k in ("nwp_name", "source_name", "wsc_variant",
                      "snow_source", "template_name"):
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

    state["warnings"] = warnings

    # Phase 4.5: scan the inputs/ directory and compute presence/missing.
    inputs_dir = project_dir / "inputs"
    input_scan = scan_inputs(inputs_dir)
    input_status = compute_input_status(state.get("intent"), input_scan)

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
