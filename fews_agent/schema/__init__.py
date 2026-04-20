"""FEWS config input schemas.

Structured per CLAUDE.md §"Design principles" — each file type takes a
typed Pydantic model as its input contract. Shared substructures
(timeSeriesSet, timeStep, relativeViewPeriod) are defined once in common.py
and composed into the per-file-type models.

Current coverage:
  - Foundation: ids, enums, common compounds
  - Registry files: Locations, Parameters, Qualifiers

Not yet covered (anchor to XSD when adding): IdMapFile, UnitConversions,
Thresholds*, ValidationRuleSets, ModifierTypes, Workflow, ImportModule,
PreprocessModule, ModelRunModule, Topology, LocationSets, and others in
data/input_parameters.json.
"""
from .common import (
    ExternUnit,
    ExtremeValues,
    FewsModel,
    RelativeViewPeriod,
    TimeSeriesSet,
    TimeStep,
    TimeZone,
)
from .enums import (
    DefaultTimeAnchor,
    ExportActivityType,
    ModuleParameterValueType,
    ParameterType,
    ReadWriteMode,
    StateSelection,
    TimeSeriesType,
    TimeUnit,
    TransformationKind,
    ValueType,
)
from .ids import (
    ClassBreaksId,
    IdMapId,
    LevelThresholdId,
    LocationId,
    LocationSetId,
    ModifierId,
    ModuleInstanceId,
    ModuleInstanceSetId,
    ModuleParameterGroupId,
    ModuleParameterId,
    ParameterGroupId,
    ParameterId,
    PermissionId,
    QualifierId,
    ThresholdGroupId,
    ThresholdValueSetId,
    TopologyNodeId,
    UnitConversionsId,
    UserGroupId,
    ValidationRuleSetId,
    VariableId,
    WarningLevelId,
    WorkflowId,
)
from .locations import Location, LocationAttribute, Locations
from .parameters import Parameter, ParameterGroup, Parameters
from .qualifiers import Qualifier, Qualifiers

__all__ = [
    # base + common
    "FewsModel",
    "TimeStep",
    "TimeSeriesSet",
    "RelativeViewPeriod",
    "TimeZone",
    "ExternUnit",
    "ExtremeValues",
    # enums
    "ValueType",
    "TimeSeriesType",
    "ReadWriteMode",
    "ParameterType",
    "TimeUnit",
    "DefaultTimeAnchor",
    "ModuleParameterValueType",
    "ExportActivityType",
    "StateSelection",
    "TransformationKind",
    # ids
    "LocationId",
    "LocationSetId",
    "ParameterId",
    "ParameterGroupId",
    "QualifierId",
    "TopologyNodeId",
    "ThresholdGroupId",
    "LevelThresholdId",
    "ThresholdValueSetId",
    "WarningLevelId",
    "ValidationRuleSetId",
    "ModifierId",
    "ModuleInstanceSetId",
    "ModuleInstanceId",
    "WorkflowId",
    "IdMapId",
    "UnitConversionsId",
    "UserGroupId",
    "PermissionId",
    "ClassBreaksId",
    "VariableId",
    "ModuleParameterGroupId",
    "ModuleParameterId",
    # Locations
    "Locations",
    "Location",
    "LocationAttribute",
    # Parameters
    "Parameters",
    "ParameterGroup",
    "Parameter",
    # Qualifiers
    "Qualifiers",
    "Qualifier",
]
