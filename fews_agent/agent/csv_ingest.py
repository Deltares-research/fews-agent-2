"""CSV ingestion — drop folder of CSVs, get typed Pydantic models.

Phase-1 POC: the agent recognises four canonical CSVs by filename and
maps their columns into the matching Pydantic root model. The user
authors CSVs once; the agent does the XML conversion.

Recognised CSVs (case-insensitive filename match):

  - ``locations.csv``                  → ``schema.Locations``
  - ``parameters.csv``                 → ``schema.Parameters``
  - ``qualifiers.csv``                 → ``schema.Qualifiers``
  - ``thresholdwarninglevels.csv``     → ``schema.ThresholdWarningLevels``
    (also ``warninglevels.csv``)

Column aliases live in ``_COLUMN_ALIASES`` per spec — the alias table
is intentionally small and explicit (POC). Phase 2 will add fuzzy /
LLM-assisted column mapping for arbitrary CSV layouts.

The ingestor never asks the user. Anything that can't be mapped is
returned as an ``IngestResult`` warning and bubbles up to
``initiative.py`` which decides whether to auto-stub, propose a
default, or fall back to interactive ask.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fews_agent.schema import (
    Locations,
    Location,
    Parameter,
    ParameterGroup,
    Parameters,
    Qualifier,
    Qualifiers,
    ThresholdWarningLevel,
    ThresholdWarningLevels,
)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class IngestResult:
    """Outcome of parsing one CSV file."""

    csv_path: Path
    spec_name: str | None  # None if the CSV couldn't be recognised
    rows_parsed: int
    rows_failed: int
    column_mapping: dict[str, str]  # original_header → field_name | "_unmapped"
    unknown_headers: list[str]
    model: object | None  # Pydantic root model on success, else None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # Per-spec extras the ingestor inferred (e.g. the geoDatum guess for
    # locations) — initiative.py reads these as proposals.
    inferred_file_fields: dict[str, object] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Filename → spec mapping (case-insensitive)
# ---------------------------------------------------------------------------

_FILENAME_TO_SPEC: dict[str, str] = {
    "locations.csv": "locations",
    "parameters.csv": "parameters",
    "qualifiers.csv": "qualifiers",
    "thresholdwarninglevels.csv": "thresholdWarningLevels",
    "warninglevels.csv": "thresholdWarningLevels",
}


# ---------------------------------------------------------------------------
# Column aliases per spec (lowercase; first match wins)
# ---------------------------------------------------------------------------

# Pattern: target_field → list of accepted header names (lowercase).
_COLUMN_ALIASES: dict[str, dict[str, list[str]]] = {
    "locations": {
        "id":             ["id", "locationid", "location_id", "code", "fewsid"],
        "name":           ["name", "locationname", "label"],
        "x":              ["x", "lng", "lon", "longitude"],
        "y":              ["y", "lat", "latitude"],
        "z":              ["z", "altitude", "elevation", "alt"],
        "description":    ["description", "desc"],
        "shortName":      ["shortname", "short_name", "short"],
        "parentLocationId": ["parentlocationid", "parent", "parent_id"],
    },
    "parameters": {
        "id":             ["id", "parameterid", "parameter_id", "code"],
        "name":           ["name", "parametername"],
        "shortName":      ["shortname", "short_name", "short"],
        "description":    ["description", "desc"],
        "valueResolution": ["valueresolution", "resolution"],
        "valueResolutionUnit": ["valueresolutionunit", "resolution_unit"],
        "allowMissing":   ["allowmissing", "allow_missing"],
        # group-level columns (read once per group from the first row)
        "group":          ["group", "parametergroup", "parametergroupid", "parameter_group"],
        "groupName":      ["groupname", "parametergroupname", "parameter_group_name"],
        "unit":           ["unit", "units"],
        "displayUnit":    ["displayunit", "display_unit"],
        "parameterType":  ["parametertype", "type"],
        "usesDatum":      ["usesdatum", "uses_datum"],
    },
    "qualifiers": {
        "id":             ["id", "qualifierid", "qualifier_id", "code"],
        "name":           ["name", "qualifiername"],
        "shortName":      ["shortname", "short_name", "short"],
        "description":    ["description", "desc"],
        "group":          ["group", "qualifiergroup"],
    },
    "thresholdWarningLevels": {
        "id":             ["id", "warninglevelid", "warning_level_id"],
        "name":           ["name", "warningname"],
        "color":          ["color", "colour"],
        "iconName":       ["iconname", "icon", "icon_name"],
        "historicOverlayIconName": [
            "historicoverlayiconname", "historic_icon",
            "historicicon", "historic_overlay_icon",
        ],
        "forecastOverlayIconName": [
            "forecastoverlayiconname", "forecast_icon",
            "forecasticon", "forecast_overlay_icon",
        ],
        "opaquenessPercentage": ["opaquenesspercentage", "opacity"],
    },
}


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def ingest_directory(inputs_dir: Path) -> dict[str, IngestResult]:
    """Walk ``inputs_dir`` and ingest every recognised CSV.

    Returns a dict keyed by spec_name. CSVs whose filename doesn't match
    any known pattern are still returned (under their stem) but flagged
    with ``spec_name=None`` so initiative.py can flag them.
    """
    if not inputs_dir.is_dir():
        raise FileNotFoundError(f"inputs dir does not exist: {inputs_dir}")

    out: dict[str, IngestResult] = {}
    for path in sorted(inputs_dir.glob("*.csv")):
        result = ingest_csv(path)
        key = result.spec_name or f"_unrecognised:{path.stem}"
        out[key] = result
    return out


def ingest_csv(path: Path) -> IngestResult:
    """Recognise one CSV by filename, map columns, parse rows."""
    spec_name = _FILENAME_TO_SPEC.get(path.name.lower())
    if spec_name is None:
        return IngestResult(
            csv_path=path,
            spec_name=None,
            rows_parsed=0,
            rows_failed=0,
            column_mapping={},
            unknown_headers=[],
            model=None,
            errors=[
                f"filename '{path.name}' doesn't match any recognised CSV "
                f"({', '.join(sorted(_FILENAME_TO_SPEC))})"
            ],
        )

    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            return IngestResult(
                csv_path=path,
                spec_name=spec_name,
                rows_parsed=0,
                rows_failed=0,
                column_mapping={},
                unknown_headers=[],
                model=None,
                errors=["CSV has no header row"],
            )
        headers = list(reader.fieldnames)
        rows = list(reader)

    column_mapping, unknown_headers = _map_headers(spec_name, headers)
    builder = _BUILDERS[spec_name]
    result = builder(
        path, spec_name, headers, rows, column_mapping, unknown_headers
    )
    # Advisory Conform lint. For locations the unmapped columns become
    # location attributeIds (csvFile convention), so lint them; for other
    # specs only the duplicate-header check applies.
    attribute_headers = unknown_headers if spec_name == "locations" else []
    result.warnings.extend(lint_conform_headers(headers, attribute_headers))
    return result


# ---------------------------------------------------------------------------
# Header → field mapping
# ---------------------------------------------------------------------------

# A valid FEWS attributeId: starts with a letter, then letters/digits only.
# Conform additionally asks for PascalCase (leading upper). Spaces,
# underscores, hyphens and dots are all disallowed in an attributeId.
_ATTR_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*$")


def lint_conform_headers(
    headers: list[str], attribute_headers: list[str],
) -> list[str]:
    """Advisory FEWS-Conform lint of a CSV's column headers.

    Two checks, both pure and side-effect-free:

    1. **Duplicate headers** (case-insensitive) anywhere in the CSV —
       these collide as attributeIds / column references.
    2. **``attribute_headers``** (the columns that become location
       ``attributeId``s via the csvFile convention — i.e. the ingest's
       *unmapped* columns) must be valid PascalCase attributeIds: no
       spaces / ``_`` / ``-`` / ``.``, and a leading uppercase letter
       (``GFS`` → ``Gfs`` is a separate value-casing rule, not checked
       here).

    Returns a list of human-readable warning strings (empty = clean).
    Reserved/mapped columns (``id``, ``lat``, ...) are intentionally
    *not* flagged for casing — the ingest maps them by alias regardless
    of case, so a minimal lowercase CSV produces zero warnings.
    """
    warnings: list[str] = []

    seen: dict[str, list[str]] = {}
    for h in headers:
        seen.setdefault(h.strip().lower(), []).append(h.strip())
    for group in seen.values():
        if len(group) > 1:
            warnings.append(
                f"duplicate column header {group[0]!r} "
                f"(x{len(group)}, case-insensitive) — attributeIds must be unique"
            )

    for h in attribute_headers:
        name = h.strip()
        # _map_headers reports duplicates as "H (duplicates F)"; the dup
        # check above already covers those, so skip the annotated form.
        if not name or "(" in name:
            continue
        if not _ATTR_ID_RE.match(name):
            warnings.append(
                f"column {name!r} becomes a location attributeId but isn't a "
                f"valid one (no spaces / _ / - / . ; must start with a letter)"
            )
        elif not name[0].isupper():
            suggestion = name[0].upper() + name[1:]
            warnings.append(
                f"column {name!r} should be PascalCase for FEWS-Conform "
                f"(e.g. {suggestion!r})"
            )

    return warnings


def _map_headers(
    spec_name: str, headers: list[str]
) -> tuple[dict[str, str], list[str]]:
    """Return (header→field_name, unknown_headers)."""
    aliases = _COLUMN_ALIASES[spec_name]
    # invert: alias_lower → field_name
    inv: dict[str, str] = {}
    for field_name, alias_list in aliases.items():
        # Field name itself is always accepted (case-insensitive).
        inv[field_name.lower()] = field_name
        for a in alias_list:
            inv[a.lower()] = field_name

    mapping: dict[str, str] = {}
    unknown: list[str] = []
    used_fields: set[str] = set()
    for h in headers:
        key = h.strip().lower()
        target = inv.get(key)
        if target is None:
            mapping[h] = "_unmapped"
            unknown.append(h)
        elif target in used_fields:
            # Two columns aliased to the same field — keep first, flag rest.
            mapping[h] = "_duplicate"
            unknown.append(f"{h} (duplicates {target})")
        else:
            mapping[h] = target
            used_fields.add(target)
    return mapping, unknown


def _row_field(row: dict, mapping: dict[str, str], field_name: str) -> str | None:
    """Pick the value from ``row`` for ``field_name`` using ``mapping``."""
    for original, target in mapping.items():
        if target == field_name:
            value = row.get(original)
            if value is None:
                return None
            value = str(value).strip()
            return value or None
    return None


# ---------------------------------------------------------------------------
# Per-spec builders
# ---------------------------------------------------------------------------

def _decimal_or_none(s: str | None) -> Decimal | None:
    if s is None or s == "":
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        raise ValueError(f"not a number: {s!r}")


def _build_locations(
    path: Path,
    spec_name: str,
    headers: list[str],
    rows: list[dict],
    column_mapping: dict[str, str],
    unknown_headers: list[str],
) -> IngestResult:
    locations: list[Location] = []
    rows_failed = 0
    errors: list[str] = []

    for i, row in enumerate(rows, start=2):  # row 1 = header
        try:
            loc = Location(
                id=_row_field(row, column_mapping, "id") or "",
                name=_row_field(row, column_mapping, "name") or "",
                x=_decimal_or_none(_row_field(row, column_mapping, "x")) or Decimal(0),
                y=_decimal_or_none(_row_field(row, column_mapping, "y")) or Decimal(0),
                z=_decimal_or_none(_row_field(row, column_mapping, "z")),
                description=_row_field(row, column_mapping, "description"),
                shortName=_row_field(row, column_mapping, "shortName"),
                parentLocationId=_row_field(
                    row, column_mapping, "parentLocationId"
                ),
            )
            locations.append(loc)
        except Exception as e:
            rows_failed += 1
            errors.append(f"row {i}: {e}")

    # Heuristic geoDatum: if all x/y look like lon/lat (|x|<=180, |y|<=90)
    # → propose WGS 1984; else leave for initiative to ask.
    inferred: dict[str, object] = {}
    if locations:
        if all(
            abs(loc.x) <= Decimal(180) and abs(loc.y) <= Decimal(90)
            for loc in locations
        ):
            inferred["geoDatum"] = "WGS 1984"

    model: Locations | None = None
    if locations:
        try:
            model = Locations(
                geoDatum=str(inferred.get("geoDatum", "WGS 1984")),
                location=locations,
            )
        except Exception as e:
            errors.append(f"root model: {e}")

    return IngestResult(
        csv_path=path,
        spec_name=spec_name,
        rows_parsed=len(locations),
        rows_failed=rows_failed,
        column_mapping=column_mapping,
        unknown_headers=unknown_headers,
        model=model,
        errors=errors,
        inferred_file_fields=inferred,
    )


def _build_parameters(
    path: Path,
    spec_name: str,
    headers: list[str],
    rows: list[dict],
    column_mapping: dict[str, str],
    unknown_headers: list[str],
) -> IngestResult:
    """Bucket rows by ``(group, unit, parameterType)`` — initiative.

    FEWS XSD puts ``unit`` and ``parameterType`` on the ParameterGroup,
    so two parameters with different units cannot share a group. If the
    CSV's ``group`` column lumps incompatible parameters together, the
    agent auto-splits into sub-groups (``{group}_{unit}``) rather than
    asking the user to fix the CSV.
    """
    rows_failed = 0
    errors: list[str] = []
    warnings: list[str] = []

    # Bucket rows by (group, unit, parameterType). The unit / type tuple
    # is what determines a valid FEWS ParameterGroup; the user's
    # ``group`` column is just the preferred grouping label.
    BucketKey = tuple[str, str | None, str | None]
    buckets: dict[BucketKey, list[dict]] = {}
    user_group_to_units: dict[str, set[str | None]] = {}
    for row in rows:
        group_id = _row_field(row, column_mapping, "group") or "default"
        unit = _row_field(row, column_mapping, "unit")
        ptype = _row_field(row, column_mapping, "parameterType")
        buckets.setdefault((group_id, unit, ptype), []).append(row)
        user_group_to_units.setdefault(group_id, set()).add(unit)

    # Detect splits — a user group with multiple distinct units.
    split_groups = {
        g for g, units in user_group_to_units.items() if len(units) > 1
    }
    for g in sorted(split_groups):
        warnings.append(
            f"group {g!r} has rows with mixed units "
            f"({sorted(str(u) for u in user_group_to_units[g])}); "
            f"auto-split into per-unit sub-groups"
        )

    parameter_groups: list[ParameterGroup] = []
    for (group_id, unit, ptype), group_rows in buckets.items():
        params: list[Parameter] = []
        first = group_rows[0]
        group_uses_datum = _row_field(first, column_mapping, "usesDatum")
        group_name = _row_field(first, column_mapping, "groupName")
        group_display_unit = _row_field(first, column_mapping, "displayUnit")

        for i, row in enumerate(group_rows, start=2):
            try:
                allow_missing = _row_field(row, column_mapping, "allowMissing")
                p = Parameter(
                    id=_row_field(row, column_mapping, "id") or "",
                    shortName=(
                        _row_field(row, column_mapping, "shortName")
                        or _row_field(row, column_mapping, "name")
                        or _row_field(row, column_mapping, "id")
                        or ""
                    ),
                    name=_row_field(row, column_mapping, "name"),
                    description=_row_field(row, column_mapping, "description"),
                    valueResolution=_decimal_or_none(
                        _row_field(row, column_mapping, "valueResolution")
                    ),
                    valueResolutionUnit=_row_field(
                        row, column_mapping, "valueResolutionUnit"
                    ),
                    allowMissing=(
                        allow_missing.lower() in {"true", "1", "yes"}
                        if allow_missing
                        else None
                    ),
                )
                params.append(p)
            except Exception as e:
                rows_failed += 1
                errors.append(f"row {i} (group {group_id!r}): {e}")

        if not params:
            continue
        # Suffix the group id with unit when a split happened, so the
        # rendered XML has unique parameterGroupIds.
        effective_id = (
            f"{group_id}_{unit}" if group_id in split_groups and unit else group_id
        )
        try:
            pg = ParameterGroup(
                id=effective_id,
                parameter=params,
                name=group_name,
                parameterType=ptype,  # type: ignore[arg-type]
                unit=unit,
                displayUnit=group_display_unit,
                usesDatum=(
                    group_uses_datum.lower() in {"true", "1", "yes"}
                    if group_uses_datum
                    else None
                ),
            )
            parameter_groups.append(pg)
        except Exception as e:
            errors.append(f"group {effective_id!r}: {e}")

    model: Parameters | None = None
    if parameter_groups:
        try:
            model = Parameters(parameterGroup=parameter_groups)
        except Exception as e:
            errors.append(f"root model: {e}")

    return IngestResult(
        csv_path=path,
        spec_name=spec_name,
        rows_parsed=sum(len(pg.parameter) for pg in parameter_groups),
        rows_failed=rows_failed,
        column_mapping=column_mapping,
        unknown_headers=unknown_headers,
        model=model,
        errors=errors,
        warnings=warnings,
    )


def _build_qualifiers(
    path: Path,
    spec_name: str,
    headers: list[str],
    rows: list[dict],
    column_mapping: dict[str, str],
    unknown_headers: list[str],
) -> IngestResult:
    qualifiers: list[Qualifier] = []
    rows_failed = 0
    errors: list[str] = []

    for i, row in enumerate(rows, start=2):
        try:
            q = Qualifier(
                id=_row_field(row, column_mapping, "id") or "",
                name=_row_field(row, column_mapping, "name"),
                description=_row_field(row, column_mapping, "description"),
                shortName=_row_field(row, column_mapping, "shortName"),
                group=_row_field(row, column_mapping, "group"),
            )
            qualifiers.append(q)
        except Exception as e:
            rows_failed += 1
            errors.append(f"row {i}: {e}")

    model: Qualifiers | None = None
    if qualifiers:
        try:
            model = Qualifiers(qualifier=qualifiers)
        except Exception as e:
            errors.append(f"root model: {e}")

    return IngestResult(
        csv_path=path,
        spec_name=spec_name,
        rows_parsed=len(qualifiers),
        rows_failed=rows_failed,
        column_mapping=column_mapping,
        unknown_headers=unknown_headers,
        model=model,
        errors=errors,
    )


def _build_warning_levels(
    path: Path,
    spec_name: str,
    headers: list[str],
    rows: list[dict],
    column_mapping: dict[str, str],
    unknown_headers: list[str],
) -> IngestResult:
    levels: list[ThresholdWarningLevel] = []
    rows_failed = 0
    errors: list[str] = []

    for i, row in enumerate(rows, start=2):
        try:
            opacity = _row_field(row, column_mapping, "opaquenessPercentage")
            level = ThresholdWarningLevel(
                id=_row_field(row, column_mapping, "id") or "",
                name=_row_field(row, column_mapping, "name"),
                color=_row_field(row, column_mapping, "color") or "",
                iconName=_row_field(row, column_mapping, "iconName"),
                historicOverlayIconName=_row_field(
                    row, column_mapping, "historicOverlayIconName"
                ),
                forecastOverlayIconName=_row_field(
                    row, column_mapping, "forecastOverlayIconName"
                ),
                opaquenessPercentage=int(opacity) if opacity else None,
            )
            levels.append(level)
        except Exception as e:
            rows_failed += 1
            errors.append(f"row {i}: {e}")

    model: ThresholdWarningLevels | None = None
    if levels:
        try:
            model = ThresholdWarningLevels(thresholdWarningLevel=levels)
        except Exception as e:
            errors.append(f"root model: {e}")

    return IngestResult(
        csv_path=path,
        spec_name=spec_name,
        rows_parsed=len(levels),
        rows_failed=rows_failed,
        column_mapping=column_mapping,
        unknown_headers=unknown_headers,
        model=model,
        errors=errors,
    )


_BUILDERS = {
    "locations": _build_locations,
    "parameters": _build_parameters,
    "qualifiers": _build_qualifiers,
    "thresholdWarningLevels": _build_warning_levels,
}


__all__ = [
    "IngestResult",
    "ingest_csv",
    "ingest_directory",
    "lint_conform_headers",
]
