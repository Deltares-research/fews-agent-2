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
    apply_removal,
    build_pattern_catalog,
    initial_state,
    write_project,
)
from fews_agent.agent.project_intents import (
    INTENTS,
    detect_basin,
    detect_basins_with_adapters,
    detect_imports,
    is_intent_ready,
    next_unfilled_question,
)
from fews_agent.agent.phases import (
    PHASE_LABELS,
    PHASE_ORDER,
    next_unbuilt_phase,
    normalize_phase,
    phase_plan,
)
from fews_agent.agent import module_focus
from fews_agent.agent.turn_engine import (
    _IMPORT_LABEL_KEYS,
    apply_disambiguation_answer,
    apply_edit_action,
    resolve_patterns as _resolve_patterns,
    run_turn_pipeline,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PATTERNS_ROOT = REPO_ROOT / "patterns"
OUTPUT_ROOT = REPO_ROOT / "projects"

# Instance-variable keys that name a module. ``_IMPORT_LABEL_KEYS`` (the
# import-labelling group, imported from turn_engine) plus basin_name form the
# full set used to resolve a user-typed module name (e.g. "GFS", "Liard")
# back to its pattern instance.
_LABEL_VAR_KEYS = _IMPORT_LABEL_KEYS + ("basin_name",)


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


def _run_module_operation(
    state: dict, focus, message: str, project_dir: Path, console: Console,
    history: list, turn: int, catalog, model: str,
) -> int:
    """Module-mode prose turn: extract ONE operation and apply it.

    When a module is in focus and the user types plain language (not a slash
    command), the LLM extracts a single validated operation and we route it:
    add/set → merge fields into slots + resolve; remove → removal edits;
    select_module → switch focus; build/list → the existing handlers. Values
    the catalog validation dropped are surfaced loudly, never silently
    applied.
    """
    from fews_agent.agent.extractor import extract_operation
    from fews_agent.agent.turn_engine import (
        apply_edit_action,
        apply_extracted_fields,
        extracted_removal_edits,
    )

    provider = _resolve_provider(model)
    op = extract_operation(message, focus_module=focus, provider=provider)

    # build / list route straight to the existing scoped handlers.
    if op.action == "build":
        rc = _run_module_scope_build(
            state, focus, project_dir, console, history, turn,
        )
        _save(project_dir, state, history)
        return rc
    if op.action == "list":
        reply = _module_list_text(state, catalog)
        _emit(project_dir, state, history, turn, reply, "module op: list", console)
        return 0

    if op.action == "select_module" and op.module:
        _module, reply = module_focus.set_focus(state, op.module)
        _emit(project_dir, state, history, turn, reply, "module op: select", console)
        return 0

    if op.action == "remove":
        edits = extracted_removal_edits(op)
        if edits:
            notes = [apply_edit_action(state, e, catalog) for e in edits]
            reply = "\n".join(notes)
        else:
            reply = "Nothing recognised to remove."
    else:  # add / set / none
        note, new_patterns = apply_extracted_fields(state, op, catalog)
        reply = note

    if op.dropped:
        reply += (
            "\n\n[!] Ignored (not in the catalog, so not applied): "
            + ", ".join(op.dropped)
            + ". Rephrase with a known name if you meant something valid."
        )

    _emit(
        project_dir, state, history, turn, reply,
        f"module op: {op.action}", console,
    )
    console.print("\n" + _module_list_text(state, catalog))
    return 0


def _emit(
    project_dir: Path, state: dict, history: list, turn: int,
    reply: str, note: str, console: Console,
) -> None:
    """Append an agent reply to history + transcript, save, and print."""
    history.append({"role": "agent", "message": reply})
    _append_log(project_dir, turn, "agent", reply, note)
    _save(project_dir, state, history)
    console.print(f"\n[bold magenta]agent[/bold magenta]: {reply}")


def _run_module_scope_build(
    state: dict, module, project_dir: Path, console: Console,
    history: list, turn: int,
) -> int:
    """Build every capability phase the focused FEWS-folder module owns.

    A folder-module (``processing``, ``display``) maps to one or more
    capability phases; this builds each that has resolved content, reusing
    the tested per-phase build. View/deriver modules (filters, topology,
    idmap, system, root) aren't built on their own — they come from inputs
    or final assembly — so this reports that instead.
    """
    from fews_agent.agent.modules import module_for_pattern

    catalog = build_pattern_catalog(PATTERNS_ROOT)
    if not module.phases:
        console.print(
            f"[yellow]The '{module.label}' module isn't built on its "
            f"own.[/yellow] It's produced from your inputs or during final "
            f"assembly — type [bold]done[/bold] to assemble the project."
        )
        return 0
    _resolve_patterns(state, catalog)
    plan = phase_plan(state.get("patterns") or [])
    target_phases = [
        e["phase"] for e in plan
        if e["patterns"]
        and module_for_pattern(e["patterns"][0]["pattern"]) == module.key
    ]
    if not target_phases:
        console.print(
            f"[yellow]Nothing resolved for the '{module.label}' module "
            f"yet.[/yellow] Add something first (e.g. [bold]/add GFS[/bold]), "
            f"then [bold]/build[/bold]."
        )
        return 0
    console.print(
        f"[cyan]Building the '{module.label}' module "
        f"({len(target_phases)} phase(s): {', '.join(target_phases)}).[/cyan]"
    )
    rc = 0
    for ph in target_phases:
        rc |= _run_phase_build(state, project_dir, ph, console, history, turn)
    return rc


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

    # Pending intent disambiguation: a prior turn asked "imports only or a
    # full forecasting project?" and is awaiting the answer. The shared helper
    # consumes this turn's message as that answer (commits + latches on a
    # clear choice, else clears the flag so the Phase 3.5 gate re-evaluates).
    apply_disambiguation_answer(state, args.message)

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

    # Module-mode: list the FEWS-folder modules you can build one at a time.
    if cmd in {"/modules", "modules"}:
        reply = module_focus.modules_overview()
        cur = state.get("current_module")
        if cur:
            reply += f"\n\nIn focus now: {cur}."
        history.append({"role": "agent", "message": reply})
        _append_log(project_dir, turn, "agent", reply, "module overview")
        _save(project_dir, state, history)
        console.print(f"\n[bold magenta]agent[/bold magenta]: {reply}")
        return 0

    # Module-mode: put ONE module in focus. Bare "/module" reports the
    # current focus; "/module <name>" selects it and prints its focus card.
    if cmd == "/module" or cmd.startswith("/module "):
        if cmd == "/module":
            cur = module_focus.get_focus(state)
            reply = (
                module_focus.focus_card(state, cur) if cur
                else "No module in focus. Pick one with  /module <name>  "
                     "(see  /modules  for the list)."
            )
        else:
            token = args.message.strip().split(None, 1)[1].strip()
            module, reply = module_focus.set_focus(state, token)
        history.append({"role": "agent", "message": reply})
        _append_log(project_dir, turn, "agent", reply, "module focus")
        _save(project_dir, state, history)
        console.print(f"\n[bold magenta]agent[/bold magenta]: {reply}")
        return 0

    # Module-by-module flow: show the capability phase plan (finer build
    # groups WITHIN the processing/display modules).
    if cmd in {"/phases", "phases", "/plan", "plan"}:
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
        # Module-mode: reject an operation the focused module doesn't allow
        # (e.g. /add while focused on a view-only module like filters).
        focus = module_focus.get_focus(state)
        if focus is not None and not focus.supports(op):
            console.print(
                f"[yellow]The '{focus.label}' module doesn't support "
                f"'{op}'.[/yellow] Its operations: "
                f"{', '.join(focus.operations)}. "
                f"Switch focus with [bold]/module <name>[/bold] first."
            )
            _save(project_dir, state, history)
            return 1
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
            # Module-mode: a bare /build with a module in focus builds THAT
            # module (its capability phases), not the next unbuilt phase.
            focus = module_focus.get_focus(state)
            if focus is not None:
                rc = _run_module_scope_build(
                    state, focus, project_dir, console, history, turn,
                )
                _save(project_dir, state, history)
                return rc
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

    # Module-mode prose path: when a module is in focus, a free-form message
    # is ONE operation on that module. Extract it (LLM), validate against the
    # catalog, apply, and reply — instead of the whole-project intent
    # pipeline. Falls through to the pipeline when no module is in focus.
    _focus = module_focus.get_focus(state)
    if _focus is not None:
        return _run_module_operation(
            state, _focus, args.message, project_dir, console, history, turn,
            catalog, args.model,
        )

    # Phases 1–5 run in the shared turn engine (fews_agent/agent/turn_engine).
    # The driver resolves the provider and owns persistence + console output;
    # the engine mutates `state` and returns the reply + diagnostics.
    provider = _resolve_provider(args.model)
    result = run_turn_pipeline(
        state, args.message, catalog,
        provider=provider,
        inputs_dir=project_dir / "inputs",
    )
    history.append({"role": "agent", "message": result.agent_message})
    _append_log(
        project_dir, turn, "agent", result.agent_message,
        result.log_note, internals=result.internals,
    )
    _save(project_dir, state, history)
    console.print(
        f"\n[bold magenta]agent[/bold magenta]: {result.agent_message}"
    )

    # On a disambiguation short-circuit the gate asked a question and resolved
    # nothing — skip the module-guidance / verbose / finalise tail.
    if result.short_circuit:
        return 0

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
        _slots = state.get("slots", {})
        console.print(
            f"\n[dim]turn={turn}  intent={state.get('intent')}  "
            f"slots_filled={sum(1 for v in _slots.values() if v)}  "
            f"patterns={len(state.get('patterns', []))}  ready={result.ready}[/dim]"
        )

    if args.finalize:
        project_path = write_project(state, project_dir)
        console.print(f"[green]Wrote {project_path}[/green]")

    return 0


if __name__ == "__main__":
    sys.exit(main())
