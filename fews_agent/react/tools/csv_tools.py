"""Input-CSV tools: author station/parameter tables, ingest them to XML.

`write_input_csv` writes a plain CSV into inputs/ (this is how
self-discovered stations become data); `ingest_csvs` runs the existing
CSV ingest (`fews_agent.agent.csv_ingest`) and renders each recognized
CSV through its spec (Locations.xml, Parameters.xml, ...), XSD-gated.
"""
from __future__ import annotations

import csv
from typing import Any

from fews_agent.agent.csv_ingest import ingest_directory
from fews_agent.agent.providers.base import ToolSpec
from fews_agent.generators import SPECS
from fews_agent.validation.xsd import validate_xsd

from ..context import ToolContext
from ..registry import Tool

_SPEC_BY_NAME = {s.name: s for s in SPECS}

RECOGNIZED = ("locations.csv, parameters.csv, qualifiers.csv, "
              "thresholdwarninglevels.csv")


def _write_input_csv(ctx: ToolContext, args: dict[str, Any]) -> Any:
    filename = str(args.get("filename") or "").strip()
    if "/" in filename or "\\" in filename or not filename:
        return {"error": "filename must be a bare name like locations.csv"}
    if not filename.lower().endswith(".csv"):
        return {"error": "filename must end in .csv"}
    header = args.get("header")
    rows = args.get("rows")
    if not isinstance(header, list) or not header:
        return {"error": "header must be a non-empty list of column names"}
    if not isinstance(rows, list):
        return {"error": "rows must be a list of row lists"}
    bad = [i for i, r in enumerate(rows)
           if not isinstance(r, list) or len(r) != len(header)]
    if bad:
        return {"error": f"rows {bad[:10]} don't match the header width "
                         f"({len(header)} columns)"}
    target = ctx.inputs_dir / filename
    overwrote = target.exists()
    with target.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)
    out: dict[str, Any] = {"ok": True, "path": f"inputs/{filename}",
                           "rows_written": len(rows)}
    if overwrote:
        out["overwrote"] = True
    return out


def _ingest_csvs(ctx: ToolContext, args: dict[str, Any]) -> Any:
    results = ingest_directory(ctx.inputs_dir)
    report: list[dict[str, Any]] = []
    for key, res in sorted(results.items()):
        entry: dict[str, Any] = {
            "csv": res.csv_path.name,
            "spec_name": res.spec_name,
            "rows_parsed": res.rows_parsed,
            "rows_failed": res.rows_failed,
            "warnings": res.warnings,
            "errors": res.errors,
        }
        spec = _SPEC_BY_NAME.get(res.spec_name or "")
        if res.model is None or spec is None:
            if res.spec_name is None:
                entry["note"] = (f"unrecognized CSV name — recognized: "
                                 f"{RECOGNIZED}")
            report.append(entry)
            continue
        xml = spec.generate(res.model)
        ok, msg = validate_xsd(xml.encode("utf-8"))
        if not ok:
            entry["error"] = f"rendered XML failed XSD: {msg}"
            report.append(entry)
            continue
        relpath = spec.output_relpath.as_posix()
        ctx.store(relpath, xml, res.spec_name, res.model)
        entry["written"] = relpath
        report.append(entry)
    return {"ingested": report}


WRITE_INPUT_CSV = Tool(
    spec=ToolSpec(
        name="write_input_csv",
        description=(
            "Write a CSV into the project's inputs/ folder. Recognized "
            f"names ({RECOGNIZED}) become XML via ingest_csvs — e.g. put "
            "discovered stations in locations.csv with columns "
            "id,name,lat,lon (aliases accepted)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "filename": {"type": "string"},
                "header": {"type": "array", "items": {"type": "string"}},
                "rows": {"type": "array",
                         "items": {"type": "array"}},
            },
            "required": ["filename", "header", "rows"],
            "additionalProperties": False,
        },
    ),
    handler=_write_input_csv,
)

INGEST_CSVS = Tool(
    spec=ToolSpec(
        name="ingest_csvs",
        description=(
            "Parse every CSV in inputs/ and render the recognized ones to "
            "their FEWS XML (Locations.xml, Parameters.xml, ...), "
            "XSD-validated. Returns a per-CSV report with parse warnings."
        ),
        input_schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    ),
    handler=_ingest_csvs,
)
