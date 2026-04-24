"""PiFileGenerator.xml — generates PI files from map-stack sources.

Top level:
  - description?
  - general (workDir, diagnosticFile, dateFormat?, geoDatum?)
  - preActivity? (ExecuteActivity)
  - activity (relativePeriod, timeStep, moduleLogFile?, mapStackFile+)
  - postActivity? (ExecuteActivity)
  - version attribute, fixed="1.1"
"""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel, RelativeViewPeriod, TimeStep
from .general_adapter_run import ExecuteActivity


class PiFileGeneratorGeneral(FewsModel):
    workDir: str
    diagnosticFile: str
    dateFormat: str | None = None
    geoDatum: str | None = None


class PiMapStackFile(FewsModel):
    """One `<mapStackFile/>` — all five attributes required per XSD."""

    mapStackXMLFile: str
    gridFilepattern: str
    gridFileType: str
    parameterID: str
    locationID: str


class PiFileGeneratorActivity(FewsModel):
    relativePeriod: RelativeViewPeriod
    timeStep: TimeStep
    moduleLogFile: str | None = None
    mapStackFile: list[PiMapStackFile] = Field(min_length=1)


class PiFileGenerator(FewsModel):
    version: str = "1.1"
    description: str | None = None
    general: PiFileGeneratorGeneral
    preActivity: ExecuteActivity | None = None
    activity: PiFileGeneratorActivity
    postActivity: ExecuteActivity | None = None
