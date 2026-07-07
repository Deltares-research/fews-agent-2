"""import_imerg — NASA GPM IMERG satellite precip (Early/Late/Final).

Farmed from FEWS-Conform (ImportImerg + ProcessImerg + ForecastStartImerg +
IdMapFromImerg). Conform drives the three latency products via
$ImergPostfix$/$ImergProductForUrl$/$UrlDash$; here each is a concrete
instance chosen by `product`. Distinguishing feature vs a generic import:
the rate->accumulation (meanToMean) aggregation before the grid->scalar
closestDistance. Tests render all three products and XSD-validate, and pin
the per-product URL/filename encoding + the accumulation transform.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from fews_agent.agent.blueprint import Blueprint, PatternRef, expand
from fews_agent.validation.xsd import validate_xsd

REPO_ROOT = Path(__file__).resolve().parents[1]
PATTERNS_ROOT = REPO_ROOT / "patterns"
PATTERN = "auto/import_imerg"

# product -> (opendap product code, filename token)
ENCODING = {
    "Early": ("GPM_3IMERGHHE.07", "3B-HHR-E."),
    "Late": ("GPM_3IMERGHHL.07", "3B-HHR-L."),
    "Final": ("GPM_3IMERGHH.07", "3B-HHR."),
}


def _render(product):
    bp = Blueprint(
        name="imerg-test", output_root=Path("out"),
        patterns=[PatternRef(pattern=PATTERN, instances=[{"product": product}])],
    )
    res = expand(bp, PATTERNS_ROOT)
    assert not res.errors, res.errors
    return {rf.relpath.replace("\\", "/"): rf.content for rf in res.rendered_files}


@pytest.mark.parametrize("product", ["Early", "Late", "Final"])
def test_product_chain_renders_and_validates(product):
    files = _render(product)
    expected = {
        f"ModuleConfigFiles/Import/ImportImerg{product}.xml",
        f"ModuleConfigFiles/Import/ForecastStartImerg{product}.xml",
        f"ModuleConfigFiles/Import/ProcessImerg{product}.xml",
        f"WorkflowFiles/Import/ImportImerg{product}.xml",
        "IdMapFiles/Import/IdMapFromImerg.xml",
    }
    assert expected <= set(files)
    for path in expected:
        ok, msg = validate_xsd(files[path].encode("utf-8"))
        assert ok, (path, msg)


@pytest.mark.parametrize("product", ["Early", "Late", "Final"])
def test_per_product_url_and_filename_encoding(product):
    mc = _render(product)[f"ModuleConfigFiles/Import/ImportImerg{product}.xml"]
    url_code, fname = ENCODING[product]
    assert url_code in mc                            # OPeNDAP product code
    assert fname in mc                               # filename dash/code
    assert f"<dataFeedId>Nasa.Imerg{product}</dataFeedId>" in mc
    # Two import blocks (T0 day + T0+24h) and credentialed OPeNDAP.
    assert mc.count("<import>") == 2
    assert "%RELATIVE_TIME_IN_SECONDS(yyyy,0)%" in mc
    assert "%RELATIVE_TIME_IN_SECONDS(yyyy,86400)%" in mc
    assert "<user>$GpmUser$</user>" in mc
    assert "<missingValue>-999</missingValue>" in mc
    assert 'multiplier="30"' in mc                   # 30-minute native step


def test_rate_to_accumulation_transform():
    # The defining IMERG feature: 30-min rate -> hourly accumulation
    # (meanToMean) BEFORE the grid->scalar interpolation.
    proc = _render("Early")["ModuleConfigFiles/Import/ProcessImergEarly.xml"]
    assert "<meanToMean>" in proc
    assert "<parameterId>PrecipitationRateObserved</parameterId>" in proc  # input rate
    assert "<parameterId>PrecipitationObserved</parameterId>" in proc      # accum output
    assert proc.count("<closestDistance>") == 2      # stations + catchments
    # Ordered: Grid (accumulate) fed into the two interpolations.
    assert proc.index("<meanToMean>") < proc.index("<closestDistance>")


def test_idmap_shared_across_products():
    idm = _render("Early")["IdMapFiles/Import/IdMapFromImerg.xml"]
    assert 'internalParameter="PrecipitationRateObserved"' in idm
    assert 'externalParameter="precipitation"' in idm
