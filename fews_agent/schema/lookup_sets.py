"""LookUpSets.xml — named lookup tables for forecast post-processing.

Each ``<lookupSet>`` binds input variables to an output via one of three
lookup strategies (XSD choice): critical-condition rules,
simple 1D / multi-dim tables.

RuleCriterias use an XSD interleaving pattern — each item in the
unbounded sequence can be either a ``ruleCriteria`` element or a
``ruleCriteriaLogicalOperator`` scalar element. We model the
sequence as an ordered ``List`` of discriminated dict items
(``{"kind": "criteria", "criteria": RuleCriteria}`` or
``{"kind": "operator", "operator": "and"|"or"}``) on ``RuleCriterias``.
The template emits them in that order.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .common import DataVariable, FewsModel


ConditionalOperator = Literal[
    "notequal", "equal", "greaterthan", "greaterorequalthan", "lessthan",
    "lessorequalthan", "ne", "eq", "gt", "ge", "lt", "le",
]
LogicalOperator = Literal["and", "or"]
DataType = Literal["float", "int", "long", "double", "string", "boolean"]
Extrapolation = Literal["none", "maxmin", "linear"]
Interpolation = Literal[
    "linear", "block", "blockBackward", "blockForward", "linearBackward",
    "linearForward",
]
Separator = Literal["space", "lineseperater", "doublequote", "singlequote"]


class Condition(FewsModel):
    """Attribute-only element — ``<rule variable=... operator=... value=... logical=.../>``."""

    variable: str
    operator: ConditionalOperator
    value: str
    logical: LogicalOperator | None = None


class ConditionGroup(FewsModel):
    """``<ruleGroup>`` — nested rules."""

    rule: list[Condition] = Field(min_length=1)


class RuleCriteria(FewsModel):
    """XSD choice at each sequence position: ``rule`` XOR ``ruleGroup``.

    Modelled as parallel optional fields — exactly one must be set."""

    rule: Condition | None = None
    ruleGroup: ConditionGroup | None = None

    @model_validator(mode="after")
    def _one_kind(self) -> RuleCriteria:
        if (self.rule is None) == (self.ruleGroup is None):
            raise ValueError(
                "ruleCriteria: supply exactly one of rule or ruleGroup"
            )
        return self


class RuleCriteriasItem(FewsModel):
    """Discriminated pair: a ``ruleCriteria`` OR a ``ruleCriteriaLogicalOperator``.

    Enables authors to interleave criteria with logical operators as the
    XSD allows — ``A and B and C`` maps to
    ``[criteria(A), operator(and), criteria(B), operator(and), criteria(C)]``.
    """

    ruleCriteria: RuleCriteria | None = None
    ruleCriteriaLogicalOperator: LogicalOperator | None = None

    @model_validator(mode="after")
    def _one_kind(self) -> RuleCriteriasItem:
        if (self.ruleCriteria is None) == (
            self.ruleCriteriaLogicalOperator is None
        ):
            raise ValueError(
                "ruleCriterias item: supply exactly one of ruleCriteria or "
                "ruleCriteriaLogicalOperator"
            )
        return self


class RuleCriterias(FewsModel):
    """The ``<criticalCondition>`` / ``<defaultValue>`` body."""

    rule: str
    ruleIndex: str
    rulePreferredColor: str | None = None
    valuetype: DataType | None = None
    indextype: DataType | None = None
    item: list[RuleCriteriasItem] = Field(min_length=1)


class CriticalConditionLookup(FewsModel):
    id: str | None = None
    criticalCondition: list[RuleCriterias] = Field(min_length=1)


class ListEntry(FewsModel):
    """XSD ListComplexType — delimited string with metadata."""

    data: str
    number: int | None = None
    type: DataType | None = None
    seperator: Separator | None = None


class ColumnDataItem(FewsModel):
    """Single ``<columndata>`` attribute-only element."""

    type: DataType
    value: str
    columnnumber: int | None = None


class ColumnData(FewsModel):
    """``<rowdata>`` wrapper with columnnumber attr on the row and
    ``<columndata/>`` children."""

    rownumber: int | None = None
    columndata: list[ColumnDataItem] = Field(min_length=1)


class InfoBlock(FewsModel):
    extrapolation: Extrapolation | None = None
    interpolation: Interpolation | None = None


class TableLookup(FewsModel):
    """Simple 1D table. XSD choice for data: rowwise / columnwise / rowdata."""

    lookUpVariableId: str
    outputVariableId: str
    rows: int
    columns: int
    LookUpData: ListEntry
    type: DataType | None = None
    rowwise: list[ListEntry] = Field(default_factory=list)
    columnwise: list[ListEntry] = Field(default_factory=list)
    rowdata: list[ColumnData] = Field(default_factory=list)
    info: InfoBlock | None = None

    @model_validator(mode="after")
    def _one_data_form(self) -> TableLookup:
        forms = [
            bool(self.rowwise),
            bool(self.columnwise),
            bool(self.rowdata),
        ]
        if sum(forms) != 1:
            raise ValueError(
                "simpleTableLookup: supply exactly one of rowwise, columnwise, "
                "or rowdata"
            )
        return self


class MultiDimensionalTableLookup(FewsModel):
    """Multi-dim table — row + column look-up axes plus the data grid."""

    outputVariableId: str
    rows: int
    columns: int
    LookUpColData: ListEntry
    LookUpRowData: ListEntry
    lookUpColVariableId: str | None = None
    lookUpRowVariableId: str | None = None
    type: DataType | None = None
    rowwise: list[ListEntry] = Field(default_factory=list)
    columnwise: list[ListEntry] = Field(default_factory=list)
    rowdata: list[ColumnData] = Field(default_factory=list)
    info: InfoBlock | None = None

    @model_validator(mode="after")
    def _one_data_form(self) -> MultiDimensionalTableLookup:
        forms = [
            bool(self.rowwise),
            bool(self.columnwise),
            bool(self.rowdata),
        ]
        if sum(forms) != 1:
            raise ValueError(
                "multiDimensionalTableLookup: supply exactly one of rowwise, "
                "columnwise, or rowdata"
            )
        return self


class LookUpSet(FewsModel):
    """XSD choice: criticalConditionLookup XOR simpleTableLookup XOR
    multiDimensionalTableLookup."""

    lookupSetId: str | None = None
    inputVariable: list[DataVariable] = Field(min_length=1)
    outputVariable: list[DataVariable] = Field(min_length=1)
    criticalConditionLookup: CriticalConditionLookup | None = None
    simpleTableLookup: TableLookup | None = None
    multiDimensionalTableLookup: MultiDimensionalTableLookup | None = None
    defaultValue: RuleCriterias | None = None
    comment: str | None = None

    @model_validator(mode="after")
    def _one_strategy(self) -> LookUpSet:
        forms = [
            self.criticalConditionLookup,
            self.simpleTableLookup,
            self.multiDimensionalTableLookup,
        ]
        if sum(f is not None for f in forms) != 1:
            raise ValueError(
                "lookupSet: supply exactly one of criticalConditionLookup, "
                "simpleTableLookup, or multiDimensionalTableLookup"
            )
        return self


class LookUpSets(FewsModel):
    version: str = "1.1"
    lookupSet: list[LookUpSet] = Field(min_length=1)
