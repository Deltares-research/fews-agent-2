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

from typing import Any

from .modules import Module, get_module, list_modules, normalize_module


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
    """Human-readable summary of what's now in focus.

    Shows the module's job, where its output lands, what operations are
    available, what it inherits from the session so far, and what it still
    needs. Deterministic — the driver prints it verbatim on selection.
    """
    lines = [f"Now building the **{module.label}** module."]
    lines.append(module.description)
    lines.append("")
    lines.append(f"Output -> {', '.join(module.folders)}")
    lines.append(f"Operations -> {', '.join(module.operations)}")
    if module.inputs:
        lines.append(f"Inputs -> {', '.join(module.inputs)}")

    inherited = module_shared_context(state, module)
    if inherited:
        pretty = ", ".join(f"{k}={v!r}" for k, v in inherited.items())
        lines.append(f"Inherited from this session -> {pretty}")

    status = module_slot_status(state, module)
    if status["unfilled"]:
        lines.append(f"Still to set -> {', '.join(status['unfilled'])}")
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
