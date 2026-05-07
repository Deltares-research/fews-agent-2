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
    out: list[PatternSummary] = []
    for pat_yaml in sorted(patterns_root.rglob("pattern.yaml")):
        rel = pat_yaml.parent.relative_to(patterns_root).as_posix()
        try:
            data = yaml.safe_load(pat_yaml.read_text(encoding="utf-8"))
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
        provider = OllamaProvider(model=model)

    catalog_text = catalog_to_prompt_text(catalog)
    state_text = yaml.safe_dump(state, sort_keys=False, width=200)

    # Show only the last 6 turns of history to keep the prompt short.
    recent_history = history[-6:]
    history_text = "\n".join(
        f"  {h['role']}: {h['message']}" for h in recent_history
    ) or "  (none)"

    system = (
        "You help a configurator author a FEWS project.yaml. The user "
        "will tell you about their project across multiple turns; you "
        "incrementally fill in the project. RULES:\n"
        "- Pick ONLY patterns that appear in the catalog (use the "
        "exact `path` value, including 'auto/' prefix where present).\n"
        "- Each turn, decide what's clear enough to add NOW vs what "
        "needs ONE follow-up question. Don't ask 5 questions at once.\n"
        "- If the user mentions data they have (CSVs, station lists), "
        "note them in `missing_data_to_add`.\n"
        "- Set `ready_to_write=true` only when at least 1 pattern is "
        "in state and there are no obvious gaps you'd ask about.\n"
        "- Be conservative: prefer asking over guessing. The user "
        "will tell you when they're done.\n"
        "- Output ONLY the JSON the schema asks for."
    )

    user = (
        f"Catalog ({len(catalog)} patterns):\n{catalog_text}\n\n"
        f"Current project state:\n{state_text}\n"
        f"Recent conversation:\n{history_text}\n\n"
        f"User just said: {user_message!r}\n\n"
        f"Propose updates and the next question (or set ready_to_write=true)."
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
        "output_root": f"../../../validation/{project_name}/generated",
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
        provider = OllamaProvider(model=model)

    catalog_text = catalog_to_prompt_text(catalog)
    state_text = yaml.safe_dump(state, sort_keys=False, width=200)
    recent_history = history[-6:]
    history_text = "\n".join(
        f"  {h['role']}: {h['message']}" for h in recent_history
    ) or "  (none)"

    system = (
        "You help a configurator author a FEWS project. Treat the "
        "current project state as a FORM with slots that get filled in "
        "across turns. RULES — strict:\n"
        "1) NEVER remove or empty a slot that is already filled. If "
        "you think the user wants something removed, put it in "
        "`removal_proposals` with a reason; the user will confirm.\n"
        "2) Patterns are ADDITIVE: each turn you may add patterns to "
        "`patterns_to_add` (use exact `path` from the catalog). "
        "Don't re-add patterns already in state.\n"
        "3) Per pattern, set ONLY the variables the catalog lists for "
        "that pattern. Hallucinated vars will be silently dropped.\n"
        "4) Settings (singleton_seeds) are key-value updates: include "
        "ONLY changes the user explicitly stated.\n"
        "5) Ask AT MOST ONE clarifying question per turn (the most "
        "important missing slot). Don't fire 5 questions at once.\n"
        "6) Output ONLY the JSON the schema asks for."
    )

    user = (
        f"Catalog ({len(catalog)} patterns):\n{catalog_text}\n\n"
        f"Current project state:\n{state_text}\n"
        f"Recent conversation:\n{history_text}\n\n"
        f"User just said: {user_message!r}\n\n"
        f"Extract slot fills from the user's message. Add patterns "
        f"or update settings only when the user explicitly mentioned "
        f"them. Propose removals only if the user explicitly asked. "
        f"Ask one focused question for the most important missing "
        f"info, or null if nothing's missing."
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
    "write_project",
]
