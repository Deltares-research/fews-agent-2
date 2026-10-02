"""``fews-check`` — coding-agent surface for the verification toolbelt.

Always prints one JSON object on stdout. ``--json`` is accepted anywhere
and is the default (skills should pass it). The agent fills JSON; this
process renders, validates, and is the only write gate (``admit``).

    uv run fews-check --json schema-shape Workflow
    uv run fews-check --json render-spec Workflow --data payload.json
    uv run fews-check --json admit PATH --from-render render.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from fews_agent.agent.config_tree import open_config
from fews_agent.agent.generation_tools import tool_admit_file
from fews_agent.validation.toolbelt import (
    tool_conform_lint,
    tool_conform_lint_xml,
    tool_explain_diagnostic,
    tool_find_examples,
    tool_id_registry,
    tool_render_spec,
    tool_schema_shape,
    tool_validate_config,
    tool_validate_xml,
)


def _dumps(payload: Any) -> str:
    return json.dumps(payload, indent=2, default=str)


def _exit_status(payload: Any) -> int:
    if not isinstance(payload, dict):
        return 0
    if payload.get("ok") is False:
        return 1
    if "error" in payload and payload.get("ok") is not True:
        return 1
    return 0


def _read_text(value: str | None) -> str:
    """Read ``-`` / omitted as stdin, an existing path as a file, else literal."""
    if value is None or value == "-":
        return sys.stdin.read()
    path = Path(value)
    if path.is_file():
        return path.read_text(encoding="utf-8")
    stripped = value.lstrip()
    if stripped[:1] in "{[<":
        return value
    raise FileNotFoundError(
        f"not a file, and not inline JSON/XML: {value!r}"
    )


def _read_json(value: str | None) -> Any:
    raw = _read_text(value)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        return {
            "ok": False,
            "error": f"JSON decode failed: {exc}",
            "validation_errors": [{
                "loc": ["data"],
                "msg": f"JSON decode failed: {exc}",
                "type": "json_error",
            }],
        }


def _parse_tiers(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    return [t.strip() for t in raw.split(",") if t.strip()]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fews-check",
        description=(
            "Render and validate Delft-FEWS XML. Always prints JSON. "
            "Skills must call this; do not Write XML with the editor."
        ),
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("schema-shape", help="Pinned Pydantic/XSD shape for a spec")
    p.add_argument("spec")

    p = sub.add_parser("render-spec", help="JSON → Jinja XML (read-only)")
    p.add_argument("spec")
    p.add_argument(
        "--data",
        required=True,
        help="JSON file, '-' for stdin, or inline object",
    )

    p = sub.add_parser("validate-xml", help="Gauntlet a pasted snippet")
    p.add_argument("--xml", required=True, help="XML file, '-' for stdin, or inline")
    p.add_argument("--spec", default=None)
    p.add_argument("--tiers", default=None)

    p = sub.add_parser("validate-config", help="Gauntlet a config folder")
    p.add_argument("path")
    p.add_argument("--tiers", default=None)

    p = sub.add_parser("admit", help="Write gate: XML lands only if ok")
    p.add_argument("path", help="Config folder (or session dir with project.yaml)")
    p.add_argument("--relpath", default=None, help="Relative path under the tree")
    p.add_argument("--xml", default=None, help="XML file, '-' for stdin, or inline")
    p.add_argument("--from-render", dest="from_render", default=None,
                   help="render-spec JSON file (uses xml + suggested_relpath)")
    p.add_argument("--spec", default=None)

    p = sub.add_parser("open-config", help="Ledger only; does not rewrite XML")
    p.add_argument("path")

    p = sub.add_parser("id-registry", help="Declared / unresolved IDs")
    p.add_argument("path")

    p = sub.add_parser("find-examples", help="Keyword search over the example corpus")
    p.add_argument("query")
    p.add_argument("-k", type=int, default=5)

    p = sub.add_parser("explain", help="Prose + fix_hint for a rule_id")
    p.add_argument("rule_id")

    p = sub.add_parser("conform-lint", help="Naming lint on a folder")
    p.add_argument("path")

    p = sub.add_parser("conform-lint-xml", help="Naming lint on a snippet")
    p.add_argument("--xml", required=True)
    p.add_argument("--spec", default=None)

    return parser


def _admit(args: argparse.Namespace) -> dict[str, Any]:
    spec = args.spec
    xml: str | None = None
    relpath = args.relpath
    if args.from_render:
        rendered = _read_json(args.from_render)
        if isinstance(rendered, dict) and rendered.get("ok") is False:
            return {
                "ok": False,
                "error": "admit: render-spec payload is not ok",
                "render": rendered,
            }
        if not isinstance(rendered, dict):
            return {"ok": False, "error": "admit: --from-render is not a JSON object"}
        xml = rendered.get("xml")
        relpath = relpath or rendered.get("suggested_relpath")
        spec = spec or rendered.get("spec")
    elif args.xml is not None:
        xml = _read_text(args.xml)
    else:
        return {
            "ok": False,
            "error": "admit: pass --xml or --from-render",
        }
    if not xml:
        return {"ok": False, "error": "admit: xml is empty"}
    if not relpath:
        return {
            "ok": False,
            "error": "admit: --relpath required (or suggested_relpath on --from-render)",
        }
    return tool_admit_file(args.path, relpath, xml, spec=spec)


def dispatch(args: argparse.Namespace) -> dict[str, Any]:
    cmd = args.cmd
    if cmd == "schema-shape":
        return tool_schema_shape(args.spec)
    if cmd == "render-spec":
        data = _read_json(args.data)
        if isinstance(data, dict) and data.get("type") == "json_error":
            data["spec"] = args.spec
            data["xml"] = ""
            data["suggested_relpath"] = None
            data["diagnostics"] = []
            return data
        return tool_render_spec(args.spec, data)
    if cmd == "validate-xml":
        return tool_validate_xml(
            _read_text(args.xml), spec=args.spec, tiers=_parse_tiers(args.tiers),
        )
    if cmd == "validate-config":
        return tool_validate_config(args.path, tiers=_parse_tiers(args.tiers))
    if cmd == "admit":
        return _admit(args)
    if cmd == "open-config":
        return open_config(args.path)
    if cmd == "id-registry":
        return tool_id_registry(args.path)
    if cmd == "find-examples":
        return tool_find_examples(args.query, k=args.k)
    if cmd == "explain":
        return tool_explain_diagnostic(args.rule_id)
    if cmd == "conform-lint":
        return tool_conform_lint(args.path)
    if cmd == "conform-lint-xml":
        return tool_conform_lint_xml(_read_text(args.xml), spec=args.spec)
    return {"error": f"unknown command {cmd!r}"}


def main(argv: Sequence[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    raw = [a for a in raw if a != "--json"]
    parser = _build_parser()
    try:
        args = parser.parse_args(raw)
    except SystemExit as exc:
        return int(exc.code or 0)
    try:
        payload = dispatch(args)
    except FileNotFoundError as exc:
        payload = {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 — CLI must never traceback to the agent
        payload = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    text = _dumps(payload)
    sys.stdout.write(text if text.endswith("\n") else text + "\n")
    return _exit_status(payload)


if __name__ == "__main__":
    raise SystemExit(main())
