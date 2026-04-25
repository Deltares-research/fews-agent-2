"""ReservoirModel.xml — reservoir routing model adapter.

Root element is ``<ReservoirModel>`` (PascalCase — an oddity in FEWS XSDs).
The ``general`` block reuses ``CommonAdapterGeneral`` from common_adapter.
Inflow/outflow functions list coefficients; the reservoir block carries
the elevation-storage rating table.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import Field

from .common import FewsModel
from .common_adapter import CommonAdapterGeneral


ReservoirMethod = Literal[
    "levelPoolMethod",
    "modifiedPulsMethod",
    "goodrichMethod",
    "holbeamMethod",
]
ReservoirInflowFunction = Literal["singleInflow", "holbeamInflow", "brutonInflow"]
ReservoirOutflowFunction = Literal["spillway", "gate", "elevationDischargeTable"]
ReservoirCoefficientType = Literal[
    "inflowFactorBelowCwiThreshold",
    "inflowFactorAboveOrEqualCwiThreshold",
    "cwiThreshold",
    "cwiMinValue",
    "gateBlockage",
    "gateCc",
    "gateLevel",
    "gateOpening",
    "gateWidth",
    "kSlow",
    "kQuick",
    "qThreshold",
    "rainIntensity",
    "spillwayCd",
    "spillwayLevel",
    "spillwaySideslope",
    "spillwayWidth",
]


class ReservoirCoefficient(FewsModel):
    value: Decimal
    coefficientType: ReservoirCoefficientType | None = None


class ReservoirInflow(FewsModel):
    inflowFunction: ReservoirInflowFunction | None = None
    coefficient: list[ReservoirCoefficient] = Field(default_factory=list)


class ReservoirOutflow(FewsModel):
    limitLower: Decimal | None = None
    limitUpper: Decimal | None = None
    outflow: ReservoirOutflowFunction | None = None
    userDefinedFunction: str | None = None
    coefficient: list[ReservoirCoefficient] = Field(default_factory=list)


class ElevationStorageRow(FewsModel):
    """XSD ElevationStorageTableComplexType — attribute-only row."""

    elevation: Decimal
    storage: Decimal
    stage: Decimal | None = None
    area: Decimal | None = None
    outflowDischarge: Decimal | None = None


class Reservoir(FewsModel):
    functionType: ReservoirMethod
    elevationInterval: Decimal
    elevationStorageTable: list[ElevationStorageRow] = Field(default_factory=list)


class ReservoirModel(FewsModel):
    """Root of ReservoirModel.xml (note PascalCase element name)."""

    general: CommonAdapterGeneral
    inflowFunctions: ReservoirInflow
    outflowFunctions: list[ReservoirOutflow] = Field(min_length=1)
    reservoir: Reservoir
