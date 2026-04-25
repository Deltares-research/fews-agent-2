"""Reports.xml — module config for batch report generation.

Reports.xsd is one of the largest FEWS schemas (~50+ format types,
deeply nested chart / table / animation specs, choice groups
inside choice groups). Modelling every leaf would dwarf this file
without adding XSD-validation value beyond what lxml gives us, so
the strategy here is:

* Top-level root: typed ``Reports`` with the XSD's two children
  (``declarations`` + ``report[]``) and the fixed ``version`` attribute.
* ``ReportsDeclarations``: keys for every top-level child are present
  but stored as ``list[dict[str, Any]]`` (or single dict / scalar)
  passthroughs, so callers populate each XSD format type as a dict.
  Templates emit each in XSD-sequence order via ``dict_to_xml``.
* ``Report``: same shape — typed top-level wrapper, dict pass-through
  for the heterogeneous instance children, plus typed scalar fields
  for ``template`` / ``outputSubDir`` / ``outputFileName`` /
  ``outputLineSeparator`` / ``defineLocal`` / attributes.

This keeps coverage of the XSD complete (any valid Reports.xml can be
expressed) while bounding schema complexity. Future work can promote
specific format types (chartFormat, tableFormat) to typed sub-models
when load-bearing.
"""
from __future__ import annotations

from typing import Any

from pydantic import Field

from .common import FewsModel


class ReportsDeclarations(FewsModel):
    """XSD ReportsDeclarationsComplexType.

    Each XSD child is exposed as an optional / list field. The deeply
    nested format types (ChartFormat, ReportSummaryFormat, …) are kept
    as dict[str, Any] passthroughs to keep coverage broad without
    duplicating the entire XSD here. Templates emit them via
    ``dict_to_xml``.
    """

    defineGlobal: list[dict[str, Any]] = Field(default_factory=list)
    chartFormat: list[dict[str, Any]] = Field(default_factory=list)
    summaryFormat: list[dict[str, Any]] = Field(default_factory=list)
    tableFormat: list[dict[str, Any]] = Field(default_factory=list)
    htmlTableFormat: list[dict[str, Any]] = Field(default_factory=list)
    rowPerLocationHtmlTableFormat: list[dict[str, Any]] = Field(default_factory=list)
    rowPerLocationCsvTableFormat: list[dict[str, Any]] = Field(default_factory=list)
    rowPerEventTimeHtmlTableFormat: list[dict[str, Any]] = Field(default_factory=list)
    thresholdsCrossingsTable: list[dict[str, Any]] = Field(default_factory=list)
    thresholdCrossingCountsTableFormat: list[dict[str, Any]] = Field(default_factory=list)
    flagCountsTableFormat: list[dict[str, Any]] = Field(default_factory=list)
    flagSourceCountsTableFormat: list[dict[str, Any]] = Field(default_factory=list)
    ratingCurveTableFormat: list[dict[str, Any]] = Field(default_factory=list)
    ensembleThresholdsTable: list[dict[str, Any]] = Field(default_factory=list)
    maximumStatusTable: list[dict[str, Any]] = Field(default_factory=list)
    mergedPrecipitationTable: list[dict[str, Any]] = Field(default_factory=list)
    modifierSummariesTableFormat: list[dict[str, Any]] = Field(default_factory=list)
    forecastPerformanceTableFormat: list[dict[str, Any]] = Field(default_factory=list)
    forecastStatisticsTableFormat: list[dict[str, Any]] = Field(default_factory=list)
    statusFormat: list[dict[str, Any]] = Field(default_factory=list)
    systemStatusTable: list[dict[str, Any]] = Field(default_factory=list)
    floodScenarioFormat: list[dict[str, Any]] = Field(default_factory=list)
    dateFormat: list[dict[str, Any]] = Field(default_factory=list)
    numberFormat: list[dict[str, Any]] = Field(default_factory=list)
    units: str | None = None
    generatePdf: bool | None = None
    generatePdfCommandLineOptions: str | None = None
    generateImage: dict[str, Any] | None = None
    templateDir: str | None = None
    reportsRootDir: str
    reportsRootSubDir: str | None = None
    sendToLocalFileSystem: bool | None = None
    temporary: bool | None = None
    embedImagesInReport: bool | None = None
    timeZone: dict[str, Any] | None = None
    locale: dict[str, Any] | None = None
    inputVariable: list[dict[str, Any]] = Field(default_factory=list)
    dataFeedId: str | None = None
    disableDataFeedInfo: bool | None = None


class Report(FewsModel):
    """XSD ReportComplexType — one report instance.

    All child elements are exposed as fields. Heterogeneous /
    deeply-nested ones are dict passthroughs; flat scalars are typed.
    """

    locationId: list[str] = Field(default_factory=list)
    locationSetId: list[str] = Field(default_factory=list)
    parentLocationId: list[str] = Field(default_factory=list)
    parentLocationSetId: list[str] = Field(default_factory=list)
    thresholdLocationId: list[str] = Field(default_factory=list)
    thresholdLocationSetId: list[str] = Field(default_factory=list)
    inputVariable: list[dict[str, Any]] = Field(default_factory=list)
    fileResource: list[dict[str, Any]] = Field(default_factory=list)
    chart: list[dict[str, Any]] = Field(default_factory=list)
    displayChart: list[dict[str, Any]] = Field(default_factory=list)
    ratingCurveChart: list[dict[str, Any]] = Field(default_factory=list)
    summary: list[dict[str, Any]] = Field(default_factory=list)
    table: list[dict[str, Any]] = Field(default_factory=list)
    htmlTable: list[dict[str, Any]] = Field(default_factory=list)
    thresholdLabelTable: list[dict[str, Any]] = Field(default_factory=list)
    valuePropertiesTags: list[dict[str, Any]] = Field(default_factory=list)
    hwLwHtmlTable: list[dict[str, Any]] = Field(default_factory=list)
    ratingCurveTable: list[dict[str, Any]] = Field(default_factory=list)
    rowPerLocationHtmlTable: list[dict[str, Any]] = Field(default_factory=list)
    rowPerLocationCsvTable: list[dict[str, Any]] = Field(default_factory=list)
    rowPerEventTimeHtmlTable: list[dict[str, Any]] = Field(default_factory=list)
    mp4: list[dict[str, Any]] = Field(default_factory=list)
    avi: list[dict[str, Any]] = Field(default_factory=list)
    animatedGif: list[dict[str, Any]] = Field(default_factory=list)
    spatialPlotSnapshots: list[dict[str, Any]] = Field(default_factory=list)
    schematicStatusDisplayPanelMp4: list[dict[str, Any]] = Field(default_factory=list)
    schematicStatusDisplayPanelAvi: list[dict[str, Any]] = Field(default_factory=list)
    schematicStatusDisplayPanelAnimatedGif: list[dict[str, Any]] = Field(default_factory=list)
    schematicStatusDisplayPanelSnapshotsPng: list[dict[str, Any]] = Field(default_factory=list)
    schematicStatusDisplayPanelSnapshotsSvg: list[dict[str, Any]] = Field(default_factory=list)
    thresholdsCrossingsTable: list[dict[str, Any]] = Field(default_factory=list)
    thresholdCrossingCountsTable: list[dict[str, Any]] = Field(default_factory=list)
    flagCountsTable: list[dict[str, Any]] = Field(default_factory=list)
    flagSourceCountsTable: list[dict[str, Any]] = Field(default_factory=list)
    ensembleThresholdsTable: list[dict[str, Any]] = Field(default_factory=list)
    maximumStatusTable: list[dict[str, Any]] = Field(default_factory=list)
    mergedPrecipitationTable: list[dict[str, Any]] = Field(default_factory=list)
    modifierSummariesTable: list[dict[str, Any]] = Field(default_factory=list)
    forecastPerformanceTable: list[dict[str, Any]] = Field(default_factory=list)
    forecastStatisticsTable: list[dict[str, Any]] = Field(default_factory=list)
    status: list[dict[str, Any]] = Field(default_factory=list)
    systemStatusTable: list[dict[str, Any]] = Field(default_factory=list)
    statusShapeFile: list[dict[str, Any]] = Field(default_factory=list)
    floodScenarioXml: dict[str, Any] | None = None
    forecastModelResultsXml: dict[str, Any] | None = None
    forecastThresholdCrossingXml: dict[str, Any] | None = None
    template: str
    outputSubDir: str | None = None
    outputFileName: str
    outputLineSeparator: str | None = None
    defineLocal: list[dict[str, Any]] = Field(default_factory=list)
    # attributes
    scrubFolder: bool | None = None
    sameAxesScale: bool | None = None
    singleLocation: bool | None = None
    omitLocationIdInOutputFileName: bool | None = None


class Reports(FewsModel):
    """Root of Reports.xml."""

    declarations: ReportsDeclarations
    report: list[Report] = Field(min_length=1)
