"""Render a ReAct session's react_log.jsonl as a readable Markdown transcript.

    python -m runners.react.transcript_md projects/<p>/<p>_<ts> \
        [--prompt "turn 1 text" ...] [--out FILE]

Writes ``_conversation.md`` into the session folder (the same filename
the chat shells use). Structure per turn: the user prompt, then one
block per agent step — any text the model emitted, followed by each
tool call paired with its own result — and the final response.

Newer logs carry ``{"kind": "user"}`` events; for older logs that lack
them, pass the prompts via ``--prompt`` in turn order.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

MAX_ARG_CHARS = 150
MAX_RESULT_CHARS = 180


def _fmt_args(name: str, args: dict) -> str:
    """One compact line of the arguments that matter for this tool."""
    if name in ("write_config_file", "write_generic_file"):
        target = (args.get("spec_name") or args.get("schema")
                  or args.get("root_tag") or "?")
        payload = args.get("data") or args.get("body")
        keys = (", ".join(list(payload)[:6])
                if isinstance(payload, dict) else "")
        out = target
        if args.get("output_path"):
            out += f" -> {args['output_path']}"
        return f"{out}" + (f"  ({keys})" if keys else "")
    parts = []
    for key, value in args.items():
        text = (value if isinstance(value, str)
                else json.dumps(value, ensure_ascii=False))
        if len(text) > 60:
            text = text[:60] + "..."
        parts.append(f"{key}={text}")
    line = ", ".join(parts)
    return line if len(line) <= MAX_ARG_CHARS else line[:MAX_ARG_CHARS] + "..."


def _fmt_result(content: str) -> str:
    """One line summarising what the tool returned."""
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return str(content)[:MAX_RESULT_CHARS]
    if not isinstance(data, dict):
        return str(data)[:MAX_RESULT_CHARS]
    if "error" in data:
        return "**ERROR** " + str(data["error"])[:MAX_RESULT_CHARS]
    if data.get("ok") and "path" in data:
        return (f"wrote `{data['path']}`"
                + (" (overwrote)" if data.get("overwrote") else ""))
    if "xsd_failures" in data:
        sem = data.get("semantic", {})
        return (f"{data.get('files')} files · "
                f"{len(data['xsd_failures'])} XSD failures · "
                f"{sem.get('unresolved_count')} unresolved refs · "
                f"{len(data.get('undefined_properties', []))} undefined "
                f"properties · "
                f"{len(data.get('expression_issues', []))} expression issues")
    if "stations" in data:
        names = ", ".join(s.get("name", "?")[:22]
                          for s in data["stations"][:4])
        return f"{data.get('count')} stations ({names}...)"
    if "ingested" in data:
        return " · ".join(
            f"{e['csv']} -> {e.get('written') or 'not written'}"
            for e in data["ingested"])
    if "hits" in data:
        return "hits: " + "; ".join(h.get("title", "")[:36]
                                    for h in data["hits"][:3])
    if "files" in data and isinstance(data["files"], str):
        return f"{data.get('count')} reference files listed"
    if "paths" in data:
        return ("wrote " + ", ".join(f"`{p}`" for p in data["paths"])
                if data["paths"] else "nothing to derive")
    if "content" in data:
        return f"read `{data.get('path', '?')}` ({len(data['content'])} chars)"
    if "schema" in data or "properties" in data:
        return f"schema for `{data.get('spec_name', '?')}`"
    if "data" in data:
        return f"standard `{data.get('name', '?')}`"
    if "specs" in data:
        n = data.get("count", 0)
        return f"{n} spec{'' if n == 1 else 's'}"
    if "standards" in data:
        return f"catalog of {data.get('count')} bundled standards"
    if "count" in data:
        n = data["count"]
        return f"{n} result{'' if n == 1 else 's'}"
    if "generated" in data:
        return (f"{len(data['generated'])} generated files, "
                f"{len(data.get('inputs', []))} inputs")
    if data.get("ok"):
        return "ok"
    return json.dumps(data, ensure_ascii=False)[:MAX_RESULT_CHARS]


def _take_call(pending: list[dict], result_event: dict) -> dict:
    """Pop the call this result belongs to.

    Parallel tool results arrive in COMPLETION order, so pair by
    ``tool_call_id`` first. Older logs stored no ids — fall back to the
    first pending call of the same tool name, then to plain order.
    """
    if not pending:
        return {}
    rid = result_event.get("tool_call_id")
    if rid:
        for i, call in enumerate(pending):
            if call.get("id") == rid:
                return pending.pop(i)
    name = result_event.get("name")
    same_name = [i for i, c in enumerate(pending)
                 if c.get("name") == name] if name else []
    # Two calls of the same tool in one step: disambiguate on the
    # identifying value the result echoes back (path / spec / standard).
    if len(same_name) > 1:
        try:
            data = json.loads(result_event.get("content", ""))
        except (json.JSONDecodeError, TypeError):
            data = {}
        if isinstance(data, dict):
            for key in ("path", "spec_name", "name"):
                echoed = data.get(key)
                if not isinstance(echoed, str):
                    continue
                for i in same_name:
                    args = pending[i].get("arguments") or {}
                    if echoed in (args.get("path"), args.get("output_path"),
                                  args.get("spec_name"), args.get("schema"),
                                  args.get("name")):
                        return pending.pop(i)
    if same_name:
        return pending.pop(same_name[0])
    return pending.pop(0)


def render(log_path: Path, prompts: list[str]) -> str:
    events = [json.loads(line) for line in
              log_path.read_text(encoding="utf-8").splitlines() if line]
    has_user_events = any(e.get("kind") == "user" for e in events)
    prompt_iter = iter(prompts)

    body: list[str] = []
    turn = 0
    step = 0
    tokens = 0
    calls_total = 0
    pending: list[dict] = []   # tool calls awaiting their results
    at_turn_start = True

    def open_turn(text: str | None) -> None:
        nonlocal turn, step
        turn += 1
        step = 0
        body.extend([f"## Turn {turn} — user", ""])
        body.extend([text.strip(), ""] if text else
                    ["*(prompt not recorded in this log)*", ""])
        body.extend([f"## Turn {turn} — agent", ""])

    for event in events:
        kind = event.get("kind")

        if kind == "user":
            open_turn(event.get("text"))
            at_turn_start = False
            continue
        if at_turn_start and kind == "assistant" and not has_user_events:
            open_turn(next(prompt_iter, None))
            at_turn_start = False

        if kind == "assistant":
            usage = event.get("usage") or {}
            tokens += (usage.get("prompt_tokens", 0) or 0) + \
                      (usage.get("completion_tokens", 0) or 0)
            calls = event.get("tool_calls") or []
            text = (event.get("text") or "").strip()
            if calls:
                step += 1
                calls_total += len(calls)
                if body and body[-1] != "":
                    body.append("")
                body.append(f"**Step {step}**"
                            + (f" — {len(calls)} tool calls" if len(calls) > 1
                               else ""))
                body.append("")
                if text:            # the model's words motivating the calls
                    body.extend([text, ""])
                pending = list(calls)
            elif text:              # final answer for this turn
                if body and body[-1] != "":
                    body.append("")
                body.extend(["**Response**", "", text, ""])
        elif kind == "tool_result":
            call = _take_call(pending, event)
            name = event.get("name") or call.get("name") or "?"
            args = call.get("arguments") or {}
            body.append(f"- `{name}` — {_fmt_args(name, args)}"
                        if args else f"- `{name}`")
            body.append(f"  → {_fmt_result(event.get('content', ''))}")
        elif kind == "stop":
            reason = event.get("reason")
            if reason != "final":
                body.extend(["", f"*turn ended early: {reason}*", ""])
            body.append("")
            at_turn_start = True

    head = [
        f"# Conversation: {log_path.parent.name}",
        "",
        f"{turn} turn(s) · {step and calls_total or calls_total} tool calls "
        f"· {tokens:,} tokens",
        "",
        "---",
        "",
    ]
    return "\n".join(head + body).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session_dir", type=Path)
    parser.add_argument("--prompt", action="append", default=[],
                        help="user prompt per turn, for logs without user "
                             "events (repeatable, in turn order)")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    log_path = args.session_dir / "react_log.jsonl"
    if not log_path.is_file():
        print(f"[FAIL] no react_log.jsonl in {args.session_dir}")
        return 1
    out = args.out or (args.session_dir / "_conversation.md")
    out.write_text(render(log_path, args.prompt), encoding="utf-8")
    print(f"[OK] {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
