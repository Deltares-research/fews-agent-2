"""Verification gauntlet — XSD → semantic → conform → FEWS check.

Each tier is independently skippable. A missing backend emits a skip
diagnostic and never crashes. Host adapters (MCP / HTTP) only serialize
the ``GauntletReport``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

from fews_agent.validation.diagnostic import Diagnostic, GauntletReport
from fews_agent.validation.fews_check import run_fews_check
from fews_agent.validation.load_tree import LoadedFile, load_tree, load_xml_bytes
from fews_agent.validation.semantic import validate_semantic
from fews_agent.validation.xsd import validate_xsd

DEFAULT_TIERS: tuple[str, ...] = ("xsd", "semantic", "conform", "fews_check")
_KNOWN_TIERS = frozenset(DEFAULT_TIERS)


def _normalize_tiers(tiers: Sequence[str] | None) -> list[str]:
    if not tiers:
        return list(DEFAULT_TIERS)
    out: list[str] = []
    for t in tiers:
        name = str(t).strip().lower()
        if name not in _KNOWN_TIERS:
            raise ValueError(
                f"unknown gauntlet tier {t!r}; valid: {sorted(_KNOWN_TIERS)}"
            )
        if name not in out:
            out.append(name)
    return out


def _xsd_diagnostics(files: Iterable[LoadedFile]) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    for f in files:
        rel = str(f.relpath).replace("\\", "/")
        ok, msg = f.xsd_ok, f.xsd_message
        # Re-validate if the loaded file was built without running xsd
        # (defensive — load_tree already ran it).
        if not msg:
            ok, msg = validate_xsd(f.data)
        if ok:
            continue
        line = None
        # lxml messages often look like ``<string>:12:0:ERROR:...``
        for part in str(msg).split(":"):
            if part.strip().isdigit():
                line = int(part.strip())
                break
        diags.append(Diagnostic(
            file=rel,
            line=line,
            severity="error",
            rule_id="xsd.schema",
            message=str(msg),
            fix_hint="Fix element order / required children against the "
            "pinned XSD (xsd:sequence).",
            evidence=str(msg),
            tier="xsd",
        ))
    return diags


def _semantic_diagnostics(tree_files: list[LoadedFile]) -> list[Diagnostic]:
    from fews_agent.schema.generic_xml_file import GenericXmlFile

    loaded = []
    for f in tree_files:
        if f.model is None or isinstance(f.model, GenericXmlFile):
            continue
        loaded.append((f.spec_name or type(f.model).__name__, f.model, f.relpath))
    if not loaded:
        return [Diagnostic(
            file="-",
            line=None,
            severity="skip",
            rule_id="semantic.no_models",
            message="No typed models loaded — semantic ID walk skipped.",
            tier="semantic",
        )]
    report = validate_semantic(loaded)
    diags: list[Diagnostic] = []
    for ref in report.unresolved:
        file_part, _, path = ref.source.partition(":")
        diags.append(Diagnostic(
            file=file_part.replace("\\", "/"),
            line=None,
            severity="error",
            rule_id="semantic.unresolved",
            message=(
                f"{ref.value} ({ref.id_type_name}) is referenced but not "
                f"declared ({path})"
            ),
            fix_hint="Declare this ID in the owning file (or fix the typo / "
            "casing).",
            evidence=ref.source,
            tier="semantic",
        ))
    return diags


def validate_config(
    path: str | Path,
    tiers: Sequence[str] | None = None,
) -> GauntletReport:
    """Run selected tiers over a FEWS config folder."""
    root = Path(path)
    chosen = _normalize_tiers(tiers)
    report = GauntletReport(path=str(root), tiers_run=chosen)
    tree = load_tree(root)
    report.files_checked = len(tree.files)
    report.diagnostics.extend(tree.diagnostics)

    if "xsd" in chosen:
        report.diagnostics.extend(_xsd_diagnostics(tree.files))
    if "semantic" in chosen:
        report.diagnostics.extend(_semantic_diagnostics(tree.files))
    if "conform" in chosen:
        from fews_agent.validation.conform import lint_tree
        report.diagnostics.extend(lint_tree(tree))
    if "fews_check" in chosen:
        report.diagnostics.extend(run_fews_check(root))
    return report


def validate_xml(
    xml: str,
    spec: str | None = None,
    tiers: Sequence[str] | None = None,
) -> GauntletReport:
    """Validate a single XML snippet (no folder). Semantic is skipped
    unless the snippet alone can load a typed model — a lone file cannot
    resolve cross-file IDs, so we only run XSD (+ optional conform on
    the snippet bytes)."""
    chosen = _normalize_tiers(tiers)
    # A snippet has no siblings — drop semantic / fews_check unless asked
    # and they can no-op usefully.
    report = GauntletReport(path="-", tiers_run=chosen)
    loaded = load_xml_bytes(xml, spec=spec)
    report.files_checked = 1
    if "xsd" in chosen:
        report.diagnostics.extend(_xsd_diagnostics([loaded]))
    if "semantic" in chosen:
        report.diagnostics.append(Diagnostic(
            file="-",
            line=None,
            severity="skip",
            rule_id="semantic.snippet",
            message="Cross-file semantic check needs a config folder "
            "(use validate_config).",
            tier="semantic",
        ))
    if "conform" in chosen:
        from fews_agent.validation.conform import lint_xml_bytes
        report.diagnostics.extend(lint_xml_bytes(loaded))
    if "fews_check" in chosen:
        report.diagnostics.append(Diagnostic(
            file="-",
            line=None,
            severity="skip",
            rule_id="fews.snippet",
            message="Headless FEWS check needs a config folder.",
            tier="fews_check",
        ))
    return report
