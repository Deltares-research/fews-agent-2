"""External model-asset detection + stub/manifest emitter.

General-adapter model runs (raven/wflow) need binaries, a schematization,
and an initial cold state that no generation layer can produce. This module
detects the gap, warns, and (opt-in) scaffolds Conform-convention
placeholders. Pure functions → tested directly with synthetic RenderedFiles.
"""
from __future__ import annotations

from dataclasses import dataclass

from fews_agent.agent.model_asset_stubs import (
    ModelAssetRequirement,
    config_has_model_assets,
    detect_model_asset_requirements,
    missing_model_asset_paths,
    model_asset_stub_files,
    render_model_asset_manifest,
)


@dataclass
class _RF:
    relpath: str
    content: str


_ADAPTER = (
    '<generalAdapterRun xmlns="http://www.wldelft.nl/fews">'
    "<general/><activities>"
    "<executable>%ROOT_DIR%\\work\\bin\\Adapter\\RavenFEWSAdapter.exe</executable>"
    "<stateConfigFile>x</stateConfigFile><coldState/>"
    "</activities></generalAdapterRun>"
)


def _run(relpath="ModuleConfigFiles/ModelRun/Liard/LiardHistoricTemplate.xml"):
    return _RF(relpath, _ADAPTER)


def test_detects_software_and_area():
    reqs = detect_model_asset_requirements([_run()])
    assert reqs == [ModelAssetRequirement(software="Raven", area="Liard")]


def test_paths_follow_conform_conventions():
    r = ModelAssetRequirement(software="Raven", area="Liard")
    assert r.binaries_path == "ModuleDataSetFiles/Binaries/BinRaven.zip"
    assert r.dataset_path == "ModuleDataSetFiles/LiardRaven.zip"
    assert r.coldstate_path == (
        "ColdStateFiles/Raven_Csf/LiardRavenHc Default.zip"
    )


def test_forecast_template_area_extraction():
    reqs = detect_model_asset_requirements([
        _run("ModuleConfigFiles/ModelRun/Snare/SnareForecastTemplate.xml"),
    ])
    assert reqs[0].area == "Snare"


def test_dedup_across_forecast_and_historic():
    reqs = detect_model_asset_requirements([
        _run("a/LiardForecastTemplate.xml"),
        _run("a/LiardHistoricTemplate.xml"),
    ])
    assert reqs == [ModelAssetRequirement(software="Raven", area="Liard")]


def test_non_stateful_adapter_ignored():
    # General adapter with an exe but no state marker → not a stateful model.
    content = (
        '<generalAdapterRun xmlns="http://www.wldelft.nl/fews">'
        "<executable>RavenFEWSAdapter.exe</executable></generalAdapterRun>"
    )
    assert detect_model_asset_requirements([_RF("x/Export.xml", content)]) == []


def test_no_adapter_exe_ignored():
    content = '<generalAdapterRun><coldState/></generalAdapterRun>'
    assert detect_model_asset_requirements([_RF("x/Foo.xml", content)]) == []


def test_config_has_model_assets():
    reqs_rf = _run()
    assert not config_has_model_assets([reqs_rf])
    assert config_has_model_assets([
        reqs_rf, _RF("ColdStateFiles/Raven_Csf/LiardRavenHc Default.zip/s", "x"),
    ])


def test_stub_files_are_folders_ending_in_zip_with_manifest():
    reqs = [ModelAssetRequirement(software="Raven", area="Liard")]
    files = dict(model_asset_stub_files(reqs))
    assert "_REQUIRED_MODEL_ASSETS.md" in files
    # Each asset is a PLACEHOLDER.md inside a *.zip folder.
    assert (
        "ColdStateFiles/Raven_Csf/LiardRavenHc Default.zip/PLACEHOLDER.md"
        in files
    )
    assert "ModuleDataSetFiles/Binaries/BinRaven.zip/PLACEHOLDER.md" in files
    assert "ModuleDataSetFiles/LiardRaven.zip/PLACEHOLDER.md" in files
    assert "folder" in files[
        "ModuleDataSetFiles/Binaries/BinRaven.zip/PLACEHOLDER.md"
    ].lower()


def test_shared_binaries_deduped_across_areas():
    reqs = [
        ModelAssetRequirement(software="Raven", area="Liard"),
        ModelAssetRequirement(software="Raven", area="Snare"),
    ]
    paths = [p for p, _ in model_asset_stub_files(reqs)]
    binaries = [p for p in paths if "Binaries/BinRaven.zip" in p]
    assert len(binaries) == 1                      # one Bin<Sw>.zip for both
    assert missing_model_asset_paths(reqs).count(
        "ModuleDataSetFiles/Binaries/BinRaven.zip"
    ) == 1


def test_manifest_empty_when_no_requirements():
    assert render_model_asset_manifest([]) == ""
    assert model_asset_stub_files([]) == []
