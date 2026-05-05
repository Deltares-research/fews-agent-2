"""Render a replay JSONL transcript as Markdown for human review.

Reads ``runners/agent/logs/<spec>.jsonl`` (or any path) and writes a
companion ``.md`` file that lays out the conversation with token totals,
thinking blocks (when the provider surfaces them), and per-call detail
for every tool/generator invocation.

Usage::

    python -m runners.agent.export_log --log runners/agent/logs/locations.jsonl
    python -m runners.agent.export_log --log locations    # short form

Token counts come from the provider's own usage report (Ollama's
``prompt_eval_count``/``eval_count``, Anthropic's ``usage.*``). When the
provider doesn't surface them, the per-round line says ``(usage not
reported)`` and the totals show the partial sum.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOG_DIR = REPO_ROOT / "runners" / "agent" / "logs"
DEFAULT_VALIDATION_ROOT = REPO_ROOT / "validation"


def load_events(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line))
    return out


def render(events: list[dict[str, Any]]) -> str:
    if not events:
        return "# (empty log)\n"

    head = next((e for e in events if e["type"] == "session_start"), None)
    val = next((e for e in events if e["type"] == "validation"), None)
    err = next((e for e in events if e["type"] == "error"), None)
    title = (head.get("project") or "(unknown project)") if head else "(unknown project)"

    # Aggregate usage across rounds (chat path) AND parser_call events
    # (wizard path).
    total_prompt = 0
    total_completion = 0
    rounds_with_usage = 0
    for e in events:
        if e["type"] in {"usage", "parser_call"}:
            total_prompt += int(e.get("prompt_tokens", 0))
            total_completion += int(e.get("completion_tokens", 0))
            if e.get("prompt_tokens") or e.get("completion_tokens"):
                rounds_with_usage += 1
    parser_calls = [e for e in events if e["type"] == "parser_call"]
    parser_errors = sum(1 for e in parser_calls if e.get("error"))

    tool_call_count = sum(1 for e in events if e["type"] == "tool_call")
    generate_calls = [
        e for e in events if e["type"] == "tool_call" and e.get("name") == "generate"
    ]
    other_calls = [
        e for e in events if e["type"] == "tool_call" and e.get("name") != "generate"
    ]
    wizard_asks = [e for e in events if e["type"] == "wizard_ask"]
    wizard_confirms = [e for e in events if e["type"] == "wizard_confirm"]
    direct_generates = [e for e in events if e["type"] == "generate"]

    parts: list[str] = []
    parts.append(f"# Replay — {title}\n")
    if head:
        parts.append("## Session\n")
        parts.append(f"- **Project:** `{head.get('project', '?')}`")
        if head.get("fixture_root"):
            parts.append(f"- **Fixture root:** `{head['fixture_root']}`")
        parts.append(f"- **Provider:** `{head.get('provider', '?')}`")
        parts.append(f"- **Model:** `{head.get('model', '?')}`")
        if head.get("description"):
            parts.append(f"- **Description:** {head['description']}")
        parts.append("")

    parts.append("## Token usage\n")
    if rounds_with_usage:
        if parser_calls:
            parts.append(
                f"- **Parser calls:** {len(parser_calls)} "
                f"({parser_errors} failed)"
            )
        parts.append(f"- **Calls with usage reported:** {rounds_with_usage}")
        parts.append(f"- **Prompt tokens (total):** {total_prompt:,}")
        parts.append(f"- **Completion tokens (total):** {total_completion:,}")
        parts.append(f"- **Total tokens:** {total_prompt + total_completion:,}")
        if parser_calls and rounds_with_usage:
            avg_per_call = (
                (total_prompt + total_completion) // rounds_with_usage
            )
            parts.append(f"- **Avg tokens per parser call:** {avg_per_call:,}")
    else:
        parts.append("- (provider did not report token usage)")
    parts.append("")

    if wizard_asks or wizard_confirms or direct_generates:
        parts.append("## Wizard activity\n")
        # Phase summary if the script has multiple phases.
        phases = [e for e in events if e["type"] == "phase_start"]
        if len(phases) > 1:
            parts.append(f"- **Phases:** {len(phases)}")
            for p in phases:
                phase_label = p.get("phase", "?")
                phase_calls = sum(
                    1 for e in events
                    if e["type"] == "parser_call" and e.get("phase") == phase_label
                )
                phase_tokens = sum(
                    int(e.get("total_tokens", 0))
                    for e in events
                    if e["type"] == "parser_call" and e.get("phase") == phase_label
                )
                done = any(
                    e["type"] == "phase_done" and e.get("phase") == phase_label
                    for e in events
                )
                phase_glyph = "✅" if done else "❌"
                parts.append(
                    f"  - {phase_glyph} `{phase_label}` "
                    f"(spec=`{p.get('spec', '?')}`, "
                    f"{p.get('answers_count', 0)} answers, "
                    f"{phase_calls} parser calls, {phase_tokens:,} tokens)"
                )
        parts.append(f"- **Wizard prompts answered:** {len(wizard_asks)}")
        parts.append(f"- **Wizard yes/no confirms:** {len(wizard_confirms)}")
        parts.append(f"- **`generate` calls:** {len(direct_generates)}")
        ar_total = sum(
            int(e.get("count", 0))
            for e in events
            if e["type"] == "answers_remaining"
        )
        if ar_total:
            parts.append(
                f"- **Scripted answers unused:** {ar_total} (some "
                f"phase(s) finished short)"
            )
        if any(e.get("type") in {"wizard_ask_underflow", "wizard_confirm_underflow"} for e in events):
            n_under = sum(
                1 for e in events
                if e.get("type") in {"wizard_ask_underflow", "wizard_confirm_underflow"}
            )
            parts.append(
                f"- ⚠ **Script underflow:** {n_under} prompt(s) exceeded the "
                f"answer queue and used defaults"
            )
        parts.append("")
    elif tool_call_count or generate_calls:
        parts.append("## Tool calls\n")
        parts.append(f"- **Total tool invocations:** {tool_call_count}")
        parts.append(
            f"- **`generate` calls (XML emission):** {len(generate_calls)}  "
            f"— see per-call details below"
        )
        if other_calls:
            names: dict[str, int] = {}
            for c in other_calls:
                names[c["name"]] = names.get(c["name"], 0) + 1
            breakdown = ", ".join(f"`{n}` × {ct}" for n, ct in sorted(names.items()))
            parts.append(f"- **Other tool calls:** {breakdown}")
        parts.append("")

    parts.append("## Validation\n")
    if err:
        parts.append(f"- ❌ **error:** {err.get('error')}")
    elif val:
        files = val.get("files", []) or []
        n_total = val.get("files_total", len(files))
        n_xsd = val.get("files_xsd_ok", sum(1 for r in files if r.get("xsd_ok")))
        n_fix = val.get("files_with_fixture", sum(1 for r in files if r.get("fixture_present")))
        n_match = val.get(
            "files_byte_equivalent",
            sum(1 for r in files if r.get("byte_equivalent")),
        )
        parts.append(f"- **Files generated:** {n_total}")
        parts.append(f"- **XSD-valid:** {n_xsd} / {n_total}")
        parts.append(
            f"- **Byte-equivalent vs fixture:** {n_match} / {n_fix} "
            f"(of {n_total - n_fix} files no fixture exists)"
        )
        parts.append("")
        if files:
            parts.append("| File | XSD | Byte-equivalent | XSD message |")
            parts.append("|---|---|---|---|")
            for r in files:
                relpath = r.get("relpath", "?")
                xsd_glyph = "✅" if r.get("xsd_ok") else "❌"
                if r.get("byte_equivalent") is True:
                    byte_glyph = "✅ match"
                elif r.get("byte_equivalent") is False:
                    byte_glyph = "❌ DRIFT"
                else:
                    byte_glyph = "— no fixture"
                msg = (r.get("xsd_msg", "") or "").replace("|", "\\|")
                parts.append(f"| `{relpath}` | {xsd_glyph} | {byte_glyph} | {msg} |")
            parts.append("")
    else:
        parts.append("- (no validation event recorded)")
    parts.append("")

    # Wizard-driven conversation: render every ask/confirm/generate
    # event in chronological order. (The chat-driven runner used a
    # different shape with `turn` indices — kept as a fallback below.)
    if wizard_asks or wizard_confirms or direct_generates:
        parts.append("## Conversation (wizard-driven)\n")
        for e in events:
            t = e["type"]
            if t == "phase_start":
                parts.append(
                    f"### Phase: `{e.get('phase', '?')}` "
                    f"(spec=`{e.get('spec', '?')}`, "
                    f"{e.get('answers_count', 0)} answers)"
                )
                parts.append("")
                continue
            if t == "phase_done":
                parts.append(
                    f"<sub>Phase `{e.get('phase', '?')}` complete.</sub>"
                )
                parts.append("")
                continue
            if t == "phase_failed":
                parts.append(
                    f"⚠ **Phase `{e.get('phase', '?')}` generate failed:** "
                    f"`{e.get('result', {})}`"
                )
                parts.append("")
                continue
            if t == "wizard_ask":
                prompt = e.get("prompt", "")
                ans = e.get("answer", "")
                parts.append(f"**Wizard:** {prompt}")
                parts.append("")
                parts.append("**User:**")
                parts.append("")
                parts.append(_blockquote(ans))
                parts.append("")
            elif t == "wizard_confirm":
                prompt = e.get("prompt", "")
                ans = e.get("answer", "")
                resolved = e.get("resolved")
                resolved_glyph = "✅ yes" if resolved else "❌ no"
                parts.append(
                    f"**Wizard (confirm):** {prompt}  →  {ans!r} ({resolved_glyph})"
                )
                parts.append("")
            elif t == "wizard_ask_underflow":
                parts.append(
                    f"⚠ **Underflow:** wizard asked `{e.get('prompt')}` "
                    f"but the script queue was empty; used default "
                    f"`{e.get('used_default', '')}`."
                )
                parts.append("")
            elif t == "wizard_confirm_underflow":
                parts.append(
                    f"⚠ **Underflow:** wizard asked confirm "
                    f"`{e.get('prompt')}` with empty queue; defaulted to no."
                )
                parts.append("")
            elif t == "generate":
                spec = e.get("spec", "?")
                result = e.get("result", {}) or {}
                xsd_ok = result.get("xsd_ok")
                xsd_glyph = "✅" if xsd_ok else "❌" if xsd_ok is False else "?"
                parts.append(f"**Generate** (`{spec}`): xsd_ok={xsd_glyph}")
                parts.append("")
                parts.append("```json")
                parts.append(_json_pretty(result, limit=1200))
                parts.append("```")
                parts.append("")
            elif t == "answers_remaining":
                parts.append(
                    f"<sub>{e.get('count', 0)} answer(s) unused at end "
                    f"of run.</sub>"
                )
                parts.append("")
        return "\n".join(parts).rstrip() + "\n"

    # Per-turn body (chat-driven runner — kept for backwards compat).
    parts.append("## Conversation\n")
    by_turn: dict[int, list[dict[str, Any]]] = {}
    for e in events:
        if e.get("turn") is None:
            continue
        by_turn.setdefault(int(e["turn"]), []).append(e)
    for turn_idx in sorted(by_turn):
        parts.append(f"### Turn {turn_idx}\n")
        for e in by_turn[turn_idx]:
            t = e["type"]
            if t == "user":
                parts.append("**User:**")
                parts.append("")
                parts.append(_blockquote(e["content"]))
                parts.append("")
            elif t == "thinking":
                parts.append(f"**Thinking** (round {e.get('round', '?')}):")
                parts.append("")
                parts.append("```")
                parts.append(e["content"].strip())
                parts.append("```")
                parts.append("")
            elif t == "usage":
                parts.append(
                    f"<sub>round {e.get('round', '?')} — "
                    f"prompt={e.get('prompt_tokens', 0):,} "
                    f"completion={e.get('completion_tokens', 0):,} "
                    f"total={e.get('total_tokens', 0):,} tokens</sub>"
                )
                parts.append("")
            elif t == "assistant":
                parts.append("**Assistant:**")
                parts.append("")
                parts.append(_blockquote(e["content"]))
                parts.append("")
            elif t == "tool_call":
                parts.append(f"**Tool call:** `{e['name']}`")
                parts.append("")
                parts.append("```json")
                parts.append(_json_pretty(e["arguments"], limit=4000))
                parts.append("```")
                parts.append("")
            elif t == "tool_result":
                tcid = e.get("tool_call_id", "")
                result = e.get("result", {})
                # Highlight generate-tool results separately for the eye.
                is_generate = isinstance(result, dict) and "spec_name" in result
                label = (
                    "**Generator result:**" if is_generate else "**Tool result:**"
                )
                parts.append(f"{label} <sub>(tool_call_id: `{tcid}`)</sub>")
                parts.append("")
                parts.append("```json")
                parts.append(_json_pretty(result, limit=2400))
                parts.append("```")
                parts.append("")
            elif t == "turn_end":
                final = e.get("final_text", "").strip()
                if final:
                    parts.append(f"<sub>turn {turn_idx} final text:</sub>")
                    parts.append("")
                    parts.append(_blockquote(final))
                    parts.append("")

    return "\n".join(parts).rstrip() + "\n"


def _blockquote(text: str) -> str:
    return "\n".join("> " + line if line else ">" for line in text.splitlines())


def _json_pretty(obj: Any, limit: int = 1600) -> str:
    text = json.dumps(obj, indent=2, ensure_ascii=False, default=str)
    if len(text) > limit:
        return text[:limit] + f"\n  // ... <{len(text) - limit} more chars>"
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--log",
        required=True,
        help="JSONL log path, or a short name resolved against runners/agent/logs/.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Markdown output path (default: same dir, .md sibling).",
    )
    args = parser.parse_args(argv)

    log_path = Path(args.log)
    # Resolution order:
    # 1. Path is an existing file → use directly.
    # 2. Path is a directory → look for events.jsonl inside.
    # 3. Short name → newest validation/<short>/<timestamp>/events.jsonl.
    # 4. Short name → legacy runners/agent/logs/<short>.jsonl.
    if log_path.is_dir():
        candidate = log_path / "events.jsonl"
        if candidate.is_file():
            log_path = candidate
        else:
            print(f"no events.jsonl in {log_path}", file=sys.stderr)
            return 1
    elif not log_path.is_file():
        validation_proj = DEFAULT_VALIDATION_ROOT / args.log
        if validation_proj.is_dir():
            runs = sorted(
                p for p in validation_proj.iterdir()
                if p.is_dir() and (p / "events.jsonl").is_file()
            )
            if runs:
                log_path = runs[-1] / "events.jsonl"
        if not log_path.is_file():
            legacy = DEFAULT_LOG_DIR / f"{args.log}.jsonl"
            if legacy.is_file():
                log_path = legacy
        if not log_path.is_file():
            print(f"log not found: {args.log}", file=sys.stderr)
            return 1

    out_path = Path(args.out) if args.out else log_path.with_suffix(".md")
    events = load_events(log_path)
    md = render(events)
    out_path.write_text(md, encoding="utf-8")
    print(f"wrote {out_path} ({len(md):,} chars, {len(events)} events)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
