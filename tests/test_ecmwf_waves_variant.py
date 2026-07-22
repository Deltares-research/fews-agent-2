"""ECMWF ECWAM wave import — a variant of nwp_grid_ecmwf_ifs.

Waves is the same timeSeriesImportRun shape as the meteo import, so per
"one pattern per shape" it's an instance of nwp_grid_ecmwf_ifs rather than a
separate pattern — reached via the s3_subpath=wave + module_suffix=Waves
knobs (farmed from FEWS-Conform ImportEcmwfWavesTemplate.xml). These tests
pin the wave variant and guard that the default (meteo) output is unchanged.
"""
from __future__ import annotations

from pathlib import Path

from fews_agent.agent.blueprint import Blueprint, PatternRef, expand
from fews_agent.validation.xsd import validate_xsd

REPO_ROOT = Path(__file__).resolve().parents[1]
PATTERNS_ROOT = REPO_ROOT / "fews_agent" / "patterns"
PATTERN = "auto/nwp_grid_ecmwf_ifs"

WAVE_PARAMS = [
    {"id": "WaveDirectionMean", "unit": "degrees",
     "external": "Direction", "interpolate": True},
    {"id": "WaveHeightSignificant", "unit": "m",
     "external": "Significant_height", "interpolate": True},
    {"id": "WavePeriodMean", "unit": "s",
     "external": "Mean_period", "interpolate": True},
    {"id": "WavePeriodPeak", "unit": "s",
     "external": "Peak_period", "interpolate": True},
]
WAVES = {
    "source_name": "Ecmwf", "variant": "Waves",
    "s3_subpath": "wave", "module_suffix": "Waves",
    "data_feed_id": "Ecmwf.Ecwam", "emit_idmap": False,
    "parameters": WAVE_PARAMS,
}


def _render(inst):
    bp = Blueprint(
        name="ecmwf-test", output_root=Path("out"),
        patterns=[PatternRef(pattern=PATTERN, instances=[inst])],
    )
    res = expand(bp, PATTERNS_ROOT)
    assert not res.errors, res.errors
    return {rf.relpath.replace("\\", "/"): rf.content for rf in res.rendered_files}


def test_waves_variant_reproduces_ecwam_import():
    files = _render(WAVES)
    mc = files["ModuleConfigFiles/Import/ImportEcmwfWaves.xml"]
    ok, msg = validate_xsd(mc.encode("utf-8"))
    assert ok, msg
    assert "/ifs/0p25/wave/" in mc                   # ECWAM S3 sub-path
    assert "<dataFeedId>Ecmwf.Ecwam</dataFeedId>" in mc
    assert mc.count("<moduleInstanceId>ImportEcmwfWaves</moduleInstanceId>") == 4
    for p in ("WaveDirectionMean", "WaveHeightSignificant",
              "WavePeriodMean", "WavePeriodPeak"):
        assert f"<parameterId>{p}</parameterId>" in mc
    # Per-param externUnit (degrees / m / s / s) + interpolateSerie.
    assert '<externUnit parameterId="WaveDirectionMean" unit="degrees"/>' in mc
    assert mc.count("<interpolateSerie") == 4
    # Anonymous S3 + forecast-hour cap preserved.
    assert 'key="anonymousS3Credentials"' in mc
    # Its own workflow, no idMap (shares the meteo idMap).
    assert "WorkflowFiles/Import/ImportEcmwfWaves.xml" in files
    assert not any("IdMap" in k for k in files)


def test_default_meteo_output_unchanged():
    # Regression guard: the behaviour-preserving knobs must leave the
    # default (meteo) instance rendering exactly as before.
    mc = _render({"source_name": "Ecmwf"})["ModuleConfigFiles/Import/ImportEcmwf.xml"]
    assert "/ifs/0p25/oper/" in mc
    assert "<moduleInstanceId>ImportEcmwfMeteo</moduleInstanceId>" in mc
    assert "<dataFeedId>ECMWF - IFS</dataFeedId>" in mc
