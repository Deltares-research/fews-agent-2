"""Agent-authored input CSVs — locations/parameters/qualifiers from prose.

Human testing surfaced the gap verbatim: the agent collected a station's
name and coordinates, then admitted it had nowhere to put them ("then why
did you ask for the stations? what help is that?"). This module closes the
loop: the ``write_input_file`` patch op lets the model hand over structured
rows, and Python validates them against the SAME column-alias table the CSV
ingest reads with (``csv_ingest._COLUMN_ALIASES`` — single source of truth,
so a written file is ingestible by construction) and writes/upserts
``inputs/<file>``.

Split of responsibilities:
  - here: pure row normalization, validation, merge, CSV text (no disk I/O
    beyond what the caller passes in — testable on plain data)
  - ``patch_ops``: op-level validation → ``PatchResult.input_writes``
  - ``llm_turn._perform_input_writes``: the actual disk write into the
    session's ``inputs/`` dir, with failures reported LOUDLY

Existing files are merged by ``id`` (new rows appended, same-id rows
updated); unknown columns already present in a user-uploaded file are
preserved verbatim — the agent must never destroy configurator data.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path

from fews_agent.agent.csv_ingest import _COLUMN_ALIASES

# file name → (alias-table spec, required fields, preferred column order)
SUPPORTED_FILES: dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]] = {
    "locations.csv": (
        "locations", ("id", "x", "y"),
        ("id", "name", "shortName", "y", "x", "z", "description",
         "parentLocationId"),
    ),
    "parameters.csv": (
        "parameters", ("id",),
        ("id", "name", "shortName", "unit", "parameterType", "group",
         "groupName", "displayUnit", "description", "allowMissing",
         "usesDatum"),
    ),
    "qualifiers.csv": (
        "qualifiers", ("id",),
        ("id", "name", "shortName", "group", "description"),
    ),
}

# The header we WRITE per canonical field — friendly names that are also
# ingest aliases (lat/lon read back as y/x).
_WRITE_HEADER = {"x": "lon", "y": "lat"}

_RANGES = {"x": (-180.0, 180.0), "y": (-90.0, 90.0)}


def _alias_map(spec: str) -> dict[str, str]:
    """lowercase alias → canonical field, for one spec."""
    out: dict[str, str] = {}
    for field_name, aliases in _COLUMN_ALIASES[spec].items():
        for a in aliases:
            out.setdefault(a, field_name)
    return out


def normalize_row(spec: str, row: dict) -> dict:
    """Map a raw row's keys onto canonical fields; unknown keys are kept
    verbatim (they may be legitimate attribute columns in an existing file)."""
    amap = _alias_map(spec)
    out: dict = {}
    for k, v in (row or {}).items():
        key = amap.get(str(k).strip().lower(), str(k).strip())
        if key not in out or out[key] in ("", None):
            out[key] = v
    return out


def validate_rows(filename: str, rows: list) -> tuple[list[dict], list[str]]:
    """Normalize + validate a batch of rows. Returns (clean, errors).

    Errors are worded for the model/user ("row 2: lat 91.0 out of range"),
    and any error rejects the WHOLE batch — a half-written file is worse
    than a loud retry.
    """
    if filename not in SUPPORTED_FILES:
        return [], [
            f"unsupported input file {filename!r} "
            f"(supported: {', '.join(sorted(SUPPORTED_FILES))})"
        ]
    spec, required, _ = SUPPORTED_FILES[filename]
    errors: list[str] = []
    clean: list[dict] = []
    seen_ids: set[str] = set()
    for i, raw in enumerate(rows or [], start=1):
        if not isinstance(raw, dict):
            errors.append(f"row {i}: not an object")
            continue
        row = normalize_row(spec, raw)
        for req in required:
            if str(row.get(req, "") or "").strip() == "":
                errors.append(f"row {i}: missing required {req!r}"
                              + (" (lat/lon)" if req in ("x", "y") else ""))
        rid = str(row.get("id", "") or "").strip()
        if rid:
            if rid in seen_ids:
                errors.append(f"row {i}: duplicate id {rid!r} in this batch")
            seen_ids.add(rid)
        for coord in ("x", "y"):
            if coord in row and str(row[coord]).strip() != "":
                try:
                    val = float(row[coord])
                except (TypeError, ValueError):
                    errors.append(
                        f"row {i}: {'lon' if coord == 'x' else 'lat'} "
                        f"{row[coord]!r} is not a number"
                    )
                    continue
                lo, hi = _RANGES[coord]
                if not lo <= val <= hi:
                    errors.append(
                        f"row {i}: {'lon' if coord == 'x' else 'lat'} "
                        f"{val} out of range [{lo}, {hi}]"
                    )
                row[coord] = val
        clean.append(row)
    if not rows:
        errors.append("no rows given")
    return (clean, []) if not errors else ([], errors)


def read_existing(path: Path, spec: str) -> list[dict]:
    """Existing file → normalized rows ([] when absent/unreadable)."""
    try:
        with Path(path).open(newline="", encoding="utf-8-sig") as fh:
            return [normalize_row(spec, r) for r in csv.DictReader(fh)]
    except FileNotFoundError:
        return []
    except Exception:  # noqa: BLE001 — a broken file is replaced, not fatal
        return []


def merge_rows(existing: list[dict], new: list[dict]) -> tuple[list[dict], int, int]:
    """Upsert by id: same-id rows are updated field-wise, new ids appended.
    Returns (rows, n_added, n_updated)."""
    out = [dict(r) for r in existing]
    index = {str(r.get("id", "")).strip(): r for r in out
             if str(r.get("id", "")).strip()}
    added = updated = 0
    for row in new:
        rid = str(row.get("id", "")).strip()
        target = index.get(rid)
        if target is not None:
            before = dict(target)
            target.update({k: v for k, v in row.items() if v not in ("", None)})
            updated += 1 if target != before else 0
        else:
            out.append(dict(row))
            index[rid] = out[-1]
            added += 1
    return out, added, updated


def build_csv(filename: str, rows: list[dict]) -> str:
    """Render rows as CSV text with canonical, ingest-compatible headers.

    Column order: the spec's preferred order first (only columns actually
    used), then any preserved unknown columns in first-seen order.
    """
    _, _, preferred = SUPPORTED_FILES[filename]
    used: list[str] = []
    for col in preferred:
        if any(str(r.get(col, "") or "").strip() != "" for r in rows):
            used.append(col)
    for r in rows:
        for k in r:
            if k not in used and k not in preferred:
                used.append(k)
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow([_WRITE_HEADER.get(c, c) for c in used])
    for r in rows:
        writer.writerow([r.get(c, "") for c in used])
    return buf.getvalue()


def write_input_file(inputs_dir: Path, filename: str, rows: list[dict],
                     delete_ids: list[str] | None = None) -> str:
    """Merge validated rows into ``inputs_dir/filename`` (and/or delete rows
    by id) and return a note. Caller validates first; this only merges,
    deletes and writes. A delete id that isn't in the file is reported in
    the note rather than silently ignored."""
    spec, _, _ = SUPPORTED_FILES[filename]
    inputs_dir = Path(inputs_dir)
    inputs_dir.mkdir(parents=True, exist_ok=True)
    path = inputs_dir / filename
    existing = read_existing(path, spec)
    merged, added, updated = merge_rows(existing, rows)
    removed, missing = [], []
    for rid in delete_ids or []:
        rid = str(rid).strip()
        before = len(merged)
        merged = [r for r in merged
                  if str(r.get("id", "")).strip() != rid]
        (removed if len(merged) < before else missing).append(rid)
    path.write_text(build_csv(filename, merged), encoding="utf-8")
    bits = []
    if added:
        bits.append(f"{added} new row{'s' if added != 1 else ''}")
    if updated:
        bits.append(f"{updated} updated")
    if removed:
        bits.append(f"removed {', '.join(removed)}")
    detail = " + ".join(bits) if bits else "no changes"
    note = f"Wrote inputs/{filename} — {detail} ({len(merged)} total)."
    if missing:
        note += f" Not found (nothing to remove): {', '.join(missing)}."
    return note
