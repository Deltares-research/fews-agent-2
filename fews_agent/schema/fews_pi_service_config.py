"""FewsPiServiceConfig.xml — legacy PI service plugin config.

Marked ``LEGACY, NO LONGER USED``. Optional general block + parallel
lists of timeSeries / moduleDataSet / moduleParameterSet / moduleState
activity entries.

``<timeSeries>`` has an inner XSD choice: timeSeriesSet[] XOR the
empty markers ``selectedTimeSeries`` / ``selectedSegmentTimeSeries``.
"""
from __future__ import annotations

from decimal import Decimal

from pydantic import Field, model_validator

from .common import FewsModel, TimeSeriesSet, TimeZone


class PiServiceGeneral(FewsModel):
    importDir: str | None = None
    importIdMap: str | None = None
    importUnitConversionsId: str | None = None
    exportDir: str | None = None
    exportIdMap: str | None = None
    exportUnitConversionsId: str | None = None
    writeToFile: bool | None = None
    timeZone: TimeZone | None = None


class PiServiceExternalUnit(FewsModel):
    parameterId: str
    unit: str


class PiServiceTimeSeries(FewsModel):
    """Inner XSD choice: ``timeSeriesSet[]`` XOR exactly one of the
    empty-element markers."""

    id: str
    description: str | None = None
    exportBinFile: bool | None = None
    timeSeriesSet: list[TimeSeriesSet] = Field(default_factory=list)
    selectedTimeSeries: bool = False
    selectedSegmentTimeSeries: bool = False
    omitMissingValues: bool | None = None
    missingValue: Decimal | None = None
    convertDatum: bool | None = None
    externalUnit: list[PiServiceExternalUnit] = Field(default_factory=list)

    @model_validator(mode="after")
    def _one_source(self) -> PiServiceTimeSeries:
        sources = [
            bool(self.timeSeriesSet),
            self.selectedTimeSeries,
            self.selectedSegmentTimeSeries,
        ]
        if sum(sources) != 1:
            raise ValueError(
                "piServiceConfig.timeSeries: supply exactly one of "
                "timeSeriesSet[], selectedTimeSeries=True, selectedSegmentTimeSeries=True"
            )
        return self


class PiServiceModuleData(FewsModel):
    id: str
    moduleInstanceId: str
    description: str | None = None


class FewsPiServiceConfig(FewsModel):
    general: PiServiceGeneral | None = None
    timeSeries: list[PiServiceTimeSeries] = Field(default_factory=list)
    moduleDataSet: list[PiServiceModuleData] = Field(default_factory=list)
    moduleParameterSet: list[PiServiceModuleData] = Field(default_factory=list)
    moduleState: list[PiServiceModuleData] = Field(default_factory=list)
