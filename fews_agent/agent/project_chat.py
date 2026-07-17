"""Prose → project.yaml via qwen.

The conversational front-end of the build pipeline. Configurator types
a sentence describing their project; this module builds a catalog of
available patterns, calls qwen to match prose to patterns, and emits
a draft ``project.yaml``.

Single-turn for now — qwen reads the catalog + prose once, returns
its best draft. The configurator reviews and edits the yaml before
running the build. Multi-turn clarifications can come later.

The LLM operates on a tightly-bounded task: pick from a fixed list
of patterns + propose variable values. It can't invent new patterns
or hallucinate XML structure — those are constrained by the catalog
and the deterministic engine that consumes the project.yaml.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment

from .providers.ollama_provider import OllamaProvider


# ---------------------------------------------------------------------------
# Pattern catalog
# ---------------------------------------------------------------------------

@dataclass
class PatternSummary:
    """Compact view of one pattern for the LLM."""

    path: str            # e.g. "auto/nwp_grid_eccc_HRDPS"
    name: str
    description: str
    keywords: list[str]
    variables: dict[str, dict[str, Any]]  # var_name → {type, default, ...}


def build_pattern_catalog(patterns_root: Path) -> list[PatternSummary]:
    """Walk patterns/ and summarise every pattern.yaml.

    The catalog is what the LLM sees — it can ONLY pick patterns that
    appear here. Mechanical names from the auto-derived patterns make
    matching harder; semantic names from polished patterns are
    easier. Either way, the description + keywords carry the semantic
    weight.
    """
    # Permissive env: pattern.yaml may contain {% if %}/{% for %} blocks
    # (for the per-instance render). Empty-context rendering strips them
    # so yaml.safe_load can parse the surrounding metadata.
    discovery_env = Environment(keep_trailing_newline=True)

    out: list[PatternSummary] = []
    for pat_yaml in sorted(patterns_root.rglob("pattern.yaml")):
        rel = pat_yaml.parent.relative_to(patterns_root).as_posix()
        try:
            raw_text = pat_yaml.read_text(encoding="utf-8")
            stripped = discovery_env.from_string(raw_text).render()
            data = yaml.safe_load(stripped)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        out.append(PatternSummary(
            path=rel,
            name=data.get("name", rel),
            description=data.get("description", "").strip(),
            keywords=data.get("keywords", []),
            variables=data.get("variables", {}),
        ))
    return out


def catalog_to_prompt_text(catalog: list[PatternSummary]) -> str:
    """One compact line per pattern, for the LLM context."""
    lines = []
    for p in catalog:
        var_summary = ", ".join(
            f"{n}({s.get('type','str')})" for n, s in p.variables.items()
        )
        keywords = ", ".join(p.keywords) if p.keywords else "—"
        # Truncate description so the prompt stays readable.
        desc = (p.description or p.name)[:120]
        lines.append(
            f"- path: {p.path}\n"
            f"  desc: {desc}\n"
            f"  keywords: [{keywords}]\n"
            f"  vars: {var_summary or '(none)'}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Multi-turn LLM call
# ---------------------------------------------------------------------------

def initial_state(project_name: str) -> dict[str, Any]:
    """Empty project state at turn 0."""
    return {
        "name": project_name,
        "patterns": [],
        "singleton_seeds": {"Locations": {"geoDatum": "WGS 1984"}},
        "missing_data": [],
    }


def propose_updates(
    state: dict[str, Any],
    history: list[dict[str, str]],
    user_message: str,
    catalog: list[PatternSummary],
    provider: OllamaProvider | None = None,
    model: str = "qwen2.5:7b-instruct",
) -> dict[str, Any]:
    """One turn of the conversation. Returns updates + next question.

    The LLM sees: catalog + current state + recent history + new user
    message. It returns: deltas to merge into state, optionally a next
    question to ask, and a flag for whether the project is ready to
    write.

    Returns dict with keys:
      - ``patterns_to_add``: list of {pattern: path, instances: [...]}
      - ``patterns_to_remove``: list of pattern paths
      - ``singleton_seed_updates``: dict to merge into state.singleton_seeds
      - ``missing_data_to_add``: list of file names
      - ``next_question``: str or null
      - ``ready_to_write``: bool
      - ``reasoning``: str — why qwen made these picks (for the log)
    """
    if provider is None:
        from .providers.factory import get_provider_or_ollama
        provider = get_provider_or_ollama(model)

    catalog_text = catalog_to_prompt_text(catalog)
    state_text = yaml.safe_dump(state, sort_keys=False, width=200)

    # Show only the last 6 turns of history to keep the prompt short.
    recent_history = history[-6:]
    history_text = "\n".join(
        f"  {h['role']}: {h['message']}" for h in recent_history
    ) or "  (none)"

    from fews_agent.agent import prompts

    system = prompts.load("propose_updates.system")
    user = prompts.load(
        "propose_updates.user",
        n_patterns=len(catalog), catalog_text=catalog_text,
        state_text=state_text, history_text=history_text,
        user_message=repr(user_message),
    )

    schema = {
        "type": "object",
        "properties": {
            "patterns_to_add": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string"},
                        "instances": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": True,
                            },
                        },
                    },
                    "required": ["pattern", "instances"],
                },
            },
            "patterns_to_remove": {
                "type": "array", "items": {"type": "string"},
            },
            "singleton_seed_updates": {
                "type": "object",
                "additionalProperties": {"type": "object"},
            },
            "missing_data_to_add": {
                "type": "array", "items": {"type": "string"},
            },
            "next_question": {"type": ["string", "null"]},
            "ready_to_write": {"type": "boolean"},
            "reasoning": {"type": "string"},
        },
        "required": ["ready_to_write"],
    }

    resp = provider.generate_json(system=system, user=user, schema=schema)
    data = resp.data or {}
    # Defaults — be lenient about missing keys in the LLM response.
    data.setdefault("patterns_to_add", [])
    data.setdefault("patterns_to_remove", [])
    data.setdefault("singleton_seed_updates", {})
    data.setdefault("missing_data_to_add", [])
    data.setdefault("next_question", None)
    data.setdefault("ready_to_write", False)
    data.setdefault("reasoning", "")
    return data


def apply_updates(
    state: dict[str, Any],
    updates: dict[str, Any],
    catalog: list[PatternSummary],
) -> list[str]:
    """Mutate ``state`` with the LLM's proposed updates. Drop hallucinated
    pattern paths AND hallucinated variables. Returns notes to log."""
    catalog_by_path = {p.path: p for p in catalog}
    notes: list[str] = []

    # Add patterns (drop hallucinated paths).
    existing_paths = {p["pattern"] for p in state.get("patterns", [])}
    for entry in updates.get("patterns_to_add", []):
        path = entry.get("pattern", "")
        cat_entry = catalog_by_path.get(path)
        if cat_entry is None:
            notes.append(
                f"dropped pattern {path!r} (not in catalog)"
            )
            continue
        # Filter each instance dict: keep only variables the pattern
        # declares. Hallucinated vars get dropped with a note.
        valid_var_names = set(cat_entry.variables.keys())
        clean_instances = []
        for inst in entry.get("instances", []):
            clean = {k: v for k, v in inst.items() if k in valid_var_names}
            dropped = set(inst.keys()) - valid_var_names
            if dropped:
                notes.append(
                    f"dropped vars {sorted(dropped)!r} from "
                    f"{path} (not in pattern)"
                )
            clean_instances.append(clean)
        clean_entry = {"pattern": path, "instances": clean_instances}

        if path in existing_paths:
            for p in state["patterns"]:
                if p["pattern"] == path:
                    # Dedup: skip instances that exactly match existing.
                    existing_inst_repr = {
                        repr(sorted(i.items())) for i in p.get("instances", [])
                    }
                    for ci in clean_instances:
                        if repr(sorted(ci.items())) not in existing_inst_repr:
                            p.setdefault("instances", []).append(ci)
                    break
        else:
            state["patterns"].append(clean_entry)
            existing_paths.add(path)

    # Remove patterns.
    for path in updates.get("patterns_to_remove", []):
        state["patterns"] = [
            p for p in state["patterns"] if p["pattern"] != path
        ]

    # Singleton seed updates.
    for cls_name, fields in updates.get("singleton_seed_updates", {}).items():
        state.setdefault("singleton_seeds", {}).setdefault(cls_name, {}).update(fields)

    # Missing-data reminders.
    for fname in updates.get("missing_data_to_add", []):
        if fname not in state.get("missing_data", []):
            state.setdefault("missing_data", []).append(fname)

    return notes


# ---------------------------------------------------------------------------
# Project assembly
# ---------------------------------------------------------------------------

def write_project(
    state: dict[str, Any],
    output_dir: Path,
) -> Path:
    """Write project.yaml from the final state. Creates inputs/ skeleton."""
    project_name = state["name"]
    project: dict[str, Any] = {
        "name": project_name,
        "output_root": "generated",
        "patterns": state.get("patterns", []),
        "singleton_seeds": state.get("singleton_seeds", {}),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "inputs").mkdir(exist_ok=True)
    project_path = output_dir / "project.yaml"
    project_path.write_text(
        yaml.safe_dump(project, sort_keys=False, width=200),
        encoding="utf-8",
    )
    return project_path


# ---------------------------------------------------------------------------
# Slot-filling architecture (Issue 1 fix)
# ---------------------------------------------------------------------------

# Common configurator-spelled values that should normalise to the
# canonical FEWS values. Add freely as we hit more cases.
_VALUE_NORMALISERS: dict[str, dict[str, str]] = {
    "geoDatum": {
        "WGS 84": "WGS 1984",
        "WGS84": "WGS 1984",
        "wgs 84": "WGS 1984",
        "wgs84": "WGS 1984",
    },
}


def _normalise_setting(field: str, value: Any) -> Any:
    """Map common configurator spellings to canonical FEWS values."""
    if not isinstance(value, str):
        return value
    table = _VALUE_NORMALISERS.get(field, {})
    return table.get(value.strip(), value)


def propose_slot_fills(
    state: dict[str, Any],
    history: list[dict[str, str]],
    user_message: str,
    catalog: list[PatternSummary],
    provider: OllamaProvider | None = None,
    model: str = "qwen2.5:7b-instruct",
) -> dict[str, Any]:
    """One turn — LLM extracts slot values from the user's message.

    Constraints baked into the prompt:
      - Patterns are ADDITIVE. The LLM never removes a pattern; it
        can only PROPOSE removal as ``removal_proposals``, which the
        user has to confirm in a later turn.
      - Settings can be UPDATED but each update is logged so the user
        sees what changed.
      - One question per turn maximum.
      - If a slot is unfilled and the user's message doesn't fill it,
        the LLM asks about it; otherwise the agent uses defaults
        from the pattern catalog (no LLM judgment needed).
    """
    if provider is None:
        from .providers.factory import get_provider_or_ollama
        provider = get_provider_or_ollama(model)

    catalog_text = catalog_to_prompt_text(catalog)
    state_text = yaml.safe_dump(state, sort_keys=False, width=200)
    recent_history = history[-6:]
    history_text = "\n".join(
        f"  {h['role']}: {h['message']}" for h in recent_history
    ) or "  (none)"

    from fews_agent.agent import prompts

    system = prompts.load("propose_slot_fills.system")
    user = prompts.load(
        "propose_slot_fills.user",
        n_patterns=len(catalog), catalog_text=catalog_text,
        state_text=state_text, history_text=history_text,
        user_message=repr(user_message),
    )

    schema = {
        "type": "object",
        "properties": {
            "patterns_to_add": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string"},
                        "instances": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": True,
                            },
                        },
                    },
                    "required": ["pattern", "instances"],
                },
            },
            "settings_updates": {
                "type": "object",
                "additionalProperties": {"type": "object"},
            },
            "removal_proposals": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": ["pattern", "reason"],
                },
            },
            "missing_data_to_add": {
                "type": "array", "items": {"type": "string"},
            },
            "clarifying_question": {"type": ["string", "null"]},
            "reasoning": {"type": "string"},
        },
        "required": [],
    }

    resp = provider.generate_json(system=system, user=user, schema=schema)
    data = resp.data or {}
    data.setdefault("patterns_to_add", [])
    data.setdefault("settings_updates", {})
    data.setdefault("removal_proposals", [])
    data.setdefault("missing_data_to_add", [])
    data.setdefault("clarifying_question", None)
    data.setdefault("reasoning", "")
    return data


def apply_slot_fills(
    state: dict[str, Any],
    proposal: dict[str, Any],
    catalog: list[PatternSummary],
) -> tuple[list[str], list[dict[str, Any]]]:
    """Apply additive updates to state. Returns (notes, pending_removals).

    pending_removals is a list of ``{pattern, reason}`` dicts the
    runner must confirm with the user before applying.
    """
    catalog_by_path = {p.path for p in catalog}
    catalog_lookup = {p.path: p for p in catalog}
    notes: list[str] = []

    # 1. Add patterns (additive, deduped, var-filtered).
    existing_paths = {p["pattern"] for p in state.get("patterns", [])}
    for entry in proposal.get("patterns_to_add", []):
        path = entry.get("pattern", "")
        cat = catalog_lookup.get(path)
        if cat is None:
            notes.append(f"dropped {path!r}: not in catalog")
            continue
        valid_var_names = set(cat.variables.keys())
        clean_instances = []
        for inst in entry.get("instances", []):
            clean = {k: v for k, v in inst.items() if k in valid_var_names}
            dropped = set(inst.keys()) - valid_var_names
            if dropped:
                notes.append(
                    f"dropped vars {sorted(dropped)} from {path}: "
                    f"not declared by pattern"
                )
            clean_instances.append(clean)

        if path in existing_paths:
            for p in state["patterns"]:
                if p["pattern"] == path:
                    existing_inst_repr = {
                        repr(sorted(i.items())) for i in p.get("instances", [])
                    }
                    for ci in clean_instances:
                        if repr(sorted(ci.items())) not in existing_inst_repr:
                            p.setdefault("instances", []).append(ci)
                    break
        else:
            state["patterns"].append({
                "pattern": path, "instances": clean_instances,
            })
            existing_paths.add(path)

    # 2. Settings updates with normalisation.
    for cls_name, fields in proposal.get("settings_updates", {}).items():
        target = state.setdefault("singleton_seeds", {}).setdefault(
            cls_name, {}
        )
        for field_name, value in (fields or {}).items():
            normed = _normalise_setting(field_name, value)
            if normed != value:
                notes.append(
                    f"normalised {cls_name}.{field_name}: "
                    f"{value!r} → {normed!r}"
                )
            target[field_name] = normed

    # 3. Missing-data hints.
    for fname in proposal.get("missing_data_to_add", []):
        if fname not in state.get("missing_data", []):
            state.setdefault("missing_data", []).append(fname)

    # 4. Removal proposals — DON'T apply; return for the runner to confirm.
    pending_removals = []
    for r in proposal.get("removal_proposals", []):
        path = r.get("pattern")
        if path and path in existing_paths:
            pending_removals.append(r)
        elif path:
            notes.append(
                f"removal proposal for {path!r} ignored: not in state"
            )

    return notes, pending_removals


def is_ready_to_write(
    state: dict[str, Any],
    catalog: list[PatternSummary],
) -> tuple[bool, list[str]]:
    """Deterministic check: does state have enough to write a project.yaml?

    Returns (ready, reasons_not_ready). Used instead of LLM-decided
    ``ready_to_write`` to avoid the model committing prematurely.
    """
    reasons: list[str] = []
    if not state.get("patterns"):
        reasons.append("no patterns in state")
        return False, reasons

    catalog_lookup = {p.path: p for p in catalog}
    for entry in state["patterns"]:
        path = entry.get("pattern", "")
        cat = catalog_lookup.get(path)
        if cat is None:
            reasons.append(f"pattern {path!r} not in catalog")
            continue
        for inst_idx, inst in enumerate(entry.get("instances", [])):
            for var_name, var_spec in cat.variables.items():
                if not var_spec.get("required"):
                    continue
                if var_name in inst:
                    continue
                if "default" in var_spec:
                    continue  # default fills it
                reasons.append(
                    f"{path}[{inst_idx}].{var_name} required but missing"
                )
    return len(reasons) == 0, reasons


def apply_removal(state: dict[str, Any], pattern_path: str) -> bool:
    """Remove a pattern from state. Called only after user confirms."""
    before = len(state.get("patterns", []))
    state["patterns"] = [
        p for p in state.get("patterns", [])
        if p["pattern"] != pattern_path
    ]
    return len(state["patterns"]) < before


# ---------------------------------------------------------------------------
# Mid-chat edit mutators (stepwise add / remove / set-variable)
# ---------------------------------------------------------------------------
#
# These operate on ``state["slots"]`` — NOT ``state["patterns"]`` — because
# the chat loop fully rebuilds ``patterns`` from slots every turn via the
# active intent's resolver (chat_step._resolve_patterns). Anything written
# straight to ``patterns`` is clobbered on the next resolve; slot edits
# survive. The caller re-resolves after each mutation.
#
# They are intent-agnostic: they only touch the canonical slots
# (``imports``, ``basins``, ``grid_resolution``, ``forecast_horizon_hours``,
# ``data_types``) that the resolvers read. Whether the active intent's
# resolver actually consumes a given slot is the caller's concern.


def _clear_built_for_label(state: dict[str, Any], label: str) -> None:
    """Drop any ``built_modules`` marker for a label that just changed.

    Markers are ``"<pattern>::<label>"``; a changed/removed module's
    rendered output is now stale, so the phase plan should show it as
    needing a rebuild.
    """
    built = state.get("built_modules") or []
    state["built_modules"] = [
        k for k in built if not str(k).endswith(f"::{label}")
    ]


def add_module(
    state: dict[str, Any],
    target: Any,
    target_kind: str,
) -> str:
    """Add an import or basin to the slots (additive, deduped).

    ``target_kind == "import"``: ``target`` is an import name (str),
    appended to ``slots["imports"]``.
    ``target_kind == "basin"``: ``target`` is a ``{"basin_name", ...,
    "model_adapter"}`` dict (or a bare basin-name str), appended to
    ``slots["basins"]``.

    Returns a human-readable note. Caller re-resolves patterns.
    """
    slots = state.setdefault("slots", {})
    if target_kind == "import":
        name = str(target).strip()
        imports = slots.setdefault("imports", [])
        if any(str(x).lower() == name.lower() for x in imports):
            return f"{name} is already an import; nothing added."
        imports.append(name)
        return f"Added import {name}."
    if target_kind == "basin":
        if isinstance(target, dict):
            pair = {
                "basin_name": str(target.get("basin_name", "")).strip(),
                "model_adapter": str(target.get("model_adapter") or "").strip()
                or None,
            }
        else:
            pair = {"basin_name": str(target).strip(), "model_adapter": None}
        if not pair["basin_name"]:
            return "No basin name given; nothing added."
        basins = slots.setdefault("basins", [])
        if any(
            isinstance(b, dict)
            and b.get("basin_name", "").lower() == pair["basin_name"].lower()
            for b in basins
        ):
            return f"Basin {pair['basin_name']} is already in the project."
        basins.append(pair)
        adapter_txt = (
            f" using {pair['model_adapter']}" if pair["model_adapter"]
            else " (no model adapter yet — set one with /set <basin> adapter <x>)"
        )
        return f"Added basin {pair['basin_name']}{adapter_txt}."
    return f"Unknown target kind {target_kind!r}; nothing added."


def remove_module(
    state: dict[str, Any],
    target: str,
    target_kind: str,
) -> str:
    """Remove an import or basin from the slots (subtractive).

    Matches case-insensitively. Clears any built-module marker for the
    target so the phase plan reflects the change. Returns a note.
    """
    slots = state.setdefault("slots", {})
    name = str(target).strip()
    if target_kind == "import":
        imports = slots.get("imports") or []
        kept = [x for x in imports if str(x).lower() != name.lower()]
        if len(kept) == len(imports):
            return f"{name} is not an import; nothing removed."
        slots["imports"] = kept
        # Drop any per-import variable overrides for the removed import.
        overrides = slots.get("import_overrides")
        if isinstance(overrides, dict):
            for k in [k for k in overrides if k.lower() == name.lower()]:
                overrides.pop(k, None)
        _clear_built_for_label(state, name)
        return f"Removed import {name}."
    if target_kind == "basin":
        basins = slots.get("basins") or []
        kept = [
            b for b in basins
            if not (
                isinstance(b, dict)
                and b.get("basin_name", "").lower() == name.lower()
            )
        ]
        if len(kept) == len(basins):
            return f"{name} is not a basin in the project; nothing removed."
        slots["basins"] = kept
        # Keep the singular fallback slots consistent so the resolver and
        # readiness check don't resurrect the basin from basin_name.
        if str(slots.get("basin_name", "")).lower() == name.lower():
            slots.pop("basin_name", None)
            slots.pop("model_adapter", None)
        _clear_built_for_label(state, name)
        return f"Removed basin {name}."
    return f"Unknown target kind {target_kind!r}; nothing removed."


# Canonical variable names that ``set_variable`` understands. Project-wide
# scalars are stored on the matching top-level slot; ``model_adapter`` is
# scoped to the named basin; ``data_types`` is an append-to-list.
_SETTABLE_VARIABLES = frozenset(
    {"grid_resolution", "forecast_horizon_hours", "data_types", "model_adapter"}
)


def set_variable(
    state: dict[str, Any],
    target: str,
    variable: str,
    value: Any,
) -> str:
    """Set one instance variable on a named module (already-canonical args).

    The caller (chat_step.apply_edit_action) is responsible for resolving
    synonyms to a canonical ``variable`` name and parsing ``value`` to its
    canonical form (e.g. "half-degree" → "0p50").

    Scoping: ``grid_resolution`` and ``forecast_horizon_hours`` are scoped
    to a single named import via ``slots["import_overrides"][<import>]``
    (the resolver applies override → project-level fallback per instance).
    When no valid import is named (e.g. NL "make it half-degree"), the
    value lands on the project-level slot as the default for every NWP
    import without its own override. ``model_adapter`` is scoped to the
    named basin. The returned note states the scope.
    """
    slots = state.setdefault("slots", {})
    name = str(target).strip()
    if variable not in _SETTABLE_VARIABLES:
        return (
            f"Don't know how to set {variable!r}. Settable: "
            f"{', '.join(sorted(_SETTABLE_VARIABLES))}."
        )

    if variable == "model_adapter":
        basins = slots.get("basins") or []
        for b in basins:
            if (
                isinstance(b, dict)
                and b.get("basin_name", "").lower() == name.lower()
            ):
                b["model_adapter"] = value
                if str(slots.get("basin_name", "")).lower() == name.lower():
                    slots["model_adapter"] = value
                _clear_built_for_label(state, b["basin_name"])
                return f"Set {b['basin_name']} model adapter to {value}."
        return f"{name} is not a basin in the project; nothing changed."

    # NWP scalars (grid_resolution / forecast_horizon_hours). Scoped to a
    # single named import when one is given (per-instance, Slice 4);
    # otherwise applied project-wide as the default for every NWP import
    # that lacks its own override.
    imports = [str(x) for x in (slots.get("imports") or [])]
    canonical = next((x for x in imports if x.lower() == name.lower()), None)
    if variable in {"grid_resolution", "forecast_horizon_hours"}:
        if canonical:
            overrides = slots.setdefault("import_overrides", {})
            overrides.setdefault(canonical, {})[variable] = value
            _clear_built_for_label(state, canonical)
            return f"Set {variable} to {value} for {canonical} only."
        # No named import (NL "make it half-degree") or an unknown name →
        # project-wide default. A non-empty unknown name gets a note so a
        # typo doesn't silently become a project-wide change.
        slots[variable] = value
        _clear_built_for_label(state, name)
        scope = (
            "" if not name
            else f" (note: {name} is not a current import; applied project-wide)"
        )
        return (
            f"Set {variable} to {value} (default for all NWP imports "
            f"without a per-import override){scope}."
        )

    if variable == "data_types":
        dts = slots.setdefault("data_types", [])
        added = [
            v for v in (value if isinstance(value, list) else [value])
            if v not in dts
        ]
        dts.extend(added)
        _clear_built_for_label(state, name)
        if not added:
            return f"{value} already in the parameter list; nothing added."
        return f"Added parameter(s) {', '.join(added)} (project-wide in v1)."

    return f"Don't know how to set {variable!r}."


def grid_bbox(
    first_x: float, first_y: float, columns: int, rows: int, cell_size: float,
) -> tuple[float, float, float, float]:
    """West/south/east/north extent of a north-up lat/lon grid.

    ``first_x``/``first_y`` are the FEWS ``firstCellCenter`` — the CENTRE of
    the top-left (north-west) cell — so the grid's west/north edges sit half a
    cell beyond it, and rows run south. Used by the coordinates subwindow to
    draw the grid box on a map in real time.
    """
    cs = float(cell_size)
    cols = int(columns)
    r = int(rows)
    west = float(first_x) - cs / 2
    north = float(first_y) + cs / 2
    east = west + cols * cs
    south = north - r * cs
    return (west, south, east, north)


def set_grid_geometry(
    state: dict, name: str, *,
    first_x: float, first_y: float, columns: int, rows: int,
) -> str:
    """Set an NWP import's grid geometry: firstCellCenter (x, y) + columns (X)
    + rows (Y). Cell size is **inherited** — the build's resolution/default
    rewriter sets ``xCellSize``/``yCellSize``; this only repositions the grid's
    top-left cell centre and resizes the row/column count, so it composes with
    (and overrides) the region-bbox crop.

    Stored as the per-import ``grid_geometry`` override
    (``slots["import_overrides"][<import>]``, scoped like grid_resolution). The
    build stamps it onto the matching ``<regular>`` gridsFile entry. Returns a
    human note; the caller re-resolves patterns.
    """
    slots = state.setdefault("slots", {})
    imports = [str(x) for x in (slots.get("imports") or [])]
    canonical = next(
        (x for x in imports if x.lower() == str(name).lower()), str(name),
    )
    geom = {
        "first_x": float(first_x), "first_y": float(first_y),
        "columns": int(columns), "rows": int(rows),
    }
    overrides = slots.setdefault("import_overrides", {})
    overrides.setdefault(canonical, {})["grid_geometry"] = geom
    _clear_built_for_label(state, canonical)
    return (
        f"Set grid geometry for {canonical}: firstCellCenter="
        f"({first_x}, {first_y}), {columns} cols x {rows} rows "
        f"(cell size inherited)."
    )


__all__ = [
    "PatternSummary",
    "build_pattern_catalog",
    "catalog_to_prompt_text",
    "initial_state",
    "propose_updates",
    "apply_updates",
    "propose_slot_fills",
    "apply_slot_fills",
    "is_ready_to_write",
    "apply_removal",
    "add_module",
    "remove_module",
    "set_variable",
    "set_grid_geometry",
    "grid_bbox",
    "write_project",
]
