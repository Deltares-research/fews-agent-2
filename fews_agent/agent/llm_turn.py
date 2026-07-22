"""The LLM-first elicitation turn: one model call, reply + slot patch.

Replaces the classification pipeline (``parse_turn`` intent taxonomy +
detectors + module-support gating) for prose turns. Python's job here is to
FIND INFO AND BRING IT TO THE PROMPT — the soft-grounding digests below — and
to validate/apply what comes back (``patch_ops.apply_patch``). All
understanding, routing, and phrasing belongs to the model. Feasible because
the whole domain fits in the prompt: ~72 patterns ≈ 5–6k tokens, state ≈ 1k.

    run_llm_turn(state, message, catalog, provider, history, inputs_dir)
        -> ModuleTurnResult (reply · grey confirmation = applied-op notes ·
                             build/assemble/coordinates signals)

Deliberately NOT an agent loop — a single structured call per turn (plus one
capped repair round on malformed JSON). If evidence ever demands mid-turn
tool use (e.g. the catalog outgrows the prompt), this design can grow into
one; the reverse migration would never happen.

This bakes in a capable-model dependency (gpt-4-class or better): a small
local model will produce worse conversations here than the old deterministic
pipeline did. That trade is deliberate.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from fews_agent.agent import module_focus, prompts
from fews_agent.agent.modules import get_module
from fews_agent.agent.patch_ops import apply_patch
from fews_agent.agent.project_intents import (
    compute_input_status,
    scan_inputs,
)
from fews_agent.agent.turn_engine import (
    ModuleTurnResult,
    _history_text,
    module_vars_text,
)

_logger = logging.getLogger(__name__)

# One repair round on malformed model output, then fall back gracefully.
_MAX_ATTEMPTS = 2

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "patch": {"type": "array", "items": {"type": "object"}},
    },
    "required": ["reply", "patch"],
}


# ---------------------------------------------------------------------------
# Soft-grounding digests — Python briefs, never decides.
# ---------------------------------------------------------------------------

def _first_sentence(text: str, cap: int = 160) -> str:
    t = " ".join(str(text or "").split())
    dot = t.find(". ")
    if dot != -1:
        t = t[: dot + 1]
    return t[:cap]


def catalog_digest(catalog) -> str:
    """One line per pattern: what it is, what it needs, what it produces.

    Leads with the IMPORT SOURCES line — the canonical names ``add_import``
    accepts. Without it the model routed known sources (HRDPS) through
    ``add_capability <pattern>`` because only pattern names were visible.
    Derived from ``_IMPORT_PATTERN_MAP``, never hand-listed.
    """
    from fews_agent.agent.project_intents import _IMPORT_PATTERN_MAP

    lines: list[str] = [
        "IMPORT SOURCES — add these with add_import {name}: "
        + ", ".join(sorted(_IMPORT_PATTERN_MAP)),
        "",
    ]
    for e in catalog or []:
        req = [n for n, s in (e.variables or {}).items()
               if isinstance(s, dict) and s.get("required")]
        opts = [
            f"{n}={s.get('default')}" for n, s in (e.variables or {}).items()
            if isinstance(s, dict) and not s.get("required")
            and s.get("default") not in (None, "", [], {})
        ]
        produces = ", ".join(
            Path(o).name for o in (e.outputs or [])[:3]
        ) + ("…" if len(e.outputs or []) > 3 else "")
        bits = [f"- {e.name} ({e.path}): {_first_sentence(e.description)}"]
        if req:
            bits.append(f"  requires: {', '.join(req)}")
        if opts:
            bits.append(f"  optional: {', '.join(opts[:6])}")
        if produces:
            bits.append(f"  produces: {produces}")
        lines.append("\n".join(bits))
    return "\n".join(lines)


def state_digest(state: dict) -> str:
    """Compact project state: focus (advisory), slots, build progress."""
    slots = state.get("slots") or {}
    lines: list[str] = []
    focus = module_focus.get_focus(state)
    if focus is not None:
        lines.append(
            f"User is currently viewing the {focus.key} module "
            f"({focus.label}) — advisory context, not a restriction."
        )
    interesting = {
        k: v for k, v in slots.items()
        if k not in ("import_overrides",) and v not in (None, "", [], {})
    }
    if interesting:
        for k, v in interesting.items():
            lines.append(f"{k}: {json.dumps(v, default=str)}")
    else:
        lines.append("(project is empty — nothing configured yet)")
    overrides = slots.get("import_overrides") or {}
    for name, ov in overrides.items():
        lines.append(f"per-import overrides for {name}: "
                     f"{json.dumps(ov, default=str)}")
    built = state.get("built_phases") or []
    lines.append(
        f"built phases (rendered + XSD-validated): "
        f"{', '.join(built) if built else 'none yet'}"
    )
    if state.get("full_build_ok"):
        lines.append("full project assembly: completed successfully")
    return "\n".join(lines)


def gap_digest(state: dict, inputs_dir) -> str:
    """The computed gap to a buildable project — the model prioritizes this
    conversationally instead of reciting one scripted next step."""
    slots = state.get("slots") or {}
    scan = scan_inputs(inputs_dir)
    status = compute_input_status(state.get("intent"), scan, slots)
    lines: list[str] = []
    if not (slots.get("imports") or slots.get("basins")
            or slots.get("extra_patterns")):
        lines.append("nothing configured yet — the user needs to add a data "
                     "source, a basin model, or another capability first")
    for c in status.get("csvs_required_missing") or []:
        lines.append(f"required input file missing: {c}")
    for n in status.get("extra_notes") or []:
        lines.append(n)
    if not lines:
        lines.append("(no known gaps — the project can be built/assembled)")
    return "\n".join(lines)


def inputs_digest(inputs_dir) -> str:
    """What's actually in inputs/ — including CSV headers + row counts, so
    uploads get grounded reactions ('your 42 stations are in')."""
    p = Path(inputs_dir) if inputs_dir else None
    if p is None or not p.is_dir():
        return "(no inputs directory yet — no files provided)"
    lines: list[str] = []
    for f in sorted(p.glob("*.csv")):
        try:
            with f.open("r", encoding="utf-8-sig", errors="replace") as fh:
                header = fh.readline().strip()
                n_rows = sum(1 for _ in fh)
            lines.append(f"{f.name}: {n_rows} rows; columns: {header}")
        except OSError:
            lines.append(f"{f.name}: (unreadable)")
    yamls = sorted(x.name for x in list(p.glob("*.yaml")) + list(p.glob("*.yml")))
    if yamls:
        lines.append("yaml inputs: " + ", ".join(yamls))
    others = sorted(
        x.name for x in p.iterdir()
        if x.is_file() and x.suffix.lower() not in (".csv", ".yaml", ".yml")
    )
    if others:
        lines.append("other files: " + ", ".join(others[:10]))
    return "\n".join(lines) if lines else "(inputs directory is empty)"


def build_digest(state: dict) -> str:
    """The last build's outcome, so post-build questions are answerable."""
    s = state.get("last_build_summary")
    if not isinstance(s, dict):
        return "(no build has run yet this session)"
    lines = [
        f"scope: {s.get('scope') or s.get('phase') or 'full assembly'}",
        f"files generated: {s.get('files_total', '?')}, "
        f"XSD-valid: {s.get('files_xsd_ok', '?')}/{s.get('files_xml', '?')}",
    ]
    errors = s.get("errors") or []
    if errors:
        lines.append("errors: " + "; ".join(str(e) for e in errors[:5]))
    failed = [
        f["path"] for f in (s.get("files") or []) if not f.get("xsd_ok", True)
    ]
    if failed:
        lines.append("XSD failures: " + ", ".join(failed[:8]))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The single call
# ---------------------------------------------------------------------------

def _fallback_reply(state: dict) -> str:
    return (
        "I couldn't reach the language model just now, so nothing was "
        "changed. Try again in a moment — slash commands (/vars, /build, "
        "/done) still work without it."
    )


def run_llm_turn(
    state: dict, message: str, catalog, *, provider,
    history: list | None = None, inputs_dir=None,
) -> ModuleTurnResult:
    """One user message → one model call → validated patch → result."""
    system = prompts.load("llm_turn.system")
    user = prompts.load(
        "llm_turn.user",
        catalog_digest=catalog_digest(catalog),
        state_digest=state_digest(state),
        instances_view=module_vars_text(state, catalog, None),
        gap_digest=gap_digest(state, inputs_dir),
        inputs_digest=inputs_digest(inputs_dir),
        build_digest=build_digest(state),
        history_text=_history_text(history, limit=8),
        message=message,
    )

    reply, ops = None, None
    last_err = ""
    for attempt in range(_MAX_ATTEMPTS):
        try:
            ask = user if not last_err else (
                user + "\n\nYour previous response was invalid "
                f"({last_err}). Return ONLY the JSON object."
            )
            resp = provider.generate_json(
                system=system, user=ask, schema=_RESPONSE_SCHEMA,
            )
            data = resp.data or {}
            reply = str(data.get("reply") or "").strip()
            ops = data.get("patch")
            if reply and isinstance(ops, list):
                break
            last_err = "missing reply or patch is not a list"
            reply, ops = None, None
        except Exception as exc:  # noqa: BLE001
            _logger.warning("llm_turn call failed (attempt %d): %s: %s",
                            attempt + 1, type(exc).__name__, exc)
            last_err = f"{type(exc).__name__}"
    if reply is None:
        return ModuleTurnResult(_fallback_reply(state), "llm turn: provider "
                                "failed", kind="reply")

    res = apply_patch(state, ops, catalog)

    if res.dropped:
        reply += (
            "\n\n[!] Not applied (failed validation): "
            + "; ".join(res.dropped)
        )
    kind = "edit" if (res.notes or res.new_patterns) else "reply"
    return ModuleTurnResult(
        reply, f"llm turn: {len(res.notes)} applied, {len(res.dropped)} "
        f"dropped", kind=kind,
        confirmation="\n".join(res.notes),
        new_patterns=res.new_patterns,
        wants_build=res.wants_build, build_scope=res.build_scope,
        wants_assemble=res.wants_assemble,
        coordinates_for=res.coordinates_for,
    )
