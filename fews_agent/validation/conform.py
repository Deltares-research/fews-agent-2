"""FEWS-Conform lint — house rules no XSD and no wiki encode.

Each rule has a stable ``rule_id``, a severity, a detector, a fix hint,
and a citation. Rules without a test derived from files in this repo
do not ship.

Severity: ``error`` only for things that break FEWS; ``warning`` for
portability (the IdImportGlobSnow casing bug); ``convention`` for
house style. The generation path must never auto-fix these — the
tutorial's known findings are *reported*, not rewritten.
"""
from __future__ import annotations

import csv
import io
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

from fews_agent.agent.csv_ingest import lint_conform_headers
from fews_agent.validation.diagnostic import Diagnostic
from fews_agent.validation.load_tree import LoadedFile, LoadedTree

_PARAM_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*(?:\.[A-Za-z0-9]+)?$")
_KNOWN_PARAM_SUFFIXES = frozenset({
    "nwp", "obs", "sim", "simulated", "forecast", "hist", "historical",
    "anal", "analysis",
})


@dataclass(frozen=True)
class ConformRule:
    rule_id: str
    severity: str
    title: str
    fix_hint: str
    citation: str
    detect: Callable[[LoadedTree], list[Diagnostic]]


def _local(tag: str) -> str:
    return tag.split("}", 1)[-1]


def _iter_text(data: bytes, element: str) -> list[str]:
    try:
        root = etree.fromstring(data)
    except etree.XMLSyntaxError:
        return []
    out: list[str] = []
    for el in root.iter():
        if _local(el.tag) == element and el.text and el.text.strip():
            out.append(el.text.strip())
    return out


def _root_id(data: bytes) -> str | None:
    try:
        root = etree.fromstring(data)
    except etree.XMLSyntaxError:
        return None
    value = root.get("id")
    return value.strip() if value else None


def _rule_csv_attr_pascal(tree: LoadedTree) -> list[Diagnostic]:
    """Lift of ``csv_ingest.lint_conform_headers`` over every CSV in the tree."""
    diags: list[Diagnostic] = []
    for path in sorted(tree.root.rglob("*.csv")):
        if any(p.startswith(".") for p in path.parts):
            continue
        rel = str(path.relative_to(tree.root)).replace("\\", "/")
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError:
            continue
        reader = csv.reader(io.StringIO(text))
        try:
            headers = next(reader)
        except StopIteration:
            continue
        headers = [h.strip() for h in headers]
        # Treat every column as a potential attributeId — reserved
        # aliases (id/lat/lon) produce no warning inside lint_conform_headers
        # only when they are *not* passed as attribute_headers. Pass
        # non-reserved-looking columns.
        reserved = {
            "id", "fewsid", "name", "lat", "latitude", "lon", "longitude",
            "x", "y", "z", "description", "parentlocationid",
            "parameterid", "unit", "parametertype",
        }
        attrs = [h for h in headers if h.strip().lower() not in reserved]
        for warn in lint_conform_headers(headers, attrs):
            diags.append(Diagnostic(
                file=rel,
                line=1,
                severity="convention",
                rule_id="conform.csv_attr_pascal",
                message=warn,
                fix_hint="Use PascalCase attributeIds with no spaces / _ / - / .",
                evidence=warn,
                tier="conform",
            ))
    return diags


def _rule_idmap_casing(tree: LoadedTree) -> list[Diagnostic]:
    """idMapId references that match a file stem only when case-folded.

    Tutorial seed: ImportGLOBSNOW.xml says ``IdImportGlobSnow`` but the
    declaring file is ``IdImportGLOBSNOW.xml`` — works on Windows, breaks
    on Linux FEWS. Citation: CLAUDE.md 'Known findings'.
    """
    stems: dict[str, str] = {}
    for f in tree.files:
        parts = [p.lower() for p in f.relpath.parts]
        if "idmapfiles" in parts or f.spec_name == "IdMap":
            stems[f.relpath.stem.lower()] = f.relpath.stem
    if not stems:
        # Also accept any xml stem starting with Id / idMap
        for f in tree.files:
            stem = f.relpath.stem
            if stem.lower().startswith("id"):
                stems[stem.lower()] = stem
    diags: list[Diagnostic] = []
    for f in tree.files:
        for ref in _iter_text(f.data, "idMapId"):
            key = ref.lower()
            declared = stems.get(key)
            if declared and declared != ref:
                diags.append(Diagnostic(
                    file=str(f.relpath).replace("\\", "/"),
                    line=None,
                    severity="warning",
                    rule_id="conform.idmap_casing",
                    message=(
                        f"idMapId {ref!r} does not match declaring file "
                        f"stem {declared!r} (case-only difference)"
                    ),
                    fix_hint=f"Change the reference to {declared!r} (or "
                    "rename the IdMap file) so Linux FEWS resolves it.",
                    evidence=f"{ref} vs {declared}",
                    tier="conform",
                ))
    return diags


def _rule_filename_id_agreement(tree: LoadedTree) -> list[Diagnostic]:
    """Root ``id`` attribute should match the file stem when both exist.

    Common FEWS convention for descriptors / topology / filters. Not
    every file has a root id — those are ignored.
    """
    diags: list[Diagnostic] = []
    for f in tree.files:
        rid = _root_id(f.data)
        if not rid:
            continue
        stem = f.relpath.stem
        if rid != stem:
            diags.append(Diagnostic(
                file=str(f.relpath).replace("\\", "/"),
                line=None,
                severity="warning",
                rule_id="conform.filename_id_agreement",
                message=f"root id {rid!r} does not match filename stem {stem!r}",
                fix_hint="Rename the file or the @id so they agree.",
                evidence=f"{rid} vs {stem}",
                tier="conform",
            ))
    return diags


def _rule_param_suffix(tree: LoadedTree) -> list[Diagnostic]:
    """Parameter ids should look like ``PC.nwp`` / ``TA.obs`` (quantity + source).

    Citation: FEWS-Conform / tutorial Parameters.xml convention. Only
    fires when a Parameters.xml (or parameterGroups) is present.
    """
    diags: list[Diagnostic] = []
    for f in tree.files:
        if f.spec_name != "Parameters" and f.relpath.name.lower() != "parameters.xml":
            continue
        try:
            root = etree.fromstring(f.data)
        except etree.XMLSyntaxError:
            continue
        for el in root.iter():
            if _local(el.tag) != "parameter":
                continue
            pid = el.get("id")
            if not pid:
                continue
            if not _PARAM_ID_RE.match(pid):
                diags.append(Diagnostic(
                    file=str(f.relpath).replace("\\", "/"),
                    line=None,
                    severity="convention",
                    rule_id="conform.param_suffix",
                    message=f"parameterId {pid!r} is not quantity[.suffix]",
                    fix_hint="Use a quantity + optional source suffix "
                    "(e.g. PC.nwp, TA.obs, Q.sim).",
                    evidence=pid,
                    tier="conform",
                ))
                continue
            if "." in pid:
                suffix = pid.rsplit(".", 1)[-1].lower()
                if suffix not in _KNOWN_PARAM_SUFFIXES and not suffix.isalnum():
                    diags.append(Diagnostic(
                        file=str(f.relpath).replace("\\", "/"),
                        line=None,
                        severity="convention",
                        rule_id="conform.param_suffix",
                        message=f"parameterId {pid!r} has an unusual suffix",
                        fix_hint="Common suffixes: nwp, obs, sim, forecast.",
                        evidence=pid,
                        tier="conform",
                    ))
    return diags


RULES: list[ConformRule] = [
    ConformRule(
        rule_id="conform.csv_attr_pascal",
        severity="convention",
        title="CSV attribute headers are PascalCase attributeIds",
        fix_hint="Use PascalCase attributeIds with no spaces / _ / - / .",
        citation="fews_agent/agent/csv_ingest.py::lint_conform_headers "
        "(FEWS-Conform csvFile convention)",
        detect=_rule_csv_attr_pascal,
    ),
    ConformRule(
        rule_id="conform.idmap_casing",
        severity="warning",
        title="idMapId must match the IdMap filename stem exactly",
        fix_hint="Align idMapId with the IdMapFiles stem (Linux-safe).",
        citation="CLAUDE.md Known findings — IdImportGlobSnow vs "
        "IdImportGLOBSNOW",
        detect=_rule_idmap_casing,
    ),
    ConformRule(
        rule_id="conform.filename_id_agreement",
        severity="warning",
        title="Root @id agrees with the filename stem",
        fix_hint="Rename the file or the @id so they agree.",
        citation="FEWS convention: descriptors / filters / topology ids "
        "match their filename",
        detect=_rule_filename_id_agreement,
    ),
    ConformRule(
        rule_id="conform.param_suffix",
        severity="convention",
        title="parameterId uses quantity[.source] form",
        fix_hint="e.g. PC.nwp, TA.obs, Q.sim",
        citation="examples/config-tutorial Parameters.xml + FEWS-Conform "
        "parameter naming",
        detect=_rule_param_suffix,
    ),
]

RULES_BY_ID: dict[str, ConformRule] = {r.rule_id: r for r in RULES}


def lint_tree(tree: LoadedTree) -> list[Diagnostic]:
    out: list[Diagnostic] = []
    for rule in RULES:
        out.extend(rule.detect(tree))
    return out


def lint_xml_bytes(loaded: LoadedFile) -> list[Diagnostic]:
    """Conform rules that can fire on a single snippet (no folder)."""
    fake = LoadedTree(root=Path("."), files=[loaded])
    # CSV rule needs a real tree; filename/id and param suffix can run.
    out: list[Diagnostic] = []
    out.extend(_rule_filename_id_agreement(fake))
    out.extend(_rule_param_suffix(fake))
    out.extend(_rule_idmap_casing(fake))
    return out


def explain_rule(rule_id: str) -> dict[str, str] | None:
    rule = RULES_BY_ID.get(rule_id)
    if rule is None:
        return None
    return {
        "rule_id": rule.rule_id,
        "severity": rule.severity,
        "title": rule.title,
        "fix_hint": rule.fix_hint,
        "citation": rule.citation,
    }
