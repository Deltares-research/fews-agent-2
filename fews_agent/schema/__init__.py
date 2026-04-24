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
    Addition,
    Attribute,
    CalendarTimeSpan,
    ConfigFile,
    EnsembleMemberIndexRangeAttr,
    ExternUnit,
    ExtremeValueLimit,
    ExtremeValues,
    FewsModel,
    DataVariable,
    GeoPoint,
    GridDefinition,
    HarmonicComponent,
    Period,
    RelativePeriod,
    RelativeTime,
    RelativeViewPeriod,
    TimeSeriesFilter,
    TimeSeriesFilterNot,
    SeasonCondition,
    TimeSeriesDataPoint,
    TimeSeriesSet,
    TimeShift,
    TimeStep,
    TimeZone,
    UnitMultiplier,
    ValidPeriod,
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
    ModuleInstanceMapping,
    ParameterMapping,
)
from .annotation_metadata_schema import (
    AnnotationEnumeration,
    AnnotationEnumerationValue,
    AnnotationEnumerationsCsvFile,
    AnnotationMetadataSchema,
    AnnotationProperties,
    AnnotationPropertiesCsvFile,
    AnnotationProperty,
    AnnotationStringType,
    AnnotationValueTypes,
)
from .config_update_module import ConfigUpdateImport, ConfigUpdateModule
from .content_update_checker import ContentUpdateChecker
from .base_build_file_set import BaseBuildFile, BaseBuildFileSet
from .correlation_event_sets_descriptors import (
    CorrelationEventSetsDescriptor,
    CorrelationEventSetsDescriptors,
)
from .annotation_display import AnnotationDisplay
from .annotations_display import AnnotationsDisplay
from .branches import Branch, BranchNodePoint, Branches
from .clob_historical_event import ClobHistoricalEvent
from .correlation_event_sets import (
    AttrMappedCorrelationEventSet,
    CorrelationEvent,
    CorrelationEventSet,
    CorrelationEventSets,
    InlineCorrelationEventSet,
)
from .event_actions import (
    EventActions,
    LegacyEnhance,
    LegacyEventAction,
    LegacyOneoff,
    LegacyOneoffCardinalTime,
    LegacyRepeatInterval,
    LegacyResume,
    LegacySuspend,
    LegacyTag,
)
from .import_archive_module import (
    ArchiveImportBasic,
    ArchiveImportMessages,
    ImportArchiveModule,
)
from .overtopping_module import (
    OvertoppingDataCoefficient,
    OvertoppingDataCoefficientMappings,
    OvertoppingFile,
    OvertoppingFileDataMapping,
    OvertoppingFileDataMappings,
    OvertoppingGeneral,
    OvertoppingModule,
)
from .sobek_model import (
    SobekAdapterFiles,
    SobekFolderNames,
    SobekModel,
    SobekModelFiles,
)
from .southern_transfer_functions import (
    SouthernTransferFunctions,
    SouthernTransferFunctionsArgument,
    SouthernTransferFunctionsFileNames,
    SouthernTransferFunctionsFolderNames,
)
from .transformations import (
    PeriodDependantTransformation,
    Transformations,
    TransformationEntry,
    TransformationTable,
    TransformationTableRecord,
    TransformationValidPeriod,
)
from .lookup_display import (
    LookupDisplay,
    LookupDisplayDescriptor,
    LookupDisplayGeneral,
)
from .html_template_displays import (
    DataObject,
    HtmlTemplateDisplay,
    HtmlTemplateDisplays,
    HtmlTemplateField,
    HtmlTemplateRequiredValue,
    LoopEnsembleMemberVariable,
    LoopLocationVariable,
    LoopTimeSeriesSetVariable,
    SelectedLocationVariable,
    SelectedTimeVariable,
    TimeSeriesSetReferences,
    TimeSeriesSetVariable,
)
from .dynamic_report_displays import (
    DynamicReportDisplay,
    DynamicReportDisplays,
)
from .scenarios import Scenario, ScenarioVariable, Scenarios
from .statistics_sets import (
    MovingAverage,
    StandardStatistics,
    StatisticalFunctions,
    StatisticsSet,
    StatisticsSets,
)
from .workflow_loop_runner import (
    RunPeriodOptions,
    StepValueTrigger,
    TriggerOptions,
    ValueTrigger,
    WorkflowLoopRunner,
)
from .lis_flood import (
    LisFlood,
    LisFloodAdapterFiles,
    LisFloodDirectories,
    LisFloodModelFiles,
    LisFloodOutputFile,
)
from .log_message import LogMessage
from .ribasim_model import (
    RibasimAdapterFiles,
    RibasimFile,
    RibasimFileHeader,
    RibasimFolderNames,
    RibasimModel,
    RibasimModelFiles,
)
from .configuration_management import (
    ConfigChildType,
    ConfigGroup,
    ConfigParams,
    ConfigurationManagement,
)
from .configuration_validation import (
    ConfigRef,
    ConfigType,
    ConfigurationValidation,
)
from .custom_colors import CustomColorKey, CustomColors
from .correlation_display import (
    CorrelationDisplay,
    CorrelationDisplayOptions,
    DisplayOptions,
    ReferencePoint,
    ReferencePoints,
    ScatterPlotDisplayOptions,
    ScatterPlotThresholdOptions,
    TimeSeriesSetInfo,
    UserDefinedRelation,
)
from .forecaster_aid_selection_panel import ForecasterAidSelectionPanel
from .forecast_management import (
    DefaultTimeThreshold,
    ExtraDispatchTimeThreshold,
    ForecastManagement,
    TimeThreshold,
)
from .product_info import ProductInfo
from .sacramento_model import (
    AdapterMapping,
    SacramentoAdapterActivities,
    SacramentoAdapterActivity,
    SacramentoAdapterGeneral,
    SacramentoModel,
)
from .water_coach_dictionary import DictionaryEntry, WaterCoachDictionary
from .encoded_partition_sequences import (
    EncodedPartitionSequence,
    EncodedPartitionSequences,
)
from .modifier_migration_tool import (
    LocationAttributeModifierMigration,
    ModifierMigrationTool,
)
from .threshold_events_display import ThresholdEventsDisplay
from .time_series_modifiers import (
    TimeSeriesModifierEntry,
    TimeSeriesModifiers,
)
from .da_filter import DAFilter
from .data_download_display import DataDownloadDisplay, DataDownloadTemplate
from .double_mass_display import DoubleMassDisplay
from .external_tables_mirror_update import ExternalTablesMirrorUpdate
from .on_the_fly_expression_time_series import (
    OnTheFlyExpressionTimeSeries,
    OnTheFlyExpressionTimeSeriesDefinition,
)
from .wapda_timeseries_reader import (
    WapdaColumnDefinition,
    WapdaTimeSeriesReader,
)
from .environment_agency_time_units import (
    EnvironmentAgencyTimeUnit,
    EnvironmentAgencyTimeUnits,
)
from .launcher import (
    Launcher,
    LauncherAction,
    LauncherExecutable,
    LauncherJavaApp,
    LauncherWebPage,
)
from .ldap_login_module import (
    LDAPConnection,
    LDAPLoginModule,
    LDAPSearch,
)
from .forecast_product_info_display import (
    ClassificationToggle,
    Confidence,
    ForecastProductInfoColumn,
    ForecastProductInfoColumns,
    ForecastProductInfoDisplay,
    ForecastProductInfoForecastTime,
    ProductSelection,
)
from .tabular_config_files_display import (
    EnvironmentVariable,
    TabularConfigFilesDisplay,
    TabularConfigFilesDisplayTask,
)
from .web_browser_display import (
    DomainAccess,
    DomainWhiteList,
    WebBrowserDisplay,
)
from .weboc_micro_frontends import WebOCMicroFrontEnd, WebOCMicroFrontEnds
from .flag_conversions import (
    FlagConversion,
    FlagConversions,
    FlagInt,
    FlagString,
)
from .general_settings import GeneralSettings, StateSettings
from .hymos_transfer_db_import_run import (
    HymosTransferDbImportRun,
    HymosTransferDbImportTask,
)
from .model_run_period import ModelRunPeriod, ModelRunPeriodWindow
from .openda_calibration_display import (
    CalibrationParameter,
    OpenDACalibrationDisplay,
)
from .priority_list import Priorities, Priority, PriorityList
from .time_series_table_display import (
    TimeSeriesTableColumn,
    TimeSeriesTableDisplay,
    TimeSeriesTableForecastFilter,
    TimeSeriesTableGeneral,
    TimeSeriesTableTab,
    TimeSeriesTableVariableDefinition,
)
from .sample_display import (
    ModuleInstancePermission,
    SampleDisplay,
    SampleDisplayPermissions,
    SampleDisplaySeason,
)
from .sample_properties import SamplePropertiesBlock, SamplePropertiesFile
from .security import (
    Security,
    SecurityAction,
    SecurityGrants,
    SecurityRole,
)
from .travel_times import (
    CorrelationEquations,
    TravelTime,
    TravelTimeLocation,
    TravelTimes,
)
from .trend_display import (
    RelativeTime,
    TrendDisplay,
    TrendDisplayGeneral,
    TrendGroup,
    TrendGroupChild,
)
from .warning_entry_display import (
    WarningEntryDisplay,
    WarningEntryValueProperty,
)
from .value_attribute_maps import (
    ValueAttributeMap,
    ValueAttributeMaps,
    ValueAttributes,
)
from .flag_conversions_descriptors import (
    FlagConversionsDescriptor,
    FlagConversionsDescriptors,
)
from .travel_times_descriptors import (
    TravelTimesDescriptor,
    TravelTimesDescriptors,
)
from .unit_conversions_descriptors import (
    UnitConversionsDescriptor,
    UnitConversionsDescriptors,
)
from .what_if_scenarios_descriptors import (
    WhatIfScenariosDescriptor,
    WhatIfScenariosDescriptors,
)
from .config_revision_set import (
    ConfigRevisionSet,
    ConfigRevisionSetMetaData,
    ConfigRevisionSetTableVersion,
)
from .display_descriptors import DisplayDescriptor, DisplayDescriptors
from .display_instance_descriptors import (
    DisplayInstanceDescriptor,
    DisplayInstanceDescriptors,
)
from .module_descriptors import ModuleDescriptor, ModuleDescriptors
from .run_info_panel import RunInfoPanel
from .storage_basin_system import (
    ConstantDischarge,
    ElevationStorageTableEntry,
    PumpState,
    PumpingStation,
    StorageBasinSystem,
    Structure,
)
from .import_amalgamate import ImportAmalgamate
from .module_config_properties import ModuleConfigProperties
from .module_run_table_display import ModuleRunTableDisplay
from .support_station_sets import SupportStationSet, SupportStationSets
from .unreferenced_nc_files_cleaner import (
    NcRootDir,
    UnreferencedNcFilesCleaner,
)
from .custom_flag_sources import CustomFlagSource, CustomFlagSources
from .flood_periods_module import (
    FloodPeriodThresholdCrossings,
    FloodPeriodsModule,
    ImportedThresholdCrossings,
    ThresholdProperty,
    ThresholdPropertyValueMap,
    ThresholdValuesSetsCrossings,
)
from .sample_metadata_schema import (
    SampleEnumeration,
    SampleEnumerationValue,
    SampleEnumerationsCsvFile,
    SampleMetadataSchema,
    SampleProperties,
    SamplePropertiesCsvFile,
    SampleProperty,
    SampleValueType,
    SampleValueTypes,
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
from .flag_source_columns import (
    FlagSourceColumn,
    FlagSourceColumns,
    TimeOfValidity,
)
from .historical_events import (
    EventData,
    EventDataPoint,
    HistoricalEvent,
    HistoricalEvents,
    HistoricalEventSet,
)
from .polygons import EsriShape, EsriShapeFile, Polygons
from .locations import Location, LocationVisibilityPeriod, Locations
from .module_instance_sets import ModuleInstanceSet, ModuleInstanceSets
from .parameters import (
    Dimension,
    EnumerationValue,
    Parameter,
    ParameterGroup,
    Parameters,
    TimeSeriesValueEnumeration,
    TimeSeriesValueEnumerations,
)
from .permissions import Permission, Permissions, UserGroupRef
from .qualifiers import Qualifier, QualifierNode, Qualifiers, QualifiersCsvFile
from .threshold_warning_levels import ThresholdWarningLevel, ThresholdWarningLevels
from .thresholds import (
    DefaultThreshold,
    ForecastAvailableThreshold,
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
from .manual_forecast_display import (
    ManualForecastColdState,
    ManualForecastDisplay,
    ManualForecastTask,
    ManualForecastWarmState,
    RunningPredefined,
)
from .modifiers_display import (
    CreateModifierButtons,
    DropDownMenuModifierDisplayOrder,
    DropDownMenuModifierItem,
    ModifierDisplay,
    TimeSeriesModifiersDisplayConfig,
)
from .forecast_length_estimator import ForecastLengthEstimator
from .generic_xml_file import GenericXmlFile
from .id_map_descriptors import IdMapDescriptor, IdMapDescriptors
from .cold_module_instance_state_groups import (
    ColdModuleInstanceStateGroup,
    ColdModuleInstanceStateGroups,
    SeasonalColdModuleInstanceStateGroup,
)
from .data_analysis_displays import (
    DataAnalysisDisplay,
    DataAnalysisDisplayResults,
    DataAnalysisDisplayWorkflow,
    DataAnalysisDisplays,
    DataAnalysisFilter,
    ExportArchiveProduct,
    ExportArchiveProductAttribute,
    ExportArchiveProductMetaData,
    ExportArchiveProductProperties,
    ExportArchiveProductsAttributes,
    LocationAttributeSelection,
    LocationSelection,
    ModuleInstanceSelection,
    ParameterSelection,
    SelectionPanel,
    ToolBoxes,
)
from .objective_analyzer_display import (
    MeansTable,
    ObjectiveAnalyzerDisplay,
    ObjectiveAnalyzerDisplayGeneral,
    ObservedVariable,
    PeakVariable,
    RunningMeans,
    Site,
    TargetVariable,
)
from .fews_adapter_launcher import FewsAdapterLauncher
from .pi_file_generator import (
    PiFileGenerator,
    PiFileGeneratorActivity,
    PiFileGeneratorGeneral,
    PiMapStackFile,
)
from .web_oc_dashboards import (
    WebOCDashboard,
    WebOCDashboardElement,
    WebOCDashboardElements,
    WebOCDashboardGroup,
    WebOCDashboardGroups,
    WebOCDashboardItem,
    WebOCDashboardItems,
    WebOCDashboards,
)
from .calibration import CalibrationSet, CalibrationStopCriteria
from .mc_synchronisation import (
    McModifier,
    McRecordTypeEntry,
    McRemoteMcId,
    McSynchId,
    McSynchLevel,
    McSynchParams,
    McSynchronisation,
)
from .log_displays import (
    LogDisplay,
    LogDisplayLogDissemination,
    LogDisplayLogDisseminationAction,
    LogDisplayLogDisseminationActions,
    LogDisplayManualLog,
    LogDisplays,
    LogDisplaySystemEventCodes,
    LogDisplaySystemLog,
)
from .import_run import (
    ImportEntry,
    ImportRun,
    StartTimeShift,
    TimeStampTolerance,
)
from .archive_metadata import (
    ArchiveMetaData,
    DateTimePair,
    FewsSessionKey,
    LatestAvailableData,
    ModifierDescriptorKey,
    ModuleInstanceRunKey,
    TaskKey,
    TaskRunKey,
    TimeSeriesBlobKey,
    WarmStateKey,
    WhatIfScenarioKey,
)
from .pc_raster import (
    PCRaster,
    PCRasterAdapterFiles,
    PCRasterDirectories,
    PCRasterFile,
    PCRasterLongTermAverageInputFile,
    PCRasterModelFiles,
)
from .threshold_skill_score_display import (
    EventMatchingCriteria,
    LocationEventMatchingCriteria,
    ThresholdSkillScoreAttribute,
    ThresholdSkillScoreDisplay,
    ThresholdSkillScoreDisplayGeneral,
    ThresholdSkillScoreGroup,
    ThresholdSkillScoreGroupChild,
    ThresholdSkillScoreParameterPair,
)
from .report_export import (
    CurrentForecastReports,
    ExportForecastReports,
    ExportSystemStatusReports,
    GenerateImage,
    ReportExport,
    ReportExportTelegramPhoto,
    TelegramSendPhoto,
)
from .archive_module_display import (
    ArchiveModuleDisplay,
    ArchiveThresholdIds,
    DataSearchProperty,
    DownloadFolders,
    SearchDataTypes,
)
from .delft3d_model import (
    Delft3DGeneral,
    Delft3DMapStack,
    Delft3DMapStackOutput,
    Delft3DModel,
    Delft3DPostAdapter,
    Delft3DPreAdapter,
    Delft3DTimeSeries,
    Delft3DTimeSeriesOutput,
)
from .threshold_export import (
    MapThreshold,
    MultiValuedAttributeTag,
    ThresholdExport,
    ThresholdExportDateFormat,
    ThresholdExportFileName,
    ThresholdExportModule,
    ThresholdExportNumberFormat,
    ThresholdLogFilter,
)
from .hbv_model import (
    HbvActionSpecifications,
    HbvAdapterFiles,
    HbvFolderNames,
    HbvModel,
    HbvModelDirectories,
    HbvModelFiles,
    HbvModelPropertiesFiles,
    HbvVariables,
)
from .mass_balance import (
    MassBalance,
    SliceHorizontalFlux,
    SliceHorizontalVelocity,
    SliceStorageChange,
    SliceVerticalFlux,
    SliceVerticalVelocity,
)
from .correlation_sets import (
    Correlation,
    CorrelationSet,
    CorrelationSets,
    SelectionCriteria,
    SelectionPeriod,
    SelectionTags,
    SelectionThreshold,
)
from .task_properties_predefined import (
    BatchTask,
    OverrulingModuleInstanceRunKey,
    TaskPropertiesPredefined,
)
from .spatial_interpolation import (
    DistanceGeographic,
    InterpolationDebug,
    SpatialInterpolation,
    Variogram,
)
from .interpolation_sets import (
    Basin,
    BasinGroup,
    InterpolationOutputSet,
    InterpolationSet,
    InterpolationSets,
    PointPosition,
    SerialInterpolation,
)
from .midlands_models import (
    Dodo,
    DodoInputForecastParameters,
    DodoInputHindcastParameters,
    DodoInputParameters,
    DodoOutputForecastParameters,
    DodoOutputHindcastParameters,
    DodoOutputParameters,
    DodoParameters,
    DodoStateParameters,
    Mcrm,
    McrmInputForecastParameters,
    McrmInputHindcastParameters,
    McrmInputParameters,
    McrmOutputForecastParameters,
    McrmOutputHindcastParameters,
    McrmOutputParameters,
    McrmParameters,
    McrmStateParameters,
    MidlandsAdapterFileNames,
    MidlandsFolderNames,
    MidlandsInflow,
    MidlandsModel,
    MidlandsModuleFileNames,
    MidlandsVariables,
)
from .what_if import (
    SelectedModifier,
    WhatIf,
    WhatIfLocation,
    WhatIfLocationSet,
)
from .what_if_scenario import (
    LocationSelection,
    PolygonSelection,
    WhatIfScenario,
    WhatIfScenarioContent,
    WhatIfScenarios,
)
from .what_if_scenario_filters import (
    ModuleDataSetFiles,
    ModuleParameterFiles,
    VariableSets,
    WhatIfConfigFiles,
    WhatIfFilterEnumerations,
    WhatIfFilterProperties,
    WhatIfFilterProperty,
    WhatIfFilterStringEnumeration,
    WhatIfModuleParameter,
    WhatIfModuleParameterBoolData,
    WhatIfModuleParameterData,
    WhatIfModuleParameterDoubleData,
    WhatIfModuleParameterIntData,
    WhatIfModuleParameters,
    WhatIfScenarioFilters,
)
from .flood_map_sets import (
    ContourOutput,
    FloodDemMap,
    FloodExtentMap,
    FloodExtrapolation,
    FloodMapDirectories,
    FloodMapInput,
    FloodMapOutput,
    FloodMapSet,
    FloodMapSets,
    GridFileOutput,
    LongitudinalProfile,
    PcrScript,
)
from .forecast_mixer import (
    ForecastMixer,
    ForecastMixing,
)
from .time_series_buttons_panels import (
    TimeSeriesButtonsPanels,
    TsButtonsButton,
    TsButtonsPanel,
)
from .reservoir_model import (
    ElevationStorageRow,
    Reservoir,
    ReservoirCoefficient,
    ReservoirInflow,
    ReservoirModel,
    ReservoirOutflow,
)
from .synchronisation_profiles import (
    ContinuousSynchActivity,
    SingleSynchActivity,
    SynchActivities,
    SynchActivity,
    SynchModifier,
    SynchModifierList,
    SynchModifiers,
    SynchProfile,
    SynchSchedule,
    SynchTrigger,
    SynchTriggers,
    SynchronisationProfiles,
)
from .task_run_properties import (
    ExternalForecastTime,
    InputProduct,
    TaskRunProperties,
    UnexpectedColdStateUsed,
)
from .common_adapter import (
    CommonAdapter,
    CommonAdapterActivities,
    CommonAdapterActivity,
    CommonAdapterGeneral,
    CommonAdapterMapping,
    CommonAdapterPointMapping,
    CommonAdapterProfileActivity,
    CommonAdapterTimeSeriesActivity,
)
from .archive_run import (
    ArchiveRun,
    ExportArchiveRun,
    ImportArchiveRun,
    LogEventConstraint,
)
from .document_displays import (
    DocumentDisplay,
    DocumentDisplayBrowser,
    DocumentDisplayBrowserArchiveProducts,
    DocumentDisplayBrowserLayout,
    DocumentDisplayBrowserLayoutHeaders,
    DocumentDisplayCompose,
    DocumentDisplayHeader,
    DocumentDisplayReport,
    DocumentDisplayShowReport,
    DocumentDisplays,
)
from .fews_pi_service_config import (
    FewsPiServiceConfig,
    PiServiceExternalUnit,
    PiServiceGeneral,
    PiServiceModuleData,
    PiServiceTimeSeries,
)
from .web_service import (
    MCTaskWebService,
    WebService,
)
from .synchronisation_configuration import (
    SynchConfigConnection,
    SynchConfigDatabase,
    SynchConfigFactory,
    SynchConfigJNDIContext,
    SynchConfigLogin,
    SynchConfigMC,
    SynchConfigMessaging,
    SynchConfigProcessor,
    SynchConfigQueue,
    SynchConfigQueueConnection,
    SynchConfigRoot,
    SynchConfigSchema,
    SynchConfigSynch,
    SynchConfigSynchronisation,
    SynchronisationConfiguration,
)
from .rdbms_export import (
    RdbmsExport,
    RdbmsExportFilter,
    RdbmsExportModuleInstance,
)
from .amalgamate_module import (
    AmalgamateModule,
    AmalgamateTask,
)
from .synchronisation_channels import (
    SynchChannel,
    SynchChannelTableNames,
    SynchronisationChannels,
)
from .export_run import (
    ExportRun,
    ExportRunEntry,
)
from .geo_reference_data_set import (
    GeoReferenceData,
    GeoReferenceDataPoint,
    GeoReferenceDataSet,
)
from .grib_time_series_reader import (
    GribRecordDefinition,
    GribTimeSeriesReader,
)
from .config_update_script_config import (
    ConfigUpdateScriptConfig,
    ImportMapLayerFilesSettings,
)
from .workflow_test_run import (
    WftrActivities,
    WftrCheckPerformanceActivity,
    WftrCompareActivity,
    WftrCopyActivity,
    WftrDirDefinition,
    WftrExportLogsActivity,
    WftrExportTimeSeriesActivity,
    WftrGeneral,
    WftrPurgeActivity,
    WftrSetSystemTimeActivity,
    WftrSleepActivity,
    WftrTestReport,
    WftrTextMatchActivity,
    WftrTimeSeriesSets,
    WftrWorkflowActivity,
    WorkflowTestRun,
)
from .task_properties import (
    EnsembleMemberIndexRange,
    ScheduledTask,
    Scheduling,
    SingleTask,
    TaskList,
    TaskListTaskGroup,
    TaskProperties,
    TaskSelection,
    YearlyScheduling,
)
from .barriers import (
    Barrier,
    BarrierStateDefinition,
    BarrierStateTransition,
    BarrierStateValue,
    Barriers,
    ParameterValue,
    StateVariable,
    StateVariableValue,
    StateVariables,
    TransitionLevelSpeed,
    TransitionTimeOffset,
    TransitionValue,
    Transitions,
)
from .decision_module import (
    Decision,
    DecisionConditionalWorkflow,
    DecisionEvaluation,
    DecisionInitialConditionalWorkflow,
    DecisionModule,
    DecisionStateChange,
    DecisionStates,
    DecisionTree,
    DecisionVariableDefinition,
    RuleConstraint,
    RuleConstraints,
    Rules,
    StateChanges,
    TimeOffset,
    TransitionRule,
    TransitionRules,
)
from .system_monitor_display import (
    DefaultTimeThreshold,
    DeprecatedExtraTimeThreshold,
    SystemMonitorBulletinBoard,
    SystemMonitorBulletinBoardPlus,
    SystemMonitorDisplay,
    SystemMonitorTransferStatus,
    TimeThreshold,
    TransferStatusDataFeed,
    VisibleColumns,
)
from .prtf_display import (
    BooleanData,
    DisplayOptions,
    DoubleData,
    IntData,
    PRTFDisplay,
    PRTFGroup,
    PRTFGroupOptions,
    PRTFItem,
    PRTFParameter,
    PRTFSubGroup,
    ParameterData,
)
from .verification_analysis_display import (
    ConnectedTimeSeries,
    SelectionFilter,
    VADColumnChoice,
    VADLocationColumn,
    ValuePropertyColumn,
    ValuePropertyCountColumn,
    ValuePropertyMaxColumn,
    VerificationAnalysisDataTab,
    VerificationAnalysisDisplay,
)
from .state_editor import (
    Climatology,
    Event,
    Model,
    ModelGroup,
    ModelGroups,
    SeriesGroup,
    StateEditor,
    StateEditorGeneral,
    StateParameter,
    StateParameterGroup,
    StateRange,
    StateSeries,
)
from .web_oc_component_settings import (
    ComponentSettings,
    GeneralChart,
    GridLayer,
    LocationsLayer,
    LocationsLayerZoomLevel,
    MetaDataPanel,
    OverLay,
    Overlays,
    PanelPlacementBlock,
    TimeSeriesChart,
    TimeSeriesChartLegend,
    TimeSeriesTable,
    VerticalProfileTable,
    WebOCAction,
    WebOCChart,
    WebOCComponentSettings,
    WebOCExternalLayer,
    WebOCMap,
    WebOCSSD,
    WebOCWmsLayer,
    WebOcXAxis,
    WebOcYAxis,
)
from .system_metrics import (
    DatabaseMetric,
    FSSStatusMetric,
    LogEntryMetric,
    MCStatusMetric,
    SystemMetricGeneral,
    SystemMetrics,
    TableMetric,
    WorkflowMetric,
)
from .error_model_sets import (
    AutoOrderMethod,
    ErrorModelInterpolation,
    ErrorModelParameter,
    ErrorModelParameters,
    ErrorModelSet,
    ErrorModelSets,
    FixedOrderMethod,
)
from .lookup_sets import (
    ColumnData,
    ColumnDataItem,
    Condition,
    ConditionGroup,
    CriticalConditionLookup,
    InfoBlock,
    ListEntry,
    LookUpSet,
    LookUpSets,
    MultiDimensionalTableLookup,
    RuleCriteria,
    RuleCriterias,
    RuleCriteriasItem,
    TableLookup,
)
from .pcr_transformation_sets import (
    PcrAreaMap,
    PcrDefinitions,
    PcrInputVariable,
    PcrInternalVariable,
    PcrOutputVariable,
    PcrScriptTextModel,
    PcrTransformationSet,
    PcrTransformationSets,
)
from .threshold_overview_display import (
    ColumnAttributes,
    ForecastFilter,
    ForecastTime,
    Tab1,
    Tab2,
    Tab3,
    Tab3Column,
    Tab4,
    ThresholdOverviewAttribute,
    ThresholdOverviewCrossingCountsTab,
    ThresholdOverviewDisplay,
    ThresholdOverviewDisplayDescriptor,
    ThresholdOverviewDisplayGeneral,
)
from .water_coach_display import (
    Config,
    ExperienceLevel,
    FileAssociation,
    ImportGridsAsReference,
    ImportModelStates,
    ImportModifiers,
    MultipleSystems,
    OnTheFlySystem,
    TimeControl,
    WaterCoachDisplay,
)
from .structures import (
    BroadCrestedWeir,
    CapacityHead,
    CapacityState,
    CapacityStateHead,
    Coefficient,
    GeneralWeir,
    Orifice,
    Pump,
    SharpCrestedWeir,
    Structures,
    TriangularBroadCrestedWeir,
    TriangularSharpCrestedWeir,
    UserDefinedExpression,
    UserDefinedWeir,
    Weir,
)
from .performance_indicator_sets import (
    CriteriaEntry,
    LeadTime,
    LeadTimeAccuracyIndicator,
    LeadTimePeriod,
    LeadTimePeriods,
    LeadTimes,
    ModulePerformanceIndicator,
    PeaksAccuracyIndicator,
    PerformanceIndicatorSet,
    PerformanceIndicatorSets,
    PrecipitationPerformanceIndicator,
    SelectPeak,
    SelectPeaks,
    ThresholdClassBreaks,
    ThresholdIdEntry,
    ThresholdIds,
    ThresholdTimingIndicator,
)
from .task_run_dialog import (
    PixelDimension,
    PixelPosition,
    TaskRunDialog,
    TaskRunDialogArchiveTask,
    TaskRunDialogFlowchart,
    TaskRunDialogOperatorTask,
    TaskRunDialogPanel,
    TaskRunDialogScenarioEntry,
    TaskRunDialogScenarioSelector,
    TaskRunDialogSimpleTask,
    TaskRunDialogTaskDependency,
    TaskRunDialogTaskGroup,
    TaskRunDialogTimeEditor,
    TaskRunDialogValueEditor,
    TaskRunDialogValueNonEditable,
)
from .rating_curves import (
    BackWaterCorrection,
    ConstantFallMethod,
    JonesEquation,
    NormalFallMethod,
    RatingCurve,
    RatingCurveCorrection,
    RatingCurveEquation,
    RatingCurveEquationCoefficient,
    RatingCurveLocation,
    RatingCurveTable,
    RatingCurveTableRecord,
    RatingCurves,
    UnsteadyFlowCorrection,
)
from .fews_installation_configurator import (
    ArchiveServerInstall,
    ClientInstall,
    DatabaseServerInstall,
    FewsInstallation,
    FewsInstallationConfigurator,
    ForecastingShellInstall,
    JMSServerInstall,
    MasterControllerInstall,
    RemoteMasterControllerInstall,
)
from .module_execution_controller_run import (
    DiagnosticDetails,
    MECtoMC,
    MecFactory,
    MecGeneral,
    MecJNDIContext,
    MecJmsConnectionDetails,
    MecQueue,
    MecQueueConnection,
    MecRoot,
    ModuleExecutionControllerRun,
    PiDiagnosticsScan,
    SearchCriteria,
    SearchStrings,
    TimeSeriesChecks,
    TimeSeriesFile,
    TimeSeriesFileThreshold,
)
from .what_if_templates import (
    SingleRunWhatIf,
    TriggerProperty,
    WhatIfTemplate,
    WhatIfTemplateBoolValue,
    WhatIfTemplateConfigFile,
    WhatIfTemplateDateTimeValue,
    WhatIfTemplateDoubleValue,
    WhatIfTemplateEnumeration,
    WhatIfTemplateEnumerationValue,
    WhatIfTemplateIntValue,
    WhatIfTemplateMultiPropertyEnumeration,
    WhatIfTemplateMultiPropertyEnumerationValue,
    WhatIfTemplateProperties,
    WhatIfTemplateProperty,
    WhatIfTemplateStringValue,
    WhatIfTemplateTemplateId,
    WhatIfTemplateValueTypes,
    WhatIfTemplates,
)
from .location_icons import LocationIcon, LocationIcons
from .module_instance_descriptors import (
    ModuleInstanceDescriptor,
    ModuleInstanceDescriptorAttributeFile,
    ModuleInstanceDescriptors,
    ModuleInstanceDescriptorsCsvFile,
    ModuleInstanceGroup,
)
from .time_steps import (
    DayOfMonthWithAggregationPeriod,
    MonthDayWithAggregationPeriod,
    MonthlyTimeStep,
    NamedTimeStep,
    TimeSteps,
    TimesOfWeekDay,
    WeeklyTimeStep,
    YearlyTimeStep,
)
from .workflow_descriptors import (
    CardinalTimeStepRef,
    WorkflowDescriptor,
    WorkflowDescriptorNode,
    WorkflowDescriptorRootNode,
    WorkflowDescriptors,
)
from .forecaster_notes_display import (
    EventCode,
    ForecasterNotesDisplay,
    ForecasterNotesElements,
    MsgTemplate,
    MultipleForecasterNotesMaker,
    Note,
    NoteChoice,
    NoteChoiceGroup,
    NoteGroup,
    NotesTableColumn,
    NotesTableColumns,
    TextNote,
)
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
    "EnsembleMemberIndexRangeAttr",
    "TimeShift",
    "RelativePeriod",
    "RelativeViewPeriod",
    "TimeSeriesFilter",
    "TimeSeriesFilterNot",
    "TimeZone",
    "UnitMultiplier",
    "ExternUnit",
    "ExtremeValues",
    "ExtremeValueLimit",
    "Addition",
    "Attribute",
    "CalendarTimeSpan",
    "ConfigFile",
    "DataVariable",
    "GeoPoint",
    "GridDefinition",
    "HarmonicComponent",
    "Period",
    "RelativeTime",
    "SeasonCondition",
    "TimeSeriesDataPoint",
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
    # Polygons
    "Polygons",
    "EsriShapeFile",
    "EsriShape",
    # HistoricalEvents
    "HistoricalEvents",
    "HistoricalEventSet",
    "HistoricalEvent",
    "EventData",
    "EventDataPoint",
    # CustomFlagSources
    "CustomFlagSources",
    "CustomFlagSource",
    # FlagSourceColumns
    "FlagSourceColumns",
    "FlagSourceColumn",
    "TimeOfValidity",
    # FloodPeriodsModule
    "FloodPeriodsModule",
    "FloodPeriodThresholdCrossings",
    "ThresholdValuesSetsCrossings",
    "ImportedThresholdCrossings",
    "ThresholdProperty",
    "ThresholdPropertyValueMap",
    # ContentUpdateChecker
    "ContentUpdateChecker",
    # ConfigUpdateModule
    "ConfigUpdateModule",
    "ConfigUpdateImport",
    # ModuleRunTableDisplay
    "ModuleRunTableDisplay",
    # UnreferencedNcFilesCleaner
    "UnreferencedNcFilesCleaner",
    "NcRootDir",
    # SupportStationSets
    "SupportStationSets",
    "SupportStationSet",
    # ImportAmalgamate
    "ImportAmalgamate",
    # ModuleConfigProperties
    "ModuleConfigProperties",
    # BaseBuildFileSet
    "BaseBuildFileSet",
    "BaseBuildFile",
    # ConfigRevisionSet
    "ConfigRevisionSet",
    "ConfigRevisionSetMetaData",
    "ConfigRevisionSetTableVersion",
    # RunInfoPanel
    "RunInfoPanel",
    # DisplayDescriptors
    "DisplayDescriptors",
    "DisplayDescriptor",
    # DisplayInstanceDescriptors
    "DisplayInstanceDescriptors",
    "DisplayInstanceDescriptor",
    # ModuleDescriptors
    "ModuleDescriptors",
    "ModuleDescriptor",
    # StorageBasinSystem
    "StorageBasinSystem",
    "Structure",
    "PumpingStation",
    "PumpState",
    "ConstantDischarge",
    "ElevationStorageTableEntry",
    # ModelRunPeriod
    "ModelRunPeriod",
    "ModelRunPeriodWindow",
    # CustomColors
    "CustomColors",
    "CustomColorKey",
    # GeneralSettings
    "GeneralSettings",
    "StateSettings",
    # ValueAttributeMaps
    "ValueAttributeMaps",
    "ValueAttributeMap",
    "ValueAttributes",
    # TravelTimes
    "TravelTimes",
    "TravelTime",
    "TravelTimeLocation",
    "CorrelationEquations",
    # Security
    "Security",
    "SecurityAction",
    "SecurityRole",
    "SecurityGrants",
    # TrendDisplay
    "TrendDisplay",
    "TrendDisplayGeneral",
    "TrendGroup",
    "TrendGroupChild",
    "RelativeTime",
    # SampleDisplay
    "SampleDisplay",
    "SampleDisplayPermissions",
    "SampleDisplaySeason",
    "ModuleInstancePermission",
    # WarningEntryDisplay
    "WarningEntryDisplay",
    "WarningEntryValueProperty",
    # OpenDACalibrationDisplay
    "OpenDACalibrationDisplay",
    "CalibrationParameter",
    # HymosTransferDbImportRun
    "HymosTransferDbImportRun",
    "HymosTransferDbImportTask",
    # Priorities (priorityList)
    "Priorities",
    "PriorityList",
    "Priority",
    # FlagConversions
    "FlagConversions",
    "FlagConversion",
    "FlagInt",
    "FlagString",
    # TimeSeriesTableDisplay
    "TimeSeriesTableDisplay",
    "TimeSeriesTableGeneral",
    "TimeSeriesTableForecastFilter",
    "TimeSeriesTableVariableDefinition",
    "TimeSeriesTableTab",
    "TimeSeriesTableColumn",
    # TabularConfigFilesDisplay
    "TabularConfigFilesDisplay",
    "TabularConfigFilesDisplayTask",
    "EnvironmentVariable",
    # DataDownloadDisplay
    "DataDownloadDisplay",
    "DataDownloadTemplate",
    # WebBrowserDisplay
    "WebBrowserDisplay",
    "DomainWhiteList",
    "DomainAccess",
    # ForecastProductInfoDisplay
    "ForecastProductInfoDisplay",
    "ProductSelection",
    "ForecastProductInfoForecastTime",
    "Confidence",
    "ClassificationToggle",
    "ForecastProductInfoColumns",
    "ForecastProductInfoColumn",
    # WebOCMicroFrontEnds
    "WebOCMicroFrontEnds",
    "WebOCMicroFrontEnd",
    # DAFilter
    "DAFilter",
    # EnvironmentAgencyTimeUnits
    "EnvironmentAgencyTimeUnits",
    "EnvironmentAgencyTimeUnit",
    # LDAPLoginModule
    "LDAPLoginModule",
    "LDAPConnection",
    "LDAPSearch",
    # Launcher
    "Launcher",
    "LauncherAction",
    "LauncherWebPage",
    "LauncherJavaApp",
    "LauncherExecutable",
    # ClobHistoricalEvent (DB-blob variant)
    "ClobHistoricalEvent",
    # DoubleMassDisplay
    "DoubleMassDisplay",
    # WapdaTimeSeriesReader
    "WapdaTimeSeriesReader",
    "WapdaColumnDefinition",
    # ExternalTablesMirrorUpdate
    "ExternalTablesMirrorUpdate",
    # OnTheFlyExpressionTimeSeries
    "OnTheFlyExpressionTimeSeries",
    "OnTheFlyExpressionTimeSeriesDefinition",
    # AnnotationDisplay
    "AnnotationDisplay",
    # EncodedPartitionSequences
    "EncodedPartitionSequences",
    "EncodedPartitionSequence",
    # ThresholdEventsDisplay
    "ThresholdEventsDisplay",
    # TimeSeriesModifiers
    "TimeSeriesModifiers",
    "TimeSeriesModifierEntry",
    # ModifierMigrationTool
    "ModifierMigrationTool",
    "LocationAttributeModifierMigration",
    # ProductInfo
    "ProductInfo",
    # ConfigurationValidation
    "ConfigurationValidation",
    "ConfigType",
    "ConfigRef",
    # SacramentoModel
    "SacramentoModel",
    "SacramentoAdapterGeneral",
    "SacramentoAdapterActivities",
    "SacramentoAdapterActivity",
    "AdapterMapping",
    # ForecastManagement
    "ForecastManagement",
    "DefaultTimeThreshold",
    "ExtraDispatchTimeThreshold",
    "TimeThreshold",
    # WaterCoachDictionary
    "WaterCoachDictionary",
    "DictionaryEntry",
    # LogMessage
    "LogMessage",
    # AnnotationsDisplay (stub)
    "AnnotationsDisplay",
    # LisFlood
    "LisFlood",
    "LisFloodDirectories",
    "LisFloodAdapterFiles",
    "LisFloodOutputFile",
    "LisFloodModelFiles",
    # RibasimModel
    "RibasimModel",
    "RibasimFolderNames",
    "RibasimAdapterFiles",
    "RibasimFile",
    "RibasimFileHeader",
    "RibasimModelFiles",
    # SobekModel
    "SobekModel",
    "SobekFolderNames",
    "SobekAdapterFiles",
    "SobekModelFiles",
    # SouthernTransferFunctions
    "SouthernTransferFunctions",
    "SouthernTransferFunctionsFolderNames",
    "SouthernTransferFunctionsFileNames",
    "SouthernTransferFunctionsArgument",
    # StatisticsSets
    "StatisticsSets",
    "StatisticsSet",
    "StatisticalFunctions",
    "StandardStatistics",
    "MovingAverage",
    # LookupDisplay
    "LookupDisplay",
    "LookupDisplayGeneral",
    "LookupDisplayDescriptor",
    # HtmlTemplateDisplays
    "HtmlTemplateDisplays",
    "HtmlTemplateDisplay",
    "DataObject",
    "HtmlTemplateField",
    "HtmlTemplateRequiredValue",
    "TimeSeriesSetReferences",
    "TimeSeriesSetVariable",
    "LoopTimeSeriesSetVariable",
    "LoopLocationVariable",
    "SelectedLocationVariable",
    "SelectedTimeVariable",
    "LoopEnsembleMemberVariable",
    # DynamicReportDisplays (reuses inner types from HtmlTemplateDisplays)
    "DynamicReportDisplays",
    "DynamicReportDisplay",
    # Scenarios
    "Scenarios",
    "Scenario",
    "ScenarioVariable",
    # WorkflowLoopRunner
    "WorkflowLoopRunner",
    "RunPeriodOptions",
    "TriggerOptions",
    "ValueTrigger",
    "StepValueTrigger",
    # Transformations (region-level lookup form)
    "Transformations",
    "TransformationEntry",
    "PeriodDependantTransformation",
    "TransformationTable",
    "TransformationTableRecord",
    "TransformationValidPeriod",
    # ImportArchiveModule
    "ImportArchiveModule",
    "ArchiveImportBasic",
    "ArchiveImportMessages",
    # OvertoppingModule
    "OvertoppingModule",
    "OvertoppingGeneral",
    "OvertoppingFile",
    "OvertoppingFileDataMappings",
    "OvertoppingFileDataMapping",
    "OvertoppingDataCoefficientMappings",
    "OvertoppingDataCoefficient",
    # ConfigurationManagement
    "ConfigurationManagement",
    "ConfigParams",
    "ConfigGroup",
    "ConfigChildType",
    # ForecasterAidSelectionPanel
    "ForecasterAidSelectionPanel",
    # Branches
    "Branches",
    "Branch",
    "BranchNodePoint",
    # CorrelationEventSets
    "CorrelationEventSets",
    "CorrelationEventSet",
    "InlineCorrelationEventSet",
    "AttrMappedCorrelationEventSet",
    "CorrelationEvent",
    # EventActions
    "EventActions",
    "LegacyEventAction",
    "LegacyEnhance",
    "LegacyOneoff",
    "LegacyOneoffCardinalTime",
    "LegacyRepeatInterval",
    "LegacyResume",
    "LegacySuspend",
    "LegacyTag",
    # CorrelationDisplay
    "CorrelationDisplay",
    "TimeSeriesSetInfo",
    "CorrelationDisplayOptions",
    "ScatterPlotDisplayOptions",
    "ScatterPlotThresholdOptions",
    "DisplayOptions",
    "UserDefinedRelation",
    "ReferencePoints",
    "ReferencePoint",
    # SamplePropertiesFile (root of SampleProperties.xml;
    # named *File to avoid collision with SampleMetadataSchema.SampleProperties)
    "SamplePropertiesFile",
    "SamplePropertiesBlock",
    # Descriptors (5 shape-identical registries)
    "UnitConversionsDescriptors",
    "UnitConversionsDescriptor",
    "FlagConversionsDescriptors",
    "FlagConversionsDescriptor",
    "WhatIfScenariosDescriptors",
    "WhatIfScenariosDescriptor",
    "TravelTimesDescriptors",
    "TravelTimesDescriptor",
    "CorrelationEventSetsDescriptors",
    "CorrelationEventSetsDescriptor",
    # SampleMetadataSchema
    "SampleMetadataSchema",
    "SampleValueTypes",
    "SampleValueType",
    "SampleEnumeration",
    "SampleEnumerationValue",
    "SampleEnumerationsCsvFile",
    "SampleProperties",
    "SampleProperty",
    "SamplePropertiesCsvFile",
    # AnnotationMetadataSchema
    "AnnotationMetadataSchema",
    "AnnotationValueTypes",
    "AnnotationStringType",
    "AnnotationEnumeration",
    "AnnotationEnumerationValue",
    "AnnotationEnumerationsCsvFile",
    "AnnotationProperties",
    "AnnotationProperty",
    "AnnotationPropertiesCsvFile",
    # Locations
    "Locations",
    "Location",
    "LocationVisibilityPeriod",
    # Parameters
    "Dimension",
    "EnumerationValue",
    "Parameter",
    "ParameterGroup",
    "Parameters",
    "TimeSeriesValueEnumeration",
    "TimeSeriesValueEnumerations",
    # Qualifiers
    "Qualifiers",
    "Qualifier",
    # IdMap
    "IdMap",
    "FunctionMapping",
    "LocationMapping",
    "MapMapping",
    "ModuleInstanceMapping",
    "ParameterMapping",
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
    "ForecastAvailableThreshold",
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
    "ModuleInstanceDescriptor",
    "ModuleInstanceDescriptors",
    "ModuleInstanceGroup",
    # WorkflowDescriptors
    "WorkflowDescriptors",
    "WorkflowDescriptor",
    "WorkflowDescriptorNode",
    "WorkflowDescriptorRootNode",
    "CardinalTimeStepRef",
    # ForecasterNotesDisplay
    "EventCode",
    "ForecasterNotesDisplay",
    "ForecasterNotesElements",
    "MsgTemplate",
    "MultipleForecasterNotesMaker",
    "Note",
    "NoteChoice",
    "NoteChoiceGroup",
    "NoteGroup",
    "NotesTableColumn",
    "NotesTableColumns",
    "TextNote",
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
    # IdMapDescriptors
    "IdMapDescriptor",
    "IdMapDescriptors",
    # ColdModuleInstanceStateGroups
    "ColdModuleInstanceStateGroup",
    "ColdModuleInstanceStateGroups",
    "SeasonalColdModuleInstanceStateGroup",
    # DataAnalysisDisplays
    "DataAnalysisDisplay",
    "DataAnalysisDisplayResults",
    "DataAnalysisDisplayWorkflow",
    "DataAnalysisDisplays",
    "DataAnalysisFilter",
    "ExportArchiveProduct",
    "ExportArchiveProductAttribute",
    "ExportArchiveProductMetaData",
    "ExportArchiveProductProperties",
    "ExportArchiveProductsAttributes",
    "LocationAttributeSelection",
    "LocationSelection",
    "ModuleInstanceSelection",
    "ParameterSelection",
    "SelectionPanel",
    "ToolBoxes",
    # ObjectiveAnalyzerDisplay
    "MeansTable",
    "ObjectiveAnalyzerDisplay",
    "ObjectiveAnalyzerDisplayGeneral",
    "ObservedVariable",
    "PeakVariable",
    "RunningMeans",
    "Site",
    "TargetVariable",
    # FewsAdapterLauncher
    "FewsAdapterLauncher",
    # PiFileGenerator
    "PiFileGenerator",
    "PiFileGeneratorActivity",
    "PiFileGeneratorGeneral",
    "PiMapStackFile",
    # WebOCDashboards
    "WebOCDashboard",
    "WebOCDashboardElement",
    "WebOCDashboardElements",
    "WebOCDashboardGroup",
    "WebOCDashboardGroups",
    "WebOCDashboardItem",
    "WebOCDashboardItems",
    "WebOCDashboards",
    # Calibration
    "CalibrationSet",
    "CalibrationStopCriteria",
    # McSynchronisation
    "McModifier",
    "McRecordTypeEntry",
    "McRemoteMcId",
    "McSynchId",
    "McSynchLevel",
    "McSynchParams",
    "McSynchronisation",
    # LogDisplays
    "LogDisplay",
    "LogDisplayLogDissemination",
    "LogDisplayLogDisseminationAction",
    "LogDisplayLogDisseminationActions",
    "LogDisplayManualLog",
    "LogDisplays",
    "LogDisplaySystemEventCodes",
    "LogDisplaySystemLog",
    # ImportRun
    "ImportEntry",
    "ImportRun",
    "StartTimeShift",
    "TimeStampTolerance",
    # ArchiveMetaData
    "ArchiveMetaData",
    "DateTimePair",
    "FewsSessionKey",
    "LatestAvailableData",
    "ModifierDescriptorKey",
    "ModuleInstanceRunKey",
    "TaskKey",
    "TaskRunKey",
    "TimeSeriesBlobKey",
    "WarmStateKey",
    "WhatIfScenarioKey",
    # PCRaster
    "PCRaster",
    "PCRasterAdapterFiles",
    "PCRasterDirectories",
    "PCRasterFile",
    "PCRasterLongTermAverageInputFile",
    "PCRasterModelFiles",
    # ThresholdSkillScoreDisplay
    "EventMatchingCriteria",
    "LocationEventMatchingCriteria",
    "ThresholdSkillScoreAttribute",
    "ThresholdSkillScoreDisplay",
    "ThresholdSkillScoreDisplayGeneral",
    "ThresholdSkillScoreGroup",
    "ThresholdSkillScoreGroupChild",
    "ThresholdSkillScoreParameterPair",
    # ReportExport
    "CurrentForecastReports",
    "ExportForecastReports",
    "ExportSystemStatusReports",
    "GenerateImage",
    "ReportExport",
    "ReportExportTelegramPhoto",
    "TelegramSendPhoto",
    # ArchiveModuleDisplay
    "ArchiveModuleDisplay",
    "ArchiveThresholdIds",
    "DataSearchProperty",
    "DownloadFolders",
    "SearchDataTypes",
    # Delft3DModel
    "Delft3DGeneral",
    "Delft3DMapStack",
    "Delft3DMapStackOutput",
    "Delft3DModel",
    "Delft3DPostAdapter",
    "Delft3DPreAdapter",
    "Delft3DTimeSeries",
    "Delft3DTimeSeriesOutput",
    # ThresholdExport
    "MapThreshold",
    "MultiValuedAttributeTag",
    "ThresholdExport",
    "ThresholdExportDateFormat",
    "ThresholdExportFileName",
    "ThresholdExportModule",
    "ThresholdExportNumberFormat",
    "ThresholdLogFilter",
    # WhatIfTemplates
    "SingleRunWhatIf",
    "TriggerProperty",
    "WhatIfTemplate",
    "WhatIfTemplateBoolValue",
    "WhatIfTemplateConfigFile",
    "WhatIfTemplateDateTimeValue",
    "WhatIfTemplateDoubleValue",
    "WhatIfTemplateEnumeration",
    "WhatIfTemplateEnumerationValue",
    "WhatIfTemplateIntValue",
    "WhatIfTemplateMultiPropertyEnumeration",
    "WhatIfTemplateMultiPropertyEnumerationValue",
    "WhatIfTemplateProperties",
    "WhatIfTemplateProperty",
    "WhatIfTemplateStringValue",
    "WhatIfTemplateTemplateId",
    "WhatIfTemplateValueTypes",
    "WhatIfTemplates",
    # HbvModel
    "HbvActionSpecifications",
    "HbvAdapterFiles",
    "HbvFolderNames",
    "HbvModel",
    "HbvModelDirectories",
    "HbvModelFiles",
    "HbvModelPropertiesFiles",
    "HbvVariables",
    # ModuleExecutionControllerRun
    "DiagnosticDetails",
    "MECtoMC",
    "MecFactory",
    "MecGeneral",
    "MecJNDIContext",
    "MecJmsConnectionDetails",
    "MecQueue",
    "MecQueueConnection",
    "MecRoot",
    "ModuleExecutionControllerRun",
    "PiDiagnosticsScan",
    "SearchCriteria",
    "SearchStrings",
    "TimeSeriesChecks",
    "TimeSeriesFile",
    "TimeSeriesFileThreshold",
    # MassBalance
    "MassBalance",
    "SliceHorizontalFlux",
    "SliceHorizontalVelocity",
    "SliceStorageChange",
    "SliceVerticalFlux",
    "SliceVerticalVelocity",
    # CorrelationSets
    "Correlation",
    "CorrelationSet",
    "CorrelationSets",
    "SelectionCriteria",
    "SelectionPeriod",
    "SelectionTags",
    "SelectionThreshold",
    # FewsInstallationConfigurator
    "ArchiveServerInstall",
    "ClientInstall",
    "DatabaseServerInstall",
    "FewsInstallation",
    "FewsInstallationConfigurator",
    "ForecastingShellInstall",
    "JMSServerInstall",
    "MasterControllerInstall",
    "RemoteMasterControllerInstall",
    # RatingCurves
    "BackWaterCorrection",
    "ConstantFallMethod",
    "JonesEquation",
    "NormalFallMethod",
    "RatingCurve",
    "RatingCurveCorrection",
    "RatingCurveEquation",
    "RatingCurveEquationCoefficient",
    "RatingCurveLocation",
    "RatingCurveTable",
    "RatingCurveTableRecord",
    "RatingCurves",
    "UnsteadyFlowCorrection",
    "ValidPeriod",
    # TaskRunDialog
    "PixelDimension",
    "PixelPosition",
    "TaskRunDialog",
    "TaskRunDialogArchiveTask",
    "TaskRunDialogFlowchart",
    "TaskRunDialogOperatorTask",
    "TaskRunDialogPanel",
    "TaskRunDialogScenarioEntry",
    "TaskRunDialogScenarioSelector",
    "TaskRunDialogSimpleTask",
    "TaskRunDialogTaskDependency",
    "TaskRunDialogTaskGroup",
    "TaskRunDialogTimeEditor",
    "TaskRunDialogValueEditor",
    "TaskRunDialogValueNonEditable",
    # PerformanceIndicatorSets
    "CriteriaEntry",
    "LeadTime",
    "LeadTimeAccuracyIndicator",
    "LeadTimePeriod",
    "LeadTimePeriods",
    "LeadTimes",
    "ModulePerformanceIndicator",
    "PeaksAccuracyIndicator",
    "PerformanceIndicatorSet",
    "PerformanceIndicatorSets",
    "PrecipitationPerformanceIndicator",
    "SelectPeak",
    "SelectPeaks",
    "ThresholdClassBreaks",
    "ThresholdIdEntry",
    "ThresholdIds",
    "ThresholdTimingIndicator",
    # Structures
    "BroadCrestedWeir",
    "CapacityHead",
    "CapacityState",
    "CapacityStateHead",
    "Coefficient",
    "GeneralWeir",
    "Orifice",
    "Pump",
    "SharpCrestedWeir",
    "Structures",
    "TriangularBroadCrestedWeir",
    "TriangularSharpCrestedWeir",
    "UserDefinedExpression",
    "UserDefinedWeir",
    "Weir",
    # WaterCoachDisplay
    "Config",
    "ExperienceLevel",
    "FileAssociation",
    "ImportGridsAsReference",
    "ImportModelStates",
    "ImportModifiers",
    "MultipleSystems",
    "OnTheFlySystem",
    "TimeControl",
    "WaterCoachDisplay",
    # ThresholdOverviewDisplay
    "ColumnAttributes",
    "ForecastFilter",
    "ForecastTime",
    "Tab1",
    "Tab2",
    "Tab3",
    "Tab3Column",
    "Tab4",
    "ThresholdOverviewAttribute",
    "ThresholdOverviewCrossingCountsTab",
    "ThresholdOverviewDisplay",
    "ThresholdOverviewDisplayDescriptor",
    "ThresholdOverviewDisplayGeneral",
    # PcrTransformationSets
    "PcrAreaMap",
    "PcrDefinitions",
    "PcrInputVariable",
    "PcrInternalVariable",
    "PcrOutputVariable",
    "PcrScriptTextModel",
    "PcrTransformationSet",
    "PcrTransformationSets",
    # LookUpSets
    "ColumnData",
    "ColumnDataItem",
    "Condition",
    "ConditionGroup",
    "CriticalConditionLookup",
    "InfoBlock",
    "ListEntry",
    "LookUpSet",
    "LookUpSets",
    "MultiDimensionalTableLookup",
    "RuleCriteria",
    "RuleCriterias",
    "RuleCriteriasItem",
    "TableLookup",
    # ErrorModelSets
    "AutoOrderMethod",
    "ErrorModelInterpolation",
    "ErrorModelParameter",
    "ErrorModelParameters",
    "ErrorModelSet",
    "ErrorModelSets",
    "FixedOrderMethod",
    # SystemMetrics
    "DatabaseMetric",
    "FSSStatusMetric",
    "LogEntryMetric",
    "MCStatusMetric",
    "SystemMetricGeneral",
    "SystemMetrics",
    "TableMetric",
    "WorkflowMetric",
    # WebOCComponentSettings
    "ComponentSettings",
    "GeneralChart",
    "GridLayer",
    "LocationsLayer",
    "LocationsLayerZoomLevel",
    "MetaDataPanel",
    "OverLay",
    "Overlays",
    "PanelPlacementBlock",
    "TimeSeriesChart",
    "TimeSeriesChartLegend",
    "TimeSeriesTable",
    "VerticalProfileTable",
    "WebOCAction",
    "WebOCChart",
    "WebOCComponentSettings",
    "WebOCExternalLayer",
    "WebOCMap",
    "WebOCSSD",
    "WebOCWmsLayer",
    "WebOcXAxis",
    "WebOcYAxis",
    # StateEditor
    "Climatology",
    "Event",
    "Model",
    "ModelGroup",
    "ModelGroups",
    "SeriesGroup",
    "StateEditor",
    "StateEditorGeneral",
    "StateParameter",
    "StateParameterGroup",
    "StateRange",
    "StateSeries",
    # VerificationAnalysisDisplay
    "ConnectedTimeSeries",
    "SelectionFilter",
    "VADColumnChoice",
    "VADLocationColumn",
    "ValuePropertyColumn",
    "ValuePropertyCountColumn",
    "ValuePropertyMaxColumn",
    "VerificationAnalysisDataTab",
    "VerificationAnalysisDisplay",
    # PRTFDisplay
    "BooleanData",
    "DisplayOptions",
    "DoubleData",
    "IntData",
    "PRTFDisplay",
    "PRTFGroup",
    "PRTFGroupOptions",
    "PRTFItem",
    "PRTFParameter",
    "PRTFSubGroup",
    "ParameterData",
    # SystemMonitorDisplay
    "DefaultTimeThreshold",
    "DeprecatedExtraTimeThreshold",
    "SystemMonitorBulletinBoard",
    "SystemMonitorBulletinBoardPlus",
    "SystemMonitorDisplay",
    "SystemMonitorTransferStatus",
    "TimeThreshold",
    "TransferStatusDataFeed",
    "VisibleColumns",
    # DecisionModule
    "Decision",
    "DecisionConditionalWorkflow",
    "DecisionEvaluation",
    "DecisionInitialConditionalWorkflow",
    "DecisionModule",
    "DecisionStateChange",
    "DecisionStates",
    "DecisionTree",
    "DecisionVariableDefinition",
    "RuleConstraint",
    "RuleConstraints",
    "Rules",
    "StateChanges",
    "TimeOffset",
    "TransitionRule",
    "TransitionRules",
    # Barriers
    "Barrier",
    "BarrierStateDefinition",
    "BarrierStateTransition",
    "BarrierStateValue",
    "Barriers",
    "ParameterValue",
    "StateVariable",
    "StateVariableValue",
    "StateVariables",
    "TransitionLevelSpeed",
    "TransitionTimeOffset",
    "TransitionValue",
    "Transitions",
    # TaskProperties + TaskList
    "EnsembleMemberIndexRange",
    "ScheduledTask",
    "Scheduling",
    "SingleTask",
    "TaskList",
    "TaskListTaskGroup",
    "TaskProperties",
    "TaskSelection",
    "YearlyScheduling",
    # TaskPropertiesPredefined
    "BatchTask",
    "OverrulingModuleInstanceRunKey",
    "TaskPropertiesPredefined",
    # SpatialInterpolation (shared)
    "DistanceGeographic",
    "InterpolationDebug",
    "SpatialInterpolation",
    "Variogram",
    # MidlandsModels
    "Dodo",
    "DodoInputForecastParameters",
    "DodoInputHindcastParameters",
    "DodoInputParameters",
    "DodoOutputForecastParameters",
    "DodoOutputHindcastParameters",
    "DodoOutputParameters",
    "DodoParameters",
    "DodoStateParameters",
    "Mcrm",
    "McrmInputForecastParameters",
    "McrmInputHindcastParameters",
    "McrmInputParameters",
    "McrmOutputForecastParameters",
    "McrmOutputHindcastParameters",
    "McrmOutputParameters",
    "McrmParameters",
    "McrmStateParameters",
    "MidlandsAdapterFileNames",
    "MidlandsFolderNames",
    "MidlandsInflow",
    "MidlandsModel",
    "MidlandsModuleFileNames",
    "MidlandsVariables",
    # WhatIf
    "SelectedModifier",
    "WhatIf",
    "WhatIfLocation",
    "WhatIfLocationSet",
    # WhatIfScenario / WhatIfScenarios
    "LocationSelection",
    "PolygonSelection",
    "WhatIfScenario",
    "WhatIfScenarioContent",
    "WhatIfScenarios",
    # WhatIfScenarioFilters
    "ModuleDataSetFiles",
    "ModuleParameterFiles",
    "VariableSets",
    "WhatIfConfigFiles",
    "WhatIfFilterEnumerations",
    "WhatIfFilterProperties",
    "WhatIfFilterProperty",
    "WhatIfFilterStringEnumeration",
    "WhatIfModuleParameter",
    "WhatIfModuleParameterBoolData",
    "WhatIfModuleParameterData",
    "WhatIfModuleParameterDoubleData",
    "WhatIfModuleParameterIntData",
    "WhatIfModuleParameters",
    "WhatIfScenarioFilters",
    # InterpolationSets
    "Basin",
    "BasinGroup",
    "InterpolationOutputSet",
    "InterpolationSet",
    "InterpolationSets",
    "PointPosition",
    "SerialInterpolation",
    # FloodMapSets
    "ContourOutput",
    "FloodDemMap",
    "FloodExtentMap",
    "FloodExtrapolation",
    "FloodMapDirectories",
    "FloodMapInput",
    "FloodMapOutput",
    "FloodMapSet",
    "FloodMapSets",
    "GridFileOutput",
    "LongitudinalProfile",
    "PcrScript",
    # ForecastMixer
    "ForecastMixer",
    "ForecastMixing",
    # TimeSeriesButtonsPanels
    "TimeSeriesButtonsPanels",
    "TsButtonsButton",
    "TsButtonsPanel",
    # ReservoirModel
    "ElevationStorageRow",
    "Reservoir",
    "ReservoirCoefficient",
    "ReservoirInflow",
    "ReservoirModel",
    "ReservoirOutflow",
    # SynchronisationProfiles
    "ContinuousSynchActivity",
    "SingleSynchActivity",
    "SynchActivities",
    "SynchActivity",
    "SynchModifier",
    "SynchModifierList",
    "SynchModifiers",
    "SynchProfile",
    "SynchSchedule",
    "SynchTrigger",
    "SynchTriggers",
    "SynchronisationProfiles",
    # TaskRunProperties
    "ExternalForecastTime",
    "InputProduct",
    "TaskRunProperties",
    "UnexpectedColdStateUsed",
    # CommonAdapter
    "CommonAdapter",
    "CommonAdapterActivities",
    "CommonAdapterActivity",
    "CommonAdapterGeneral",
    "CommonAdapterMapping",
    "CommonAdapterPointMapping",
    "CommonAdapterProfileActivity",
    "CommonAdapterTimeSeriesActivity",
    # ArchiveRun
    "ArchiveRun",
    "ExportArchiveRun",
    "ImportArchiveRun",
    "LogEventConstraint",
    # DocumentDisplays
    "DocumentDisplay",
    "DocumentDisplayBrowser",
    "DocumentDisplayBrowserArchiveProducts",
    "DocumentDisplayBrowserLayout",
    "DocumentDisplayBrowserLayoutHeaders",
    "DocumentDisplayCompose",
    "DocumentDisplayHeader",
    "DocumentDisplayReport",
    "DocumentDisplayShowReport",
    "DocumentDisplays",
    # FewsPiServiceConfig
    "FewsPiServiceConfig",
    "PiServiceExternalUnit",
    "PiServiceGeneral",
    "PiServiceModuleData",
    "PiServiceTimeSeries",
    # WebService
    "MCTaskWebService",
    "WebService",
    # SynchronisationConfiguration
    "SynchConfigConnection",
    "SynchConfigDatabase",
    "SynchConfigFactory",
    "SynchConfigJNDIContext",
    "SynchConfigLogin",
    "SynchConfigMC",
    "SynchConfigMessaging",
    "SynchConfigProcessor",
    "SynchConfigQueue",
    "SynchConfigQueueConnection",
    "SynchConfigRoot",
    "SynchConfigSchema",
    "SynchConfigSynch",
    "SynchConfigSynchronisation",
    "SynchronisationConfiguration",
    # RdbmsExport
    "RdbmsExport",
    "RdbmsExportFilter",
    "RdbmsExportModuleInstance",
    # AmalgamateModule
    "AmalgamateModule",
    "AmalgamateTask",
    # SynchronisationChannels
    "SynchChannel",
    "SynchChannelTableNames",
    "SynchronisationChannels",
    # ExportRun
    "ExportRun",
    "ExportRunEntry",
    # GeoReferenceDataSet
    "GeoReferenceData",
    "GeoReferenceDataPoint",
    "GeoReferenceDataSet",
    # GribTimeSeriesReader
    "GribRecordDefinition",
    "GribTimeSeriesReader",
    # ConfigUpdateScriptConfig
    "ConfigUpdateScriptConfig",
    "ImportMapLayerFilesSettings",
    # WorkflowTestRun
    "WftrActivities",
    "WftrCheckPerformanceActivity",
    "WftrCompareActivity",
    "WftrCopyActivity",
    "WftrDirDefinition",
    "WftrExportLogsActivity",
    "WftrExportTimeSeriesActivity",
    "WftrGeneral",
    "WftrPurgeActivity",
    "WftrSetSystemTimeActivity",
    "WftrSleepActivity",
    "WftrTestReport",
    "WftrTextMatchActivity",
    "WftrTimeSeriesSets",
    "WftrWorkflowActivity",
    "WorkflowTestRun",
]
