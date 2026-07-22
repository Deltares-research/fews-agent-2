"""Module registry — the FEWS-folder units the agent builds one at a time.

This is the backbone of the *module-mode* UX: instead of eliciting a whole
project in one shot, the configurator focuses **one module** at a time and
runs small operations on it (add / set / remove / list / build). A module is
the coherent unit of config work the agent scopes prompts, patterns, schemas,
and inputs to while it's in focus.

Definition — "1 coherent unit of config work = 1 module". This *mostly*
lines up with the always-present FEWS config folders
(``ModuleConfigFiles``, ``IdMapFiles``, ``DisplayConfigFiles``, ...), but two
folders don't map 1:1 and the registry reflects that:

  * **Weld** — one *capability* spans two folders. Adding a single import
    writes ``ModuleConfigFiles/Import/ImportGFS.xml`` **and**
    ``WorkflowFiles/Import/ImportGFSGrids.xml`` (and an IdMap row). Splitting
    those into separate modules would force the configurator to hand-wire the
    matching workflow + keep IDs consistent by hand — exactly what the
    patterns exist to prevent. So ``ModuleConfigFiles`` + ``WorkflowFiles``
    (+ ``ModuleParFiles``) are one ``processing`` module.
  * **Split** — one *folder* holds several independent files from different
    sources. ``RegionConfigFiles`` carries ``Locations`` (CSV ingest),
    ``Parameters`` (CSV ingest), ``Filters`` (LLM), ``Topology`` (deriver) —
    unrelated work with nothing shared but the folder name. Treating it as
    one module would merge four different jobs, so it splits into
    ``locations`` / ``parameters`` / ``filters`` / ``topology``.

Nothing here talks to an LLM or the build path. It's a static description the
turn engine reads to decide what loads when a module is in focus, and the
build runner reads to scope a per-module render. ``phases.py`` (the
capability taxonomy: imports/process/model/visualize) is still used *inside*
the ``processing`` module to tell an add-import from an add-model; this
registry is the coarser, folder-level layer above it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .phases import classify_phase


# How a module's files come into existence — mirrors the auto-generation
# layers in build_from_blueprint. A module can have more than one (the
# ``display`` module is a pattern output + a bundled standard), so this is
# the *primary* source; ``also_from`` lists secondary contributors.
SourceKind = str  # "patterns" | "csv_ingest" | "llm" | "deriver" | "bundled"


@dataclass(frozen=True)
class Module:
    """One focusable unit of FEWS config work.

    ``key`` is the stable identifier used in chat state (``current_module``)
    and on the CLI (``/module <key>``). Everything else describes what loads
    when this module is in focus.
    """

    key: str
    label: str
    description: str

    # FEWS output folders this module owns (or, for a split folder, the
    # specific files within it). Purely descriptive — used for the scoped
    # build and for telling the user where output lands.
    folders: tuple[str, ...]

    # Primary generation source + any secondary contributors.
    source_kind: SourceKind
    also_from: tuple[SourceKind, ...] = ()

    # For pattern-backed modules: which capability *phases* (from phases.py)
    # a pattern must classify into to belong to this module. Empty for
    # non-pattern modules. ``processing`` claims imports/process/model;
    # ``display`` claims visualize.
    phases: tuple[str, ...] = ()

    # Slot/variable names this module elicits from the user.
    variables: tuple[str, ...] = ()

    # Cross-cutting scalars this module READS from the accumulated
    # project.yaml (``singleton_seeds``) so it never re-asks what an earlier
    # module already established, and WRITES back so later modules inherit
    # them. This is the "shared variables persist" mechanism — the store is
    # project.yaml itself, not a separate dict.
    shared_reads: tuple[str, ...] = ()
    shared_writes: tuple[str, ...] = ()

    # Configurator-supplied inputs. A trailing "?" marks an optional input.
    inputs: tuple[str, ...] = ()

    # Operations valid while this module is in focus. Every module supports
    # list + build; pattern/CSV modules add add/remove/set.
    operations: tuple[str, ...] = ("list", "build")

    # Focused system-prompt fragment injected when this module is in focus.
    # Kept short and imperative — it steers the extractor + reply toward
    # this module's job without dragging in the other modules' concerns.
    prompt: str = ""

    def supports(self, op: str) -> bool:
        return op in self.operations


# Operation sets, reused across modules.
_FULL_OPS = ("add", "set", "remove", "list", "build")
_EDIT_OPS = ("set", "list", "build")          # single-file, no items to add
_VIEW_OPS = ("list", "build")                 # deriver / bundled: no editing


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------
#
# Ordered roughly the way a config is assembled (data in → reference data →
# processing → chrome), but there is NO enforced sequence: the configurator
# selects whichever module they want. Order here only sets a sensible default
# for listings.

MODULES: dict[str, Module] = {
    # --- reference data (RegionConfigFiles, split) ------------------------
    "locations": Module(
        key="locations",
        label="RegionConfigFiles · Locations",
        description="Station / point locations and the location sets that "
                    "group them.",
        folders=("RegionConfigFiles/Locations.xml",
                 "RegionConfigFiles/LocationSets.xml"),
        source_kind="csv_ingest",
        also_from=("deriver",),
        variables=("geoDatum", "locations_source"),
        shared_reads=("geoDatum", "region"),
        shared_writes=("geoDatum", "region"),
        inputs=("locations.csv",),
        operations=_EDIT_OPS,
        prompt="You are building the Locations module: the station/point "
               "locations and their location sets. Elicit the geographic "
               "datum and where the location list comes from (a locations.csv "
               "is the norm). Do not discuss imports or models here.",
    ),
    "parameters": Module(
        key="parameters",
        label="RegionConfigFiles · Parameters",
        description="Parameter definitions (PC, TA, Q, ...) and their groups.",
        folders=("RegionConfigFiles/Parameters.xml",),
        source_kind="csv_ingest",
        variables=("data_types",),
        inputs=("parameters.csv",),
        operations=_EDIT_OPS,
        prompt="You are building the Parameters module: the parameter "
               "definitions and groups. Elicit which physical quantities the "
               "project uses. A parameters.csv is the usual source.",
    ),

    # --- the welded processing module (ModuleConfig + Workflow + ModulePar) -
    "processing": Module(
        key="processing",
        label="ModuleConfigFiles + WorkflowFiles (imports, transforms, model runs)",
        description="The module configs and their workflows: data imports, "
                    "preprocessing / interpolation transforms, and model "
                    "runs. One capability = its config + workflow + id-map "
                    "row, emitted together.",
        folders=("ModuleConfigFiles/", "WorkflowFiles/", "ModuleParFiles/"),
        source_kind="patterns",
        also_from=("deriver",),  # descriptors + topology reference these
        phases=("imports", "process", "model"),
        variables=("imports", "basins", "basin_name", "model_adapter",
                   "data_types", "grid_resolution", "forecast_horizon_hours",
                   "wants_interpolation", "region", "custom_bbox"),
        shared_reads=("geoDatum", "region", "basin_name"),
        shared_writes=("region", "basin_name"),
        inputs=("locations.csv?",),
        operations=_FULL_OPS,
        prompt="You are building the Processing module: imports, transforms, "
               "and model runs. Each item the user adds is a capability "
               "(an import source like GFS/HRDPS, an interpolation, or a "
               "model run) that emits its config file, its workflow, and its "
               "id-map row together. Elicit which sources/models to add and "
               "their parameters. Do not ask about display or filters here.",
    ),

    # --- id maps ----------------------------------------------------------
    "idmap": Module(
        key="idmap",
        label="IdMapFiles",
        description="Internal↔external id maps. Mostly bundled standards; "
                    "each processing capability contributes its own row.",
        folders=("IdMapFiles/",),
        source_kind="bundled",
        also_from=("patterns",),
        operations=_VIEW_OPS,
        prompt="You are building the ID-maps module. Most rows are bundled "
               "standards or contributed automatically by processing "
               "capabilities; surface what exists and only elicit overrides.",
    ),

    # --- filters (RegionConfigFiles, split) -------------------------------
    "filters": Module(
        key="filters",
        label="RegionConfigFiles · Filters",
        description="The Data Viewer filter tree grouping the project's "
                    "series. LLM-drafted from the project's IDs.",
        folders=("RegionConfigFiles/Filters.xml",),
        source_kind="llm",
        operations=_VIEW_OPS,
        prompt="You are building the Filters module: the Data Viewer filter "
               "grouping. It is drafted from the IDs already present in the "
               "project, so build it after imports/processing exist.",
    ),

    # --- display ----------------------------------------------------------
    "display": Module(
        key="display",
        label="DisplayConfigFiles (Spatial Display, grid plots)",
        description="Spatial Display / grid display configs for viewing "
                    "imported grids and station series.",
        folders=("DisplayConfigFiles/",),
        source_kind="patterns",
        also_from=("bundled",),
        phases=("visualize",),
        variables=("wants_visualization", "imports", "data_types",
                   "forecast_horizon_hours"),
        shared_reads=("region", "imports"),
        operations=_FULL_OPS,
        prompt="You are building the Display module: Spatial Display and grid "
               "plots for the imported grids and station series. Elicit which "
               "sources/parameters to visualize and the display window.",
    ),

    # --- topology (RegionConfigFiles, split) ------------------------------
    "topology": Module(
        key="topology",
        label="RegionConfigFiles · Topology",
        description="The Topology tree grouping workflows for the Forecast "
                    "panel. Derived from the project's workflows.",
        folders=("RegionConfigFiles/Topology.xml",),
        source_kind="deriver",
        operations=_VIEW_OPS,
        prompt="You are building the Topology module: the Forecast-panel "
               "tree. It is derived from the workflows already in the "
               "project, so build it after processing exists.",
    ),

    # --- system standards -------------------------------------------------
    "system": Module(
        key="system",
        label="SystemConfigFiles (time steps, unit conversions)",
        description="Near-universal system config: time steps and unit "
                    "conversions. Bundled standards, project-trimmed.",
        folders=("SystemConfigFiles/", "UnitConversionsFiles/"),
        source_kind="bundled",
        operations=_VIEW_OPS,
        prompt="You are building the System module: time steps and unit "
               "conversions. These are bundled standards; surface them and "
               "only elicit project-specific overrides.",
    ),

    # --- root -------------------------------------------------------------
    "root": Module(
        key="root",
        label="RootConfigFiles (sa_global.Properties)",
        description="RootConfigFiles/sa_global.Properties — the placeholder "
                    "value map FEWS resolves at startup. Derived from the "
                    "project's basins + region.",
        folders=("RootConfigFiles/",),
        source_kind="deriver",
        shared_reads=("region", "basin_name", "geoDatum"),
        operations=_VIEW_OPS,
        prompt="You are building the Root module: sa_global.Properties, the "
               "map of $PLACEHOLDER$ values FEWS resolves at startup. It is "
               "derived from the project's basins and region.",
    ),
}


# Default listing order (assembly-ish: data → reference → processing → chrome).
MODULE_ORDER: tuple[str, ...] = (
    "locations", "parameters", "processing", "display",
    "filters", "topology", "idmap", "system", "root",
)


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def get_module(key: str | None) -> Module | None:
    """Return the module for ``key`` (case-insensitive), or None."""
    if not key:
        return None
    return MODULES.get(key.strip().lower())


def list_modules() -> list[Module]:
    """All modules in the canonical listing order."""
    return [MODULES[k] for k in MODULE_ORDER if k in MODULES]


# User-typed synonyms → canonical module key. Deliberately generous so
# "imports", "import a grid", "meteo", etc. all land on ``processing``.
_MODULE_SYNONYMS: dict[str, str] = {
    "location": "locations", "locations": "locations", "station": "locations",
    "stations": "locations", "locationsets": "locations",
    "parameter": "parameters", "parameters": "parameters", "param": "parameters",
    "params": "parameters",
    "processing": "processing", "process": "processing", "module": "processing",
    "moduleconfig": "processing", "moduleconfigfiles": "processing",
    "import": "processing", "imports": "processing", "workflow": "processing",
    "workflows": "processing", "model": "processing", "models": "processing",
    "run": "processing", "transform": "processing", "interpolate": "processing",
    "interpolation": "processing",
    "idmap": "idmap", "idmaps": "idmap", "idmapfiles": "idmap",
    "filter": "filters", "filters": "filters",
    "display": "display", "displays": "display", "spatial": "display",
    "spatialdisplay": "display", "viz": "display", "visualize": "display",
    "visualise": "display", "grid_display": "display", "plots": "display",
    "topology": "topology", "topo": "topology",
    "system": "system", "timesteps": "system", "units": "system",
    "unitconversions": "system",
    "root": "root", "properties": "root", "global": "root",
    "sa_global": "root",
}


def normalize_module(token: str | None) -> str | None:
    """Resolve a user-typed module token to a canonical module key.

    Tries the synonym map, then a direct key match. Returns None when the
    token doesn't name a known module so the caller can ask.
    """
    t = (token or "").strip().lower()
    if not t:
        return None
    if t in _MODULE_SYNONYMS:
        return _MODULE_SYNONYMS[t]
    if t in MODULES:
        return t
    return None


def module_for_pattern(pattern_path: str) -> str:
    """Map a resolved pattern path to the module that owns it.

    Reuses the capability ``classify_phase`` and folds the capability phases
    into the coarser folder-level modules: imports/process/model →
    ``processing``; visualize → ``display``; maintenance stays its own
    concern (folded into ``processing`` for now, since amalgamate/archive
    are ModuleConfig+Workflow capabilities).
    """
    phase = classify_phase(pattern_path)
    if phase == "visualize":
        return "display"
    # imports, process, model, maintenance are all ModuleConfig+Workflow work.
    return "processing"


def modules_present(patterns: list[dict[str, Any]] | None) -> list[str]:
    """Which modules the already-resolved patterns populate, in order.

    ``patterns`` is ``state['patterns']``. Used to show the configurator
    which modules a session has touched so far.
    """
    seen: set[str] = set()
    for entry in patterns or []:
        seen.add(module_for_pattern(entry.get("pattern", "")))
    return [k for k in MODULE_ORDER if k in seen]


# The folders a delivered Delft-FEWS Config directory normally contains.
# Used by the "download Config" bundle: every folder is present in the zip
# even when this project generated nothing into it (empty folders included),
# so the download drops straight into a FEWS region as a complete skeleton.
CONFIG_FOLDERS: tuple[str, ...] = (
    "ColdStateFiles",
    "CoefficientSetsFiles",
    "DisplayConfigFiles",
    "FlagConversionsFiles",
    "IconFiles",
    "IdMapFiles",
    "MapLayerFiles",
    "ModuleConfigFiles",
    "ModuleDataSetFiles",
    "ModuleParFiles",
    "PiClientConfigFiles",
    "RegionConfigFiles",
    "ReportTemplateFiles",
    "RootConfigFiles",
    "SystemConfigFiles",
    "UnitConversionsFiles",
    "WorkflowFiles",
)
