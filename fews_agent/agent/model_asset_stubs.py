"""Emit stubs + a manifest for the external model assets FEWS needs.

The FEWS-Conform audit of ``raven_basin`` (and any general-adapter model)
surfaced three file classes that **no** generation layer produces, because
they're genuinely external — model binaries, the model schematization, and
the initial cold state:

  - ``ModuleDataSetFiles/Binaries/Bin<Software>.zip``  — model + adapter exes
  - ``ModuleDataSetFiles/<Area><Software>.zip``        — the schematization
  - ``ColdStateFiles/<Software>_Csf/<Area><Software>Hc Default.zip``
                                                       — the initial state

Today they're *silently* absent — the config XSD-validates but a model run
would fail at FEWS startup. That violates the repo's "fail loudly" rule.
This module closes the gap two ways:

  1. **Detection + loud warning (always):** walk the rendered general-adapter
     runs, work out what each model needs, and — when the config tree carries
     none of it — surface a warning listing the missing assets. Adds no
     files, so the byte-equivalent oracle is untouched.
  2. **Stub + manifest scaffolding (opt-in):** on
     ``metadata.emit_model_asset_stubs`` the runner also writes placeholder
     markers at the exact Conform paths (each a *folder ending in .zip*, per
     the 2024.02 convention) plus a ``_REQUIRED_MODEL_ASSETS.md`` manifest.

Everything here is pure and I/O-free; the runner owns rendering/printing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .blueprint import RenderedFile


# The adapter executable names the model software: RavenFEWSAdapter.exe →
# Raven, WflowFEWSAdapter.exe → Wflow. Captured group is PascalCased.
_ADAPTER_RE = re.compile(r"([A-Za-z][A-Za-z0-9]*)FEWSAdapter\.exe", re.IGNORECASE)

# Simulation-type suffixes stripped off a template filename to recover the
# model area/basin: LiardHistoricTemplate.xml → Liard.
_SIM_SUFFIXES = (
    "Forecast", "Hindcast", "Historic", "Historical", "Update", "Scenario",
)

# A general-adapter file only needs external assets if it actually runs a
# stateful model — i.e. carries one of these state markers.
_STATE_MARKERS = ("<coldState", "<warmState", "<stateConfigFile")


@dataclass(frozen=True)
class ModelAssetRequirement:
    """One (software, area) model that needs external binaries + state."""

    software: str
    area: str

    @property
    def binaries_path(self) -> str:
        # One Bin<Software>.zip serves every area of that software.
        return f"ModuleDataSetFiles/Binaries/Bin{self.software}.zip"

    @property
    def dataset_path(self) -> str:
        return f"ModuleDataSetFiles/{self.area}{self.software}.zip"

    @property
    def coldstate_path(self) -> str:
        return (
            f"ColdStateFiles/{self.software}_Csf/"
            f"{self.area}{self.software}Hc Default.zip"
        )


def _software_from(content: str) -> str | None:
    m = _ADAPTER_RE.search(content)
    if not m:
        return None
    name = m.group(1)
    return name[:1].upper() + name[1:]


def _area_from(relpath: str) -> str:
    base = PurePosixPath(relpath.replace("\\", "/")).name
    stem = base[:-4] if base.lower().endswith(".xml") else base
    if stem.endswith("Template"):
        stem = stem[: -len("Template")]
    for suffix in _SIM_SUFFIXES:
        if stem.endswith(suffix) and len(stem) > len(suffix):
            return stem[: -len(suffix)]
    return stem


def detect_model_asset_requirements(
    rendered_files: list["RenderedFile"],
) -> list[ModelAssetRequirement]:
    """Find general-adapter model runs and the external assets they need.

    Deduplicated and sorted by (software, area). A general-adapter file is
    only counted when it both looks like a general adapter, names an adapter
    executable (so we can identify the software), and carries a state marker
    (so it's a stateful model run, not e.g. a pure export adapter).
    """
    found: set[ModelAssetRequirement] = set()
    for rf in rendered_files:
        content = rf.content
        if "<generalAdapterRun" not in content:
            continue
        if not any(marker in content for marker in _STATE_MARKERS):
            continue
        software = _software_from(content)
        if software is None:
            continue
        area = _area_from(rf.relpath)
        if not area:
            continue
        found.add(ModelAssetRequirement(software=software, area=area))
    return sorted(found, key=lambda r: (r.software, r.area))


def config_has_model_assets(rendered_files: list["RenderedFile"]) -> bool:
    """True if the tree already carries any ColdState/ModuleDataSet file —
    i.e. the configurator (or an input) provided the assets, so we stay quiet.
    """
    for rf in rendered_files:
        rel = rf.relpath.replace("\\", "/")
        if rel.startswith("ColdStateFiles/") or rel.startswith(
            "ModuleDataSetFiles/"
        ):
            return True
    return False


def missing_model_asset_paths(
    reqs: list[ModelAssetRequirement],
) -> list[str]:
    """Flat, deduped list of the required asset paths (for warnings/summary)."""
    paths: list[str] = []
    seen: set[str] = set()
    for r in reqs:
        for p in (r.binaries_path, r.dataset_path, r.coldstate_path):
            if p not in seen:
                seen.add(p)
                paths.append(p)
    return paths


_STUB_ROOT = "_REQUIRED_MODEL_ASSETS"


def _stub_marker(kind: str, req: ModelAssetRequirement, path: str) -> str:
    return (
        f"PLACEHOLDER — supply the real {kind} here.\n\n"
        f"Model: {req.software}   Area: {req.area}\n"
        f"Expected at: {path}\n\n"
        f"This directory name ends in '.zip' on purpose: since FEWS 2024.02, "
        f"store the contents as a FOLDER (not a compressed archive); FEWS "
        f"zips it on upload while keeping files individually diffable.\n"
    )


def render_model_asset_manifest(
    reqs: list[ModelAssetRequirement],
) -> str:
    """Markdown manifest enumerating the external assets the configurator
    must supply. Empty string if there are no requirements."""
    if not reqs:
        return ""
    lines = [
        "# Required model assets (external — not generated)",
        "",
        "This project runs one or more general-adapter models. FEWS needs "
        "the following files, which no generation layer can produce (model "
        "binaries, schematization, and initial state). Supply each before "
        "running the model — the config is XSD-valid without them but the "
        "model run will fail at startup.",
        "",
        "> Each `*.zip` path below is a **folder** whose name ends in `.zip` "
        "(FEWS 2024.02 convention), not a compressed archive.",
        "",
    ]
    for r in reqs:
        lines.append(f"## {r.area} {r.software}")
        lines.append("")
        lines.append(f"- **Binaries** (model + adapter exes): `{r.binaries_path}`")
        lines.append(f"- **Schematization**: `{r.dataset_path}`")
        lines.append(f"- **Cold state** (initial): `{r.coldstate_path}`")
        lines.append("")
    return "\n".join(lines)


def model_asset_stub_files(
    reqs: list[ModelAssetRequirement],
) -> list[tuple[str, str]]:
    """(relpath, content) placeholder files for the opt-in scaffold.

    One marker inside each required `.zip` folder (so the folder exists and
    demonstrates the convention) plus the top-level manifest. Deduped so a
    shared `Bin<Software>.zip` isn't written twice.
    """
    if not reqs:
        return []
    out: list[tuple[str, str]] = []
    seen: set[str] = set()

    def _add(path: str, kind: str, req: ModelAssetRequirement) -> None:
        marker = f"{path}/PLACEHOLDER.md"
        if marker in seen:
            return
        seen.add(marker)
        out.append((marker, _stub_marker(kind, req, path)))

    for r in reqs:
        _add(r.binaries_path, "model + adapter binaries", r)
        _add(r.dataset_path, "model schematization", r)
        _add(r.coldstate_path, "initial cold state", r)
    out.append((f"{_STUB_ROOT}.md", render_model_asset_manifest(reqs)))
    return out


__all__ = [
    "ModelAssetRequirement",
    "config_has_model_assets",
    "detect_model_asset_requirements",
    "missing_model_asset_paths",
    "model_asset_stub_files",
    "render_model_asset_manifest",
]
