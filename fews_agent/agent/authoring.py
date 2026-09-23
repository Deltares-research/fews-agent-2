"""Open-world file authoring behind the verification gauntlet.

The host LLM (or our own provider) proposes XML; ``validate_xml`` /
``validate_config`` decide whether it may land on disk. One capped
repair round, then a loud fail — same shape as ``filter_drafter``.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fews_agent.agent import prompts
from fews_agent.agent.ledger import Ledger, load_ledger
from fews_agent.validation.diagnostic import Diagnostic
from fews_agent.validation.examples import find_examples
from fews_agent.validation.gauntlet import validate_config, validate_xml
from fews_agent.validation.schema_shape import schema_shape
from fews_agent.validation.toolbelt import tool_id_registry

_logger = logging.getLogger(__name__)

_AUTHOR_SCHEMA = {
    "type": "object",
    "properties": {"xml": {"type": "string"}},
    "required": ["xml"],
}


@dataclass
class AuthoredFile:
    relpath: str
    content: str
    diagnostics: list[Diagnostic] = field(default_factory=list)
    verified: list[str] = field(default_factory=list)
    ok: bool = False
    error: str = ""


def _schema_digest(spec: str) -> str:
    try:
        shape = schema_shape(spec)
    except KeyError as exc:
        return f"(unknown spec: {exc})"
    req = ", ".join(shape.get("required") or []) or "(none listed)"
    xsd = shape.get("xsd_rel") or "?"
    return f"required={req}; xsd={xsd}"


def _id_digest(tree_path: Path | None) -> str:
    if tree_path is None or not Path(tree_path).is_dir():
        return "(no config tree)"
    reg = tool_id_registry(str(tree_path))
    declared = reg.get("declared") or {}
    parts = [f"{k}: {', '.join(v[:12])}" for k, v in sorted(declared.items())]
    return "\n".join(parts) or "(empty)"


def _examples_digest(request: str, spec: str) -> str:
    hits = find_examples(f"{spec} {request}", k=2)
    if not hits:
        return "(none)"
    blocks = []
    for h in hits:
        blocks.append(f"# {h['path']} ({h['provenance']})\n{h['snippet'][:800]}")
    return "\n\n".join(blocks)


def _extract_xml(raw: Any) -> str | None:
    if isinstance(raw, dict) and isinstance(raw.get("xml"), str):
        text = raw["xml"].strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("xml"):
                text = text[3:].lstrip()
        return text or None
    return None


def author_file(
    request: str,
    *,
    spec: str,
    relpath: str = "-",
    tree_path: Path | None = None,
    provider: Any | None = None,
    max_repairs: int = 1,
) -> AuthoredFile:
    """Ask ``provider`` for XML, then run the gauntlet. Never writes."""
    result = AuthoredFile(relpath=relpath, content="")
    if provider is None or not hasattr(provider, "generate_json"):
        result.error = "author_file: no structured-output provider"
        return result

    repair_errors = ""
    attempts = 1 + max(0, int(max_repairs))
    last_xml = ""
    for attempt in range(attempts):
        system = prompts.load("author_file.system")
        user = prompts.load(
            "author_file.user",
            request=request,
            spec=spec,
            relpath=relpath,
            schema_digest=_schema_digest(spec),
            id_digest=_id_digest(tree_path),
            examples_digest=_examples_digest(request, spec),
            repair_errors=repair_errors,
        )
        try:
            resp = provider.generate_json(
                system=system, user=user, schema=_AUTHOR_SCHEMA,
            )
            xml = _extract_xml(getattr(resp, "data", None) or {})
        except Exception as exc:  # noqa: BLE001
            _logger.warning("author_file provider failed: %s", exc)
            result.error = f"author_file: provider failed ({type(exc).__name__})"
            return result
        if not xml:
            result.error = "author_file: model returned no xml"
            return result
        last_xml = xml
        report = validate_xml(xml, spec=spec, tiers=["xsd", "conform"])
        result.diagnostics = list(report.diagnostics)
        if report.ok:
            result.content = xml
            result.ok = True
            result.verified = ["xsd", "conform"]
            if tree_path is not None:
                # Cross-file check after a tentative write is the caller's
                # job; we only confirm the snippet shape here.
                pass
            return result
        repair_errors = "\n".join(
            f"{d.rule_id}: {d.message}" for d in report.errors
        ) or "validation failed"
        if attempt + 1 >= attempts:
            break
    result.content = last_xml
    result.error = "author_file: gauntlet rejected the draft after repair"
    return result


def write_authored(
    tree_path: Path,
    authored: AuthoredFile,
    *,
    ledger: Ledger | None = None,
) -> Path | None:
    """Write a passing authored file and mark the ledger ``origin: llm``.

    Refuses to write on failed gauntlet or over a human/llm file.
    """
    if not authored.ok:
        return None
    root = Path(tree_path)
    rel = authored.relpath.replace("\\", "/").lstrip("/")
    if rel in {"", "-"}:
        return None
    dest = root / rel
    ledger = ledger or load_ledger(root)
    ok, reason = ledger.may_overwrite(rel)
    if not ok:
        authored.error = f"author_file: not written ({reason})"
        authored.ok = False
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    data = authored.content.encode("utf-8")
    dest.write_bytes(data)
    ledger.mark_llm(rel, data, authored.verified)
    ledger.save()
    # Folder-level gauntlet (xsd+semantic+conform) after write — if it
    # introduces new *errors* we keep the file (the snippet itself passed)
    # but attach diagnostics. Never silently delete.
    folder = validate_config(root, tiers=["xsd", "semantic", "conform"])
    authored.diagnostics.extend(folder.diagnostics)
    return dest
