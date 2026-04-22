"""IdMapFile — maps source-system ids to internal FEWS ids.

Files have no id attribute on the root; the idMapId is the filename.
A single file may use one or more of four mapping shapes, in any mix:

  - parameter: scalar parameter name mapping
      <parameter internal="FEWS_param" external="source_param"/>
  - location: station/location id mapping
      <location internal="FEWS_loc" external="source_loc"/>
  - function: pattern-based mapping for model outputs
      <function internalLocationSet=".." externalLocationFunction="@Sub@"
                externalParameterFunction=".." internalParameter=".."/>
  - map: grid-to-grid mapping
      <map internalParameter=".." internalLocation=".."
           externalParameter=".." externalLocation=".."/>

All four lists default to empty so partial files validate. The optional
`enableOneToOneMapping` flag (empty element in XML) is modeled as a bool.
"""
from __future__ import annotations

from pydantic import Field, model_validator

from .common import FewsModel
from .ids import LocationId, LocationSetId, ParameterId, QualifierId


class ParameterMapping(FewsModel):
    """Scalar parameter mapping."""

    internal: ParameterId
    external: str
    internalQualifier: QualifierId | None = None
    externalQualifier: str | None = None


class LocationMapping(FewsModel):
    """Station / location id mapping."""

    internal: LocationId
    external: str


class FunctionMapping(FewsModel):
    """Pattern-based mapping used for model outputs.

    externalLocationFunction and externalParameterFunction are FEWS runtime
    substitution patterns (e.g. `@SubBasin@`) — not our templating tokens.
    Stored verbatim.
    """

    internalLocationSet: LocationSetId
    externalLocationFunction: str
    externalParameterFunction: str
    internalParameter: ParameterId
    internalQualifier: QualifierId | None = None


class MapMapping(FewsModel):
    """Grid-to-grid mapping (SNODAS, E2O, GPM, GSMAP).

    CanadaWCS uses internalEnsemble/internalEnsembleMemberId on REPS
    members to demux ensemble streams to distinct member indices.
    """

    internalParameter: ParameterId
    internalLocation: LocationId
    externalParameter: str
    externalLocation: str
    internalEnsemble: str | None = None
    internalEnsembleMemberId: str | None = None


class IdMap(FewsModel):
    """Root of an IdMapFile. At least one mapping must be supplied."""

    parameter: list[ParameterMapping] = Field(default_factory=list)
    location: list[LocationMapping] = Field(default_factory=list)
    function: list[FunctionMapping] = Field(default_factory=list)
    map: list[MapMapping] = Field(default_factory=list)
    enableOneToOneMapping: bool = False
    version: str = "1.1"

    @model_validator(mode="after")
    def _at_least_one_mapping(self) -> IdMap:
        if not (self.parameter or self.location or self.function or self.map):
            raise ValueError(
                "idMap: supply at least one of parameter, location, function, or map"
            )
        return self
