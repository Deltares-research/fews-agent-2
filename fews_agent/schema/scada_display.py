"""ScadaDisplay.xml — schematic-status (SCADA) display config.

The XSD root carries a fixed sequence of typed siblings (displayName,
backgroundColor, ...) followed by a 1..n choice of ``scadaPanel`` /
``scadaPanelId``. Each panel is a deep tree of svg-component behaviour
definitions (text/shape/chart/...) — ~30 sub-types. Only the root-level
fields are typed here; deeper subtrees pass through as ``dict[str, Any]``
to the dict_to_xml renderer per the project's "wide passthrough for deep
recursive trees" convention.
"""
from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from .common import FewsModel, TimeStep, TimeZone


class ScadaDateFormat(FewsModel):
    """``<dateFormat id="...">`` — id-attributed pattern + optional tz."""

    id: str
    timeZone: TimeZone | None = None
    dateTimePattern: str


class ScadaNumberFormat(FewsModel):
    """``<numberFormat id="...">`` — id-attributed numeric format pattern."""

    id: str
    pattern: str


class ScadaVariableDefinition(FewsModel):
    """``<variable>`` — typed timeSeriesSet defining one named variable.

    The XSD requires both ``variableId`` and ``timeSeriesSet``. We accept
    ``timeSeriesSet`` as a passthrough dict because TimeSeriesSet is a
    huge optional-heavy tree better rendered by dict_to_xml than retyped
    here; we already have the typed ``TimeSeriesSet`` model in common.py
    if a caller needs validation.
    """

    variableId: str
    timeSeriesSet: dict[str, Any]


class ScadaPanel(FewsModel):
    """``<scadaPanel>`` — one SVG-backed schematic panel.

    Top-level metadata is typed; the 0..n inner choice (text/shape/chart/
    ... componentBehaviourDefinition) is a dict-passthrough list because
    each branch has its own deep tree.
    """

    svgFile: str
    overrulingTimeNavigatorTimeStep: TimeStep | None = None
    nodeId: str | None = None
    permission: str | None = None
    backgroundColor: str | None = None
    # Ordered list of single-key dicts for the inner choice:
    #   {"textComponentBehaviourDefinition": {...}}
    #   {"shapeComponentBehaviourDefinition": {...}}
    #   {"chartComponentBehaviourDefinition": {...}}
    #   ...
    components: list[dict[str, Any]] = Field(default_factory=list)
    # Attributes — id is XSD-required.
    id: str
    name: str | None = None


class ScadaTimeNavigatorToolbarSettings(FewsModel):
    """``<showTimeNavigatorToolbar>`` settings (passthrough)."""

    # Modelled as passthrough to avoid duplicating sharedTypes' deep
    # ScadaTimeNavigatorToolbarSettingsComplexType structure here.
    fields: dict[str, Any] = Field(default_factory=dict)


class ScadaDisplay(FewsModel):
    """Root of ScadaDisplay.xml.

    XSD ScadaDisplayComplexType — sequence:
      - displayName (required)
      - showTimeNavigatorToolbar (optional, deep tree → passthrough)
      - globalDatumButtonViewPermission (optional)
      - backgroundColor (optional)
      - dateFormat[] (optional)
      - numberFormat[] (optional)
      - variable[] (optional)
      - transformation[] (optional, TransformationFunctionComplexType is
        deep — passthrough dict each)
      - choice (1..n) of scadaPanel / scadaPanelId

    The terminal choice is exposed as ``panels`` (typed list) +
    ``scadaPanelId`` (list of str refs). Either or both may be populated.
    """

    displayName: str
    showTimeNavigatorToolbar: dict[str, Any] | None = None
    globalDatumButtonViewPermission: str | None = None
    backgroundColor: str | None = None
    dateFormat: list[ScadaDateFormat] = Field(default_factory=list)
    numberFormat: list[ScadaNumberFormat] = Field(default_factory=list)
    variable: list[ScadaVariableDefinition] = Field(default_factory=list)
    transformation: list[dict[str, Any]] = Field(default_factory=list)
    # The terminal choice — order across the two lists isn't preserved,
    # but in practice files mix them rarely. Callers needing strict order
    # should put everything into one list of single-key dicts via
    # ``panelChoice`` (also accepted: list of dicts with 'scadaPanel' or
    # 'scadaPanelId' keys).
    scadaPanel: list[ScadaPanel] = Field(default_factory=list)
    scadaPanelId: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _at_least_one_panel(self) -> ScadaDisplay:
        if not self.scadaPanel and not self.scadaPanelId:
            raise ValueError(
                "scadaDisplay: must contain at least one scadaPanel or "
                "scadaPanelId (XSD choice maxOccurs=unbounded, minOccurs=1)"
            )
        return self
