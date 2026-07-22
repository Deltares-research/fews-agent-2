"""tpl_generate_reference_et — Penman-Monteith / Makkink reference ET.

Farmed from FEWS-Conform Generate{Forecast,Hindcast,Historical}
EvapotranspirationTemplate.xml. A `tpl_` shared template (keeps FEWS
$PLACEHOLDER$s literal) that computes reference-crop evapotranspiration from
gridded air temperature + solar radiation via `user`/`simple` expression
transforms with a coefficientSet. One template-family selected by
simulation_type; the formulas are identical across variants, only the
timeSeriesType / readWriteMode / relativeViewPeriod switch. Tests render all
three and XSD-validate, and pin the formula transform + the switch.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from fews_agent.agent.blueprint import Blueprint, PatternRef, expand
from fews_agent.validation.xsd import validate_xsd

REPO_ROOT = Path(__file__).resolve().parents[1]
PATTERNS_ROOT = REPO_ROOT / "fews_agent" / "patterns"
PATTERN = "auto/tpl_generate_reference_et"


def _render(simulation_type):
    bp = Blueprint(
        name="et-test", output_root=Path("out"),
        patterns=[PatternRef(pattern=PATTERN,
                             instances=[{"simulation_type": simulation_type}])],
    )
    res = expand(bp, PATTERNS_ROOT)
    assert not res.errors, res.errors
    (rf,) = res.rendered_files
    return rf.relpath.replace("\\", "/"), rf.content


@pytest.mark.parametrize("st", ["Forecast", "Hindcast", "Historical"])
def test_renders_and_validates(st):
    relpath, xml = _render(st)
    assert relpath == (
        f"ModuleConfigFiles/Import/Generate{st}EvapotranspirationTemplate.xml"
    )
    ok, msg = validate_xsd(xml.encode("utf-8"))
    assert ok, msg


def test_makkink_formula_transform():
    _, xml = _render("Forecast")
    # user/simple expression transforms (the novel shape) + coefficientSet.
    assert "<simple>" in xml
    assert "ln(10)" in xml                                  # Slope formula
    assert "UnitConversionEvapotranspiration" in xml        # ETref formula
    assert '<coefficient id="Rho" value="1000"/>' in xml
    assert '<coefficient id="UnitConversionRadiationSolar" value="3600"/>' in xml
    # Output is the reference-ET grid.
    assert "<parameterId>EvapotranspirationReference</parameterId>" in xml
    # tpl_ shared template keeps FEWS placeholders literal.
    assert "$MeteoModuleInstanceId$" in xml
    assert "$MODULE_INSTANCE_ID$" in xml


def test_simulation_type_switch():
    _, fc = _render("Forecast")
    _, hc = _render("Hindcast")
    _, hist = _render("Historical")
    # Forecast: forecasting series, no view window.
    assert "<timeSeriesType>external forecasting</timeSeriesType>" in fc
    assert "<relativeViewPeriod" not in fc
    assert "$ExpiryTimeGridExternalForecastingInDays$" in fc
    # Hindcast: historical series, 0/0 window.
    assert "<timeSeriesType>external historical</timeSeriesType>" in hc
    assert 'start="0" end="0"' in hc
    assert "$ExpiryTimeGridExternalHistoricalInDays$" in hc
    # Historical: historical series, configurable view window.
    assert 'start="$ViewPeriodStartInHours$" end="$ViewPeriodEndInHours$"' in hist
