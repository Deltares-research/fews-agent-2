"""Bundled-standards tool: fetch a near-universal default yaml as JSON.

The 38 yamls in `fews_agent/agent/standard_inputs/` are hand-authored
defaults (timeSteps, unit conversions, idMaps for common sources,
display/explorer skeletons). Each stem IS a registered spec name, so the
agent adapts the returned data and writes it back via write_config_file.
FEWS runtime placeholders ($MODELNAME1$, $TIMEZONE$, ...) inside them
stay literal — FEWS resolves them from sa_global properties at startup.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from fews_agent.agent.providers.base import ToolSpec
from fews_agent.generators import SPECS

from ..context import ToolContext
from ..registry import Tool

STANDARD_INPUTS_DIR = (Path(__file__).resolve().parents[2]
                       / "agent" / "standard_inputs")

_SPEC_BY_NAME = {s.name: s for s in SPECS}


def _catalog() -> list[dict[str, Any]]:
    rows = []
    for path in sorted(STANDARD_INPUTS_DIR.glob("*.yaml")):
        spec = _SPEC_BY_NAME.get(path.stem)
        rows.append({
            "name": path.stem,
            "spec_name": path.stem if spec else None,
            "output_relpath": (spec.output_relpath.as_posix()
                               if spec else None),
        })
    return rows


def _get_standard(ctx: ToolContext, args: dict[str, Any]) -> Any:
    name = str(args.get("name") or "").strip()
    if not name:
        return {"count": len(_catalog()), "standards": _catalog()}
    path = STANDARD_INPUTS_DIR / f"{name}.yaml"
    if not path.is_file():
        stems = [p.stem for p in STANDARD_INPUTS_DIR.glob("*.yaml")]
        return {"error": f"no bundled standard {name!r}; "
                         f"available: {stems}"}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    spec = _SPEC_BY_NAME.get(name)
    return {
        "name": name,
        "spec_name": name if spec else None,
        "output_relpath": spec.output_relpath.as_posix() if spec else None,
        "data": data,
    }


GET_STANDARD = Tool(
    spec=ToolSpec(
        name="get_standard",
        description=(
            "Fetch a bundled near-universal default config as a data dict "
            "(timeSteps, unit conversions, idImport maps for common "
            "sources, grids/filters/explorer/display skeletons). Call "
            "without a name for the catalog. Bodies are large and stay "
            "in context — fetch ONLY standards you will actually write, "
            "once each. Adapt the data to the project (drop entries for "
            "sources you don't import), then write it with "
            "write_config_file using the same spec_name. Keep "
            "$PLACEHOLDER$ strings literal."
        ),
        input_schema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "additionalProperties": False,
        },
    ),
    handler=_get_standard,
)
