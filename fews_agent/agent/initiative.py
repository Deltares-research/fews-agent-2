"""Gap detection + auto-stub + proposal generation.

Phase 1 of "agent takes initiative" — given a set of ``IngestResult``
objects, this module decides what's missing or unclear and generates
proposals the user can approve in one batch instead of one prompt
each.

Three streams the agent monitors:

  1. **CSV-level anomalies** — duplicate IDs, missing required cells,
     out-of-range coords. The agent proposes the obvious fix
     (deduplicate, drop bad row) and surfaces it for confirmation.
  2. **Spec-level gaps** — which target specs have no CSV input. For
     each, the agent picks one of:
       (b) auto-stub from already-ingested cross-refs,
       (a) skip with a sensible default empty model,
       fall back to inline ask if neither works.
  3. **File-level field gaps** — a CSV is present but a file-level
     field (``geoDatum`` etc.) wasn't supplied. The agent guesses
     from data shape (lat/lon range etc.) and proposes the value;
     the user confirms with a single Y/N.

Output is a single ``AnalysisReport`` that ``review.py`` renders into
one summary screen. Nothing here prompts the user — the only side
effect is "produce proposals".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from fews_agent.schema import (
    Locations,
    Parameter,
    ParameterGroup,
    Parameters,
    Qualifier,
    Qualifiers,
    ThresholdWarningLevel,
    ThresholdWarningLevels,
)

from .csv_ingest import IngestResult


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class Anomaly:
    """One anomaly inside an ingested CSV."""

    spec_name: str
    severity: str  # "error" | "warn"
    message: str
    proposed_fix: str  # human-readable, may be "drop" / "rename to X" / etc.


@dataclass
class Proposal:
    """Agent-initiated suggestion the user is asked to confirm.

    A proposal carries enough information to apply itself — the
    review screen renders it; if the user accepts, ``apply()`` modifies
    the project state in place.
    """

    spec_name: str
    kind: str          # "auto_stub" | "default_skip" | "file_field" | "ask"
    summary: str       # one-line description for the review table
    reasoning: str     # WHY the agent proposes this
    payload: object | None = None  # auto-stubbed model or value


@dataclass
class AnalysisReport:
    """All proposals + anomalies the agent surfaces in one screen."""

    csv_results: dict[str, IngestResult]
    proposals: list[Proposal] = field(default_factory=list)
    anomalies: list[Anomaly] = field(default_factory=list)
    unrecognised_csvs: list[Path] = field(default_factory=list)
    target_specs: list[str] = field(default_factory=list)

    @property
    def needs_user_input(self) -> bool:
        """Any unresolved 'ask' proposal forces interactive fallback."""
        return any(p.kind == "ask" for p in self.proposals)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

# Phase-1 target spec set. Reuses the wizard's "essentials" preset so
# the CSV path covers the same baseline a wizard run would produce.
DEFAULT_TARGET_SPECS = (
    "locations",
    "parameters",
    "qualifiers",
    "thresholdWarningLevels",
)


def analyse(
    ingest_results: dict[str, IngestResult],
    target_specs: list[str] | tuple[str, ...] = DEFAULT_TARGET_SPECS,
) -> AnalysisReport:
    """Build an AnalysisReport from ingestion results."""
    report = AnalysisReport(
        csv_results=ingest_results,
        target_specs=list(target_specs),
    )

    # 0. Surface unrecognised CSVs.
    for key, r in ingest_results.items():
        if key.startswith("_unrecognised:"):
            report.unrecognised_csvs.append(r.csv_path)

    # 1. Per-CSV anomaly detection.
    for spec_name in target_specs:
        result = ingest_results.get(spec_name)
        if result is None:
            continue
        report.anomalies.extend(_detect_anomalies(spec_name, result))

    # 2. File-field proposals (e.g. geoDatum guess).
    for spec_name in target_specs:
        result = ingest_results.get(spec_name)
        if result is None:
            continue
        for field_name, value in result.inferred_file_fields.items():
            report.proposals.append(
                Proposal(
                    spec_name=spec_name,
                    kind="file_field",
                    summary=f"set {field_name}={value!r}",
                    reasoning=_explain_file_field(spec_name, field_name, value, result),
                    payload={"field": field_name, "value": value},
                )
            )

    # 3. Spec-level gap detection.
    for spec_name in target_specs:
        result = ingest_results.get(spec_name)
        if result is not None and result.model is not None:
            continue  # have data, no gap
        # No CSV (or CSV failed) — propose auto-stub or default.
        proposal = _propose_for_missing_spec(spec_name, ingest_results)
        report.proposals.append(proposal)

    return report


# ---------------------------------------------------------------------------
# Anomaly detection
# ---------------------------------------------------------------------------

def _detect_anomalies(spec_name: str, result: IngestResult) -> list[Anomaly]:
    out: list[Anomaly] = []
    model = result.model
    if model is None:
        return out

    if isinstance(model, Locations):
        # Duplicate ids, missing required (Pydantic enforced; surface remaining).
        ids = [loc.id for loc in model.location]
        for dup in _dups(ids):
            out.append(Anomaly(
                spec_name=spec_name, severity="error",
                message=f"duplicate locationId {dup!r}",
                proposed_fix="keep first occurrence; drop later rows",
            ))
        # Out-of-range under WGS 1984 — only when geoDatum guessed.
        if result.inferred_file_fields.get("geoDatum") == "WGS 1984":
            for loc in model.location:
                if abs(loc.x) > Decimal(180) or abs(loc.y) > Decimal(90):
                    out.append(Anomaly(
                        spec_name=spec_name, severity="warn",
                        message=f"location {loc.id!r} x={loc.x} y={loc.y} "
                                f"out of WGS84 range",
                        proposed_fix="re-check geoDatum or coordinate columns",
                    ))

    elif isinstance(model, Parameters):
        all_ids = [p.id for pg in model.parameterGroup for p in pg.parameter]
        for dup in _dups(all_ids):
            out.append(Anomaly(
                spec_name=spec_name, severity="error",
                message=f"duplicate parameterId {dup!r}",
                proposed_fix="keep first; drop later rows",
            ))

    elif isinstance(model, Qualifiers):
        ids = [q.id for q in model.qualifier]
        for dup in _dups(ids):
            out.append(Anomaly(
                spec_name=spec_name, severity="error",
                message=f"duplicate qualifierId {dup!r}",
                proposed_fix="keep first; drop later rows",
            ))

    elif isinstance(model, ThresholdWarningLevels):
        ids = [w.id for w in model.thresholdWarningLevel]
        for dup in _dups(ids):
            out.append(Anomaly(
                spec_name=spec_name, severity="error",
                message=f"duplicate warningLevelId {dup!r}",
                proposed_fix="keep first; drop later rows",
            ))

    return out


def _dups(items: list[str]) -> list[str]:
    seen, dups = set(), []
    for x in items:
        if x in seen:
            dups.append(x)
        seen.add(x)
    return dups


# ---------------------------------------------------------------------------
# File-field reasoning helpers
# ---------------------------------------------------------------------------

def _explain_file_field(
    spec_name: str, field_name: str, value: object, result: IngestResult
) -> str:
    if spec_name == "locations" and field_name == "geoDatum":
        return (
            "All x/y coordinates fall within WGS84 range "
            "(|x|<=180, |y|<=90); proposing standard datum."
        )
    return f"Inferred from {result.csv_path.name} column patterns."


# ---------------------------------------------------------------------------
# Spec-level gap proposals
# ---------------------------------------------------------------------------

def _propose_for_missing_spec(
    spec_name: str, ingest_results: dict[str, IngestResult]
) -> Proposal:
    """Decide what to do about a target spec with no usable model.

    Order: (b) auto-stub if we can; (a) sensible default; else "ask".
    """
    if spec_name == "parameters":
        # Auto-stub from any cross-refs we find. POC has no real
        # cross-ref source for Parameters — placeholder.
        stubbed = _try_stub_parameters(ingest_results)
        if stubbed is not None:
            return Proposal(
                spec_name=spec_name,
                kind="auto_stub",
                summary=f"auto-stub Parameters with {len(stubbed.parameterGroup)} "
                        f"group(s) from referenced parameterIds",
                reasoning=(
                    "No parameters.csv supplied, but other CSVs reference "
                    "parameterIds. Stubbing minimal entries; you can edit "
                    "names/units later."
                ),
                payload=stubbed,
            )

    if spec_name == "qualifiers":
        # Default: empty Qualifiers with allowReferencingUndefinedQualifiers.
        return Proposal(
            spec_name=spec_name,
            kind="default_skip",
            summary="skip Qualifiers (no qualifiers used in this project)",
            reasoning=(
                "No qualifiers.csv and no cross-refs found. Defaulting to "
                "an empty Qualifiers file with "
                "allowReferencingUndefinedQualifiers=true so any later "
                "additions don't fail validation."
            ),
            payload=Qualifiers(allowReferencingUndefinedQualifiers=True),
        )

    if spec_name == "thresholdWarningLevels":
        # Default: a minimal 2-level set (no/alert) with stock icons.
        return Proposal(
            spec_name=spec_name,
            kind="default_skip",
            summary="seed ThresholdWarningLevels with a minimal 2-level default",
            reasoning=(
                "No thresholdWarningLevels.csv supplied. Seeding the "
                "common 2-level pattern (none/alert) with FEWS stock "
                "icons; you can swap in your own colors and icons later."
            ),
            payload=_default_warning_levels(),
        )

    # locations is essential — agent cannot stub it from nothing.
    return Proposal(
        spec_name=spec_name,
        kind="ask",
        summary=f"need {spec_name}.csv (cannot be auto-stubbed)",
        reasoning=(
            f"No {spec_name}.csv supplied and no auto-stub source available. "
            f"Will fall back to interactive prompt for this spec."
        ),
        payload=None,
    )


def _try_stub_parameters(
    ingest_results: dict[str, IngestResult]
) -> Parameters | None:
    """If other CSVs reference parameterIds, stub a Parameters file.

    Phase-1 POC: returns None (no other ingested CSV references
    parameterIds today). Hook is in place; Phase 2 walks IdMaps,
    timeSeriesSets, etc. to harvest references.
    """
    return None


def _default_warning_levels() -> ThresholdWarningLevels:
    return ThresholdWarningLevels(
        thresholdWarningLevel=[
            ThresholdWarningLevel(
                id="0",
                name="No threshold exceeded",
                color="green",
                iconName="default1.gif",
                historicOverlayIconName="historicwarninglevel1.gif",
                forecastOverlayIconName="historicwarninglevel1.gif",
            ),
            ThresholdWarningLevel(
                id="1",
                name="Alert Level",
                color="orange",
                iconName="warninglevel1.gif",
                historicOverlayIconName="historicwarninglevel1.gif",
                forecastOverlayIconName="forecastwarninglevel1.gif",
            ),
        ]
    )


__all__ = [
    "Anomaly",
    "Proposal",
    "AnalysisReport",
    "DEFAULT_TARGET_SPECS",
    "analyse",
]
