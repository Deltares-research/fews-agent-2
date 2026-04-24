"""Structures.xml — pumps, weirs, orifices.

Root is a ``choice maxOccurs="unbounded"`` over pump / weir / orifice.
Modelled as parallel lists (same pattern as massBalance/whatIfTemplates).

Weir has an inner XSD choice with 10 named elements over 6 distinct
body shapes. We carry them as 10 separate optional fields on
``Weir`` and enforce 'exactly one' via a model_validator, so round-
tripping the chosen variant keeps its element name.
"""
from __future__ import annotations

from pydantic import Field, model_validator

from .common import FewsModel


class CapacityState(FewsModel):
    pumpingState: float
    capacity: float


class CapacityHead(FewsModel):
    head: float
    capacity: float


class CapacityStateHead(FewsModel):
    pumpingState: float
    head: float
    capacity: float


class Pump(FewsModel):
    """XSD choice: one of capacityConstant / capacityStateTable* /
    capacityHeadTable* / capacityStateHeadTable*."""

    id: str
    name: str | None = None
    capacityConstant: float | None = None
    capacityStateTable: list[CapacityState] = Field(default_factory=list)
    capacityHeadTable: list[CapacityHead] = Field(default_factory=list)
    capacityStateHeadTable: list[CapacityStateHead] = Field(default_factory=list)

    @model_validator(mode="after")
    def _one_capacity(self) -> Pump:
        branches = [
            self.capacityConstant is not None,
            bool(self.capacityStateTable),
            bool(self.capacityHeadTable),
            bool(self.capacityStateHeadTable),
        ]
        if sum(branches) != 1:
            raise ValueError(
                "pump: supply exactly one capacity form (constant / state / "
                "head / state+head table)"
            )
        return self


class Coefficient(FewsModel):
    id: str
    value: float


class UserDefinedExpression(FewsModel):
    expression: str
    coefficient: list[Coefficient] = Field(min_length=1)


class GeneralWeir(FewsModel):
    id: str
    name: str | None = None
    width: float
    freeFlowLimitCoefficient: float
    freeDischargeCoefficient: float
    drownedDischargeCoefficient: float
    height: float | None = None


class UserDefinedWeir(FewsModel):
    id: str
    name: str | None = None
    freeFlowLimitCoefficient: float
    freeFlowExpression: UserDefinedExpression
    drownedFlowExpression: UserDefinedExpression


class BroadCrestedWeir(FewsModel):
    """Shared body for rectangularProfile / roundNoseHorizontalCrest /
    romijn / faiyum / triangularBroadCrest-base."""

    id: str
    name: str | None = None
    width: float
    length: float
    height: float | None = None


class SharpCrestedWeir(FewsModel):
    """Shared body for rectangularThinPlate / cipoletti / crump /
    triangularThinPlate-base / flatV-base."""

    id: str
    name: str | None = None
    width: float
    height: float | None = None


class TriangularBroadCrestedWeir(BroadCrestedWeir):
    heightTriangle: float


class TriangularSharpCrestedWeir(SharpCrestedWeir):
    heightTriangle: float


class Weir(FewsModel):
    """XSD choice of 10 weir-variant elements; exactly one must be set."""

    generalWeir: GeneralWeir | None = None
    userDefinedWeir: UserDefinedWeir | None = None
    rectangularProfileWeir: BroadCrestedWeir | None = None
    roundNoseHorizontalCrestWeir: BroadCrestedWeir | None = None
    romijnWeir: BroadCrestedWeir | None = None
    triangularBroadCrestWeir: TriangularBroadCrestedWeir | None = None
    faiyumWeir: BroadCrestedWeir | None = None
    rectangularThinPlateWeir: SharpCrestedWeir | None = None
    triangularThinPlateWeir: TriangularSharpCrestedWeir | None = None
    cipolettiWeir: SharpCrestedWeir | None = None
    crumpWeir: SharpCrestedWeir | None = None
    flatVWeir: TriangularSharpCrestedWeir | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> Weir:
        variants = [
            self.generalWeir, self.userDefinedWeir,
            self.rectangularProfileWeir, self.roundNoseHorizontalCrestWeir,
            self.romijnWeir, self.triangularBroadCrestWeir, self.faiyumWeir,
            self.rectangularThinPlateWeir, self.triangularThinPlateWeir,
            self.cipolettiWeir, self.crumpWeir, self.flatVWeir,
        ]
        if sum(v is not None for v in variants) != 1:
            raise ValueError(
                "weir: supply exactly one of the 12 weir-variant fields"
            )
        return self


class Orifice(FewsModel):
    """The XSD nests a weir inside orifice ``<weir>`` element."""

    id: str
    name: str | None = None
    freeDischargeCoefficient: float
    freeContractionCoefficient: float
    drownedDischargeCoefficient: float
    drownedContractionCoefficient: float
    weir: Weir
    gateLevel: float | None = None


class Structures(FewsModel):
    pump: list[Pump] = Field(default_factory=list)
    weir: list[Weir] = Field(default_factory=list)
    orifice: list[Orifice] = Field(default_factory=list)

    @model_validator(mode="after")
    def _at_least_one(self) -> Structures:
        if not any([self.pump, self.weir, self.orifice]):
            raise ValueError("structures: supply at least one pump/weir/orifice")
        return self
