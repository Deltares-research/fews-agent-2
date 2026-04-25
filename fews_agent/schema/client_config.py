"""ClientConfig.xml — per-OC / FSS / SA system connection + caching.

Top-level XSD sequence is wide and mixes simple options with broad
sub-trees (databaseServer, synchProfile[], externalTables, …). The
top-level fields are typed in XSD-sequence order; deep configuration
sub-trees are passed through as ``dict[str, Any]``.

The XSD's ConnectionsChoice group (``databaseServer + jmsServer?`` OR
``connection[]``) is exposed as two parallel optional fields; callers
honour the "exactly one" choice. This avoids embedding large
sub-models in this schema while still preserving XSD ordering.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from .common import FewsModel


class RootConfigFiles(FewsModel):
    """XSD RootConfigFilesComplexType — list of file names."""

    name: list[str] = Field(min_length=1)


class Logging(FewsModel):
    """XSD LoggingComplexType."""

    debugEnabled: bool | None = None
    rollingTotalSizeMB: int | None = None
    logFileEntryIncludesTaskRunId: bool | None = None
    windowsEventLogEnabled: bool | None = None
    linuxSyslogFacility: str | None = None


class AutoExportModuleDataSet(FewsModel):
    """XSD AutoExportModuleDataSetComplexType — attribute-only."""

    name: str
    exportDir: str


class DirectSynchProfile(FewsModel):
    """XSD DirectSynchProfileComplexType."""

    description: str | None = None
    id: str
    name: str | None = None


class ClientConfig(FewsModel):
    """Root of ClientConfig.xml."""

    title: str | None = None
    clientType: Literal[
        "Forecasting Shell",
        "Operator Client",
        "Stand alone",
        "Computational Framework",
        "Web Services",
        "WaterCoach Leader",
        "WaterCoach Participant",
    ] | None = None
    otherRootConfigFiles: RootConfigFiles | None = None
    # ConnectionsChoice — supply at most one shape. Both are
    # passthrough dicts because their content (DatabaseServer,
    # JMSServer, ClientConnection) is broad.
    databaseServer: dict[str, Any] | None = None
    jmsServer: dict[str, Any] | None = None
    connection: list[dict[str, Any]] = Field(default_factory=list)
    jvmOption: list[str] = Field(default_factory=list)
    localCacheSizeMB: int | None = None
    localDataStoreFormat: Literal["Firebird", "Derby", "HyperSQL"] | None = None
    logging: Logging | None = None
    coldStatesDirectory: str | None = None
    warmStatesDirectory: str | None = None
    autoExportModuleDataSet: list[AutoExportModuleDataSet] = Field(default_factory=list)
    # ProxyAutoConfigChoice — at most one.
    proxyAutoConfigScriptUrl: str | None = None
    proxyAutoConfigScriptContent: str | None = None
    # Dummy / synch profile sequence.
    directSynchProfile: DirectSynchProfile | None = None
    synchProfile: list[dict[str, Any]] = Field(default_factory=list)
    # ExternalTables is large; passthrough.
    externalTables: dict[str, Any] | None = None
