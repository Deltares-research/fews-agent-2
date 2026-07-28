"""Per-FEWS-module build status — shared by every shell (chat, API).

Extracted from ``app.chatter.ChatSession.module_statuses`` /
``_module_fingerprint`` / ``_stamp_module_fingerprint`` so the HTTP API
shell can expose the same green/amber/grey sidebar signal the Streamlit
shell already computes, without duplicating the logic. ``ChatSession``'s
methods now delegate here.
"""
from __future__ import annotations

import hashlib
import json

from fews_agent.agent.modules import get_module, list_modules, module_for_pattern
from fews_agent.agent.phases import phase_plan
from fews_agent.agent.turn_engine import resolve_patterns


def module_statuses(state: dict, catalog) -> list[dict]:
    """Per-FEWS-module status for the sidebar navigator, in registry order.

    Each entry: ``{"key", "label", "built", "status", "focused"}``. ``built``
    (the green light) means the module's XMLs actually exist: for modules
    that own capability phases (processing, display) — every phase of
    theirs with resolved content is in ``built_phases`` (and there IS
    content); for the deriver/view modules (locations, filters, topology,
    ...) — their files only exist after final assembly, so green requires
    ``full_build_ok``. Grey = not worked/built yet.
    """
    resolve_patterns(state, catalog)
    plan = phase_plan(state.get("patterns") or [])
    built_phases = set(state.get("built_phases") or [])
    full_ok = bool(state.get("full_build_ok"))
    focused = state.get("current_module")

    # phase → has resolved content, per the same mapping the scoped
    # build uses (module_for_pattern on the phase's patterns).
    module_phases: dict[str, list[tuple[str, bool]]] = {}
    for entry in plan:
        pats = entry.get("patterns") or []
        if not pats:
            continue
        mod_key = module_for_pattern(pats[0]["pattern"])
        module_phases.setdefault(mod_key, []).append(
            (entry["phase"], entry["phase"] in built_phases)
        )

    forced = bool(state.get("full_build_forced"))
    stamps = state.get("module_fingerprints") or {}
    out: list[dict] = []
    for m in list_modules():
        short = m.label.split(" (")[0].strip() or m.key
        if m.phases:
            phases_here = module_phases.get(m.key) or []
            built = bool(phases_here) and all(ok for _, ok in phases_here)
        else:
            built = full_ok
        status = "built" if built else "none"
        if built:
            if not m.phases and forced:
                # Assembly was /force-done'd through missing required
                # inputs — the derived files exist but are not healthy.
                status = "forced"
            elif m.key in stamps and (
                    stamps[m.key] != module_fingerprint(state, m.key)):
                # Built, but the project changed since — the rendered
                # XMLs no longer match what's configured.
                status = "stale"
        out.append({
            "key": m.key, "label": short,
            "built": built, "status": status,
            "focused": m.key == focused,
        })
    return out


def module_fingerprint(state: dict, key: str) -> str:
    """Stable hash of what a module's build DEPENDS on right now.

    Phase-owning modules (processing, display): their own resolved
    pattern instances. Deriver/view modules (topology, filters, ...): the
    WHOLE project — their files are derived from everything, so any
    change staling them is correct, not oversensitive.
    """
    m = get_module(key)
    patterns = state.get("patterns") or []
    if m is not None and m.phases:
        content: object = [
            p for p in patterns
            if module_for_pattern(str(p.get("pattern", ""))) == key
        ]
    else:
        content = {"patterns": patterns, "slots": state.get("slots") or {}}
    blob = json.dumps(content, sort_keys=True, default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


def stamp_module_fingerprint(state: dict, catalog, key: str) -> None:
    """Record 'this module's XMLs match this content' at build success."""
    resolve_patterns(state, catalog)
    state.setdefault("module_fingerprints", {})[key] = module_fingerprint(state, key)
