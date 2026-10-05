"""One-shot ReAct run: natural-language request -> FEWS config tree.

    python -m runners.react.run_react --project gfs_demo \
        --prompt "Configure a NOAA GFS import for ..."

The loop drives the deterministic writer through tools; this runner owns
all I/O: session-dir layout (same as the chat shells, so sessions are
inspectable side by side), console progress lines (ASCII only — Windows
cp1252 consoles), and the per-run ``react_log.jsonl`` event log.

Interactive/chat mode is deliberately deferred — one-shot is the v1
contract (the oracle is a zero-interaction prompt).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

from fews_agent.agent.providers.factory import get_provider  # noqa: E402
from fews_agent.react import prompts  # noqa: E402
from fews_agent.react.context import ToolContext  # noqa: E402
from fews_agent.react.loop import run_react  # noqa: E402
from fews_agent.react.tools import build_registry  # noqa: E402
from fews_agent.react.tools.validate_tools import VALIDATE_PROJECT  # noqa: E402

PROJECTS_ROOT = REPO_ROOT / "projects"


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(REPO_ROOT / ".env", override=False)


def _safe_name(name: str) -> str:
    cleaned = "".join(
        c if (c.isalnum() or c in "-_.") else "-" for c in str(name).strip()
    )
    return cleaned or "project"


def new_session_dir(name: str, root: Path | None = None) -> Path:
    """Mint projects/<name>/<name>_<YYYY-MM-DD_HHMMSS>/ (chat-shell layout,
    replicated from app/chatter.py which we can't import — Streamlit).
    ``root`` defaults to the module-level PROJECTS_ROOT (resolved at call
    time so tests can monkeypatch it)."""
    safe = _safe_name(name)
    parent = (root or PROJECTS_ROOT) / safe
    parent.mkdir(parents=True, exist_ok=True)
    dt = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out = parent / f"{safe}_{dt}"
    n = 2
    while out.exists():  # two runs in the same second
        out = parent / f"{safe}_{dt}_{n}"
        n += 1
    out.mkdir(parents=True, exist_ok=True)
    return out


def _result_digest(content: str) -> str:
    """One console-friendly line from a tool-result JSON string."""
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return content[:120]
    if isinstance(data, dict):
        if "error" in data:
            return "ERROR " + str(data["error"])[:160]
        if data.get("ok") and "path" in data:
            extra = " (overwrote)" if data.get("overwrote") else ""
            return f"OK {data['path']}{extra}"
        if "xsd_failures" in data:
            sem = data.get("semantic", {})
            return (f"files={data.get('files')} "
                    f"xsd_failures={len(data['xsd_failures'])} "
                    f"unresolved={sem.get('unresolved_count')}")
        if "count" in data:
            return f"OK count={data['count']}"
    return "OK"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prompt")
    group.add_argument("--prompt-file", type=Path)
    parser.add_argument("--max-iterations", type=int, default=60)
    parser.add_argument("--token-budget", type=int, default=1_500_000)
    parser.add_argument("--engine", choices=("langgraph", "native"),
                        default="langgraph",
                        help="agent loop engine (default: langgraph; "
                             "'native' is the dependency-free fallback)")
    parser.add_argument("--then", action="append", default=[],
                        metavar="PROMPT",
                        help="follow-up user turn(s) run in the SAME "
                             "session after the first prompt finishes "
                             "(repeatable; e.g. an edit instruction). "
                             "LangGraph engine only.")
    parser.add_argument("--provider", default=None,
                        help="override FEWS_AGENT_PROVIDER")
    parser.add_argument("--model", default=None,
                        help="override FEWS_AGENT_MODEL")
    args = parser.parse_args(argv)

    _load_env()
    provider = get_provider(args.provider, args.model)
    user_prompt = (args.prompt_file.read_text(encoding="utf-8")
                   if args.prompt_file else args.prompt)

    session_dir = new_session_dir(args.project)
    ctx = ToolContext.for_session(session_dir)
    registry = build_registry(ctx)
    system = prompts.load("react.system")
    log_path = session_dir / "react_log.jsonl"

    print(f"[SESSION] {session_dir}")
    print(f"[MODEL] {provider.model}")
    print(f"[ENGINE] {args.engine}")
    if args.engine == "langgraph":
        from fews_agent.react.lg_agent import langsmith_status
        print(f"[LANGSMITH] {langsmith_status()}")

    def on_event(kind: str, data: dict) -> None:
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"kind": kind, **data}, default=str) + "\n")
        if kind == "assistant":
            for call in data.get("tool_calls", []):
                print(f"[TOOL] {call['name']}", flush=True)
            if data.get("text") and not data.get("tool_calls"):
                print(f"[AGENT] {data['text'][:400]}", flush=True)
        elif kind == "tool_result":
            print(f"       -> {_result_digest(data['content'])}", flush=True)
        elif kind == "stop":
            print(f"[STOP] {data['reason']}", flush=True)

    if args.engine == "langgraph":
        from fews_agent.react.lg_agent import ReactSession, default_chat_model
        session = ReactSession(
            default_chat_model(provider.model), registry, ctx, system,
            max_iterations=args.max_iterations, on_event=on_event,
        )
        on_event("user", {"text": user_prompt})
        result = session.send(user_prompt)
        for i, followup in enumerate(args.then, start=2):
            if result.stopped != "final":
                break
            print(f"\n[TURN {i}] {followup[:120]}")
            on_event("user", {"text": followup})
            result = session.send(followup)
    else:
        if args.then:
            print("[FAIL] --then needs the langgraph engine")
            return 1
        on_event("user", {"text": user_prompt})
        result = run_react(
            provider, system, user_prompt, registry, ctx,
            max_iterations=args.max_iterations,
            token_budget=args.token_budget,
            on_event=on_event,
        )

    final_check = VALIDATE_PROJECT.handler(ctx, {})
    xsd_failures = final_check["xsd_failures"]
    unresolved = final_check["semantic"]["unresolved_count"]
    print()
    print(f"[SUMMARY] files={final_check['files']} "
          f"xsd_failures={len(xsd_failures)} unresolved={unresolved} "
          f"iterations={result.iterations} "
          f"tokens={ctx.usage.total()} "
          f"(prompt={ctx.usage.prompt_tokens} "
          f"completion={ctx.usage.completion_tokens})")
    for failure in xsd_failures:
        print(f"[XSD-FAIL] {failure['path']}: {failure['message'][:200]}")
    if result.final_text:
        print()
        print(result.final_text)

    if result.stopped != "final":
        print(f"[FAIL] loop stopped on {result.stopped} — incomplete run")
        return 1
    if xsd_failures:
        print("[FAIL] XSD failures remain")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
