"""Read-only walk of a FEWS config tree into typed models + bytes.

Gives ``validate_semantic`` the ``(spec, model, relpath)`` triples the
build runner already has after render, but for *any* on-disk folder —
including one this agent never created.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lxml import etree
from pydantic import BaseModel

from fews_agent.agent.blueprint import schema_class_for
from fews_agent.pattern_farm.xml_ingest import _element_to_value, parse_xml
from fews_agent.schema.generic_xml_file import GenericXmlFile
from fews_agent.validation.diagnostic import Diagnostic
from fews_agent.validation.xsd import _xsd_rel_from_hint, validate_xsd

# Folders we never descend into while walking a config (or a session dir
# that happens to contain one).
_SKIP_DIRS = frozenset({
    ".git", ".fews-agent", "__pycache__", ".venv", "node_modules",
    ".pytest_cache",
})


@dataclass
class LoadedFile:
    """One XML file from a config tree."""

    relpath: Path
    data: bytes
    spec_name: str | None
    model: BaseModel | None
    xsd_ok: bool
    xsd_message: str


@dataclass
class LoadedTree:
    """A FEWS config folder after a read-only walk."""

    root: Path
    files: list[LoadedFile] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def models_for_semantic(self) -> list[tuple[str, BaseModel, Path]]:
        """Triples ``validate_semantic`` accepts. Generic-body files with
        no typed model are omitted (the walker cannot see their IDs)."""
        out: list[tuple[str, BaseModel, Path]] = []
        for f in self.files:
            if f.model is None:
                continue
            if isinstance(f.model, GenericXmlFile):
                continue
            out.append((f.spec_name or type(f.model).__name__, f.model, f.relpath))
        return out


def _class_name_from_token(token: str) -> str:
    """``timeSeriesImportRun`` / ``timeSeriesImportRun.xsd`` → class name."""
    stem = Path(token).stem
    if not stem:
        return ""
    return stem[0].upper() + stem[1:]


def guess_schema_class(xml_bytes: bytes, relpath: Path | None = None) -> type:
    """Best-effort Pydantic class for one XML document.

    Order: ``xsi:schemaLocation`` basename → root element localname →
    ``GenericXmlFile``. Unknown names never raise; the generic body is
    the safe fallback (typed parse is attempted only when the class is
    registered in SPECS).
    """
    xsd_rel = _xsd_rel_from_hint(xml_bytes)
    if xsd_rel:
        name = _class_name_from_token(xsd_rel)
        try:
            return schema_class_for(name)
        except KeyError:
            pass
    try:
        root = etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError:
        return GenericXmlFile
    tag = root.tag.split("}", 1)[-1]
    name = _class_name_from_token(tag)
    if name:
        try:
            return schema_class_for(name)
        except KeyError:
            pass
    if relpath is not None:
        parts = [p.lower() for p in relpath.parts]
        if "workflowfiles" in parts or "workflows" in parts:
            try:
                return schema_class_for("Workflow")
            except KeyError:
                pass
        if "idmapfiles" in parts:
            try:
                return schema_class_for("IdMap")
            except KeyError:
                pass
    return GenericXmlFile


def _parse_model(
    path: Path, cls: type, xml_bytes: bytes,
) -> tuple[BaseModel | None, Diagnostic | None]:
    if cls is GenericXmlFile:
        try:
            root = etree.fromstring(xml_bytes)
            raw = _element_to_value(root)
            body: Any = raw if isinstance(raw, (dict, list)) else []
            return GenericXmlFile(body=body), None
        except Exception as exc:  # noqa: BLE001
            return None, Diagnostic(
                file=str(path.name),
                line=None,
                severity="warning",
                rule_id="load.parse",
                message=f"generic parse failed: {exc}",
                tier="xsd",
            )
    try:
        data = parse_xml(path, cls)
        return cls.model_validate(data), None
    except Exception as exc:  # noqa: BLE001
        return None, Diagnostic(
            file=str(path.name),
            line=None,
            severity="warning",
            rule_id="load.schema",
            message=f"typed parse as {cls.__name__} failed: {exc}",
            fix_hint="File still XSD-checked; semantic IDs from this file "
            "are skipped.",
            evidence=cls.__name__,
            tier="xsd",
        )


def load_tree(root: Path) -> LoadedTree:
    """Walk ``root`` for ``*.xml`` and parse what we can.

    Never writes. A parse failure is a diagnostic, not an exception —
    XSD bytes are still kept so the gauntlet can report shape errors.
    """
    root = Path(root).resolve()
    tree = LoadedTree(root=root)
    if not root.is_dir():
        tree.diagnostics.append(Diagnostic(
            file=str(root),
            line=None,
            severity="error",
            rule_id="load.missing",
            message=f"config path is not a directory: {root}",
            tier="xsd",
        ))
        return tree

    for path in sorted(root.rglob("*.xml")):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        rel = path.relative_to(root)
        try:
            data = path.read_bytes()
        except OSError as exc:
            tree.diagnostics.append(Diagnostic(
                file=str(rel).replace("\\", "/"),
                line=None,
                severity="error",
                rule_id="load.read",
                message=str(exc),
                tier="xsd",
            ))
            continue
        xsd_ok, xsd_msg = validate_xsd(data)
        cls = guess_schema_class(data, rel)
        model, parse_diag = _parse_model(path, cls, data)
        spec_name = None if cls is GenericXmlFile else cls.__name__
        tree.files.append(LoadedFile(
            relpath=rel,
            data=data,
            spec_name=spec_name,
            model=model,
            xsd_ok=xsd_ok,
            xsd_message=xsd_msg,
        ))
        if parse_diag is not None:
            tree.diagnostics.append(Diagnostic(
                file=str(rel).replace("\\", "/"),
                line=parse_diag.line,
                severity=parse_diag.severity,
                rule_id=parse_diag.rule_id,
                message=parse_diag.message,
                fix_hint=parse_diag.fix_hint,
                evidence=parse_diag.evidence,
                tier=parse_diag.tier,
            ))
    return tree


def load_xml_bytes(xml: str | bytes, spec: str | None = None) -> LoadedFile:
    """Parse a single snippet (no folder). ``file`` is ``-``."""
    data = xml.encode("utf-8") if isinstance(xml, str) else xml
    xsd_ok, xsd_msg = validate_xsd(data)
    if spec:
        try:
            cls = schema_class_for(spec)
        except KeyError:
            cls = guess_schema_class(data)
    else:
        cls = guess_schema_class(data)
    # parse_xml wants a path; write is avoided — use a dummy Path name
    # only for error messages, and parse from bytes via a temp-less path
    # by calling the generic walker + model_validate directly.
    model: BaseModel | None = None
    if cls is GenericXmlFile:
        try:
            root = etree.fromstring(data)
            raw = _element_to_value(root)
            body: Any = raw if isinstance(raw, (dict, list)) else []
            model = GenericXmlFile(body=body)
        except Exception:
            model = None
    else:
        try:
            root = etree.fromstring(data)
            raw = _element_to_value(root)
            if not isinstance(raw, dict):
                raw = {"__root__": raw}
            from fews_agent.pattern_farm.xml_ingest import _normalize_for_schema
            normalized = _normalize_for_schema(raw, cls)
            model = cls.model_validate(normalized)
        except Exception:
            model = None
    spec_name = None if cls is GenericXmlFile else cls.__name__
    return LoadedFile(
        relpath=Path("-"),
        data=data,
        spec_name=spec_name,
        model=model,
        xsd_ok=xsd_ok,
        xsd_message=xsd_msg,
    )
