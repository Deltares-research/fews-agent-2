"""Writer + workspace tools.

`write_config_file` is the canonical deterministic-writer idiom
(model_validate -> render -> XSD) behind a tool boundary: validation
errors return verbatim as the tool result, so the ReAct loop is the
repair loop. The model NEVER writes XML text.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

from pydantic import ValidationError

from fews_agent.agent.blueprint import schema_class_for, template_for_schema
from fews_agent.agent.providers.base import ToolSpec
from fews_agent.generators import SPECS
from fews_agent.generators.base import render as render_template
from fews_agent.validation.xsd import validate_xsd

from ..context import ToolContext
from ..registry import Tool
from ..render_generic import known_xsd, render_generic

_SPEC_BY_NAME = {s.name: s for s in SPECS}

MAX_READ_CHARS = 18_000


def _floats_to_decimal(data: Any) -> Any:
    """Tool args arrive through json.loads, so 0.25 is a float. Convert
    via Decimal(str(f)) so the writer's fixed-point rendering applies
    (matching the repo's parse_float=Decimal convention)."""
    if isinstance(data, float):
        return Decimal(str(data))
    if isinstance(data, list):
        return [_floats_to_decimal(v) for v in data]
    if isinstance(data, dict):
        return {k: _floats_to_decimal(v) for k, v in data.items()}
    return data


def safe_relpath(raw: str) -> str | None:
    """Normalize an output path to a posix relpath inside generated/;
    None when it escapes (absolute, drive letter, or `..`)."""
    text = str(raw).replace("\\", "/").strip()
    if not text:
        return None
    if PureWindowsPath(text).is_absolute() or text.startswith("/"):
        return None
    p = PurePosixPath(text)
    if any(part in ("..", "") for part in p.parts):
        return None
    return p.as_posix()


def _write_config_file(ctx: ToolContext, args: dict[str, Any]) -> Any:
    spec_name = str(args.get("spec_name") or "")
    schema_name = str(args.get("schema") or "")
    if bool(spec_name) == bool(schema_name):
        return {"error": "pass exactly one of spec_name (a singleton from "
                         "list_specs) or schema (a model class name like "
                         "'Workflow', 'TimeSeriesImportRun', 'IdMap' for "
                         "per-instance files)"}

    if spec_name:
        spec = _SPEC_BY_NAME.get(spec_name)
        if spec is None:
            return {"error": f"unknown spec {spec_name!r}; call list_specs"}
        model_class = spec.model_class
        default_path: str | None = spec.output_relpath.as_posix()
        label = spec_name
    else:
        try:
            model_class = schema_class_for(schema_name)
        except KeyError as exc:
            return {"error": str(exc)}
        default_path = None
        label = schema_name

    data = args.get("data")
    if not isinstance(data, dict):
        return {"error": "data must be a JSON object matching "
                         f"describe_spec for {label!r}"}
    data = _floats_to_decimal(data)
    try:
        model = model_class.model_validate(data)
    except ValidationError as exc:
        return {"error": f"data does not match the {label} schema",
                "validation_errors": str(exc)}
    try:
        template = (spec.template_name if spec_name
                    else template_for_schema(model_class))
        xml = render_template(template, model)
    except Exception as exc:  # noqa: BLE001 — surfaced for repair
        return {"error": f"render failed: {type(exc).__name__}: {exc}"}
    ok, msg = validate_xsd(xml.encode("utf-8"))
    if not ok:
        return {"error": "rendered XML failed XSD validation — fix the "
                         "data and retry (element ORDER matters: "
                         "xsd:sequence)", "xsd": msg}
    raw_path = args.get("output_path") or default_path
    if not raw_path:
        return {"error": "output_path is required when writing by schema "
                         "(per-instance files have no default path)"}
    relpath = safe_relpath(raw_path)
    if relpath is None:
        return {"error": f"output_path {raw_path!r} must be a relative "
                         "path inside the generated config tree"}
    overwrote = ctx.store(relpath, xml, label, model)
    out: dict[str, Any] = {"ok": True, "path": relpath, "xsd": msg,
                           "bytes": len(xml)}
    if overwrote:
        out["overwrote"] = True
    return out


def _write_generic_file(ctx: ToolContext, args: dict[str, Any]) -> Any:
    root_tag = str(args.get("root_tag") or "").strip()
    xsd_name = str(args.get("xsd_name") or "").strip()
    body = args.get("body")
    if not root_tag or not xsd_name:
        return {"error": "root_tag and xsd_name are required"}
    if not known_xsd(xsd_name):
        return {"error": f"unknown XSD {xsd_name!r} — must be a basename "
                         "from the pinned FEWS schema set (e.g. "
                         "'grids.xsd', 'filters.xsd')"}
    if not isinstance(body, (dict, list)):
        return {"error": "body must be a JSON object (or a list of "
                         "single-key objects when sibling order matters)"}
    relpath = safe_relpath(str(args.get("output_path") or ""))
    if relpath is None:
        return {"error": "output_path (relative, inside the config tree) "
                         "is required"}
    body = _floats_to_decimal(body)
    try:
        xml = render_generic(root_tag, xsd_name, body,
                             version=args.get("version"))
    except Exception as exc:  # noqa: BLE001 — surfaced for repair
        return {"error": f"render failed: {type(exc).__name__}: {exc}"}
    ok, msg = validate_xsd(xml.encode("utf-8"))
    if not ok:
        return {"error": "rendered XML failed XSD validation — fix the "
                         "body and retry (element ORDER matters: "
                         "xsd:sequence)", "xsd": msg}
    overwrote = ctx.store(relpath, xml, f"generic:{root_tag}", None)
    out: dict[str, Any] = {"ok": True, "path": relpath, "xsd": msg,
                           "bytes": len(xml)}
    if overwrote:
        out["overwrote"] = True
    return out


def _read_project_file(ctx: ToolContext, args: dict[str, Any]) -> Any:
    raw = str(args.get("path") or "")
    relpath = safe_relpath(raw)
    if relpath is None:
        return {"error": f"bad path {raw!r}"}
    rendered = ctx.rendered.get(relpath)
    if rendered is not None:
        content = rendered.content
    else:
        for root in (ctx.generated_dir, ctx.inputs_dir, ctx.session_dir):
            target = root / relpath
            if target.is_file():
                content = target.read_text(encoding="utf-8")
                break
        else:
            return {"error": f"no such file: {relpath}"}
    clipped = content[:MAX_READ_CHARS]
    out: dict[str, Any] = {"path": relpath, "content": clipped}
    if len(content) > MAX_READ_CHARS:
        out["truncated_chars"] = len(content) - MAX_READ_CHARS
    return out


def _list_project_files(ctx: ToolContext, args: dict[str, Any]) -> Any:
    generated = [
        {"path": f.relpath, "bytes": len(f.content),
         "spec_name": f.instance_label}
        for f in ctx.rendered_list()
    ]
    inputs = sorted(
        p.name for p in ctx.inputs_dir.iterdir() if p.is_file()
    ) if ctx.inputs_dir.is_dir() else []
    return {"generated": generated, "inputs": inputs}


WRITE_CONFIG_FILE = Tool(
    spec=ToolSpec(
        name="write_config_file",
        description=(
            "Render one FEWS config file deterministically from a data "
            "dict (see describe_spec for the schema) and XSD-validate it. "
            "Two modes: spec_name for singletons from list_specs (default "
            "output path applies), OR schema + output_path for "
            "per-instance files — schema is the model class name "
            "('TimeSeriesImportRun' for import module configs, 'Workflow' "
            "for workflows, 'IdMap' for id mappings, ...). On {error}, "
            "fix the data and call again — never give up on a file."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "spec_name": {"type": "string"},
                "schema": {
                    "type": "string",
                    "description": "model class name, e.g. 'Workflow'; "
                                   "mutually exclusive with spec_name",
                },
                "data": {"type": "object"},
                "output_path": {
                    "type": "string",
                    "description": "relative path inside the config tree, "
                                   "e.g. ModuleConfigFiles/Import/"
                                   "ImportGFS.xml; REQUIRED with schema, "
                                   "optional with spec_name",
                },
            },
            "required": ["data"],
            "additionalProperties": False,
        },
    ),
    handler=_write_config_file,
)

WRITE_GENERIC_FILE = Tool(
    spec=ToolSpec(
        name="write_generic_file",
        description=(
            "Fallback writer for FEWS file types without a registered "
            "spec: deterministic dict->XML under any root tag, validated "
            "against a named XSD from the pinned schema set. Prefer "
            "write_config_file whenever list_specs has the file type — "
            "it knows the correct root/XSD/output path. Note: IDs "
            "declared in generic bodies are invisible to the semantic "
            "validator."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "root_tag": {"type": "string"},
                "xsd_name": {
                    "type": "string",
                    "description": "XSD basename, e.g. 'grids.xsd'",
                },
                "output_path": {"type": "string"},
                "body": {
                    "description": "object, or list of single-key objects "
                                   "for ordered siblings; '@key' = attribute",
                },
                "version": {"type": "string"},
            },
            "required": ["root_tag", "xsd_name", "output_path", "body"],
            "additionalProperties": False,
        },
    ),
    handler=_write_generic_file,
)

READ_PROJECT_FILE = Tool(
    spec=ToolSpec(
        name="read_project_file",
        description="Read one generated config file or input CSV back.",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
    ),
    handler=_read_project_file,
)

LIST_PROJECT_FILES = Tool(
    spec=ToolSpec(
        name="list_project_files",
        description="List every generated file and input CSV so far.",
        input_schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    ),
    handler=_list_project_files,
)
