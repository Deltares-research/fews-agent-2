"""Skills — an intent's capabilities that TAKE ACTIONS.

The word "skill" was reclaimed this session. The old regex "skills"
(``detect_*`` / ``extract_skills``) are just **prose filtering** — they scan
prose and surface known tokens, deciding and acting on nothing (see
``project_intents.filter_prose``). A **skill** now means an *intent-connected
action*: a thing bound to an intent that mutates project state.

A skill is identified by **(intent, action)** — e.g. ``build_processing`` +
``add`` (add an import/basin to the processing module), ``build_processing`` +
``set`` (change a variable), ``build_display`` + ``remove``. The registry is
the single source of truth for **which actions an intent supports** and **how
each is handled**, replacing the old inline ``if action == ...`` routing in
``turn_engine.apply_operation`` (which now just dispatches here).

Scope: only the state-mutating actions (``add``/``set``/``remove``) are
skills. ``select_module`` is a focus change, and ``build``/``list`` are
driver-executed (console / build I/O), so they aren't registered here.

The registry is derived from each module's declared ``operations`` (so the
module registry and the skills can't drift), with shared handler functions
that live in ``turn_engine`` (imported lazily to avoid a load-time cycle —
``turn_engine.apply_operation`` imports *this* module, not the reverse).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .modules import get_module, list_modules
from .project_intents import INTENTS

# The state-mutating actions that can be skills. build/list (I/O) and
# select_module (focus) are handled elsewhere.
MUTATING_ACTIONS: tuple[str, ...] = ("add", "set", "remove")

# Handler signature: (state, op, catalog) -> (reply, new_pattern_paths).
Handler = Callable[[dict, Any, Any], "tuple[str, list[str]]"]


@dataclass(frozen=True)
class Skill:
    """One intent-connected action. ``handler`` executes it against state."""

    intent: str          # e.g. "build_processing" (a module- or project-intent)
    action: str          # add | set | remove
    handler: Handler
    description: str = ""

    @property
    def key(self) -> tuple[str, str]:
        return (self.intent, self.action)


def _action_handlers() -> dict[str, Handler]:
    # Lazy import: turn_engine imports this module (in apply_operation), so we
    # must NOT import turn_engine at load time — only when the registry builds.
    from .turn_engine import apply_extracted_fields, apply_removal
    return {
        "add": apply_extracted_fields,   # reads op.action to fill vs override
        "set": apply_extracted_fields,
        "remove": apply_removal,
    }


def _build_registry() -> dict[tuple[str, str], Skill]:
    """One skill per (module-intent, supported mutating action).

    Derived from each module's ``operations`` so the two can't drift — a
    view-only module (list/build only) simply registers no add/set/remove
    skills, which is exactly the operation-support policy.
    """
    handlers = _action_handlers()
    registry: dict[tuple[str, str], Skill] = {}

    # Whole-project intents support the full add/set/remove editing surface.
    for intent, meta in INTENTS.items():
        for action in MUTATING_ACTIONS:
            registry[(intent, action)] = Skill(
                intent=intent, action=action, handler=handlers[action],
                description=f"{action} — {meta.description.split('.')[0]}",
            )

    # Module intents: only the actions the module declares (a view-only
    # module registers no add/set/remove — exactly the support policy).
    for module in list_modules():
        intent = f"build_{module.key}"
        for action in MUTATING_ACTIONS:
            if action in module.operations:
                registry[(intent, action)] = Skill(
                    intent=intent, action=action, handler=handlers[action],
                    description=f"{action} in the {module.label} module",
                )
    return registry


SKILLS: dict[tuple[str, str], Skill] = _build_registry()


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def find_skill(intent: str | None, action: str | None) -> Skill | None:
    """The skill for ``(intent, action)``, or None if unsupported."""
    if not intent or not action:
        return None
    return SKILLS.get((intent, action))


def supports(intent: str | None, action: str | None) -> bool:
    """Whether ``intent`` has a skill for ``action``."""
    return find_skill(intent, action) is not None


def skills_for_intent(intent: str) -> list[Skill]:
    """All skills an intent offers (in MUTATING_ACTIONS order)."""
    return [
        SKILLS[(intent, a)] for a in MUTATING_ACTIONS
        if (intent, a) in SKILLS
    ]


def skills_for_module(module_key: str) -> list[Skill]:
    """All skills the module's build-intent offers."""
    module = get_module(module_key)
    return skills_for_intent(f"build_{module.key}") if module else []
