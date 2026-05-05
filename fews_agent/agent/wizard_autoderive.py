"""Auto-derive ``WizardSpec`` entries from existing ``GeneratorSpec`` models.

The wizard architecture is generic — given a ``WizardSpec`` it knows how
to elicit fields, validate them, and write to project state. Most FEWS
specs share a simple shape ("scalar file-level fields + one repeating
list of typed items"), and that shape can be inferred mechanically from
the Pydantic model. This module walks the SPECS registry and returns
auto-derived ``WizardSpec`` entries for everything that fits, leaving
the runner's job of "register all specs" to a single function call.

Hand-authored ``WizardSpec`` entries (e.g. ``LOCATIONS_SPEC`` with its
tuned bulk prompt and supports_attributes=True) take precedence; the
auto path only fills in specs that don't already have a manual entry.
"""
from __future__ import annotations

import inspect
import logging
import types
import typing
from decimal import Decimal
from enum import Enum
from typing import Any, get_args, get_origin

from pydantic import BaseModel

from fews_agent.generators.base import GeneratorSpec

from .wizard import (
    FileLevelSetter,
    WizardField,
    WizardGroup,
    WizardSection,
    WizardSpec,
)

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Annotation helpers
# ---------------------------------------------------------------------------


def _strip_optional(annotation: Any) -> tuple[Any, bool]:
    """Return ``(inner_type, was_optional)``.

    Handles ``Optional[X]``, ``X | None``, and ``Union[X, None]``.
    Multi-arg unions return the original annotation untouched.
    """
    origin = get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        args = [a for a in get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return args[0], True
    return annotation, False


def _classify_field_kind(
    annotation: Any,
) -> tuple[str | None, list[str] | None]:
    """Map a Pydantic field annotation to ``(kind, allowed_values)``.

    Returns ``(None, None)`` when the field is too complex for the
    wizard (dicts, nested Pydantic models — those are handled
    elsewhere via flattening). Lists of primitives become
    ``list_str`` / ``list_decimal``.
    """
    inner, _ = _strip_optional(annotation)

    # NewType (e.g. ``WarningLevelId = NewType("WarningLevelId", str)``)
    # is a function that wraps a real type. Unwrap to the supertype so
    # the rest of the classifier sees the underlying primitive.
    while hasattr(inner, "__supertype__"):
        inner = inner.__supertype__

    # Annotated[X, ...] — the actual type is the first arg.
    if get_origin(inner) is typing.Annotated:
        inner = get_args(inner)[0]

    # list[str] / list[int] etc. → list_str / list_decimal.
    origin = get_origin(inner)
    if origin is list:
        args = get_args(inner)
        if not args:
            return None, None
        item_inner, _ = _strip_optional(args[0])
        # Skip nested-Pydantic and dict items here — caller (auto-derive
        # for repeating sections) handles those at the spec level.
        if isinstance(item_inner, type) and issubclass(item_inner, BaseModel):
            return None, None
        if get_origin(item_inner) in (list, dict) or item_inner is dict:
            return None, None
        # Numeric vs string. Decimal/int/float → list_decimal so the
        # wizard validates each entry as a number; everything else is
        # list_str.
        if item_inner in (int, float, Decimal):
            return "list_decimal", None
        # Strings (incl. NewTypes / Annotated) → list_str.
        return "list_str", None
    if origin in (dict, tuple, set, frozenset):
        return None, None
    if isinstance(inner, type) and issubclass(inner, BaseModel):
        return None, None

    # Literal["a", "b", ...] → enum
    if origin is typing.Literal:
        values = [str(v) for v in get_args(inner)]
        return "enum", values

    # StrEnum / IntEnum → enum with member values
    if isinstance(inner, type) and issubclass(inner, Enum):
        values = [str(m.value) for m in inner]
        return "enum", values

    # Scalar primitives.
    if inner is bool:
        return "bool", None
    if inner is Decimal:
        return "decimal", None
    if inner in (int, float):
        return "decimal", None
    if inner is str:
        return "scalar", None

    # Pydantic constrained / Annotated str types end up as string
    # subclasses or special objects; treat anything string-shaped as
    # scalar by default.
    try:
        if isinstance(inner, type) and issubclass(inner, str):
            return "scalar", None
    except TypeError:
        pass

    # Last resort — unknown annotation, skip.
    return None, None


def _is_pydantic_model(t: Any) -> bool:
    return isinstance(t, type) and issubclass(t, BaseModel)


# ---------------------------------------------------------------------------
# Spec inspection
# ---------------------------------------------------------------------------


def _find_repeating_fields(model_class: type) -> list[tuple[str, type]]:
    """Find every ``list[<PydanticItem>]`` field on the model.

    Returns a list of ``(field_name, item_type)`` tuples in declaration
    order. ``list[dict[str, Any]]`` and ``list[str]`` etc. are skipped —
    the caller decides what to do when those exist alongside Pydantic
    lists (today: skip the spec entirely).
    """
    candidates: list[tuple[str, type]] = []
    for name, info in model_class.model_fields.items():
        annotation, _ = _strip_optional(info.annotation)
        if get_origin(annotation) is not list:
            continue
        args = get_args(annotation)
        if not args:
            continue
        item_inner, _ = _strip_optional(args[0])
        if not _is_pydantic_model(item_inner):
            continue
        candidates.append((name, item_inner))
    return candidates


def _has_disallowed_lists(model_class: type) -> bool:
    """True if the model has shapes the wizard can't elicit at all.

    ``list[dict[...]]`` is the hard blocker — that's the
    GenericXmlFile passthrough body, intentionally untyped.
    ``list[Pydantic]`` and ``list[primitive]`` are both fine: the
    former becomes a section, the latter a ``list_str`` field.
    """
    for name, info in model_class.model_fields.items():
        annotation, _ = _strip_optional(info.annotation)
        if get_origin(annotation) is not list:
            continue
        args = get_args(annotation)
        if not args:
            continue
        item_inner, _ = _strip_optional(args[0])
        if get_origin(item_inner) is dict or item_inner is dict:
            return True
    return False


def _file_level_setters_for(
    model_class: type,
    skip_fields: set[str],
) -> list[FileLevelSetter]:
    """File-level fields elicited before any items.

    Walks scalar fields plus one level into REQUIRED nested Pydantic
    objects (emitting dotted paths for the leaves). Optional nested
    Pydantic fields are skipped — expanding them produces a forest of
    optional asks the user usually wants to leave unset, and they're
    awkward to default-skip in scripted replays. Lists and dicts at
    the file level are still skipped.
    """
    out: list[FileLevelSetter] = []
    for name, info in model_class.model_fields.items():
        if name in skip_fields:
            continue
        if name == "version":  # pinned default; don't ask.
            continue
        annotation, was_optional = _strip_optional(info.annotation)
        origin = get_origin(annotation)
        if origin in (list, dict, tuple, set, frozenset):
            continue
        # Skip OPTIONAL nested Pydantic at file_level — too many asks for
        # something the user might just want to leave unset. Required
        # ones still get expanded (we have to elicit them).
        if (
            isinstance(annotation, type)
            and issubclass(annotation, BaseModel)
            and was_optional
        ):
            continue
        for wf in _flat_field(name, info):
            default_val: str | None = None
            if (
                "." not in wf.path
                and info.default is not inspect.Parameter.empty
                and info.default is not None
            ):
                try:
                    default_val = (
                        str(info.default)
                        if not isinstance(info.default, type(...))
                        else None
                    )
                except Exception:  # noqa: BLE001
                    default_val = None
            out.append(
                FileLevelSetter(
                    field=wf.path,
                    prompt=wf.path,
                    default=default_val,
                    required=not wf.optional,
                )
            )
    return out


_MAX_NESTING_DEPTH = 2  # parent.child.grandchild


def _flat_field(
    name: str,
    info: Any,
    *,
    parent_path: str = "",
    parent_optional: bool = False,
) -> list[WizardField]:
    """Return one WizardField for ``name`` (and its descendants if nested).

    Handles three cases:
      1. Plain scalar / enum / decimal / list_str / list_decimal →
         one WizardField at ``name``.
      2. Nested Pydantic (``Foo: SomeModel``) → recurse, emitting one
         field per leaf with dotted paths. Capped at ``_MAX_NESTING_DEPTH``
         to keep field-count manageable; deeper nesting produces no
         field for that branch.
      3. Other (dicts) → empty list (caller handles).
    """
    full_name = f"{parent_path}.{name}" if parent_path else name
    annotation, opt = _strip_optional(info.annotation)
    optional = parent_optional or opt or not info.is_required()

    # NewType / Annotated unwrap (mirrors _classify_field_kind).
    while hasattr(annotation, "__supertype__"):
        annotation = annotation.__supertype__
    if get_origin(annotation) is typing.Annotated:
        annotation = get_args(annotation)[0]

    # Nested Pydantic — expand up to _MAX_NESTING_DEPTH levels.
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        depth = full_name.count(".") + 1  # depth of leaves we'd emit
        if depth > _MAX_NESTING_DEPTH:
            return []
        out: list[WizardField] = []
        for child_name, child_info in annotation.model_fields.items():
            out.extend(
                _flat_field(
                    child_name,
                    child_info,
                    parent_path=full_name,
                    parent_optional=optional,
                )
            )
        return out

    # Plain field — classify and emit.
    kind, allowed = _classify_field_kind(info.annotation)
    if kind is None:
        return []
    # Promote to ref kind when the leaf name matches a known FEWS
    # cross-spec id reference (parameterId, locationId, etc.). The
    # wizard's _resolve_ref_choices then walks project_data and offers
    # the declared ids; bulk-ask validators can sanity-check the
    # extracted value belongs to that set.
    ref_source: str | None = None
    if kind == "scalar":
        from .wizard_refs import load_ref_index

        leaf_name = name  # last segment in this recursion frame
        ref_index = load_ref_index()
        if leaf_name in ref_index:
            kind = "ref"
            ref_source = ref_index[leaf_name]
    return [
        WizardField(
            path=full_name,
            prompt=full_name,
            kind=kind,
            optional=optional,
            allowed_values=allowed,
            ref_source=ref_source,
        )
    ]


def _item_fields_for(item_type: type) -> list[WizardField]:
    """Walk the item type's fields and produce WizardFields.

    Recurses one level into nested Pydantic fields, emitting dotted
    paths (e.g. ``downstreamLocation.id``). Lists and dicts inside
    items are still skipped — those would need sub-wizards.
    """
    out: list[WizardField] = []
    for name, info in item_type.model_fields.items():
        out.extend(_flat_field(name, info))
    return out


# ---------------------------------------------------------------------------
# auto_wizard_spec entry point
# ---------------------------------------------------------------------------


def _build_section(item_field_name: str, item_type: type) -> WizardSection | None:
    """Build a WizardSection from an item type. Returns None if the
    item has no derivable fields (everything's nested / lists)."""
    item_fields = _item_fields_for(item_type)
    if not item_fields:
        return None
    field_names = ", ".join(f.path for f in item_fields)
    return WizardSection(
        item_label=item_field_name,
        item_field=item_field_name,
        item_groups=[
            WizardGroup(
                name=item_type.__name__,
                description=f"Fields for one {item_type.__name__}.",
                required=True,
                fields=item_fields,
            ),
        ],
        bulk_prompt=(
            f"Tell me about a {item_field_name}. Include any of: "
            f"{field_names}. You can answer naturally."
        ),
        supports_attributes=False,
    )


def auto_wizard_spec(generator_spec: GeneratorSpec) -> WizardSpec | None:
    """Derive a ``WizardSpec`` from a ``GeneratorSpec`` automatically.

    Handles three shapes:
      1. Single ``list[Item]`` of typed Pydantic items + file-level
         scalars  → one section.
      2. Multiple ``list[Item]`` fields (e.g. Parameters has both
         parameterGroup[] and parameter[])  → one section per list.
      3. No list fields at all (file-level config like
         ``ModuleConfigProperties``)  → empty sections, file-level only.

    Returns None for shapes that don't fit (``list[dict[...]]`` body
    passthroughs, ``list[primitive]``, items with all-nested fields).
    The bulk_prompt is intentionally bland for auto-derived specs;
    hand-author a WizardSpec in ``wizard.py`` to override.
    """
    model_class = generator_spec.model_class
    if not _is_pydantic_model(model_class):
        return None

    if _has_disallowed_lists(model_class):
        return None

    repeating = _find_repeating_fields(model_class)
    sections: list[WizardSection] = []
    for item_field, item_type in repeating:
        section = _build_section(item_field, item_type)
        if section is None:
            # Item type is too nested — bail rather than partial-derive.
            return None
        sections.append(section)

    skip_fields = {name for name, _ in repeating}
    file_level = _file_level_setters_for(model_class, skip_fields=skip_fields)

    # If we ended up with neither sections nor file-level setters there's
    # nothing for the user to do. Skip.
    if not sections and not file_level:
        return None

    return WizardSpec(
        name=generator_spec.name,
        input_key=generator_spec.input_key,
        sections=sections,
        file_level=file_level,
    )


# ---------------------------------------------------------------------------
# Registry population
# ---------------------------------------------------------------------------


def auto_register_all(
    target: dict[str, WizardSpec],
    *,
    overwrite: bool = False,
) -> dict[str, str]:
    """Populate ``target`` with auto-derived ``WizardSpec`` entries.

    Returns a status dict ``{spec_name: outcome}`` where outcome is one of:
      - "manual"     — entry already present, kept as-is
      - "auto"       — auto-derived, registered
      - "skipped:<reason>" — couldn't derive (reason recorded)
    """
    from fews_agent.generators import SPECS

    status: dict[str, str] = {}
    seen: set[str] = set()
    for gs in SPECS:
        if gs.name in seen:
            continue  # SPECS may have duplicates by spec name; pick first
        seen.add(gs.name)
        if gs.name in target and not overwrite:
            status[gs.name] = "manual"
            continue
        try:
            ws = auto_wizard_spec(gs)
        except Exception as exc:  # noqa: BLE001
            status[gs.name] = f"skipped:error:{type(exc).__name__}"
            _logger.warning("auto_wizard_spec(%s) raised: %s", gs.name, exc)
            continue
        if ws is None:
            status[gs.name] = "skipped:shape"
            continue
        target[gs.name] = ws
        status[gs.name] = "auto"
    return status


__all__ = [
    "auto_wizard_spec",
    "auto_register_all",
]
