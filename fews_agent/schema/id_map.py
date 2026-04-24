"""IdMapFile — maps source-system ids to internal FEWS ids.

Files have no id attribute on the root; the idMapId is the filename.
A single file may mix several mapping kinds in any order. This model
supports the common ones:

  - ``moduleInstance`` — internal / external id pair
  - ``parameter`` — scalar parameter name mapping (with optional
    qualifier/ensemble attrs)
  - ``location`` — station/location id mapping (with qualifier attrs)
  - ``function`` (ParameterLocationIdFunctionMap) — pattern-based
    mapping for model outputs
  - ``map`` (ParameterLocationIdMap) — grid-to-grid mapping with full
    qualifier / ensemble attribute set

Three empty-element flags at the root: ``enableOneToOneMapping``,
``enableCaseInsensitivity``, ``ignoreExternalQualifiersWhenMappingToInternal``.
Two XSD mapping kinds not yet modelled (rare in the wild):
``parameterIdFunction``, ``qualifierIdFunction``, ``locationIdFunction``
(standalone variants), and ``locationIdPattern``.
"""
from __future__ import annotations

from pydantic import Field, model_validator

from .common import FewsModel
from .ids import LocationId, LocationSetId, ParameterId, QualifierId


class ModuleInstanceMapping(FewsModel):
    """Since 2020.01 — attribute-only mapping of internal to external
    moduleInstance ids."""

    internal: str
    external: str


class ParameterMapping(FewsModel):
    """Scalar parameter mapping with full XSD attr coverage:
    qualifier1-4 chains, ensemble ID / index / member id on both sides."""

    internal: ParameterId
    external: str
    internalQualifier: QualifierId | None = None
    internalQualifier1: QualifierId | None = None
    internalQualifier2: QualifierId | None = None
    internalQualifier3: QualifierId | None = None
    internalQualifier4: QualifierId | None = None
    internalEnsemble: str | None = None
    internalEnsembleMemberIndex: str | None = None
    internalEnsembleMemberId: str | None = None
    externalQualifier: str | None = None
    externalQualifier1: str | None = None
    externalQualifier2: str | None = None
    externalQualifier3: str | None = None
    externalQualifier4: str | None = None
    externalEnsemble: str | None = None
    externalEnsembleMemberIndex: str | None = None
    externalEnsembleMemberId: str | None = None


class LocationMapping(FewsModel):
    """Station / location id mapping with qualifier1-4 chains."""

    internal: LocationId
    external: str
    internalQualifier: QualifierId | None = None
    internalQualifier1: QualifierId | None = None
    internalQualifier2: QualifierId | None = None
    internalQualifier3: QualifierId | None = None
    internalQualifier4: QualifierId | None = None
    externalQualifier: str | None = None
    externalQualifier1: str | None = None
    externalQualifier2: str | None = None
    externalQualifier3: str | None = None
    externalQualifier4: str | None = None


class FunctionMapping(FewsModel):
    """Pattern-based mapping used for model outputs
    (``ParameterLocationIdFunctionMap``).

    externalLocationFunction / externalParameterFunction /
    externalQualifierFunction* are FEWS runtime substitution patterns
    (e.g. ``@SubBasin@``) — not our templating tokens. Stored verbatim.
    """

    internalLocationSet: LocationSetId
    externalLocationFunction: str
    externalParameterFunction: str
    internalParameter: ParameterId | None = None
    internalQualifier: QualifierId | None = None
    internalQualifier1: QualifierId | None = None
    internalQualifier2: QualifierId | None = None
    internalQualifier3: QualifierId | None = None
    internalQualifier4: QualifierId | None = None
    internalEnsemble: str | None = None
    internalEnsembleMemberIndex: str | None = None
    internalEnsembleMemberId: str | None = None
    internalParameterFunction: str | None = None
    internalQualifierFunction: str | None = None
    internalQualifierFunction1: str | None = None
    internalQualifierFunction2: str | None = None
    internalQualifierFunction3: str | None = None
    internalQualifierFunction4: str | None = None
    internalEnsembleFunction: str | None = None
    internalEnsembleMemberIndexFunction: str | None = None
    internalEnsembleMemberIdFunction: str | None = None
    externalLocationFunctionLookupAttributeId: str | None = None
    externalLocationFunctionLookupText: str | None = None
    externalQualifierFunction: str | None = None
    externalQualifierFunction1: str | None = None
    externalQualifierFunction2: str | None = None
    externalQualifierFunction3: str | None = None
    externalQualifierFunction4: str | None = None
    externalEnsembleFunction: str | None = None
    externalEnsembleMemberIndexFunction: str | None = None
    externalEnsembleMemberIdFunction: str | None = None


class MapMapping(FewsModel):
    """Grid-to-grid mapping (SNODAS, E2O, GPM, GSMAP); XSD
    ``ParameterLocationIdMap``.

    CanadaWCS uses internalEnsemble/internalEnsembleMemberId on REPS
    members to demux ensemble streams to distinct member indices.
    """

    internalParameter: ParameterId
    internalLocation: LocationId
    externalParameter: str
    externalLocation: str
    internalModuleInstance: str | None = None
    internalQualifier: QualifierId | None = None
    internalQualifier1: QualifierId | None = None
    internalQualifier2: QualifierId | None = None
    internalQualifier3: QualifierId | None = None
    internalQualifier4: QualifierId | None = None
    internalEnsemble: str | None = None
    internalEnsembleMemberIndex: str | None = None
    internalEnsembleMemberId: str | None = None
    externalModuleInstance: str | None = None
    externalParameterQualifier: str | None = None
    externalQualifier: str | None = None
    externalQualifier1: str | None = None
    externalQualifier2: str | None = None
    externalQualifier3: str | None = None
    externalQualifier4: str | None = None
    externalEnsemble: str | None = None
    externalEnsembleMemberIndex: str | None = None
    externalEnsembleMemberId: str | None = None


class IdMap(FewsModel):
    """Root of an IdMapFile. At least one mapping must be supplied."""

    moduleInstance: list[ModuleInstanceMapping] = Field(default_factory=list)
    parameter: list[ParameterMapping] = Field(default_factory=list)
    location: list[LocationMapping] = Field(default_factory=list)
    function: list[FunctionMapping] = Field(default_factory=list)
    map: list[MapMapping] = Field(default_factory=list)
    enableOneToOneMapping: bool = False
    enableCaseInsensitivity: bool = False
    ignoreExternalQualifiersWhenMappingToInternal: bool = False
    version: str = "1.1"

    @model_validator(mode="after")
    def _at_least_one_mapping(self) -> IdMap:
        if not (
            self.moduleInstance or self.parameter or self.location
            or self.function or self.map
        ):
            raise ValueError(
                "idMap: supply at least one of moduleInstance, parameter, "
                "location, function, or map"
            )
        return self
