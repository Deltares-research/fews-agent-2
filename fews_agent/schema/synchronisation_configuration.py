"""SynchronisationConfiguration.xml — deprecated since 2017.02.

Root element is ``<fews-master-config>`` (hyphenated, so the generator
template hard-codes the element name rather than deriving it from the
model name). Describes JMS queue / JNDI / database / synchronisation
settings for the old FEWS Master Controller.

All types prefixed ``Obsolete*`` in the XSD.
"""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel


class SynchConfigFactory(FewsModel):
    jndi: str | None = None


class SynchConfigQueueConnection(FewsModel):
    factory: SynchConfigFactory


class SynchConfigJNDIContext(FewsModel):
    factory: str | None = None
    provider: str | None = None
    prefixes: str | None = None


class SynchConfigRoot(FewsModel):
    jndi: str | None = None


class SynchConfigSynch(FewsModel):
    jndi: str | None = None
    timeout: int | None = None


class SynchConfigQueue(FewsModel):
    root: SynchConfigRoot
    synch: SynchConfigSynch


class SynchConfigMC(FewsModel):
    jndicontext: SynchConfigJNDIContext
    queue: SynchConfigQueue
    queueconnection: SynchConfigQueueConnection | None = None
    id: str | None = None
    name: str | None = None


class SynchConfigConnection(FewsModel):
    string: str | None = None
    userid: str | None = None
    password: str | None = None


class SynchConfigDatabase(FewsModel):
    connection: SynchConfigConnection
    driverclass: str | None = None


class SynchConfigMessaging(FewsModel):
    maxrecords: int | None = None
    maxlobdata: int | None = None


class SynchConfigProcessor(FewsModel):
    maxlistsize: int | None = None


class SynchConfigSchema(FewsModel):
    location: str | None = None


class SynchConfigSynchronisation(FewsModel):
    messaging: SynchConfigMessaging
    processor: SynchConfigProcessor
    schema_: SynchConfigSchema = Field(alias="schema")


class SynchConfigLogin(FewsModel):
    timeout: int | None = None


class SynchronisationConfiguration(FewsModel):
    """Root ``<fews-master-config>`` element."""

    mc: list[SynchConfigMC] = Field(min_length=1)
    synchronisation: SynchConfigSynchronisation
    queueconnection: SynchConfigQueueConnection | None = None
    defaultMcId: str | None = None
    database: SynchConfigDatabase | None = None
    login: SynchConfigLogin | None = None
