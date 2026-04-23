"""FEWS config input schemas.

Structured per CLAUDE.md §"Design principles" — each file type takes a
typed Pydantic model as its input contract. Shared substructures
(timeSeriesSet, timeStep, relativeViewPeriod) are defined once in common.py
and composed into the per-file-type models.

Current coverage:
  - Foundation: ids, enums, common compounds (TimeStep, TimeSeriesSet, ...)
  - Registry files: Locations, Parameters, Qualifiers
  - Mapping + glue: IdMap, UnitConversions, ModuleInstanceSets
  - System: Permissions, UserGroups, ThresholdWarningLevels
  - Thresholds registry: ThresholdGroups
  - Model parameters: ModuleParameters (PI namespace)
  - Display configs: TimeSeriesDisplay, ManualForecastDisplay,
    ModifierDisplay, ForecasterNotesDisplay
  - Topology

Not yet covered (anchor to XSD when adding): LocationSets, Grids,
Filters, ModuleInstanceDescriptors, WorkflowDescriptors, and others
in data/input_parameters.json.
"""
from .common import (
    ExternUnit,
    ExtremeValueLimit,
    ExtremeValues,
    FewsModel,
    RelativeViewPeriod,
    TimeSeriesSet,
    TimeStep,
    TimeZone,
    UnitMultiplier,
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
from .id_map import (
    FunctionMapping,
    IdMap,
    LocationMapping,
    MapMapping,
    ParameterMapping,
)
from .documents import (
    ArchiveProduct,
    ArchiveProductSet,
    ArchiveProductSetConstraints,
    ArchiveProductSetValidation,
    AttributeTextEquals,
    ComposeProduct,
    ComposeProductTemplate,
    DocumentAttribute,
    DocumentWorkflow,
    Documents,
    Status,
    Transition,
)
from .locations import Location, LocationAttribute, Locations
from .module_instance_sets import ModuleInstanceSet, ModuleInstanceSets
from .parameters import Parameter, ParameterGroup, Parameters
from .permissions import Permission, Permissions, UserGroupRef
from .qualifiers import Qualifier, Qualifiers
from .threshold_warning_levels import ThresholdWarningLevel, ThresholdWarningLevels
from .thresholds import (
    DefaultThreshold,
    LevelThreshold,
    ThresholdGroup,
    ThresholdGroups,
)
from .module_parameters import (
    ModuleParameter,
    ModuleParameterGroup,
    ModuleParameters,
)
from .time_series_display_config import (
    ButtonFlag,
    ButtonSettings,
    ClassBreaks,
    ClassBreaksEntry,
    DefaultViewPeriod,
    DiscreteColor,
    GeneralDisplayConfig,
    GradientSegment,
    ParameterDisplayOptions,
    ParametersDisplayConfig,
    StatisticalFunction,
    StatisticalFunctions,
    StatisticalFunctionTimeSpan,
    StatisticalFunctionTimeStep,
    TimeMarkerDisplayOptions,
    TimeMarkersDisplayConfig,
    TimeSeriesDisplay,
)
from .manual_forecast_display import ManualForecastDisplay, RunningPredefined
from .modifiers_display import (
    CreateModifierButtons,
    ModifierDisplay,
    TimeSeriesModifiersDisplayConfig,
)
from .forecast_length_estimator import ForecastLengthEstimator
from .generic_xml_file import GenericXmlFile
from .location_icons import LocationIcon, LocationIcons
from .module_instance_descriptors import (
    ModuleInstanceDescriptor,
    ModuleInstanceDescriptors,
)
from .time_steps import NamedTimeStep, TimeSteps
from .workflow_descriptors import (
    CardinalTimeStepRef,
    WorkflowDescriptor,
    WorkflowDescriptorNode,
    WorkflowDescriptorRootNode,
    WorkflowDescriptors,
)
from .forecaster_notes_display import EventCode, ForecasterNotesDisplay, MsgTemplate
from .user_groups import UserGroup, UserGroups, UserRef
from .topology import Topology, TopologyNodeGroup, TopologyNodeLeaf
from .threshold_value_sets import (
    LevelThresholdValue,
    StageDischargeConversion,
    ThresholdValueSet,
    ThresholdValueSets,
)
from .validation_rule_sets import ValidationRuleSet, ValidationRuleSets
from .modifier_types import (
    DescriptiveFunction,
    DescriptiveFunctionGroup,
    DescriptiveFunctionGroups,
    ModifierTimeSeries,
    ModifierTypes,
    ModifiersGroup,
    SpatialCopyModifier,
    SpatialCopyTimeSeries,
    SpatialProfileModifier,
    SpatialProfileTimeSeries,
    TimeSeriesModifier,
    TimeSpan,
    UserDefinedDescriptionField,
)
from .workflow import (
    ActivityEnsemble,
    EnsembleMemberIndexRange,
    Workflow,
    WorkflowActivity,
    WorkflowProperties,
    WorkflowProperty,
)
from .import_module import (
    BoolProperty,
    CsvTable,
    DateTimeColumn,
    FileNameDateTimeFilter,
    ImportBlock,
    ImportGeneral,
    ImportProperties,
    LocationColumn,
    StartTimeShift,
    StringProperty,
    TimeSeriesImportRun,
    Tolerance,
    ValueColumn,
)
from .transformation_module import Transformation, TransformationModule, Variable
from .general_adapter_run import (
    Activities,
    ColdStateSelection,
    ExecutableArguments,
    ExecutableCommand,
    ExecuteActivities,
    ExecuteActivity,
    ExportActivities,
    ExportDataSetActivity,
    ExportNetcdfActivity,
    ExportParameterActivity,
    ExportRunFileActivity,
    ExportStateActivity,
    FromTimeSeriesSelection,
    GeneralAdapterGeneral,
    GeneralAdapterRun,
    ImportActivities,
    ImportNetcdfActivity,
    ImportStateActivity,
    LocationModelLoop,
    PurgeActivity,
    RunFileIntProperty,
    RunFileProperties,
    RunFileStringProperty,
    StartUpActivities,
    StateFileRef,
    StateLocation,
    StateLocations,
    StateSearchPeriod,
    StateSelection,
    TemplateLocationLooping,
    TimeSeriesSetList,
    WarmStateSelection,
)
from .unit_conversions import UnitConversion, UnitConversions

__all__ = [
    # base + common
    "FewsModel",
    "TimeStep",
    "TimeSeriesSet",
    "RelativeViewPeriod",
    "TimeZone",
    "UnitMultiplier",
    "ExternUnit",
    "ExtremeValues",
    "ExtremeValueLimit",
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
    # Documents
    "Documents",
    "DocumentWorkflow",
    "Status",
    "Transition",
    "DocumentAttribute",
    "ArchiveProduct",
    "ComposeProduct",
    "ComposeProductTemplate",
    "ArchiveProductSet",
    "ArchiveProductSetConstraints",
    "ArchiveProductSetValidation",
    "AttributeTextEquals",
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
    # IdMap
    "IdMap",
    "ParameterMapping",
    "LocationMapping",
    "FunctionMapping",
    "MapMapping",
    # UnitConversions
    "UnitConversions",
    "UnitConversion",
    # ModuleInstanceSets
    "ModuleInstanceSets",
    "ModuleInstanceSet",
    # ThresholdWarningLevels
    "ThresholdWarningLevels",
    "ThresholdWarningLevel",
    # Permissions
    "Permissions",
    "Permission",
    "UserGroupRef",
    # Thresholds
    "ThresholdGroups",
    "ThresholdGroup",
    "LevelThreshold",
    "DefaultThreshold",
    # ModuleParameters
    "ModuleParameters",
    "ModuleParameterGroup",
    "ModuleParameter",
    # TimeSeriesDisplayConfig
    "TimeSeriesDisplay",
    "GeneralDisplayConfig",
    "DefaultViewPeriod",
    "ClassBreaks",
    "ClassBreaksEntry",
    "DiscreteColor",
    "GradientSegment",
    "TimeMarkersDisplayConfig",
    "TimeMarkerDisplayOptions",
    "ParametersDisplayConfig",
    "ParameterDisplayOptions",
    "StatisticalFunctions",
    "StatisticalFunction",
    "StatisticalFunctionTimeStep",
    "StatisticalFunctionTimeSpan",
    "ButtonSettings",
    "ButtonFlag",
    # ManualForecastDisplay
    "ManualForecastDisplay",
    "RunningPredefined",
    # ModifiersDisplay
    "ModifierDisplay",
    "CreateModifierButtons",
    "TimeSeriesModifiersDisplayConfig",
    # ForecastLengthEstimator
    "ForecastLengthEstimator",
    # Generic (Products, Grids, LocationSets, Filters, DisplayGroups,
    # Explorer, SpatialDisplay — structure too broad for field-by-field)
    "GenericXmlFile",
    # TimeSteps
    "TimeSteps",
    "NamedTimeStep",
    # LocationIcons
    "LocationIcons",
    "LocationIcon",
    # ModuleInstanceDescriptors
    "ModuleInstanceDescriptors",
    "ModuleInstanceDescriptor",
    # WorkflowDescriptors
    "WorkflowDescriptors",
    "WorkflowDescriptor",
    "WorkflowDescriptorNode",
    "WorkflowDescriptorRootNode",
    "CardinalTimeStepRef",
    # ForecasterNotesDisplay
    "ForecasterNotesDisplay",
    "MsgTemplate",
    "EventCode",
    # UserGroups
    "UserGroups",
    "UserGroup",
    "UserRef",
    # Topology
    "Topology",
    "TopologyNodeGroup",
    "TopologyNodeLeaf",
    # ThresholdValueSets
    "ThresholdValueSets",
    "ThresholdValueSet",
    "LevelThresholdValue",
    "StageDischargeConversion",
    # ValidationRuleSets
    "ValidationRuleSets",
    "ValidationRuleSet",
    # ModifierTypes
    "ModifierTypes",
    "TimeSeriesModifier",
    "ModifierTimeSeries",
    "SpatialCopyModifier",
    "SpatialCopyTimeSeries",
    "SpatialProfileModifier",
    "SpatialProfileTimeSeries",
    "UserDefinedDescriptionField",
    "TimeSpan",
    "DescriptiveFunction",
    "DescriptiveFunctionGroup",
    "DescriptiveFunctionGroups",
    "ModifiersGroup",
    # Workflow
    "Workflow",
    "WorkflowActivity",
    "ActivityEnsemble",
    "EnsembleMemberIndexRange",
    "WorkflowProperties",
    "WorkflowProperty",
    # ImportModule
    "TimeSeriesImportRun",
    "ImportBlock",
    "ImportGeneral",
    "StartTimeShift",
    "ImportProperties",
    "StringProperty",
    "BoolProperty",
    "CsvTable",
    "LocationColumn",
    "DateTimeColumn",
    "ValueColumn",
    "FileNameDateTimeFilter",
    "Tolerance",
    # TransformationModule (Preprocess + DataProcessing)
    "TransformationModule",
    "Variable",
    "Transformation",
    # GeneralAdapterRun (ModelRun + Maintenance)
    "GeneralAdapterRun",
    "GeneralAdapterGeneral",
    "Activities",
    "StartUpActivities",
    "PurgeActivity",
    "ExportActivities",
    "ExportStateActivity",
    "ExportDataSetActivity",
    "ExportParameterActivity",
    "TemplateLocationLooping",
    "LocationModelLoop",
    "ExportNetcdfActivity",
    "ExportRunFileActivity",
    "RunFileProperties",
    "RunFileStringProperty",
    "RunFileIntProperty",
    "StateLocations",
    "StateLocation",
    "StateSelection",
    "WarmStateSelection",
    "ColdStateSelection",
    "FromTimeSeriesSelection",
    "StateSearchPeriod",
    "TimeSeriesSetList",
    "ExecuteActivities",
    "ExecuteActivity",
    "ExecutableCommand",
    "ExecutableArguments",
    "ImportActivities",
    "ImportStateActivity",
    "StateFileRef",
    "ImportNetcdfActivity",
]
