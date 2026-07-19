"""Module-focus session layer — which module is in focus, and its context.

Module-mode lets the configurator build **one module at a time** (see
``modules.py`` for the registry). This module is the thin, pure, state-aware
layer that:

  * tracks the module in focus (``state["current_module"]``);
  * reports what a module already inherits from the session (its
    ``shared_reads``, read straight out of the persistent slots /
    singleton_seeds — there is no separate store, because
    ``state["slots"]`` already survives every turn and ``project.yaml`` is
    just its serialized form);
  * reports which of a module's own variables are still unfilled, so the
    reply chases only *this* module's gaps instead of the whole project's;
  * renders a "focus card" the driver prints when a module is selected.

Everything here is a pure function of ``state`` + the static registry — no
LLM, no I/O, no build calls. The drivers own printing and persistence.
"""
from __future__ import annotations

import re
from typing import Any

from .modules import Module, get_module, list_modules, normalize_module


# ---------------------------------------------------------------------------
# Cold module entry: enter a module from prose when nothing is in focus
# ---------------------------------------------------------------------------

# Verbs that signal "let's start building module X". A bare operation verb
# ("import GFS") is deliberately NOT here — that's an operation, handled once
# a module is in focus, not a request to enter one.
_ENTRY_VERBS: tuple[str, ...] = (
    "set up", "setup", "configure", "work on", "focus on", "start on",
    "start with", "let's do", "lets do", "let's work on", "lets work on",
    "build the", "define the",
)

# Module keywords safe to enter on an entry verb. Deliberately EXCLUDES the
# generic "imports"/"import"/"model"/"run"/"process" tokens, which collide
# with whole-project descriptions ("set up imports and a raven model" is a
# forecasting project, not the processing module). The processing module is
# entered via the explicit word "module" (rule 1 below) or "/module".
_DISTINCT_MODULE_KEYWORDS: dict[str, str] = {
    "locations": "locations", "location": "locations", "stations": "locations",
    "parameters": "parameters",
    "spatial display": "display", "display": "display",
    "filters": "filters",
    "topology": "topology",
    "id maps": "idmap", "id map": "idmap", "idmap": "idmap",
}


def detect_module_entry(message: str) -> str | None:
    """Detect a request to START building a specific module, or None.

    Conservative on purpose — fires only on clear single-module targeting, so
    it never hijacks a whole-project description on its way to the intent
    pipeline. Three ways it fires:

      1. The literal word "module": "the imports module", "processing module".
      2. An entry verb + a distinct-name module keyword: "configure
         locations", "work on the display", "set up filters". (imports/model
         are excluded here — they read as a whole-project spec.)
      3. The whole message is essentially just a module name: "locations",
         "the display".
    """
    low = (message or "").strip().lower()
    if not low:
        return None

    # Rule 1: "<something> module" — the user literally said "module".
    m = re.search(r"\b([a-z][a-z ]*?)\s+module\b", low)
    if m:
        words = m.group(1).strip().split()
        if words:
            key = normalize_module(words[-1])
            if key:
                return key

    # Rule 2: an entry verb + a distinct-name module keyword.
    if any(v in low for v in _ENTRY_VERBS):
        for kw, key in sorted(
            _DISTINCT_MODULE_KEYWORDS.items(), key=lambda kv: -len(kv[0])
        ):
            if re.search(rf"\b{re.escape(kw)}\b", low):
                return key

    # Rule 3: the whole message is basically just a module name (<= 3 words).
    stripped = low.rstrip(".!?")
    toks = stripped.split()
    if 1 <= len(toks) <= 3:
        for cand in (stripped, toks[-1]):
            key = normalize_module(cand)
            if key:
                return key

    return None


# ---------------------------------------------------------------------------
# Deterministic switch safety-net: leave a focused module for a named one
# ---------------------------------------------------------------------------

# Navigation verbs that signal moving to a DIFFERENT module mid-session.
_SWITCH_VERBS: tuple[str, ...] = (
    "switch to", "go back to", "go to", "back to", "move to", "jump to",
    "return to", "head to", "over to", "work on", "let's work on",
    "lets work on", "let's do", "lets do", "open the",
)

# Module keywords for switching — BROADER than cold-entry's distinct-name set:
# mid-session navigation to imports/processing/model is unambiguous (there's
# no whole-project-spec to collide with once you're already in a module), so
# those generic tokens are included here.
_SWITCH_MODULE_KEYWORDS: dict[str, str] = {
    **_DISTINCT_MODULE_KEYWORDS,
    "imports": "processing", "import": "processing",
    "processing": "processing", "process": "processing",
    "model": "processing", "models": "processing",
    "system": "system", "timesteps": "system",
    "root": "root", "idmaps": "idmap",
}


def detect_module_switch(message: str, current_focus: str | None) -> str | None:
    """When focused, detect an explicit navigation to a DIFFERENT module.

    A deterministic safety-net for the module-op path: the LLM won't reliably
    LEAVE a focused module on "go back to X" / "let's work on X" phrasings
    (it confidently keeps the focused intent), so an explicit navigation
    command overrides the parse. Fires only on (1) the literal "X module", or
    (2) a navigation verb + a module keyword — and only when the target
    differs from the module already in focus. Returns the target key or None.
    """
    low = (message or "").strip().lower()
    if not low or not current_focus:
        return None

    target: str | None = None
    # Rule 1: "<something> module" — a literal module reference.
    m = re.search(r"\b([a-z][a-z ]*?)\s+module\b", low)
    if m:
        words = m.group(1).strip().split()
        if words:
            target = normalize_module(words[-1])

    # Rule 2: a navigation verb + a module keyword.
    if target is None and any(v in low for v in _SWITCH_VERBS):
        for kw, key in sorted(
            _SWITCH_MODULE_KEYWORDS.items(), key=lambda kv: -len(kv[0])
        ):
            if re.search(rf"\b{re.escape(kw)}\b", low):
                target = key
                break

    if target is None or target == current_focus:
        return None
    return target


# Where a shared/settable variable physically lives in state. Most live in
# ``slots``; the geo scalars are also mirrored into
# ``singleton_seeds["Locations"]`` by the turn pipeline, so we read there as a
# fallback. Keeping this in one place means "the store" stays implicit
# (slots + singleton_seeds) rather than a third dict to keep in sync.
_SINGLETON_LOCATION_KEYS = {"geoDatum": "geoDatum", "region": "region",
                            "custom_bbox": "regionBbox"}


def read_var(state: dict, name: str) -> Any:
    """Read a variable's current value from the session, wherever it lives.

    Checks ``slots`` first (the primary store), then the Locations
    singleton seed for the mirrored geo scalars. Returns None when unset.
    """
    slots = state.get("slots") or {}
    val = slots.get(name)
    if val not in (None, [], ""):
        return val
    loc_key = _SINGLETON_LOCATION_KEYS.get(name)
    if loc_key:
        seed = (state.get("singleton_seeds") or {}).get("Locations") or {}
        v = seed.get(loc_key)
        if v not in (None, [], ""):
            return v
    return None


def _is_filled(value: Any) -> bool:
    return value not in (None, [], "", {})


def get_focus(state: dict) -> Module | None:
    """Return the module currently in focus, or None."""
    return get_module(state.get("current_module"))


def clear_focus(state: dict) -> None:
    state["current_module"] = None


def set_focus(state: dict, token: str) -> tuple[Module | None, str]:
    """Select the module named by ``token`` and put it in focus.

    Returns ``(module, card_text)`` on success, or ``(None, help_text)``
    when the token doesn't name a known module. Selecting a module does
    **not** copy any values around — the session's persistent slots already
    hold what earlier modules established; the focus card just surfaces what
    this module inherits so the user can see it.
    """
    key = normalize_module(token)
    if key is None:
        return None, _unknown_module_text(token)
    module = get_module(key)
    state["current_module"] = key
    return module, focus_card(state, module)


def module_shared_context(state: dict, module: Module) -> dict[str, Any]:
    """The module's ``shared_reads`` that the session already knows.

    Only keys with a known value are returned — the "you don't have to tell
    me this again" set.
    """
    out: dict[str, Any] = {}
    for name in module.shared_reads:
        val = read_var(state, name)
        if _is_filled(val):
            out[name] = val
    return out


def module_slot_status(state: dict, module: Module) -> dict[str, list[str]]:
    """Split the module's own ``variables`` into filled vs unfilled.

    Reads from the session store (slots + singleton mirror). Shared-read
    variables that the session already carries count as filled even if the
    module never asked — that's the point of the shared store.
    """
    filled: list[str] = []
    unfilled: list[str] = []
    for name in module.variables:
        if _is_filled(read_var(state, name)):
            filled.append(name)
        else:
            unfilled.append(name)
    return {"filled": filled, "unfilled": unfilled}


def next_unfilled_variable(state: dict, module: Module) -> str | None:
    """The first of the module's own variables the session hasn't filled.

    Used by the turn engine to scope elicitation: when a module is in focus,
    the reply asks about THIS module's next gap instead of the whole
    project's. Returns None when the module has everything it needs.
    """
    unfilled = module_slot_status(state, module)["unfilled"]
    return unfilled[0] if unfilled else None


def focus_card(state: dict, module: Module) -> str:
    """A short, friendly module-entry line (the follow-up question is appended
    by the caller via ``turn_engine.module_welcome``).

    Deliberately NOT the old folders / operations / "still to set → [pile]"
    dump — configurator feedback: "a generic pile of instructions, not user
    friendly." Just names the module and, if anything carries over from the
    session, mentions it in one grey line.
    """
    lines = [f"You're now on the **{module.label}** module."]
    inherited = module_shared_context(state, module)
    if inherited:
        pretty = ", ".join(f"{k}={v!r}" for k, v in inherited.items())
        lines.append(f"_Carrying over from this session: {pretty}._")
    return "\n".join(lines)


def _unknown_module_text(token: str) -> str:
    names = ", ".join(m.key for m in list_modules())
    return (
        f"'{token}' isn't a module I recognise. Available modules: {names}. "
        f"Pick one with e.g.  /module processing"
    )


def modules_overview() -> str:
    """A listing of every module (for ``/modules``)."""
    lines = ["Modules you can build (one at a time):"]
    for m in list_modules():
        lines.append(f"  - {m.key} : {m.label}")
        lines.append(f"      {m.description}")
    lines.append("")
    lines.append("Select one with  /module <name>  (e.g. /module processing).")
    return "\n".join(lines)
