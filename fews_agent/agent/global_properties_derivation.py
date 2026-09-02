"""Derive RootConfigFiles/sa_global.Properties from project state.

FEWS resolves runtime placeholders like ``$MODELNAME1$``, ``$REGION$``,
``$TIMEZONE$``, ``$DAY_TIMESTEP$`` from a single global properties file
at startup. Both pattern outputs and bundled standards keep these
placeholders literal — that's by design (the tutorial does the same).
But without ``sa_global.Properties``, FEWS has nothing to substitute
with and the config fails to load.

This deriver reads the project blueprint and writes a minimal
properties file mapping the placeholders to project-specific values:

  - ``MODELNAME1`` / ``MODELNAME2``: basin names from ``raven_basin`` or
    ``wflow_basin`` pattern instances (in declaration order).
  - ``TIMEZONE``: from ``singleton_seeds.Locations.timeZone`` if set, else
    ``GMT`` as a safe default.
  - ``DAY_TIMESTEP`` / ``MODEL1_TIMESTEP`` / ``MODEL2_TIMESTEP``:
    derived as ``day_<TIMEZONE>``, ``hour_<TIMEZONE>``, ``hour_<TIMEZONE>``.
  - ``REGION``: from ``singleton_seeds.Locations.region`` if set, else
    blank (FEWS treats blank as no region prefix).
  - ``EXPLORER_SYSTEMCAPTION``: the project's display name.

A configurator can override by providing their own
``RootConfigFiles/sa_global.Properties`` in inputs/.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .blueprint import Blueprint


# Patterns whose first variable is the basin model name.
_BASIN_PATTERNS = {"auto/basin/raven", "auto/basin/wflow"}


def _basin_names_from_blueprint(bp: "Blueprint") -> list[str]:
    """Extract basin names in declaration order, deduped."""
    names: list[str] = []
    for p in bp.patterns:
        if p.pattern not in _BASIN_PATTERNS:
            continue
        for inst in p.instances:
            name = inst.get("basin_name") if isinstance(inst, dict) else None
            if name and name not in names:
                names.append(str(name))
    return names


def derive_global_properties(bp: "Blueprint") -> str | None:
    """Render a sa_global.Properties text body. Returns None if there's
    nothing project-specific to put in it (no basins, no seeds)."""
    basins = _basin_names_from_blueprint(bp)
    seeds = getattr(bp, "singleton_seeds", {}) or {}
    locations_seeds = seeds.get("Locations") or {}
    timezone = str(locations_seeds.get("timeZone", "") or "GMT")
    region = str(locations_seeds.get("region", "") or "")
    project_caption = (bp.name or "FEWS Project").replace("_", " ").replace("-", " ").title()

    if not basins and not seeds:
        return None

    # Build line list in a stable order. Empty values still emitted so
    # the configurator sees the available knobs.
    lines = ["#General Settings"]
    lines.append(f"EXPLORER_SYSTEMCAPTION= {project_caption}")
    if basins:
        lines.append(f"MODELNAME1 = {basins[0]}")
        # MODELNAME2: the second basin if present, else fall back to the
        # sole basin. The raven/wflow patterns reference their OWN model
        # instances via $MODELNAME2$ (a farmed-tutorial artifact), so a
        # single-basin project must still resolve it or those ids are dead
        # at FEWS startup. Tutorial (>=2 basins) is unchanged.
        lines.append(
            f"MODELNAME2 = {basins[1] if len(basins) >= 2 else basins[0]}"
        )
    lines.append("")
    lines.append("LANGUAGE=EN")
    lines.append("COUNTRY=")
    lines.append(f"REGION={region}")
    lines.append(f"TIMEZONE={timezone}")
    lines.append(f"MODEL_TIMEZONE={timezone}")
    lines.append("MODEL_TIMESHIFT=0")
    lines.append(f"DAY_TIMESTEP=day_{timezone}")
    lines.append(f"MODEL1_TIMESTEP=hour_{timezone}")
    if basins:
        lines.append(f"MODEL2_TIMESTEP=hour_{timezone}")
    lines.append("")
    lines.append("#Directory Settings — adjust to your FEWS install layout")
    lines.append("IMPORT_FOLDER=%REGION_HOME%/Import")
    lines.append("EXPORT_FOLDER=%REGION_HOME%/Export")
    lines.append("IMPORT_FAILED_FOLDER=%REGION_HOME%/ImportFailed")
    lines.append("IMPORT_BACKUP_FOLDER=%REGION_HOME%/ImportBackup")
    lines.append("GA_DUMPFILEDIR=%REGION_HOME%/DumpFiles")
    lines.append("")
    return "\n".join(lines) + "\n"


__all__ = ["derive_global_properties"]
