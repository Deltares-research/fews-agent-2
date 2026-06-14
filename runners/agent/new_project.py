"""Conversational front-end: prose → project.yaml.

Drives a multi-turn dialogue with qwen2.5:7b (via Ollama) to author a
``project.yaml`` from a configurator's project description. The agent
matches prose to patterns from the library, asks clarifying questions
when needed, and stops when the project is well-defined enough.

Usage::

    # Interactive mode:
    python -m runners.agent.new_project --project-name liard-flood

    # Scripted mode (test the LLM with a sequence of canned answers):
    python -m runners.agent.new_project --project-name liard-flood \\
        --answers "Forecast Liard with HRDPS imports;Raven;done"

    # Output:
    #   projects/liard-flood/liard-flood_<datetime>/project.yaml
    #   projects/liard-flood/liard-flood_<datetime>/_conversation.md
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from fews_agent.agent.project_chat import (
    apply_updates,
    build_pattern_catalog,
    initial_state,
    propose_updates,
    write_project,
)
from fews_agent.agent.providers.ollama_provider import OllamaProvider

REPO_ROOT = Path(__file__).resolve().parents[2]
PATTERNS_ROOT = REPO_ROOT / "patterns"
OUTPUT_ROOT = REPO_ROOT / "projects"

MAX_TURNS = 8


def _log_turn(
    log_path: Path,
    turn: int,
    role: str,
    message: str,
    note: str | None = None,
) -> None:
    """Append a turn to the conversation log."""
    block = [f"## Turn {turn} ({role})"]
    if note:
        block.append(f"_{note}_")
    block.append("")
    block.append(message)
    block.append("")
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(block) + "\n")


def run_chat(
    project_name: str,
    output_dir: Path,
    *,
    initial_prose: str | None = None,
    canned_answers: list[str] | None = None,
    model: str = "qwen2.5:7b-instruct",
    console: Console | None = None,
) -> dict:
    """Run the multi-turn dialogue. Writes project.yaml + conversation log."""
    if console is None:
        console = Console()

    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "_conversation.md"
    log_path.write_text(
        f"# Conversation: {project_name}\n"
        f"Created: {datetime.now().isoformat(timespec='seconds')}\n\n",
        encoding="utf-8",
    )

    console.print(Panel(
        f"[bold]New project: {project_name}[/bold]\n"
        f"[dim]output: {output_dir}[/dim]\n"
        f"[dim]model: {model}[/dim]",
        border_style="cyan",
    ))

    catalog = build_pattern_catalog(PATTERNS_ROOT)
    console.print(f"[dim]Loaded {len(catalog)} patterns from catalog.[/dim]")

    from fews_agent.agent.providers.factory import get_provider_or_ollama
    provider = get_provider_or_ollama(model)
    state = initial_state(project_name)
    history: list[dict[str, str]] = []

    canned = list(canned_answers or [])
    canned_idx = 0

    for turn in range(1, MAX_TURNS + 1):
        # Get user message.
        if turn == 1 and initial_prose:
            user_msg = initial_prose
            console.print(f"\n[bold cyan]you[/bold cyan] [dim](initial)[/dim]: "
                          f"{user_msg}")
        elif canned_idx < len(canned):
            user_msg = canned[canned_idx]
            canned_idx += 1
            console.print(f"\n[bold cyan]you[/bold cyan]: {user_msg}")
        else:
            try:
                user_msg = input("\nyou: ").strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\n[yellow]Interrupted.[/yellow]")
                break
            if not user_msg:
                continue

        history.append({"role": "user", "message": user_msg})
        _log_turn(log_path, turn, "user", user_msg)

        if user_msg.lower() in {"done", "/done", "quit", "exit"}:
            console.print("[dim]User said done — writing project.yaml.[/dim]")
            break

        # Call qwen for an update + next question.
        try:
            response = propose_updates(
                state=state,
                history=history,
                user_message=user_msg,
                catalog=catalog,
                provider=provider,
            )
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]LLM call failed: {exc}[/red]")
            _log_turn(log_path, turn, "agent", "(LLM call failed)",
                      note=str(exc))
            break

        notes = apply_updates(state, response, catalog)

        # Multi-turn guard: qwen2.5:7b tends to mark ready_to_write=true
        # on the first turn even when the project is incomplete. Force
        # at least one follow-up turn unless the user explicitly says
        # "done" or the response includes no meaningful question and
        # state has both an import and a model pattern.
        if turn == 1 and response.get("ready_to_write"):
            response["ready_to_write"] = False
            if not response.get("next_question"):
                response["next_question"] = (
                    "Is there anything else you want to add (more imports, "
                    "stations, parameters)? Type 'done' to finalise."
                )
            notes.append("forced follow-up (turn 1)")

        agent_summary = _format_agent_summary(state, response, notes)
        console.print(f"\n[bold magenta]agent[/bold magenta]: {agent_summary}")
        _log_turn(log_path, turn, "agent", agent_summary,
                  note=response.get("reasoning") or None)
        history.append({"role": "agent", "message": agent_summary})

        if response.get("ready_to_write") and state.get("patterns"):
            console.print(
                "[green]Agent says project is ready to write.[/green]"
            )
            break

    # Write project.yaml at the end (whatever state we have).
    project_path = write_project(state, output_dir)
    console.print(Panel(
        f"[bold]Wrote:[/bold] {project_path}\n"
        f"[bold]Patterns:[/bold] {len(state.get('patterns', []))}\n"
        f"[bold]Missing data hints:[/bold] "
        f"{', '.join(state.get('missing_data', [])) or '(none)'}\n"
        f"[bold]Conversation log:[/bold] {log_path}\n\n"
        f"Next: drop your CSVs / yamls into {output_dir}/inputs/, then run:\n"
        f"  python -m runners.agent.build_from_blueprint --blueprint "
        f"{project_path}",
        title="Done", border_style="green",
    ))

    return {
        "project_path": str(project_path),
        "log_path": str(log_path),
        "patterns": len(state.get("patterns", [])),
        "missing_data": state.get("missing_data", []),
        "state": state,
    }


def _format_agent_summary(
    state: dict, response: dict, notes: list[str],
) -> str:
    """Build the agent's user-facing message for one turn."""
    parts = []
    added = response.get("patterns_to_add") or []
    if added:
        parts.append(
            f"matched {len(added)} pattern(s): "
            + ", ".join(p["pattern"].split("/")[-1] for p in added)
        )
    if notes:
        parts.append("notes: " + "; ".join(notes))
    if response.get("missing_data_to_add"):
        parts.append(
            f"data needed: {', '.join(response['missing_data_to_add'])}"
        )
    next_q = response.get("next_question")
    if next_q:
        parts.append(f"\n→ {next_q}")
    elif response.get("ready_to_write"):
        parts.append("\n→ ready to write project.yaml.")
    return "  ".join(parts) if parts else "(no update)"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project-name", required=True)
    parser.add_argument(
        "--initial-prose", default=None,
        help="If set, used as the first user message.",
    )
    parser.add_argument(
        "--answers", default=None,
        help=(
            "Semicolon-separated canned answers (for testing). "
            "First answer is the initial prose."
        ),
    )
    parser.add_argument(
        "--model", default="qwen2.5:7b-instruct",
    )
    args = parser.parse_args(argv)

    # Each new_project run creates a fresh datetime-stamped instance,
    # so per-project history is preserved across iterations.
    dt = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    output_dir = OUTPUT_ROOT / args.project_name / f"{args.project_name}_{dt}"

    canned = None
    initial = args.initial_prose
    if args.answers:
        all_answers = [a.strip() for a in args.answers.split(";") if a.strip()]
        if all_answers:
            initial = initial or all_answers[0]
            canned = all_answers[1:]

    summary = run_chat(
        project_name=args.project_name,
        output_dir=output_dir,
        initial_prose=initial,
        canned_answers=canned,
        model=args.model,
    )
    return 0 if summary.get("patterns") else 1


if __name__ == "__main__":
    sys.exit(main())
