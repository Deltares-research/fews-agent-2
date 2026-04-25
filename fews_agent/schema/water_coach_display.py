"""WaterCoachDisplay.xml — WaterCoach display config (gamification).

Uses the top-level ``SystemsGroupChoice`` (onTheFlySystem XOR
multipleSystems — both optional) plus one or more ``<config>`` blocks.
"""
from __future__ import annotations

from pydantic import Field, model_validator

from .common import FewsModel, RelativeViewPeriod


class TimeControl(FewsModel):
    pause: bool | None = None
    next: bool | None = None
    set: bool | None = None
    fastForwardBackward: bool | None = None


class ExperienceLevel(FewsModel):
    levels: str | None = None
    adjustLevel: bool | None = None


class FileAssociation(FewsModel):
    """simpleContent extension — filename text with ``extension`` attr."""

    value: str
    extension: str


class Config(FewsModel):
    hideYear: bool
    defaultPeriod: RelativeViewPeriod | None = None
    scenarioScriptDatabasePath: str | None = None
    gridBinFilesPath: list[str] = Field(default_factory=list)
    fileAssociation: list[FileAssociation] = Field(default_factory=list)
    timeControl: TimeControl | None = None
    experienceLevel: ExperienceLevel | None = None
    fewsLogEventCodes: str | None = None
    serverHostName: str | None = None
    serverPort: int | None = None
    writePiOutput: bool | None = None
    copyLocalDataStore: bool | None = None
    defaultUserName: str | None = None
    defaultScenario: str | None = None
    defaultScript: str | None = None
    scriptLogPath: str | None = None
    displayConfirm: bool | None = None
    clientConfigExportUrl: str | None = None


class ImportGridsAsReference(FewsModel):
    """Attribute-only element. ``import_`` aliased from ``import``."""

    visible: bool
    import_: bool = Field(alias="import")


class ImportModelStates(FewsModel):
    visible: bool
    import_: bool = Field(alias="import")


class ImportModifiers(FewsModel):
    visible: bool
    import_: bool = Field(alias="import")


class OnTheFlySystem(FewsModel):
    eventTypeId: str
    areaId: list[str] = Field(default_factory=list)
    permission: str | None = None
    importGridsAsReference: ImportGridsAsReference | None = None
    importModelStates: ImportModelStates | None = None
    importModifiers: ImportModifiers | None = None


class MultipleSystems(FewsModel):
    enabled: bool
    systemTimeFile: str


class WaterCoachDisplay(FewsModel):
    """Root — systems choice (at most one of onTheFly/multiple) + config+."""

    config: list[Config] = Field(min_length=1)
    onTheFlySystem: OnTheFlySystem | None = None
    multipleSystems: MultipleSystems | None = None

    @model_validator(mode="after")
    def _one_system(self) -> WaterCoachDisplay:
        if self.onTheFlySystem is not None and self.multipleSystems is not None:
            raise ValueError(
                "waterCoachDisplay: supply at most one of onTheFlySystem or "
                "multipleSystems"
            )
        return self
