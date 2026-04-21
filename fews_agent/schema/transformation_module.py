"""TransformationModule — root of Preprocess and DataProcessing module configs.

The `<transformationModule>` root element is shared between
ModuleConfigFiles/Preprocess/** and ModuleConfigFiles/DataProcessing/**.
They differ only in which transformation kinds are used in practice, not
in structure.

Structure:
  - Zero or more `<variable>`s name the input/output time series the
    module operates on. Each binds a module-local `variableId` to a
    `timeSeriesSet`.
  - Zero or more `<transformation>`s describe the compute: each has an
    `id` and a transformation-kind-specific body (`<accumulation>`,
    `<user>/<simple>`, `<interpolationSerialToBlock>`, ...).

Current modeling decision: `Transformation` keeps its body intentionally
open (`extra='allow'`). FEWS supports dozens of transformation kinds,
each with its own XSD subtree. Modeling them all is a project of its
own. For now we validate the outer structure and let the FEWS XSD catch
body-shape errors. Typed bodies can be added as a tagged union later
once we know which kinds matter most.
"""
from __future__ import annotations

from pydantic import ConfigDict, Field

from .common import FewsModel, TimeSeriesSet
from .ids import VariableId


class Variable(FewsModel):
    """Named input or output time series, module-local scope."""

    variableId: VariableId
    timeSeriesSet: TimeSeriesSet


class Transformation(FewsModel):
    """Transformation wrapper.

    Accepts arbitrary additional fields so callers can supply any
    transformation-kind-specific body (accumulation, user/simple,
    interpolationSerialToBlock, ...) until we tighten this to a tagged
    union.
    """

    id: str

    model_config = ConfigDict(
        extra="allow",
        str_strip_whitespace=True,
        populate_by_name=True,
    )


class TransformationModule(FewsModel):
    """Root of a Preprocess or DataProcessing module config."""

    variable: list[Variable] = Field(default_factory=list)
    transformation: list[Transformation] = Field(default_factory=list)
    version: str = "1.0"
