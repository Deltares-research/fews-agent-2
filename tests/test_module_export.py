"""Tests for the module + dependency closure walker (module_export.py).

Unit tests use a tiny synthetic ``{relpath: content}`` map so the closure
logic is exercised precisely and fast. One integration test runs the real
build for a GFS-only project and asserts the closure picks the module + its
genuine dependencies and drops the chrome.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import yaml
from rich.console import Console

from fews_agent.agent.module_export import (
    classify, compute_closure, render_manifest, trim_dependency_files,
)

NS = 'xmlns="http://www.wldelft.nl/fews"'


def _mod(module_id, *, param, idmap, grid, units):
    return f"""<?xml version="1.0"?><transformationModule {NS}>
  <variable><timeSeriesSet>
    <moduleInstanceId>{module_id}</moduleInstanceId>
    <valueType>grid</valueType>
    <parameterId>{param}</parameterId>
    <locationId>{grid}</locationId>
    <idMapId>{idmap}</idMapId>
    <unitConversionsId>{units}</unitConversionsId>
  </timeSeriesSet></variable>
</transformationModule>"""


def _params(*ids):
    body = "".join(f'<parameter id="{i}"><name>{i}</name></parameter>' for i in ids)
    return f'<?xml version="1.0"?><parameters {NS}><parameterGroup id="g">{body}</parameterGroup></parameters>'


def _grids(*locs):
    body = "".join(f'<regular locationId="{l}"/>' for l in locs)
    return f'<?xml version="1.0"?><grids {NS}>{body}</grids>'


def _idmap():
    return f'<?xml version="1.0"?><idMap {NS}><map externalParameter="x" internalParameter="y"/></idMap>'


def _units():
    return f'<?xml version="1.0"?><unitConversions {NS}/>'


def _chrome_ref(module_id):
    # Topology references INTO the module (incoming edge) — must be dropped.
    return f'<?xml version="1.0"?><topology {NS}><nodes id="n"><node id="x"><workflowId>{module_id}</workflowId></node></nodes></topology>'


def _base_project(module_id="ImportGFS", param="PC.nwp", grid="GFS",
                  idmap="IdImportGFS", units="ImportUnitConversions"):
    return {
        f"ModuleConfigFiles/Import/{module_id}.xml": _mod(
            module_id, param=param, idmap=idmap, grid=grid, units=units),
        "RegionConfigFiles/Parameters.xml": _params(param, "OTHER.par"),
        "RegionConfigFiles/Grids.xml": _grids(grid, "$MODELNAME1$Grid"),
        f"IdMapFiles/NOAA/{idmap}.xml": _idmap(),
        f"UnitConversionsFiles/{units}.xml": _units(),
        # chrome:
        "RegionConfigFiles/Topology.xml": _chrome_ref(module_id),
        "SystemConfigFiles/Permissions.xml": f'<?xml version="1.0"?><permissions {NS}/>',
        "RegionConfigFiles/TimeSteps.xml": f'<?xml version="1.0"?><timeSteps {NS}><timeStep id="unused"/></timeSteps>',
    }


SEED = "ModuleConfigFiles/Import/ImportGFS.xml"


def test_closure_pulls_the_three_dependencies():
    files = _base_project()
    r = compute_closure(files, [SEED])
    assert SEED in r.needed
    assert "RegionConfigFiles/Parameters.xml" in r.needed
    assert "RegionConfigFiles/Grids.xml" in r.needed
    assert "IdMapFiles/NOAA/IdImportGFS.xml" in r.needed
    assert "UnitConversionsFiles/ImportUnitConversions.xml" in r.needed


def test_closure_excludes_chrome():
    files = _base_project()
    r = compute_closure(files, [SEED])
    assert "RegionConfigFiles/Topology.xml" in r.chrome
    assert "SystemConfigFiles/Permissions.xml" in r.chrome
    # The module references no timeStep id → TimeSteps is NOT a dependency.
    assert "RegionConfigFiles/TimeSteps.xml" in r.chrome


def test_self_declared_module_instance_needs_no_descriptor():
    # moduleInstanceId=ImportGFS is declared by the module's own filename,
    # so a descriptor file is never pulled in.
    files = _base_project()
    files["RegionConfigFiles/ModuleInstanceDescriptors.xml"] = (
        f'<?xml version="1.0"?><moduleInstanceDescriptors {NS}>'
        f'<moduleInstanceDescriptor id="ImportGFS"/></moduleInstanceDescriptors>'
    )
    r = compute_closure(files, [SEED])
    assert "RegionConfigFiles/ModuleInstanceDescriptors.xml" not in r.needed


def test_self_contained_has_no_external_refs():
    r = compute_closure(_base_project(), [SEED])
    assert r.external == []


def test_unsatisfied_reference_becomes_external_manifest():
    # A module that references a parameter no Parameters.xml declares.
    files = _base_project(param="GHOST.par")
    # Parameters.xml only declares PC.nwp/OTHER.par, not GHOST.par.
    files["RegionConfigFiles/Parameters.xml"] = _params("PC.nwp", "OTHER.par")
    r = compute_closure(files, [SEED])
    vals = {(e.id_type, e.value) for e in r.external}
    assert ("parameter", "GHOST.par") in vals


def test_ref_declared_only_in_chrome_is_external():
    # An id whose only declarer is a chrome file is surfaced, not pulled.
    files = _base_project()
    # Add a ref to a locationSet only declared inside a chrome display file.
    files[SEED] = files[SEED].replace(
        "</timeSeriesSet>",
        "<locationSetId>OnlyInChrome</locationSetId></timeSeriesSet>")
    files["SystemConfigFiles/DisplayGroups.xml"] = (
        f'<?xml version="1.0"?><displayGroups {NS}>'
        f'<locationSet id="OnlyInChrome"/></displayGroups>')
    r = compute_closure(files, [SEED])
    # LocationSets.xml is a dependency spec, but here OnlyInChrome is NOT in
    # it — only in a chrome file — so it stays external.
    ext = {(e.id_type, e.value) for e in r.external}
    assert ("locationSet", "OnlyInChrome") in ext


def test_classify_buckets():
    assert classify("RegionConfigFiles/Parameters.xml") == "dependency"
    assert classify("IdMapFiles/NOAA/IdImportGFS.xml") == "dependency"
    assert classify("RegionConfigFiles/ModuleInstanceDescriptors.xml") == "descriptor"
    assert classify("ModuleConfigFiles/Import/ImportGFS.xml") == "module"
    assert classify("RegionConfigFiles/Topology.xml") == "chrome"


def test_manifest_mentions_deps_and_external():
    files = _base_project(param="GHOST.par")
    files["RegionConfigFiles/Parameters.xml"] = _params("PC.nwp")
    r = compute_closure(files, [SEED])
    md = render_manifest(r, "GFS")
    assert "# Export: module `GFS`" in md
    assert "Grids.xml" in md
    assert "GHOST.par" in md  # external manifest entry


def test_deterministic_output():
    files = _base_project()
    a = compute_closure(files, [SEED])
    b = compute_closure(files, [SEED])
    assert a.needed == b.needed and a.chrome == b.chrome


# --- trimming dependency files ------------------------------------------

def _params_groups(*groups):
    """groups = ((group_id, (param_id, ...)), ...)."""
    body = ""
    for gid, pids in groups:
        ps = "".join(
            f'<parameter id="{p}"><shortName>{p}</shortName></parameter>'
            for p in pids
        )
        body += f'<parameterGroup id="{gid}"><unit>mm</unit>{ps}</parameterGroup>'
    return f'<?xml version="1.0"?><parameterGroups {NS}>{body}</parameterGroups>'


def test_trim_drops_unreferenced_parameters_and_empty_groups():
    # Module references only PC.nwp; Parameters declares three across two
    # groups. Trim keeps PC.nwp, drops TA.nwp/EXTRA.par, and removes the
    # now-empty second group.
    files = {
        SEED: _mod("ImportGFS", param="PC.nwp", idmap="Id", grid="GFS", units="U"),
        "RegionConfigFiles/Parameters.xml": _params_groups(
            ("g1", ("PC.nwp", "EXTRA.par")), ("g2", ("TA.nwp",))),
        "IdMapFiles/NOAA/Id.xml": _idmap(),
        "UnitConversionsFiles/U.xml": _units(),
        "RegionConfigFiles/Grids.xml": _grids("GFS"),
    }
    r = compute_closure(files, [SEED])
    t = trim_dependency_files(files, r)
    p = t["RegionConfigFiles/Parameters.xml"]
    assert 'id="PC.nwp"' in p
    assert "TA.nwp" not in p and "EXTRA.par" not in p
    assert 'id="g1"' in p and 'id="g2"' not in p  # empty group removed


def test_trim_grid_drops_placeholder_keeps_referenced():
    files = {
        SEED: _mod("ImportGFS", param="PC.nwp", idmap="Id", grid="GFS", units="U"),
        "RegionConfigFiles/Parameters.xml": _params("PC.nwp"),
        "IdMapFiles/NOAA/Id.xml": _idmap(),
        "UnitConversionsFiles/U.xml": _units(),
        "RegionConfigFiles/Grids.xml": _grids("GFS", "$MODELNAME1$Grid"),
    }
    r = compute_closure(files, [SEED])
    t = trim_dependency_files(files, r)
    g = t["RegionConfigFiles/Grids.xml"]
    assert 'locationId="GFS"' in g
    assert "MODELNAME1" not in g


def test_trim_locationset_is_transitive():
    # Module references SetA; SetA names SetB; SetC is unrelated. Trim keeps
    # SetA + SetB (transitively), drops SetC.
    seed = (
        f'<?xml version="1.0"?><transformationModule {NS}><variable>'
        f'<timeSeriesSet><moduleInstanceId>M</moduleInstanceId>'
        f'<locationSetId>SetA</locationSetId></timeSeriesSet>'
        f'</variable></transformationModule>'
    )
    files = {
        "ModuleConfigFiles/M.xml": seed,
        "RegionConfigFiles/LocationSets.xml": (
            f'<?xml version="1.0"?><locationSets {NS}>'
            f'<locationSet id="SetA"><locationSetId>SetB</locationSetId></locationSet>'
            f'<locationSet id="SetB"><locationId>L1</locationId></locationSet>'
            f'<locationSet id="SetC"><locationId>L9</locationId></locationSet>'
            f'</locationSets>'),
    }
    r = compute_closure(files, ["ModuleConfigFiles/M.xml"])
    t = trim_dependency_files(files, r)
    ls = t["RegionConfigFiles/LocationSets.xml"]
    assert 'id="SetA"' in ls and 'id="SetB"' in ls
    assert 'id="SetC"' not in ls


def test_trim_omits_file_when_every_entry_referenced():
    # Nothing to drop → file not in the trimmed map (caller keeps it whole).
    files = {
        SEED: _mod("ImportGFS", param="PC.nwp", idmap="Id", grid="GFS", units="U"),
        "RegionConfigFiles/Parameters.xml": _params("PC.nwp"),
        "IdMapFiles/NOAA/Id.xml": _idmap(),
        "UnitConversionsFiles/U.xml": _units(),
        "RegionConfigFiles/Grids.xml": _grids("GFS"),
    }
    r = compute_closure(files, [SEED])
    t = trim_dependency_files(files, r)
    assert "RegionConfigFiles/Parameters.xml" not in t
    assert "RegionConfigFiles/Grids.xml" not in t


def test_trim_preserves_default_namespace():
    files = {
        SEED: _mod("ImportGFS", param="PC.nwp", idmap="Id", grid="GFS", units="U"),
        "RegionConfigFiles/Grids.xml": _grids("GFS", "$MODELNAME1$Grid"),
        "RegionConfigFiles/Parameters.xml": _params("PC.nwp"),
        "IdMapFiles/NOAA/Id.xml": _idmap(),
        "UnitConversionsFiles/U.xml": _units(),
    }
    r = compute_closure(files, [SEED])
    g = trim_dependency_files(files, r)["RegionConfigFiles/Grids.xml"]
    assert 'xmlns="http://www.wldelft.nl/fews"' in g
    assert "ns0:" not in g  # no ElementTree prefix leakage


def test_manifest_flags_trimmed_files():
    files = {
        SEED: _mod("ImportGFS", param="PC.nwp", idmap="Id", grid="GFS", units="U"),
        "RegionConfigFiles/Grids.xml": _grids("GFS", "$MODELNAME1$Grid"),
        "IdMapFiles/NOAA/Id.xml": _idmap(),
        "UnitConversionsFiles/U.xml": _units(),
    }
    r = compute_closure(files, [SEED])
    t = trim_dependency_files(files, r)
    md = render_manifest(r, "GFS", trimmed=set(t))
    assert "trimmed to the referenced entries" in md


# --- integration: real build of a GFS-only project ----------------------

def test_integration_gfs_closure_against_real_build():
    from runners.agent.build_from_blueprint import build_from_blueprint, build_module

    repo = Path(__file__).resolve().parents[1]
    patterns = repo / "fews_agent" / "patterns"
    with tempfile.TemporaryDirectory() as td:
        proj = Path(td) / "p"
        proj.mkdir(parents=True)
        bp = {
            "name": "exp", "output_root": "out",
            "patterns": [{"pattern": "auto/nwp_grid_noaa", "instances": [
                {"nwp_name": "GFS", "parameters": [
                    {"id": "PC.nwp", "unit": "mm", "cumulativeSum": True,
                     "startTimeShiftHours": -3}], "contribute_parameters": True}]}],
        }
        (proj / "project.yaml").write_text(yaml.safe_dump(bp), encoding="utf-8")
        full = build_from_blueprint(
            blueprint_path=proj / "project.yaml", pattern_root=patterns,
            console=Console(quiet=True))
        out = Path(full["output_root"])
        mod = build_module(
            blueprint_path=proj / "project.yaml", pattern_root=patterns,
            pattern="auto/nwp_grid_noaa", instance_match={"nwp_name": "GFS"},
            console=Console(quiet=True))
        seeds = [f["path"].replace("\\", "/") for f in mod["files"]]

        files = {
            str(p.relative_to(out)).replace("\\", "/"): p.read_text(encoding="utf-8")
            for p in out.rglob("*.xml")
        }
        r = compute_closure(files, seeds)

        # The GFS module's genuine dependencies are present…
        assert any(f.endswith("Parameters.xml") for f in r.needed)
        assert any(f.endswith("Grids.xml") for f in r.needed)
        assert any("IdMapFiles/" in f for f in r.needed)
        assert any("UnitConversionsFiles/Import" in f for f in r.needed)
        # …and the closure is far smaller than the whole project…
        assert len(r.needed) < len(files)
        assert len(r.chrome) > len(r.needed)
        # …and chrome is excluded.
        assert any(f.endswith("Topology.xml") for f in r.chrome)
        assert any(f.endswith("Filters.xml") for f in r.chrome)

        # Trimming drops the basin grid placeholder from Grids.xml, and the
        # trimmed result still XSD-validates.
        from fews_agent.agent.module_export import trim_dependency_files
        from fews_agent.validation.xsd import validate_xsd
        trimmed = trim_dependency_files(files, r)
        grid_rel = next(f for f in r.needed if f.endswith("Grids.xml"))
        assert grid_rel in trimmed
        assert "MODELNAME1" not in trimmed[grid_rel]
        ok, msg = validate_xsd(trimmed[grid_rel].encode("utf-8"))
        assert ok, msg
