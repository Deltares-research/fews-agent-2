"""Cross-file ID reference checker.

Answers the question the XSD cannot: when file A says
`<moduleInstanceId>ImportGFS</moduleInstanceId>`, does something actually
declare `ImportGFS` as a ModuleInstanceId? XSD says "this element is
allowed here"; semantic says "the value you put in it resolves."

How it works
------------
The `fews_agent.schema.ids` module tags every cross-file FEWS identifier
with a dedicated `NewType` (LocationId, ParameterId, ModuleInstanceId,
...). `Pydantic v2` preserves those NewType annotations on model fields.
We reflect over `model_fields[name].annotation`, unwrap
`Optional`/`list`/`Union`, and every NewType-typed leaf becomes a
candidate (declaration or reference).

Declarations come from two sources:
  1. DECLARING_MODELS — models whose *field named `id`* declares the
     enclosing thing (Locations.location[].id declares LocationId;
     Parameters.parameterGroup[].parameter[].id declares ParameterId;
     Topology groups/nodes recursively declare TopologyNodeId).
  2. FILENAME_DECLARES — file types whose id is the filename, not a
     field on the model (UnitConversions files are referenced by stem).

Everything else is a reference. Refs are checked against the declared
registry; values containing FEWS runtime substitution tokens (`$VAR$`,
`@pattern@`, `%REGION%`, `%TIME_ZERO(...)%`) are counted as placeholders
skipped, separate from unresolved misses.

Known scope limits (deliberate, for first iteration)
----------------------------------------------------
  - Module-local IDs (VariableId, ModuleParameterId, ModuleParameterGroupId)
    are declared *and* referenced within a single module config. This
    validator doesn't enforce module-local scope yet — it ignores those
    NewTypes entirely rather than cross-checking them globally, which
    would produce false positives.
  - LocationSetIds, FilterIds, etc. are declared inside generic-body
    files (GenericXmlFile.body: dict). They are invisible to the
    reflection walker. References to them from typed models will be
    reported as unresolved until we add filename or dict-walk support.
"""
from __future__ import annotations

import re
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Union, get_args, get_origin

from pydantic import BaseModel

from fews_agent.schema import (
    ForecastLengthEstimator,
    GeneralAdapterRun,
    IdMap,
    Locations,
    ModifierTypes,
    ModuleInstanceDescriptors,
    ModuleInstanceSets,
    Parameters,
    Permissions,
    Qualifiers,
    ThresholdGroups,
    ThresholdValueSets,
    ThresholdWarningLevels,
    TimeSeriesDisplay,
    TimeSeriesImportRun,
    Topology,
    TransformationModule,
    UnitConversions,
    UserGroups,
    ValidationRuleSets,
    Workflow,
    WorkflowDescriptors,
)

# Declaring file types: every `id`-named NewType field inside any of
# these model trees declares that ID for global lookup.
DECLARING_MODELS: set[type[BaseModel]] = {
    Locations,
    Parameters,
    Qualifiers,
    ThresholdWarningLevels,
    ThresholdGroups,
    ThresholdValueSets,
    ValidationRuleSets,
    Permissions,
    UserGroups,
    ModuleInstanceSets,
    ModuleInstanceDescriptors,
    WorkflowDescriptors,
    Topology,
    ModifierTypes,
    TimeSeriesDisplay,  # declares ClassBreaksId via classBreaks[].id
}

# File types whose identifier equals the filename stem. Maps model class →
# the NewType name declared by the filename (stem of spec.output_relpath).
#
# IdMap and UnitConversions have no id attribute on the root — the file
# IS the id. Workflow declares WorkflowId via filename; WorkflowDescriptors
# then names which workflows are user-visible, but sub-workflows invoked
# from other workflows are only file-declared.
#
# Module configs (Import / Preprocess / DataProcessing / ModelRun / ...)
# contribute a declared ModuleInstanceId via filename. ModuleInstance-
# Descriptors also declares ModuleInstanceIds; either source suffices.
FILENAME_DECLARES: dict[type[BaseModel], str] = {
    UnitConversions: "UnitConversionsId",
    IdMap: "IdMapId",
    Workflow: "WorkflowId",
    TransformationModule: "ModuleInstanceId",
    GeneralAdapterRun: "ModuleInstanceId",
    TimeSeriesImportRun: "ModuleInstanceId",
    ForecastLengthEstimator: "ModuleInstanceId",
}

# NewTypes whose scope is a single module-config file, not the whole
# config set. Skip cross-file lookup for these to avoid false positives.
_MODULE_LOCAL = frozenset({
    "VariableId",
    "ModuleParameterId",
    "ModuleParameterGroupId",
})

# FEWS runtime substitution tokens. Examples observed in tutorial:
#   $MODELNAME2$  — property placeholder resolved from workflow <properties>
#   @pattern@     — used in some import filename templates
#   %REGION%      — scheduled-task parameter substitution
#   %TIME_ZERO(unit='day',multiplier=-7)% — parametrized scheduler token
# A value containing any of these is not a real id yet; count as skipped
# rather than unresolved, so the report separates runtime-substitution
# noise from actual broken references.
_PLACEHOLDER_PATTERNS = (
    re.compile(r"\$[A-Za-z0-9_]+\$"),
    re.compile(r"@[A-Za-z0-9_.\-]+@"),
    re.compile(r"%[A-Za-z0-9_()=,'\-]+%"),
)


def is_placeholder(value: str) -> bool:
    return any(p.search(value) for p in _PLACEHOLDER_PATTERNS)


@dataclass(frozen=True)
class IdRef:
    """One id occurrence found while walking a loaded model."""

    id_type_name: str
    value: str
    # e.g. "Locations.xml:location[3].parentLocationId"
    source: str


@dataclass
class SemanticReport:
    declared: dict[str, set[str]] = field(default_factory=dict)
    refs: list[IdRef] = field(default_factory=list)
    placeholders: list[IdRef] = field(default_factory=list)
    unresolved: list[IdRef] = field(default_factory=list)
    ignored_module_local: list[IdRef] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.unresolved

    def total_declared(self) -> int:
        return sum(len(v) for v in self.declared.values())


def _is_newtype(t: Any) -> bool:
    """NewType has a populated __supertype__ attribute; plain classes don't."""
    return hasattr(t, "__supertype__") and hasattr(t, "__name__")


def _is_union(origin: Any) -> bool:
    """Both old-style `Union[X, None]` and PEP-604 `X | None` are unions."""
    return origin is Union or origin is types.UnionType


def _walk(ann: Any, value: Any, path: str) -> Iterator[tuple[str, str, str]]:
    """Yield (id_type_name, str_value, dotted_path) for every NewType leaf."""
    if value is None:
        return
    origin = get_origin(ann)
    if _is_union(origin):
        # Pick the first non-None branch; schemas use `X | None`, not
        # ambiguous unions of multiple IDs.
        for arg in get_args(ann):
            if arg is type(None):
                continue
            yield from _walk(arg, value, path)
            return
        return
    if origin in (list, tuple, set, frozenset):
        args = get_args(ann)
        inner = args[0] if args else Any
        for i, item in enumerate(value):
            yield from _walk(inner, item, f"{path}[{i}]")
        return
    if _is_newtype(ann):
        yield ann.__name__, str(value), path
        return
    if isinstance(ann, type) and issubclass(ann, BaseModel):
        for fname, finfo in type(value).model_fields.items():
            sub_val = getattr(value, fname)
            if sub_val is None:
                continue
            sub_path = f"{path}.{fname}" if path else fname
            yield from _walk(finfo.annotation, sub_val, sub_path)
        return
    # scalar / enum / Any / dict[str, Any] → no NewType leaf reachable


def _is_declaration(
    model_class: type[BaseModel], id_type_name: str, path: str
) -> bool:
    """A NewType field at `path` inside a DECLARING_MODELS tree is a
    declaration iff its last path segment is either:
      - exactly `id` (most registries: Location.id, ThresholdGroup.id,
        TopologyNodeGroup.id/TopologyNodeLeaf.id, ClassBreaks.id, ...), or
      - the NewType name in lowerCamelCase (ValidationRuleSet uses
        `validationRuleSetId: ValidationRuleSetId` instead of plain `id`).

    Excludes reference fields like Location.parentLocationId,
    TopologyNodeLeaf.workflowId, ModifiersGroup.modifierId[] — the tail
    matches neither `id` nor the same-file NewType name.
    """
    if model_class not in DECLARING_MODELS:
        return False
    tail = path.rsplit(".", 1)[-1]
    if tail == "id":
        return True
    # lowerFirst("ValidationRuleSetId") → "validationRuleSetId"
    camel = id_type_name[0].lower() + id_type_name[1:]
    return tail == camel


def validate_semantic(
    loaded: list[tuple[str, BaseModel, Path]],
) -> SemanticReport:
    """Run the cross-file ID reference pass.

    Args:
        loaded: list of (spec_name, model_instance, output_relpath) triples.
            One entry per generated file. The runner already holds these —
            it instantiated the models during the render pass.

    Returns:
        SemanticReport with declared / refs / placeholders / unresolved.
    """
    report = SemanticReport()

    # Pass 1 — register declarations (model-resident + filename-based).
    for spec_name, model, relpath in loaded:
        model_class = type(model)
        # Filename-based declarations (e.g. UnitConversions files).
        if model_class in FILENAME_DECLARES:
            report.declared.setdefault(
                FILENAME_DECLARES[model_class], set()
            ).add(relpath.stem)
        # Model-resident declarations — walk the model and keep the
        # leaves whose path tail is `.id` inside a DECLARING_MODELS tree.
        if model_class in DECLARING_MODELS:
            for id_type_name, value, path in _walk(model_class, model, ""):
                if _is_declaration(model_class, id_type_name, path):
                    report.declared.setdefault(
                        id_type_name, set()
                    ).add(value)

    # Pass 2 — walk all models; classify every NewType leaf.
    for spec_name, model, relpath in loaded:
        model_class = type(model)
        for id_type_name, value, path in _walk(model_class, model, ""):
            source = f"{relpath}:{path}"

            # Skip declarations — already registered above.
            if _is_declaration(model_class, id_type_name, path):
                continue
            # Filename-based declarations are not reachable from the walker
            # (no `id` field), so no skip needed here.

            ref = IdRef(id_type_name=id_type_name, value=value, source=source)
            report.refs.append(ref)

            if is_placeholder(value):
                report.placeholders.append(ref)
                continue
            if id_type_name in _MODULE_LOCAL:
                report.ignored_module_local.append(ref)
                continue
            if value not in report.declared.get(id_type_name, ()):
                report.unresolved.append(ref)

    return report
