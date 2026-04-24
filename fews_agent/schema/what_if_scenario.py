"""WhatIfScenario.xml — persisted user selections for one what-if scenario.

Fixed ``version="1.1"``. Most children are optional and reuse models
that already exist:

  - ``properties`` → ``ModuleConfigProperties`` (PropertiesComplexType)
  - ``configFiles`` → ``WhatIfConfigFiles`` (from
    ``what_if_scenario_filters`` — same XSD ConfigComplexType)
  - ``visibilityEndTime`` → ``DateTimePair``

``transformationSets`` resolves to ``TransformationSetsComplexType``
from ``transformationSets.xsd``, which is rooted in the 12 000-line
``transformationTypes.xsd`` tree. Keeping it as a ``dict`` passthrough:
authors can supply pre-rendered JSON-style nested dicts rendered with
the shared ``dict_to_xml`` filter. Shell is still typed.

``WhatIfScenarios.xml`` is the plural container — fixed ``version="1.1"``
wrapping one or more ``<whatifScenario>`` entries (note the XSD
typo: ``whatifScenario`` not ``whatIfScenario``).
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from .common import FewsModel
from .archive_metadata import DateTimePair
from .module_config_properties import ModuleConfigProperties
from .what_if_scenario_filters import WhatIfConfigFiles


class LocationSelection(FewsModel):
    """List of locationIds to restrict General-Adapter exports to."""

    locationId: list[str] = Field(default_factory=list)


class PolygonSelection(FewsModel):
    """Base64-encoded .shp payload for area-selection exports."""

    areaSelectionShapeFileBase64: str | None = None


class WhatIfScenarioContent(FewsModel):
    """Body shared between WhatIfScenario.xml (root) and each
    <whatifScenario> inside WhatIfScenarios.xml. Both carry the same
    ``WhatIfScenarioGroup`` XSD group plus id/name/version attrs."""

    id: str
    name: str
    version: Literal["1.1"] = "1.1"
    description: str | None = None
    properties: ModuleConfigProperties | None = None
    transformationSets: dict[str, Any] | None = None
    configFiles: WhatIfConfigFiles | None = None
    locationSelection: LocationSelection | None = None
    polygonSelection: PolygonSelection | None = None
    isPersistent: bool | None = None
    isVisible: bool | None = None
    isPendingDeletion: bool | None = None
    workflowId: str | None = None
    visibilityEndTime: DateTimePair | None = None


class WhatIfScenario(WhatIfScenarioContent):
    """Root of WhatIfScenario.xml — one scenario per file."""


class WhatIfScenarios(FewsModel):
    """Root of WhatIfScenarios.xml — plural container.

    XSD uses the (typo) element name ``<whatifScenario>`` for each
    entry; the Python field keeps the typo so the template renders the
    right tag without hand-crafting a mapping."""

    whatifScenario: list[WhatIfScenarioContent] = Field(min_length=1)
    version: Literal["1.1"] = "1.1"
