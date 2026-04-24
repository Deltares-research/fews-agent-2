"""ModuleExecutionControllerRun.xml — MEC runtime configuration.

Each MEC instance run consumes one of these. Reuses ExecuteActivity
from general_adapter_run for both the ``<module>`` and the
``<diagnosticModule>`` sub-elements.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import FewsModel
from .general_adapter_run import ExecuteActivity


SearchAction = Literal["Report", "Report+Stop"]


class MecGeneral(FewsModel):
    description: str | None = None
    rootDir: str | None = None
    workDir: str | None = None


class SearchCriteria(FewsModel):
    searchString: str
    action: SearchAction


class SearchStrings(FewsModel):
    searchCriteria: list[SearchCriteria] = Field(min_length=1)


class PiDiagnosticsScan(FewsModel):
    fileLocation: str
    timeStepAlias: str
    searchStrings: SearchStrings | None = None


class TimeSeriesFileThreshold(FewsModel):
    upper: float
    lower: float


class TimeSeriesFile(FewsModel):
    fileLocation: str
    name: str | None = None
    softThreshold: TimeSeriesFileThreshold
    hardThreshold: TimeSeriesFileThreshold


class TimeSeriesChecks(FewsModel):
    timeSeriesFile: list[TimeSeriesFile] = Field(min_length=1)


class DiagnosticDetails(FewsModel):
    diagnosticModule: ExecuteActivity
    interval: int
    piDiagnosticsScan: PiDiagnosticsScan
    timeSeriesChecks: TimeSeriesChecks | None = None


class MecFactory(FewsModel):
    jndi: str | None = None


class MecQueueConnection(FewsModel):
    factory: MecFactory


class MecJNDIContext(FewsModel):
    factory: str | None = None
    provider: str | None = None
    prefixes: str | None = None


class MecRoot(FewsModel):
    jndi: str | None = None


class MECtoMC(FewsModel):
    jndi: str | None = None
    timeout: int | None = None


class MecQueue(FewsModel):
    root: MecRoot
    mectomc: MECtoMC


class MecJmsConnectionDetails(FewsModel):
    queueconnection: MecQueueConnection
    jndicontext: MecJNDIContext
    queue: MecQueue


class ModuleExecutionControllerRun(FewsModel):
    """Root of ``<ModuleExecutionControllerRun>``."""

    mecGeneral: MecGeneral | None = None
    module: ExecuteActivity
    diagnosticDetails: DiagnosticDetails
    jmsConnectionDetails: MecJmsConnectionDetails | None = None
