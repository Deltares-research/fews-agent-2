"""The project route — a deterministic GPS over the path to a complete config.

The elicitation agent kept behaving like an order-taker: after a source was
added it immediately offered "build what you have?" while the weather
variables were still on silent defaults, and it lost track of unfinished
steps (real tester histories). Those are *navigation* failures — there was
no single, coherent model of "where are we on the road to a complete,
assemblable project, and what's the next useful step".

This module is that model. It is PURE and deterministic (no LLM): given the
project state (+ the inputs/ dir), ``route_position`` reports which legs of
the journey are done, which is current, what still blocks final assembly,
and which recommended steps are still open. Phase 2 feeds this to the prompt
as one ROUTE digest, replacing the scattered ``gap_digest`` /
``_next_step_hint`` / ad-hoc rules; the model then NAVIGATES (leads with the
current step, never pushes assembly before the blocking legs are done)
instead of taking orders.

Two leg kinds:
  * ``blocking``  — needed for a complete, assemblable project. While any is
    open, the project is NOT ``ready_to_assemble`` and the agent must not
    steer toward "done".
  * ``advisory``  — recommended, quality-improving (choose variables rather
    than defaulting, set a map area). Surfaced as the current step when
    nothing blocking is pending, but the driver may skip them freely — the
    reply layer's say-once discipline keeps them from nagging.

Reusing the existing input machinery (``scan_inputs`` /
``compute_input_status``) so the CSV legs never drift from the build's own
notion of what a project requires.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Leg:
    """One step on the route to a complete project."""

    id: str
    title: str
    kind: str                       # "blocking" | "advisory"
    active: bool                    # does this leg apply to THIS project?
    done: bool
    guidance: str = ""              # what to do / ask next for this leg
    detail: str = ""                # extra context (e.g. current defaults)


@dataclass
class RoutePosition:
    """Where the project is on the route, as structured facts."""

    legs: list[Leg] = field(default_factory=list)
    current: Leg | None = None                  # first active+open leg, in order
    blocking_open: list[Leg] = field(default_factory=list)
    advisory_open: list[Leg] = field(default_factory=list)
    ready_to_assemble: bool = False
    assembled: bool = False


# ---------------------------------------------------------------------------
# leg predicates — small, pure helpers over slots
# ---------------------------------------------------------------------------

def _parameterizable_imports(imports: list[str]) -> list[str]:
    """Imports whose weather variables are USER-selectable (NOAA family);
    ECCC grids carry a fixed parameter set, so they have no 'variables' leg."""
    from fews_agent.agent.project_intents import (
        _IMPORT_PATTERN_MAP,
        _PARAMETERIZED_NWP_PATTERNS,
    )
    out = []
    for name in imports:
        entry = _IMPORT_PATTERN_MAP.get(name)
        if entry and entry[0] in _PARAMETERIZED_NWP_PATTERNS:
            out.append(name)
    return out


def _imports_on_default_variables(slots: dict) -> list[str]:
    """Parameterizable imports still on their DEFAULT variables — i.e. the
    user never chose (global ``data_types`` unset) and there is no per-import
    ``parameters`` override for them. These are the 'forgot to set variables'
    sources the agent should guide toward."""
    params_imports = _parameterizable_imports(
        [str(i) for i in (slots.get("imports") or [])]
    )
    if not params_imports:
        return []
    if slots.get("data_types"):
        return []                    # a global choice covers every source
    overrides = slots.get("import_overrides") or {}
    return [
        name for name in params_imports
        if "parameters" not in (overrides.get(name) or {})
    ]


def _fixed_variable_imports(slots: dict) -> list[str]:
    """NWP imports whose weather-variable set is FIXED (not user-selectable) —
    every gridded import that is NOT parameterizable. Derived from the same
    catalog facts as the variables leg, so the 'don't ask which variables'
    guidance can never drift from what's actually selectable (today: the ECCC
    grids HRDPS/GDPS/RDPS/REPS/HRDPA/RDPA)."""
    from fews_agent.agent.project_intents import _IMPORT_PATTERN_MAP
    imports = [str(i) for i in (slots.get("imports") or [])]
    selectable = set(_parameterizable_imports(imports))
    out = []
    for name in imports:
        entry = _IMPORT_PATTERN_MAP.get(name)
        if (entry and entry[0].startswith("auto/nwp_grid_")
                and name not in selectable):
            out.append(name)
    return out


def _nwp_imports_without_map_area(slots: dict) -> list[str]:
    """NWP imports with no map framing (no project region/bbox and no
    per-import grid geometry). Advisory — the bundled default extent works,
    but a region crops the grids and orients the map."""
    if slots.get("region") or slots.get("custom_bbox"):
        return []
    from fews_agent.agent.project_intents import _IMPORT_PATTERN_MAP
    overrides = slots.get("import_overrides") or {}
    out = []
    for name in (slots.get("imports") or []):
        entry = _IMPORT_PATTERN_MAP.get(str(name))
        if entry and entry[0].startswith("auto/nwp_grid_"):
            if "grid_geometry" not in (overrides.get(name) or {}):
                out.append(str(name))
    return out


def _basins_without_adapter(slots: dict) -> list[str]:
    return [
        str(b.get("basin_name", "?")) for b in (slots.get("basins") or [])
        if not b.get("model_adapter")
    ]


# ---------------------------------------------------------------------------
# the route
# ---------------------------------------------------------------------------

def route_position(state: dict, inputs_dir: Any = None) -> RoutePosition:
    """Compute where the project stands on the route to a complete config.

    Order matters: the ``current`` step is the first ACTIVE, not-done leg,
    which is what the agent should guide toward next.
    """
    from fews_agent.agent.project_intents import (
        compute_input_status,
        scan_inputs,
    )

    slots = state.get("slots") or {}
    has_capability = bool(
        slots.get("imports") or slots.get("basins")
        or slots.get("basin_name") or slots.get("extra_patterns")
    )

    # Blocking: required input CSVs for the derived intent (reuses the build's
    # own requirement list — station/interpolation conditionals included).
    scan = scan_inputs(inputs_dir)
    status = compute_input_status(state.get("intent"), scan, slots)
    missing_required = list(status.get("csvs_required_missing") or [])

    on_defaults = _imports_on_default_variables(slots)
    no_map = _nwp_imports_without_map_area(slots)
    no_adapter = _basins_without_adapter(slots)

    legs: list[Leg] = [
        Leg(
            id="capability",
            title="Add a data source or model",
            kind="blocking",
            active=True,
            done=has_capability,
            guidance=("Add a data source (e.g. GFS, HRDPS) or a basin model "
                      "to begin."),
        ),
        Leg(
            id="basin_adapter",
            title="Set each basin's model",
            kind="blocking",
            active=bool(slots.get("basins")),
            done=not no_adapter,
            guidance=(f"Which model does {no_adapter[0]} run on "
                      f"(raven, wflow, hbv96)?" if no_adapter else ""),
        ),
        Leg(
            id="source_variables",
            title="Choose each source's weather variables",
            kind="advisory",
            active=bool(_parameterizable_imports(
                [str(i) for i in (slots.get("imports") or [])])),
            done=not on_defaults,
            guidance=(f"{on_defaults[0]} is on its default variables — "
                      f"choose what it should carry, or keep the defaults."
                      if on_defaults else ""),
            detail=("default: precipitation (PC.nwp) + temperature (TA.nwp)"
                    if on_defaults else ""),
        ),
        Leg(
            id="map_area",
            title="Set the map area",
            kind="advisory",
            active=bool(no_map) or bool(slots.get("region")),
            done=not no_map,
            guidance=("Set a map area/region to crop the grids and orient the "
                      "map (or keep the default extent)." if no_map else ""),
        ),
        Leg(
            id="required_inputs",
            title="Provide the required input files",
            kind="blocking",
            active=has_capability,
            done=has_capability and not missing_required,
            guidance=(f"Provide {', '.join(missing_required)} (upload, or give "
                      f"the data in chat and I'll write it)."
                      if missing_required else ""),
        ),
        Leg(
            id="assemble",
            title="Assemble the project",
            kind="blocking",
            active=True,
            done=bool(state.get("full_build_ok")),
            guidance="Everything's in place — say 'done' to assemble the "
                     "whole project.",
        ),
    ]

    active = [lg for lg in legs if lg.active]
    blocking_open = [lg for lg in active
                     if lg.kind == "blocking" and not lg.done
                     and lg.id != "assemble"]
    advisory_open = [lg for lg in active
                     if lg.kind == "advisory" and not lg.done]
    ready = not blocking_open
    # The current step: first open blocking leg, else first open advisory,
    # else (all done) the assemble leg if not yet assembled.
    current = None
    for lg in active:
        if lg.id == "assemble":
            continue
        if not lg.done:
            current = lg
            break
    if current is None and ready and not state.get("full_build_ok"):
        current = next((lg for lg in legs if lg.id == "assemble"), None)
    if state.get("full_build_ok"):
        current = None               # arrived — the journey is complete

    return RoutePosition(
        legs=legs,
        current=current,
        blocking_open=blocking_open,
        advisory_open=advisory_open,
        ready_to_assemble=ready and has_capability,
        assembled=bool(state.get("full_build_ok")),
    )


def route_digest(state: dict, inputs_dir: Any = None) -> str:
    """Render the route position as the ROUTE grounding block for the prompt.

    States position, the single next step, what still blocks assembly, and
    open recommendations — so the model NAVIGATES (leads with the next step,
    never steers to 'done' before ``ready_to_assemble``) rather than dumping
    a menu or pushing a premature build."""
    pos = route_position(state, inputs_dir)
    lines: list[str] = []

    done = [lg.title for lg in pos.legs if lg.active and lg.done
            and lg.id != "assemble"]
    if pos.assembled:
        lines.append("The project has been assembled successfully.")
    if done:
        lines.append("Done: " + "; ".join(done) + ".")

    fixed = _fixed_variable_imports(state.get("slots") or {})
    if fixed:
        lines.append(
            "Fixed variable set (NOT selectable — never ask which variables "
            "these carry): " + ", ".join(fixed) + "."
        )

    if pos.current is not None:
        step = f"NEXT STEP: {pos.current.guidance or pos.current.title}"
        if pos.current.detail:
            step += f" ({pos.current.detail})"
        lines.append(step)

    if pos.blocking_open:
        # Use each leg's specific guidance (names the actual missing files),
        # not the generic title — "provide locations.csv, parameters.csv"
        # beats "provide the required input files".
        lines.append(
            "Still needed before the project can be assembled: "
            + "; ".join(lg.guidance or lg.title for lg in pos.blocking_open)
        )
    # The current step is already stated above; only list the OTHER open
    # advisories here so nothing is echoed twice.
    other_advisory = [lg for lg in pos.advisory_open if lg is not pos.current]
    if other_advisory:
        lines.append(
            "Recommended (optional): "
            + "; ".join(lg.guidance or lg.title for lg in other_advisory)
        )
    lines.append(
        "Ready to assemble ('done'): "
        + ("yes" if pos.ready_to_assemble else
           "NOT yet — finish the blocking steps above first")
    )
    return "\n".join(lines)
