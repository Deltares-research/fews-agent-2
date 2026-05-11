"""Generic Pydantic-introspecting field walker for /edit handlers.

Each /edit handler covers one yaml file. Most handlers share the same
mechanics: ask the configurator for one field at a time, type-aware
parsing, validate against the Pydantic model at the end. This module
extracts that common machinery so new handlers only need ~50 lines of
overrides instead of ~200.

Usage in a handler::

    from . import _generic as G

    SPEC = G.HandlerSpec(
        item_model=ModuleInstanceSet,
        list_field_on_root=("moduleInstanceSet", ModuleInstanceSets),
        labels={"id": "Set id", ...},
        hints={"moduleInstanceId": "moduleInstanceIds"},
        skip_fields={"description"},
    )

    def advance(state, message, project_dir):
        return G.advance_via_walker(state, message, project_dir, SPEC)

The walker handles state transitions for required scalar fields, list-
of-scalar fields, and the outer "add another item?" loop. Handlers
override behaviour by populating ``HandlerSpec`` fields.
"""
from __future__ import annotations

import typing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml as _yaml
from lxml import etree


# ---------------------------------------------------------------------------
# Field introspection
# ---------------------------------------------------------------------------


@dataclass
class FieldSpec:
    """One question to ask, derived from a Pydantic model field."""
    name: str
    label: str
    kind: str  # "str" | "bool" | "int" | "list_str" | "skip"
    required: bool
    hint_key: str | None = None  # e.g. "moduleInstanceIds" for ID hints


def _unwrap_optional(annotation: Any) -> tuple[Any, bool]:
    """Strip ``Optional[X]`` / ``X | None``. Returns (inner, was_optional)."""
    args = typing.get_args(annotation)
    if args and type(None) in args:
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return non_none[0], True
    return annotation, False


def _kind_of(annotation: Any) -> str:
    """Map a type annotation to a walker ``kind`` tag."""
    inner, _ = _unwrap_optional(annotation)
    origin = typing.get_origin(inner)
    if origin is list:
        list_inner = typing.get_args(inner)[0] if typing.get_args(inner) else None
        # Detect single-field id-wrapper: e.g. UserGroupRef(id: str).
        # Common in FEWS schemas where a list element is rendered as
        # ``<userGroup id="X"/>``. The configurator types plain ids;
        # the walker wraps each as {"id": "<value>"}.
        if (
            list_inner is not None
            and isinstance(list_inner, type)
            and hasattr(list_inner, "model_fields")
            and list(list_inner.model_fields.keys()) == ["id"]
        ):
            return "list_id_wrapper"
        return "list_str"
    if inner is bool:
        return "bool"
    if inner is int:
        return "int"
    # Default to string-ish for anything else (str, custom id types).
    return "str"


def discover_fields(
    model_class: type,
    *,
    labels: dict[str, str] | None = None,
    hints: dict[str, str] | None = None,
    skip_fields: set[str] | None = None,
    force_ask: set[str] | None = None,
    skip_optional: bool = True,
) -> list[FieldSpec]:
    """Walk ``model_class.model_fields`` into a list of FieldSpec.

    Args:
      model_class: a Pydantic v2 model class.
      labels: per-field human-readable prompts (override the default
        ``field name + ":"``).
      hints: per-field key into the project-context dict (e.g.
        ``{"moduleInstanceId": "moduleInstanceIds"}``).
      skip_fields: field names to omit entirely.
      force_ask: field names to include even if Pydantic-optional —
        useful for fields that have ``default_factory=list`` but are
        the whole point of the yaml (e.g. ``moduleInstanceId`` on a
        ``moduleInstanceSet``).
      skip_optional: when True, only required + force_ask fields are
        returned.
    """
    labels = labels or {}
    hints = hints or {}
    skip = skip_fields or set()
    forced = force_ask or set()
    out: list[FieldSpec] = []
    for name, info in model_class.model_fields.items():
        if name in skip:
            continue
        required = info.is_required()
        if skip_optional and not required and name not in forced:
            continue
        kind = _kind_of(info.annotation)
        label = labels.get(name) or _humanise(name)
        out.append(FieldSpec(
            name=name, label=label, kind=kind, required=required,
            hint_key=hints.get(name),
        ))
    return out


def _humanise(field_name: str) -> str:
    """Turn ``moduleInstanceId`` into ``Module instance id``."""
    out = []
    for i, ch in enumerate(field_name):
        if ch.isupper() and i > 0:
            out.append(" ")
            out.append(ch.lower())
        else:
            out.append(ch)
    s = "".join(out).strip()
    return s[:1].upper() + s[1:]


# ---------------------------------------------------------------------------
# Parsing user input
# ---------------------------------------------------------------------------


def parse_value(field: FieldSpec, raw: str) -> tuple[Any, str | None]:
    """Coerce raw user text to the field's type. Returns (value, error)."""
    raw = raw.strip()
    if field.kind == "str":
        if not raw:
            return None, f"{field.label} can't be empty"
        return raw, None
    if field.kind == "bool":
        low = raw.lower()
        if low in {"y", "yes", "true", "1"}:
            return True, None
        if low in {"n", "no", "false", "0"}:
            return False, None
        return None, f"{field.label}: answer y or n"
    if field.kind == "int":
        try:
            return int(raw), None
        except ValueError:
            return None, f"{field.label}: must be an integer"
    if field.kind == "list_str":
        # Comma-separated list (one-shot).
        items = [s.strip() for s in raw.split(",") if s.strip()]
        if not items:
            return None, f"{field.label}: list can't be empty"
        return items, None
    if field.kind == "list_id_wrapper":
        # Comma-separated ids wrapped as {"id": ...} per element.
        items = [s.strip() for s in raw.split(",") if s.strip()]
        if not items:
            return None, f"{field.label}: list can't be empty"
        return [{"id": s} for s in items], None
    return raw, None  # fallback


# ---------------------------------------------------------------------------
# Project context — project-specific ID hints
# ---------------------------------------------------------------------------


def collect_project_ids(project_dir: Path) -> dict[str, list[str]]:
    """Find moduleInstanceIds / parameterIds / locationSetIds /
    locationIds from rendered XMLs under ``validation/<project>/generated``.

    Same logic as ``modifier_types._collect_ids`` — extracted here so
    every walker-using handler can rely on it.
    """
    repo_root = _find_repo_root(project_dir)
    if repo_root is None:
        return {}
    rendered_root = repo_root / "validation" / project_dir.name / "generated"
    if not rendered_root.is_dir():
        return {}
    tag_to_key = {
        "moduleInstanceId": "moduleInstanceIds",
        "parameterId": "parameterIds",
        "locationSetId": "locationSetIds",
        "locationId": "locationIds",
        "workflowId": "workflowIds",
    }
    seen: dict[str, set[str]] = {k: set() for k in tag_to_key.values()}
    for p in rendered_root.rglob("*.xml"):
        try:
            tree = etree.fromstring(p.read_bytes())
        except etree.XMLSyntaxError:
            continue
        for tag, key in tag_to_key.items():
            for el in tree.iter("{*}" + tag):
                text = (el.text or "").strip()
                if text and "$" not in text:
                    seen[key].add(text)
    return {k: sorted(v) for k, v in seen.items()}


def _find_repo_root(start: Path) -> Path | None:
    cur = start.resolve()
    for parent in [cur, *cur.parents]:
        if (parent / "patterns").is_dir() or (parent / "pyproject.toml").is_file():
            return parent
    return None


def format_prompt(field: FieldSpec, ids: dict[str, list[str]]) -> str:
    """Format the question with up to 8 hints when applicable."""
    if field.hint_key and field.hint_key in ids:
        candidates = ids[field.hint_key]
        if candidates:
            shown = candidates[:8]
            extra = (
                f" (project has {len(candidates)} total)"
                if len(candidates) > 8 else ""
            )
            return f"{field.label} (existing: {', '.join(shown)}){extra}:"
    return f"{field.label}:"


# ---------------------------------------------------------------------------
# Handler spec — what a per-yaml override supplies
# ---------------------------------------------------------------------------


@dataclass
class HandlerSpec:
    """Configures a walker-driven /edit handler.

    Attributes:
      item_model: Pydantic model class for one *item* (e.g.
        ``ModuleInstanceSet``). The walker discovers questions from
        this class.
      list_field_on_root: ``(field_name, root_model_class)``. The
        list field on the root model where collected items go.
      labels, hints, skip_fields: forwarded to ``discover_fields``.
      output_filename: where to write the yaml in the project's
        ``inputs/`` directory.
      intro_text: shown when the edit session starts.
      add_more_prompt: shown after each item is added.
      review_summary: callable ``draft -> str``; defaults to a
        generic summary.
    """
    item_model: type
    list_field_on_root: tuple[str, type]
    output_filename: str
    intro_text: str
    add_more_prompt: str
    labels: dict[str, str] = field(default_factory=dict)
    hints: dict[str, str] = field(default_factory=dict)
    skip_fields: set[str] = field(default_factory=set)
    force_ask: set[str] = field(default_factory=set)
    # XSD-choice handling: when an item type's XSD requires *exactly one*
    # of N alternative fields, list those alternatives here. The walker
    # asks the configurator to pick one, then prompts only that field.
    # Format: (prompt_text, [(field_name, kind), ...]).
    choices: list[tuple[str, list[tuple[str, str]]]] = field(default_factory=list)
    review_summary: Callable[[dict[str, Any]], str] | None = None


# ---------------------------------------------------------------------------
# Walker state machine
# ---------------------------------------------------------------------------


def advance_via_walker(
    state: dict[str, Any],
    user_message: str,
    project_dir: Path,
    spec: HandlerSpec,
) -> tuple[str, bool]:
    """Drive one turn through the generic walker. Returns ``(reply, done)``.

    Edit-state shape under ``state['_editing']``::

      {file: ..., stage: '_start' | 'ask_add' | 'q:<i>' | 'review',
       draft: {<list_field>: [...]}, current: {...}, q_idx: int}
    """
    edit = state["_editing"]
    stage = edit.get("stage", "_start")
    msg = (user_message or "").strip()
    list_field, root_model = spec.list_field_on_root
    questions = discover_fields(
        spec.item_model,
        labels=spec.labels, hints=spec.hints,
        skip_fields=spec.skip_fields, force_ask=spec.force_ask,
    )
    edit.setdefault("draft", {})
    edit["draft"].setdefault(list_field, [])
    edit.setdefault("current", {})
    edit.setdefault("q_idx", 0)

    if stage == "_start":
        edit["stage"] = "ask_add"
        return (
            spec.intro_text + "\nAdd a new entry? (y/n)",
            False,
        )

    if stage == "ask_add":
        if _is_yes(msg):
            edit["current"] = {}
            edit["q_idx"] = 0
            edit["stage"] = "q"
            # Walker fields first (order-of-declaration); choices fire
            # after the walker queue is exhausted.
            return _ask_next(edit, questions, project_dir)
        if _is_no(msg):
            n = len(edit["draft"][list_field])
            if n == 0:
                return (
                    f"{root_model.__name__} requires at least one entry. "
                    f"Add one? (y/n)",
                    False,
                )
            edit["stage"] = "review"
            return (_default_review(edit["draft"], spec, root_model), False)
        return ("Please answer y or n. Add another? (y/n)", False)

    if stage == "choice":
        # User picks 1..N for the current choice block.
        choice_idx = edit.get("choice_idx", 0)
        prompt_text, alternatives = spec.choices[choice_idx]
        try:
            picked = int(msg) - 1
            if not 0 <= picked < len(alternatives):
                raise ValueError
        except ValueError:
            return (
                f"Pick a number 1-{len(alternatives)}.\n"
                f"{_ask_choice(spec.choices[choice_idx])}",
                False,
            )
        chosen_field, chosen_kind = alternatives[picked]
        edit["current_choice"] = (chosen_field, chosen_kind)
        edit["stage"] = "choice_value"
        # Build a synthetic FieldSpec for this choice — label from the
        # spec.labels dict if present.
        label = spec.labels.get(chosen_field) or _humanise(chosen_field)
        return (
            f"{label}:" if chosen_kind == "str" else
            f"{label} (comma-separated):" if "list" in chosen_kind else
            f"{label}:",
            False,
        )

    if stage == "choice_value":
        chosen_field, chosen_kind = edit["current_choice"]
        synthetic = FieldSpec(
            name=chosen_field,
            label=spec.labels.get(chosen_field) or _humanise(chosen_field),
            kind=chosen_kind, required=True,
        )
        value, err = parse_value(synthetic, msg)
        if err:
            return (f"{err}", False)
        edit["current"][chosen_field] = value
        # Advance to next choice block (if any) or fall through to walker.
        edit["choice_idx"] = edit.get("choice_idx", 0) + 1
        if edit["choice_idx"] < len(spec.choices):
            edit["stage"] = "choice"
            return (_ask_choice(spec.choices[edit["choice_idx"]]), False)
        # Done with choices — walk regular fields, but skip any that
        # the choice already populated.
        edit["stage"] = "q"
        return _ask_next_or_done(edit, questions, project_dir, spec)

    if stage == "q":
        q = questions[edit["q_idx"]]
        # Skip if this field was already populated by an earlier choice.
        if q.name in edit["current"]:
            edit["q_idx"] += 1
            return _ask_next_or_done(edit, questions, project_dir, spec)
        value, err = parse_value(q, msg)
        if err:
            return (f"{err}\n{format_prompt(q, _hints_for(project_dir))}", False)
        edit["current"][q.name] = value
        edit["q_idx"] += 1
        return _ask_next_or_done(edit, questions, project_dir, spec)

    if stage == "review":
        if _is_yes(msg):
            return _validate_and_write(
                edit["draft"], project_dir, spec, root_model,
            )
        if _is_no(msg):
            return (
                f"Cancelled. Run '/edit {spec.output_filename}' again.",
                True,
            )
        return ("Please answer y or n. Confirm write? (y/n)", False)

    return (f"(unknown stage {stage!r}; aborting)", True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ask_next(edit, questions, project_dir):
    q = questions[edit["q_idx"]]
    return (format_prompt(q, _hints_for(project_dir)), False)


def _ask_next_or_done(edit, questions, project_dir, spec):
    """Advance to the next walker question; if queue exhausted, run
    XSD-choice prompts (if any) before finalising the item."""
    list_field, _ = spec.list_field_on_root
    while edit["q_idx"] < len(questions):
        if questions[edit["q_idx"]].name in edit["current"]:
            edit["q_idx"] += 1
            continue
        return _ask_next(edit, questions, project_dir)
    # Walker queue exhausted. If any XSD-choice blocks remain, run them.
    if spec.choices and edit.get("choice_idx", 0) < len(spec.choices):
        edit["stage"] = "choice"
        return (_ask_choice(spec.choices[edit.get("choice_idx", 0)]), False)
    # Append item and ask whether to add another.
    edit["draft"][list_field].append(edit["current"])
    added_id = (
        edit["current"].get("id")
        or edit["current"].get("@id")
        or edit["current"].get("iconId")
        or "(item)"
    )
    edit["current"] = {}
    edit["q_idx"] = 0
    edit["choice_idx"] = 0
    edit["stage"] = "ask_add"
    n = len(edit["draft"][list_field])
    return (
        f"Added '{added_id}' (total: {n}). {spec.add_more_prompt}",
        False,
    )


def _ask_choice(choice_block: tuple[str, list[tuple[str, str]]]) -> str:
    prompt_text, alternatives = choice_block
    lines = [prompt_text]
    for i, (name, _kind) in enumerate(alternatives, start=1):
        lines.append(f"  {i}. {name}")
    lines.append("Pick a number:")
    return "\n".join(lines)


def _hints_for(project_dir: Path) -> dict[str, list[str]]:
    """Cache-friendly accessor for project IDs (one read per turn)."""
    return collect_project_ids(project_dir)


def _is_yes(s: str) -> bool:
    return s.lower() in {"y", "yes", "confirm", "ok"}


def _is_no(s: str) -> bool:
    return s.lower() in {"n", "no", "cancel", "skip"}


def _default_review(draft, spec, root_model):
    list_field, _ = spec.list_field_on_root
    items = draft.get(list_field, [])
    if spec.review_summary:
        return spec.review_summary(draft)
    lines = [f"Ready to write {spec.output_filename} with {len(items)} entry(ies):"]
    for it in items:
        ident = it.get("id") or it.get("@id") or "(no id)"
        lines.append(f"  - {ident}")
    lines.append("Confirm? (y/n)")
    return "\n".join(lines)


def _validate_and_write(draft, project_dir, spec, root_model):
    try:
        root_model.model_validate(draft)
    except Exception as exc:  # noqa: BLE001
        return (
            f"Validation failed: {type(exc).__name__}: "
            f"{str(exc)[:200]}\nEdit aborted; please /edit again.",
            True,
        )
    inputs_dir = project_dir / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    path = inputs_dir / spec.output_filename
    path.write_text(
        _yaml.safe_dump(draft, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    return (
        f"Wrote {path}. Re-run build_from_blueprint to regenerate.",
        True,
    )


__all__ = [
    "FieldSpec", "HandlerSpec",
    "discover_fields", "parse_value", "format_prompt",
    "collect_project_ids", "advance_via_walker",
]
