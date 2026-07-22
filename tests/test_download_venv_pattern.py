"""download_via_python_venv — the "call an external Python venv" pattern.

Farmed from FEWS-Conform ModuleConfigFiles/Import/DownloadEra5.xml, the only
generalAdapterRun in the config that shells out to a Python venv / CDS API.
These tests render it through expand(), XSD-validate the generalAdapterRun,
assert it reproduces the Conform source's defining features (credential-
preserving purge, runinfo Area/Parameter props, venv executeActivity), and
prove the generalization works for a non-ERA5 source.
"""
from __future__ import annotations

from pathlib import Path

from fews_agent.agent.blueprint import Blueprint, PatternRef, expand
from fews_agent.validation.xsd import validate_xsd

REPO_ROOT = Path(__file__).resolve().parents[1]
PATTERNS_ROOT = REPO_ROOT / "fews_agent" / "patterns"
PATTERN = "auto/download_via_python_venv"

ERA5 = {
    "source_name": "Era5",
    "import_module_instance": "ImportEra5",
    "download_area": "[-10, 112,-44,154]",
    "download_parameters": (
        "['2m_temperature', 'total_precipitation', "
        "'surface_solar_radiation_downwards']"
    ),
}


def _render(inst):
    bp = Blueprint(
        name="dl-test", output_root=Path("out"),
        patterns=[PatternRef(pattern=PATTERN, instances=[inst])],
    )
    res = expand(bp, PATTERNS_ROOT)
    assert not res.errors, res.errors
    return {rf.relpath.replace("\\", "/"): rf.content for rf in res.rendered_files}


def test_era5_renders_and_validates():
    xml = _render(ERA5)["ModuleConfigFiles/Import/DownloadEra5.xml"]
    ok, msg = validate_xsd(xml.encode("utf-8"))
    assert ok, msg


def test_defining_features_reproduced():
    xml = _render(ERA5)["ModuleConfigFiles/Import/DownloadEra5.xml"]
    # Credential-preserving purge: clears transient files, keeps .cdsapirc
    # by never matching it (5 targeted filters, dev/* recursive).
    assert xml.count("<purgeActivity>") == 5
    assert "<filter>%ROOT_DIR%/*.bat</filter>" in xml
    assert "<includeSubdirectories>true</includeSubdirectories>" in xml
    assert ".cdsapirc" not in xml                    # never purged
    # runinfo.xml carries the download spec as run properties.
    assert '<exportFile>%ROOT_DIR%/runinfo.xml</exportFile>' in xml
    assert '<string key="Area" value="[-10, 112,-44,154]"/>' in xml
    assert 'key="Parameter"' in xml
    # venv executeActivity.
    assert "<executable>%ROOT_DIR%/DownloadEra5.bat</executable>" in xml
    assert "<argument>$PythonEnvironmentFolder$/EnvDownloadEra5</argument>" in xml
    assert "<timeOut>14400000</timeOut>" in xml
    # Dummy import writing to the downstream import module.
    assert "<moduleInstanceId>ImportEra5</moduleInstanceId>" in xml
    assert "<importFile>download_%TIME0%.nc</importFile>" in xml


def test_generalizes_to_a_new_source():
    # Reuse for a different CDS/venv source — module id, rootDir, idMap and
    # venv all derive from source_name.
    inst = {
        "source_name": "Cmems",
        "import_module_instance": "ImportCmems",
        "download_area": "[30, -20, 46, 42]",
        "download_parameters": "['sea_surface_height']",
    }
    files = _render(inst)
    xml = files["ModuleConfigFiles/Import/DownloadCmems.xml"]
    ok, msg = validate_xsd(xml.encode("utf-8"))
    assert ok, msg
    assert "<rootDir>$ModulesFolder$/DownloadCmems</rootDir>" in xml
    assert "<importIdMap>IdMapFromCmems</importIdMap>" in xml
    assert "<argument>$PythonEnvironmentFolder$/EnvDownloadCmems</argument>" in xml
    assert "<moduleInstanceId>DownloadCmems</moduleInstanceId>" in xml


def test_overrides_win_over_derived_defaults():
    inst = dict(
        ERA5, venv_name="MyEnv", bat_script="fetch.bat",
        py_script="grab.py", import_id_map="IdCustom",
    )
    xml = _render(inst)["ModuleConfigFiles/Import/DownloadEra5.xml"]
    assert "<argument>$PythonEnvironmentFolder$/MyEnv</argument>" in xml
    assert "<executable>%ROOT_DIR%/fetch.bat</executable>" in xml
    assert "<argument>grab.py</argument>" in xml
    assert "<importIdMap>IdCustom</importIdMap>" in xml
