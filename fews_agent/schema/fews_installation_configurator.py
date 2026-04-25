"""FewsInstallationConfigurator.xml — installation configuration.

A ``<fewsInstallationConfigurator>`` wraps one or more
``<systemConfiguration>`` entries, each describing a complete FEWS
client-server entity: JMS server (optional, legacy), central DB
server, master controller, optional remote MCs, forecasting shells,
operator clients, and optionally a Deltares archive server.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .common import FewsModel


AppServerType = Literal["jboss", "jboss4", "jboss5", "jboss7", "weblogic", "activemq"]
DbServerType = Literal[
    "oracle", "sqlserver", "postgresql", "sqlserverms", "sqlserverjtds"
]
OS = Literal["windows", "linux", "hpux"]
FssOS = Literal["windows", "linux", "both"]
ClientMode = Literal[
    "direct database access", "synchronising client", "wis synchronising client"
]


class JMSServerInstall(FewsModel):
    """XSD JMSServerInstallComplexType — shared between installer and
    (deprecated) remote-MC entries."""

    appServerType: AppServerType
    appServerName: str
    rootJNDI: str
    appServerPort: int | None = None
    appJavaHome: str | None = None


class DatabaseServerInstall(FewsModel):
    dbServerType: DbServerType
    dbServerName: str
    dbInstanceName: str
    dbServerPort: int | None = None
    dbInstanceUser: str | None = None
    dbInstancePassword: str | None = None
    dbEncryptPassword: bool | None = None


class MasterControllerInstall(FewsModel):
    mcId: str
    mcRegionName: str
    mcOS: OS
    mcJavaHome: str
    fewsmcHome: str
    aiFilesDirBaseName: str
    mcRestartScript: str | None = None
    aiRestartScriptPath: str | None = None
    aiRestartScriptArgs: str | None = None


class RemoteMasterControllerInstall(FewsModel):
    """XSD choice: remoteDbServer XOR remoteJMSServer (legacy)."""

    remoteMcId: str
    remoteDbServer: DatabaseServerInstall | None = None
    remoteJMSServer: JMSServerInstall | None = None

    @model_validator(mode="after")
    def _one_server(self) -> RemoteMasterControllerInstall:
        if (self.remoteDbServer is None) == (self.remoteJMSServer is None):
            raise ValueError(
                "remoteMasterController: supply exactly one of remoteDbServer or "
                "remoteJMSServer"
            )
        return self


class ForecastingShellInstall(FewsModel):
    numberOfFSS: int
    fssOS: FssOS
    fssJavaHome: str
    fssRootDir: str
    fssRegionHomeName: str
    clientMode: ClientMode | None = None


class ClientInstall(FewsModel):
    ocDir: str
    clientMode: ClientMode


class ArchiveServerInstall(FewsModel):
    archiveServerName: str
    archiveServerPort: int
    archiveRootDir: str


class FewsInstallation(FewsModel):
    dbServer: DatabaseServerInstall
    masterController: MasterControllerInstall
    forecastingShells: list[ForecastingShellInstall] = Field(min_length=1)
    jmsServer: JMSServerInstall | None = None
    remoteMasterController: list[RemoteMasterControllerInstall] = Field(
        default_factory=list
    )
    operatorClients: list[ClientInstall] = Field(default_factory=list)
    archiveServer: ArchiveServerInstall | None = None


class FewsInstallationConfigurator(FewsModel):
    systemConfiguration: list[FewsInstallation] = Field(min_length=1)
