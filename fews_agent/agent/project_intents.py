"""Intent + skills layer for the chat agent.

The chat front-end works in two phases:

  1. **Skills + intent classification** — extract structured facts
     from the user's prose using deterministic regex skills first,
     then ask the LLM to classify the user's intent and confirm/extend
     what the skills found. The LLM only fills gaps the skills can't.

  2. **Slot-filling** — given the classified intent, look up its
     required + optional slots. Drive the rest of the conversation
     by asking ONE focused question per unfilled required slot.
     Patterns are derived deterministically from filled slots, not
     LLM-decided.

Why split into skills + intent: a 7B model isn't reliable at picking
the right pattern from a 37-entry catalog. Skills (regex against
known enum values) are bulletproof for the common cases; the LLM
handles the fuzzy cases. Pattern resolution from slots is
deterministic — no hallucination possible.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Callable

from .providers.ollama_provider import OllamaProvider


# ---------------------------------------------------------------------------
# Skill 1: model adapter detection
# ---------------------------------------------------------------------------

# Adapter name → list of strings the user might say.
_ADAPTER_PHRASES: dict[str, list[str]] = {
    "raven": ["raven"],
    "wflow": ["wflow"],
    "hbv96": ["hbv96", "hbv 96", "hbv-96", "hbv"],
    "mesh": ["mesh"],
    "delft3d": ["delft3d", "delft 3d", "delft-3d"],
}


def detect_model_adapter(text: str) -> str | None:
    """Return the canonical adapter name if any known phrase appears in text."""
    lower = text.lower()
    # Longest-first to avoid 'hbv' matching inside 'hbv96'.
    for adapter, phrases in sorted(
        _ADAPTER_PHRASES.items(), key=lambda kv: -max(len(p) for p in kv[1])
    ):
        for phrase in phrases:
            if re.search(rf"\b{re.escape(phrase)}\b", lower):
                return adapter
    return None


# ---------------------------------------------------------------------------
# Skill 2: data import detection
# ---------------------------------------------------------------------------

_IMPORT_NAMES: list[str] = [
    "HRDPS", "GDPS", "RDPS", "REPS", "HRDPA", "RDPA",  # ECCC NWPs
    "GFS", "NAM", "SREF",                              # NOAA NWPs
    "GPM", "GSMAP",                                    # satellite precip
    "GLOBSNOW", "SNODAS",                              # snow
    "E2O",                                             # Earth2Observe
    "WSCDaily", "WSCHourly", "WSCHistoric",            # WSC scalar
    "ECCCScalar",
]

# Aliases for import names that appear in conversational language but
# don't match the canonical name (which gets used as a pattern variable).
# The detector recognises the LHS, the resolver maps to the RHS.
_IMPORT_ALIASES: dict[str, str] = {
    "ECCCStations": "ECCCScalar",
    "WSC": "WSCHourly",  # bare "WSC" defaults to hourly variant
    "Earth2Observe": "E2O",
}

# Override the default "use import name as the variable value" behaviour
# in `_IMPORT_PATTERN_MAP` resolution. Used when a pattern expects the
# variable to be a literal filename root distinct from the import name.
_IMPORT_VALUE_OVERRIDES: dict[str, str] = {
    "NAM":  "ImportNAMGrids",
    "SREF": "ImportSREFGrids",
}


def detect_imports(text: str) -> list[str]:
    """Return canonical import names mentioned in the text (in input order)."""
    found = []
    seen = set()
    upper = text.upper()
    # Aliases: longest first to avoid 'WSC' matching inside 'WSCHourly'.
    for alias, canonical in sorted(
        _IMPORT_ALIASES.items(), key=lambda kv: -len(kv[0])
    ):
        if re.search(rf"\b{re.escape(alias.upper())}\b", upper):
            if canonical not in seen:
                found.append(canonical)
                seen.add(canonical)
    # Then known canonical names (also longest first).
    for name in sorted(_IMPORT_NAMES, key=lambda n: -len(n)):
        if re.search(rf"\b{re.escape(name.upper())}\b", upper):
            if name not in seen:
                found.append(name)
                seen.add(name)
    return found


# ---------------------------------------------------------------------------
# Skill 3: basin detection
# ---------------------------------------------------------------------------

_KNOWN_BASINS = {"liard", "snare"}  # tutorial basins — hint only, not a gate

# Capitalised English words the basin regex may mis-capture as a proper
# noun (sentence starters, pronouns, common verbs). Skill output drops
# these before they reach pattern resolution; the post-hoc warning in
# `runners.agent.chat_step` imports this same set as defence in depth.
ENGLISH_WORD_BLOCKLIST: frozenset[str] = frozenset({
    "We", "It", "The", "This", "That", "These", "Those",
    "I", "You", "He", "She", "They", "We're", "Our", "Their",
    "Hi", "Hello", "Hey", "Yes", "No", "Ok", "Okay",
    "Please", "Thanks", "Thank",
    "And", "Or", "But", "So", "Then", "Also",
    "Next", "First", "Last", "Now", "Today", "Tomorrow",
    "All", "Some", "Any", "Each", "Every", "Both",
    "Use", "Uses", "Used", "Using", "Run", "Runs", "Running",
    "Imports", "Import", "Geo", "Datum", "Region",
})


def _is_blocked_basin(name: str) -> bool:
    """True if ``name`` looks like an English word, not a basin name.

    Checked against the canonical (title-case, no whitespace handling)
    form used by `_BASIN_PATTERN` / `_USES_PATTERN` captures.
    """
    return name in ENGLISH_WORD_BLOCKLIST

# Multi-word basin name regex. Captures the leftmost capitalized word
# in patterns like "Mackenzie basin", "Mackenzie River basin",
# "Saskatchewan watershed", or "basin Mackenzie". Hydrographic-feature
# words (River/Creek/Watershed/Lake) are absorbed into the noun phrase
# so the captured name is the proper noun, not the feature word.
_BASIN_PATTERN = re.compile(
    r"(?P<n>[A-Z][a-zA-Z]+)"
    r"(?:\s+(?:[Rr]iver|[Cc]reek|[Ww]atershed|[Ll]ake|[Bb]ay))?"
    r"\s+[Bb]asin\b"
    r"|\b[Bb]asin\s+(?P<m>[A-Z][a-zA-Z]+)"
)

# Direct binding: "Mackenzie uses raven" / "Mackenzie River uses raven
# model" — high-confidence pair. `adapter` is a generic lowercase token;
# `_resolve_adapter_phrase` filters to known adapters.
_USES_PATTERN = re.compile(
    r"\b(?P<basin>[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?)\s+"
    r"(?:uses?|with|via|using)\s+"
    r"(?:the\s+)?"
    r"(?P<adapter>[a-z][a-z0-9-]{2,15})"
    r"(?:\s+(?:model|adapter|hydrolog\w*))?"
)


def detect_basin(text: str) -> str | None:
    """Return the canonical basin name if mentioned. Tries known list first."""
    lower = text.lower()
    # "no basin" / "without basin" / "skip basin" → not a basin claim.
    for neg in (r"\bno basin\b", r"\bwithout basin\b", r"\bskip basin\b"):
        if re.search(neg, lower):
            return None
    for known in _KNOWN_BASINS:
        if re.search(rf"\b{known}\b", lower):
            return known.title()  # "Liard"
    # Fallback: regex extraction of "<NAME> basin".
    m = _BASIN_PATTERN.search(text)
    if m:
        name = m.group("n") or m.group("m")
        if name and name.lower() not in {"no", "without", "skip"}:
            canonical = name[:1].upper() + name[1:].lower()
            if not _is_blocked_basin(canonical):
                return canonical
    return None


def detect_all_basins(text: str) -> list[str]:
    """All basin names found in text, deduped, in order of first appearance."""
    found = []
    lower = text.lower()
    for known in _KNOWN_BASINS:
        for m in re.finditer(rf"\b{known}\b", lower):
            name = known.title()
            if name not in found:
                found.append(name)
    # Also pick up any unknown "<NAME> basin" phrases.
    for m in _BASIN_PATTERN.finditer(text):
        name = m.group("n") or m.group("m")
        if name and name.lower() not in {"no", "without", "skip"}:
            canonical = name[:1].upper() + name[1:].lower()
            if _is_blocked_basin(canonical):
                continue
            if canonical not in found:
                found.append(canonical)
    return found


def _find_basin_positions(text: str) -> list[tuple[int, str]]:
    """All basin name occurrences with their start position. Combines
    known-name matches and the multi-word `_BASIN_PATTERN` regex."""
    found: list[tuple[int, str]] = []
    seen_names: set[str] = set()
    lower = text.lower()
    for known in _KNOWN_BASINS:
        for m in re.finditer(rf"\b{known}\b", lower):
            name = known.title()
            found.append((m.start(), name))
            seen_names.add(name)
    for m in _BASIN_PATTERN.finditer(text):
        name = m.group("n") or m.group("m")
        if not name or name.lower() in {"no", "without", "skip"}:
            continue
        canonical = name[:1].upper() + name[1:].lower()
        if _is_blocked_basin(canonical):
            continue
        if canonical not in seen_names:
            found.append((m.start("n") if m.group("n") else m.start("m"), canonical))
            seen_names.add(canonical)
    found.sort(key=lambda x: x[0])
    return found


def detect_basins_with_adapters(text: str) -> list[dict[str, str]]:
    """Pair each detected basin with an adapter.

    Two-stage detection:
      1. Direct "<Basin> uses <adapter>" syntax — high-confidence pairs
         (`_USES_PATTERN`). The basin can be any capitalized name,
         not just a known one.
      2. Proximity pairing — for basins not already paired by stage 1,
         find the nearest adapter mention within 120 chars.

    Both known basins (`_KNOWN_BASINS`) and ad-hoc multi-word basin
    phrases ("Mackenzie River basin") feed both stages.
    """
    pairs: list[dict[str, str]] = []
    paired_basins: set[str] = set()

    # Stage 1: direct "X uses Y" binding.
    for m in _USES_PATTERN.finditer(text):
        b_raw = m.group("basin").strip()
        a_raw = m.group("adapter").lower().replace(" ", "").replace("-", "")
        adapter = _resolve_adapter_phrase(a_raw)
        if not adapter:
            continue
        # Canonicalise basin: title-case each word.
        basin_canonical = " ".join(
            w[:1].upper() + w[1:].lower() for w in b_raw.split()
        )
        if _is_blocked_basin(basin_canonical):
            continue
        if basin_canonical in paired_basins:
            continue
        pairs.append(
            {"basin_name": basin_canonical, "model_adapter": adapter}
        )
        paired_basins.add(basin_canonical)

    # Stage 2: proximity pairing for any basins not yet bound.
    basins_found = _find_basin_positions(text)
    lower = text.lower()
    adapters_found: list[tuple[int, str]] = []
    for adapter, phrases in _ADAPTER_PHRASES.items():
        for phrase in phrases:
            for m in re.finditer(rf"\b{re.escape(phrase)}\b", lower):
                adapters_found.append((m.start(), adapter))
    adapters_found.sort(key=lambda x: x[0])

    # When only one adapter is mentioned in the text, all basins share it
    # ("Liard and Snare using raven"). With multiple adapters, each gets
    # consumed by its nearest basin so we don't fan one out across all.
    single_adapter = len(adapters_found) == 1
    used_adapter_positions: set[int] = set()
    for b_pos, b_name in basins_found:
        if b_name in paired_basins:
            continue
        nearest_idx = None
        min_dist = float("inf")
        for a_idx, (a_pos, _) in enumerate(adapters_found):
            if a_pos in used_adapter_positions:
                continue
            dist = abs(a_pos - b_pos)
            if dist < min_dist:
                min_dist = dist
                nearest_idx = a_idx
        if nearest_idx is not None and min_dist < 120:
            a_pos, a_name = adapters_found[nearest_idx]
            pairs.append(
                {"basin_name": b_name, "model_adapter": a_name}
            )
            paired_basins.add(b_name)
            if not single_adapter:
                used_adapter_positions.add(a_pos)
    return pairs


def _resolve_adapter_phrase(raw: str) -> str | None:
    """Normalise `_USES_PATTERN`'s adapter capture to a canonical key."""
    raw = raw.lower()
    for adapter, phrases in _ADAPTER_PHRASES.items():
        for phrase in phrases:
            if phrase.replace(" ", "").replace("-", "") == raw:
                return adapter
    return None


# ---------------------------------------------------------------------------
# Skill 4: geo datum detection
# ---------------------------------------------------------------------------

_DATUM_PHRASES: dict[str, list[str]] = {
    "WGS 1984": ["wgs 1984", "wgs1984", "wgs 84", "wgs84"],
    "NAD 83":   ["nad 83", "nad83", "nad-83"],
    "NAD 27":   ["nad 27", "nad27"],
}


def detect_geo_datum(text: str) -> str | None:
    lower = text.lower()
    for canonical, phrases in _DATUM_PHRASES.items():
        for phrase in phrases:
            if phrase in lower:
                return canonical
    return None


# ---------------------------------------------------------------------------
# Skill 5: locations source detection (CSV vs YAML vs inline)
# ---------------------------------------------------------------------------

def detect_locations_source(text: str) -> str | None:
    """Detect whether the user mentioned locations.csv / locations.yaml /etc."""
    lower = text.lower()
    if "locations.csv" in lower or "stations.csv" in lower:
        return "csv"
    if "locations.yaml" in lower or "locations.yml" in lower:
        return "yaml"
    return None


# ---------------------------------------------------------------------------
# Skill 6: region detection (named geographic region → REGION + bbox)
# ---------------------------------------------------------------------------

# Region gazetteer: canonical name → (left, right, top, bottom) in
# WGS84 degrees. Used to (a) populate the REGION property in
# sa_global.Properties so $REGION$ resolves at FEWS startup and (b)
# override the bundled spatialDisplay defaultExtent so the demo map
# opens on the right part of the world. Bboxes are coarse — the
# configurator can override either via singleton_seeds or by editing
# spatialDisplay later.
REGION_BBOX: dict[str, tuple[float, float, float, float]] = {
    "Gulf of Guinea": (-10.0, 10.0, 8.0, -5.0),
    "North Sea": (-5.0, 12.0, 60.0, 50.0),
    "Mediterranean": (-10.0, 40.0, 47.0, 30.0),
    "Baltic Sea": (10.0, 30.0, 66.0, 53.0),
    "Gulf of Mexico": (-100.0, -80.0, 32.0, 17.0),
    "Caribbean": (-90.0, -60.0, 25.0, 9.0),
    "Bay of Bengal": (78.0, 100.0, 23.0, 5.0),
    "South China Sea": (105.0, 122.0, 25.0, 0.0),
}

# Lowercased lookup; multi-word phrases get matched longest-first so
# "gulf of mexico" wins over a bare "gulf of guinea" substring miss.
_REGION_PHRASES: tuple[tuple[str, str], ...] = tuple(
    sorted(
        ((name.lower(), name) for name in REGION_BBOX),
        key=lambda kv: -len(kv[0]),
    )
)


def detect_region(text: str) -> str | None:
    """Return the canonical region name if any gazetteer entry matches."""
    lower = (text or "").lower()
    for phrase, canonical in _REGION_PHRASES:
        if phrase in lower:
            return canonical
    return None


# Coordinate phrase: signed decimal followed by a hemisphere letter, with
# optional degree marker. Examples: "5N", "10.5 S", "-12°W", "+3 e".
_COORD_RE = re.compile(
    r"([+-]?\d+(?:\.\d+)?)\s*(?:°|deg(?:rees?)?)?\s*([NSEWnsew])\b"
)


# Grid resolution: NOAA GFS publishes 0.25°, 0.5°, 1° flavours. The slug
# embedded in the DODS URL uses underscored / lowercase form (0p25 etc.)
# so we normalise to that here.
_GRID_RESOLUTION_PHRASES: tuple[tuple[str, str], ...] = (
    ("0.25 degree", "0p25"),
    ("0.25-degree", "0p25"),
    ("quarter-degree", "0p25"),
    ("quarter degree", "0p25"),
    ("0.5 degree", "0p50"),
    ("0.5-degree", "0p50"),
    ("half-degree", "0p50"),
    ("half degree", "0p50"),
    ("1 degree", "1p00"),
    ("1-degree", "1p00"),
    ("one-degree", "1p00"),
    ("one degree", "1p00"),
)


def detect_grid_resolution(text: str) -> str | None:
    """Map prose like "half-degree GFS" to a NOAA URL slug (0p25/0p50/1p00).

    Returns None when no phrase matches so the resolver doesn't force
    a value on patterns that already default sensibly.
    """
    lower = (text or "").lower()
    for phrase, slug in _GRID_RESOLUTION_PHRASES:
        if phrase in lower:
            return slug
    return None


# Forecast horizon phrases. Patterns like "N-day", "N days", "N hours",
# "weekly", etc. Returns hours so the consumer can drop straight into a
# relativeViewPeriod block. Matches are ordered so word phrases are
# tried first; numeric expressions are caught by a fall-through regex.
_HORIZON_WORD_PHRASES: tuple[tuple[str, int], ...] = (
    ("weekly forecast", 168),
    ("two-week forecast", 336),
    ("daily forecast", 24),
    ("hourly forecast", 1),
)
_HORIZON_DAYS_RE = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*-?\s*day(?:s)?\b", re.IGNORECASE
)
_HORIZON_HOURS_RE = re.compile(
    r"\b(\d+)\s*-?\s*hour(?:s)?\b", re.IGNORECASE
)


def detect_forecast_horizon_hours(text: str) -> int | None:
    """Parse forecast horizon prose to an integer hour count.

    Examples:
        "7-day forecast"   -> 168
        "120 hours"        -> 120
        "weekly forecast"  -> 168
        "10 day"           -> 240
    Returns None when no recognised phrase matches.
    """
    lower = (text or "").lower()
    for phrase, hours in _HORIZON_WORD_PHRASES:
        if phrase in lower:
            return hours
    m = _HORIZON_DAYS_RE.search(lower)
    if m:
        try:
            return int(round(float(m.group(1)) * 24))
        except ValueError:
            pass
    m = _HORIZON_HOURS_RE.search(lower)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    return None


def detect_custom_bbox(
    text: str,
) -> tuple[float, float, float, float] | None:
    """Extract a freeform bbox from prose with N/S/E/W coordinate markers.

    Returns ``(left, right, top, bottom)`` in WGS84 degrees if the text
    contains at least one latitude (N/S) AND one longitude (E/W) — and
    enough coords to define a range on each axis. Single-point input
    (one lat, one lon, no range) returns None: a 0-area extent is
    useless.

    The hemisphere letter sets the sign (S/W → negative). Returns None
    when nothing useful is found, so the caller can fall back to the
    gazetteer.
    """
    matches = _COORD_RE.findall(text or "")
    if not matches:
        return None
    lats: list[float] = []
    lons: list[float] = []
    for raw_num, letter in matches:
        try:
            val = float(raw_num)
        except ValueError:
            continue
        hem = letter.upper()
        # Explicit sign on the number wins (configurator typed -5N
        # because they meant 5S). When unsigned, hemisphere sets sign.
        if raw_num.startswith(("+", "-")):
            pass  # keep as-is
        elif hem in ("S", "W"):
            val = -abs(val)
        if hem in ("N", "S"):
            lats.append(val)
        else:
            lons.append(val)
    if not lats or not lons:
        return None
    top, bottom = max(lats), min(lats)
    left, right = min(lons), max(lons)
    if top == bottom or left == right:
        return None
    return (left, right, top, bottom)


# Free-text phrases that signal which meteorological variables the
# user wants imported. Listed longest-first so multi-word phrases are
# detected before their substring single-words (e.g. "wind speed"
# matches before bare "wind"). The returned strings are normalised
# back to the longest matching key from _DATA_TYPE_TO_PARAMETER so the
# resolver can look them up directly.
_DATA_TYPE_PHRASES: tuple[str, ...] = (
    "mean sea level pressure",
    "relative humidity",
    "dewpoint temperature",
    "air temperature",
    "wind direction",
    "wind speed",
    "dew point",
    "dewpoint",
    "humidity",
    "temperature",
    "precipitation",
    "pressure",
    "mslp",
    "precip",
)


# Phrases signalling the user wants the imported grids interpolated to
# point locations (Data Viewer) and/or visualized as gridded layers
# (Spatial Display). When any of these match, the resolver wires in the
# postprocess-template + interpolation workflow patterns so the build
# emits an end-to-end grid→station path instead of a bare import.
_INTERPOLATION_PHRASES: tuple[str, ...] = (
    "interpolate the grid",
    "interpolate the gridded",
    "interpolate gridded",
    "interpolate to locations",
    "interpolate to stations",
    "interpolate to points",
    "interpolate to a location",
    "interpolate to a station",
    "data viewer",
    "spatial display",
)

# Prose asking to view/plot the imported gridded fields. Triggers the
# standalone `spatial_display_grid` visualize pattern (one display config
# per NWP grid source). Kept distinct from interpolation so a request can
# do either or both ("interpolate to stations AND visualize the grids").
_VISUALIZATION_PHRASES: tuple[str, ...] = (
    "visualize",
    "visualise",
    "visualization",
    "visualisation",
    "spatial display",
    "data viewer",
    "grid display",
    "view the grid",
    "view the gridded",
    "display the grid",
    "display the gridded",
    "plot the grid",
    "show the grid",
)


def detect_wants_interpolation(text: str) -> bool | None:
    """Return True when prose asks for grid→point interpolation or viewing.

    Returns ``None`` (not ``False``) when no phrase matches so the
    chat_step merge logic — which skips ``None`` — won't lock in a
    negative on turn 1 and shadow a real signal on turn 2.
    """
    lower = (text or "").lower()
    return True if any(p in lower for p in _INTERPOLATION_PHRASES) else None


def detect_wants_visualization(text: str) -> bool | None:
    """Return True when prose asks to visualize/plot the imported grids.

    Returns ``None`` (not ``False``) when no phrase matches, mirroring
    ``detect_wants_interpolation`` so a turn-1 miss can't shadow a real
    signal on a later turn.
    """
    lower = (text or "").lower()
    return True if any(p in lower for p in _VISUALIZATION_PHRASES) else None


def detect_data_types(text: str) -> list[str]:
    """Return canonical data_type phrases mentioned in the text.

    Substring match, case-insensitive. Each phrase is reported at
    most once; longer phrases shadow their substrings (so "wind
    speed" does not also yield a phantom "wind speed" + bare hit).
    """
    lower = (text or "").lower()
    found: list[str] = []
    consumed_spans: list[tuple[int, int]] = []
    for phrase in _DATA_TYPE_PHRASES:
        start = 0
        while True:
            i = lower.find(phrase, start)
            if i < 0:
                break
            end = i + len(phrase)
            # Skip if this span overlaps a previously consumed (longer) span.
            if not any(cs <= i < ce or cs < end <= ce
                       for cs, ce in consumed_spans):
                consumed_spans.append((i, end))
                if phrase not in found:
                    found.append(phrase)
            start = end
    return found


# ---------------------------------------------------------------------------
# Skill: natural-language EDIT detection (remove / change-a-variable)
# ---------------------------------------------------------------------------
#
# The additive slot-fill in chat_step already handles *adding* facts
# (imports, basins, parameters) — so this skill deliberately does NOT
# emit "add" edits. It fills the two gaps the additive merge structurally
# cannot cover:
#
#   * REMOVE a module      — additive can only union, never subtract.
#   * OVERRIDE a scalar    — additive fills a slot only when it is unset,
#     (grid_resolution,      so "make GFS half-degree" wouldn't change an
#      forecast_horizon)     already-set resolution.
#
# It is verb-gated (an edit verb must be present) AND target-required (a
# known import / basin / value must resolve), so plain descriptive prose
# ("we don't want flooding") never parses as an edit and the normal
# additive path proceeds untouched.

# Removal verbs. "without" is intentionally excluded — "import GFS without
# interpolation" must not read as "remove GFS". "replace"/"swap" are also
# excluded: they imply remove-one-add-another, which the strip-then-readd
# suppression below would mishandle (use explicit /remove + /add instead).
_EDIT_REMOVE_CUES: tuple[str, ...] = (
    "remove", "drop", "delete", "get rid of", "take out", "exclude",
    "no longer", "don't want", "do not want", "dont want",
    "don't need", "do not need", "dont need",
)

# Change/override verbs for scalar variables (resolution, horizon). A
# change cue gates the override so a *first* mention ("import GFS at half
# degree") still flows through additive slot-fill rather than a no-op set.
_EDIT_CHANGE_CUES: tuple[str, ...] = (
    "change", "make", "set", "switch", "update", "instead",
    "actually", "rather", "increase", "decrease", "lower", "raise",
)


def _has_cue(lower: str, cues: tuple[str, ...]) -> bool:
    return any(c in lower for c in cues)


def _cue_positions(lower: str, cues: tuple[str, ...]) -> list[int]:
    """Start offsets of every cue occurrence in ``lower``."""
    out: list[int] = []
    for cue in cues:
        start = 0
        while True:
            i = lower.find(cue, start)
            if i < 0:
                break
            out.append(i)
            start = i + len(cue)
    return out


def _import_position(text: str, name: str) -> int:
    """Char offset of an import name in ``text`` (0 if not literally present,
    e.g. when it was matched via an alias)."""
    m = re.search(rf"\b{re.escape(name.upper())}\b", text.upper())
    return m.start() if m else 0


def detect_edit_action(text: str) -> dict | None:
    """Detect a natural-language edit (remove a module / change a variable).

    Returns ``None`` when no edit verb + resolvable target is present, so
    the caller's normal additive slot-fill runs untouched. Otherwise::

        {
          "edits": [ <edit dict for chat_step.apply_edit_action>, ... ],
          "removed_imports": [<canonical import name>, ...],
          "removed_basins":  [<basin name>, ...],
        }

    Each edit dict matches the shape ``apply_edit_action`` consumes
    (``op``/``target``/``target_kind`` (+ ``variable``/``value`` for set)).
    ``removed_*`` let the caller strip just-removed targets from the
    skill results before the additive merge so they aren't re-added.
    """
    if not text:
        return None
    lower = text.lower()
    edits: list[dict] = []
    removed_imports: list[str] = []
    removed_basins: list[str] = []

    remove_pos = _cue_positions(lower, _EDIT_REMOVE_CUES)
    change_pos = _cue_positions(lower, _EDIT_CHANGE_CUES)
    has_remove = bool(remove_pos)
    has_change = bool(change_pos)

    # Associate each detected import with the cue it sits closest to, so a
    # mixed sentence ("drop RDPS and make GFS half-degree") removes only
    # RDPS and targets the GFS set at GFS — not a greedy remove of both.
    inf = float("inf")
    imports_here = detect_imports(text)
    remove_targets: list[str] = []
    change_target: str | None = None
    best_change_dist = inf
    for name in imports_here:
        pos = _import_position(text, name)
        rd = min((abs(pos - p) for p in remove_pos), default=inf)
        cd = min((abs(pos - p) for p in change_pos), default=inf)
        if rd == inf and cd == inf:
            continue
        if rd <= cd:
            remove_targets.append(name)
        elif cd < best_change_dist:
            best_change_dist = cd
            change_target = name

    # --- SET (override a scalar variable) ------------------------------
    # Gated on a change cue; the value (resolution / horizon) must parse.
    if has_change:
        res = detect_grid_resolution(text)
        if res is not None:
            edits.append({
                "op": "set", "target": change_target,
                "target_kind": "variable",
                "variable": "grid_resolution", "value": res,
            })
        hor = detect_forecast_horizon_hours(text)
        if hor is not None:
            edits.append({
                "op": "set", "target": change_target,
                "target_kind": "variable",
                "variable": "forecast_horizon_hours", "value": hor,
            })

    # --- REMOVE (a module) ---------------------------------------------
    if has_remove:
        for name in remove_targets:
            removed_imports.append(name)
            edits.append({
                "op": "remove", "target": name, "target_kind": "import",
            })
        # Basins: only those nearer a remove cue than a change cue.
        for basin in detect_all_basins(text):
            pos = lower.find(basin.lower())
            if pos < 0:
                pos = 0
            rd = min((abs(pos - p) for p in remove_pos), default=inf)
            cd = min((abs(pos - p) for p in change_pos), default=inf)
            if rd <= cd:
                removed_basins.append(basin)
                edits.append({
                    "op": "remove",
                    "target": {"basin_name": basin},
                    "target_kind": "basin",
                })

    if not edits:
        return None
    return {
        "edits": edits,
        "removed_imports": removed_imports,
        "removed_basins": removed_basins,
    }


# ---------------------------------------------------------------------------
# Composite: extract everything the skills can find
# ---------------------------------------------------------------------------

def extract_skills(text: str) -> dict[str, Any]:
    """Run every skill on text; return everything found.

    ``basins`` (list of {basin_name, model_adapter} pairs) is the
    canonical multi-basin slot. ``basin_name`` and ``model_adapter``
    remain for backwards compatibility with single-basin intents and
    are populated only when exactly one basin is detected.
    """
    pairs = detect_basins_with_adapters(text)
    single_basin = detect_basin(text) if len(pairs) <= 1 else None
    single_adapter = detect_model_adapter(text) if len(pairs) <= 1 else None
    return {
        "basins": pairs,
        "basin_name": single_basin,
        "model_adapter": single_adapter,
        "imports": detect_imports(text),
        "geoDatum": detect_geo_datum(text),
        "locations_source": detect_locations_source(text),
        "data_types": detect_data_types(text),
        "wants_interpolation": detect_wants_interpolation(text),
        "wants_visualization": detect_wants_visualization(text),
        "region": detect_region(text),
        "custom_bbox": detect_custom_bbox(text),
        "grid_resolution": detect_grid_resolution(text),
        "forecast_horizon_hours": detect_forecast_horizon_hours(text),
    }


# ---------------------------------------------------------------------------
# Intent ontology
# ---------------------------------------------------------------------------

@dataclass
class Intent:
    name: str
    description: str
    keywords: list[str]
    required_slots: list[str]
    optional_slots: list[str]
    slot_questions: dict[str, str]
    resolver: Callable[[dict[str, Any], set[str]], list[dict]]


# ---------------------------------------------------------------------------
# Pattern resolution helpers (shared by multiple intents)
# ---------------------------------------------------------------------------

# Import name → (pattern_path, label_var_name). Each pattern declares
# its label variable in its cluster YAML; the resolver passes the
# import name as the value of that variable.
_IMPORT_PATTERN_MAP: dict[str, tuple[str, str]] = {
    # ECCC NWP grids — label_var = nwp_name
    "HRDPS": ("auto/nwp_grid_eccc_HRDPS", "nwp_name"),
    "GDPS":  ("auto/nwp_grid_eccc_GDPS", "nwp_name"),
    "RDPS":  ("auto/nwp_grid_eccc_RDPS", "nwp_name"),
    "REPS":  ("auto/nwp_grid_eccc_REPS", "nwp_name"),
    "HRDPA": ("auto/nwp_grid_eccc_HRDPA", "nwp_name"),
    "RDPA":  ("auto/nwp_grid_eccc_RDPA", "nwp_name"),
    # NOAA
    "GFS":  ("auto/nwp_grid_noaa", "nwp_name"),
    # NAM/SREF: the patterns emit ``{{ template_name }}.xml`` literally,
    # so the variable value IS the filename root. Override the default
    # (which would set it to the import name) via _IMPORT_VALUE_OVERRIDES.
    "NAM":  ("auto/wf_import_nam_grids", "template_name"),
    "SREF": ("auto/wf_import_sref_grids", "template_name"),
    # Satellite — label_var = source_name
    "GPM":   ("auto/satellite_precip_GPM", "source_name"),
    "GSMAP": ("auto/satellite_precip_GSMAP", "source_name"),
    # Snow — label_var = snow_source
    "GLOBSNOW": ("auto/snow_import_GLOBSNOW", "snow_source"),
    "SNODAS":   ("auto/snow_import_SNODAS", "snow_source"),
    # Earth2Observe — label_var = source_name
    "E2O": ("auto/earth2observe", "source_name"),
    # ECCCScalar — label_var = source_name
    "ECCCScalar": ("auto/eccc_scalar", "source_name"),
    # WSC scalar — label_var = wsc_variant
    "WSCDaily":    ("auto/wsc_scalar_WSCDaily_WSCHourly", "wsc_variant"),
    "WSCHourly":   ("auto/wsc_scalar_WSCDaily_WSCHourly", "wsc_variant"),
    "WSCHistoric": ("auto/wsc_scalar_WSCHistoric", "wsc_variant"),
}

# Adapter → basin pattern path.
_ADAPTER_PATTERN_MAP = {
    "raven": "auto/raven_basin",
    "wflow": "auto/wflow_basin",
}


# Free-text data_type slot → canonical FEWS parameter row consumed by
# the NWP pattern's `parameters` variable. Keys are lower-cased; the
# resolver matches by `.lower()` substring/exact comparison.
#
# `startTimeShiftHours` is only set on accumulated quantities (precip):
# FEWS' TimeSeriesImportRun supports a single startTimeShift block per
# <import>, so the pattern picks the first parameter that declares one.
_DATA_TYPE_TO_PARAMETER: dict[str, dict[str, Any]] = {
    "precipitation": {
        "id": "PC.nwp", "unit": "mm",
        "cumulativeSum": True, "startTimeShiftHours": -3,
    },
    "precip": {
        "id": "PC.nwp", "unit": "mm",
        "cumulativeSum": True, "startTimeShiftHours": -3,
    },
    "temperature": {"id": "TA.nwp", "unit": "K"},
    "air temperature": {"id": "TA.nwp", "unit": "K"},
    "temp": {"id": "TA.nwp", "unit": "K"},
    "wind speed": {"id": "WS10.nwp", "unit": "m/s"},
    "wind direction": {"id": "WD10.nwp", "unit": "degree"},
    "mean sea level pressure": {"id": "PA.nwp", "unit": "hPa"},
    "mslp": {"id": "PA.nwp", "unit": "hPa"},
    "pressure": {"id": "PA.nwp", "unit": "hPa"},
    "relative humidity": {"id": "RH.nwp", "unit": "%"},
    "humidity": {"id": "RH.nwp", "unit": "%"},
    "dewpoint temperature": {"id": "TD.nwp", "unit": "K"},
    "dew point": {"id": "TD.nwp", "unit": "K"},
    "dewpoint": {"id": "TD.nwp", "unit": "K"},
}


def unrecognised_data_types(data_types: list[str] | None) -> list[str]:
    """Return data_type phrases the parameter mapper can't translate.

    Mirrors the dispatch logic in ``_data_types_to_parameter_rows`` so
    callers (chat_step warning surface) can flag silent drops to the
    configurator without re-implementing the lookup.
    """
    if not data_types:
        return []
    out: list[str] = []
    for raw in data_types:
        key = (raw or "").strip().lower()
        if key and key not in _DATA_TYPE_TO_PARAMETER:
            out.append(raw)
    return out


# Patterns whose template accepts a `parameters` variable. When the
# chat agent has filled the `data_types` slot, the resolver injects the
# translated parameter list into instances of these patterns. Other
# patterns keep their hardcoded behaviour.
_PARAMETERIZED_NWP_PATTERNS: frozenset[str] = frozenset({
    "auto/nwp_grid_noaa",
})


def _data_types_to_parameter_rows(
    data_types: list[str] | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Translate the free-text data_types slot into FEWS parameter rows.

    Returns (rows, unrecognised). Empty `rows` means the resolver
    should NOT inject ``parameters`` — patterns then fall back to
    their own default.
    """
    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    unrecognised: list[str] = []
    for raw in data_types or []:
        key = (raw or "").strip().lower()
        row = _DATA_TYPE_TO_PARAMETER.get(key)
        if not row:
            unrecognised.append(raw)
            continue
        if row["id"] in seen_ids:
            continue
        seen_ids.add(row["id"])
        rows.append(dict(row))
    return rows, unrecognised


def _resolve_import_patterns(
    imports: list[str], catalog_paths: set[str],
    data_types: list[str] | None = None,
    wants_interpolation: bool = False,
    grid_resolution: str | None = None,
    forecast_horizon_hours: int | None = None,
    wants_visualization: bool = False,
) -> list[dict]:
    """Map import names to pattern instances using each pattern's own
    label variable name. Dedups by path.

    When ``data_types`` is non-empty and they translate to known FEWS
    parameter rows, each instance whose pattern accepts a ``parameters``
    variable receives ``parameters: [rows]``. Otherwise the pattern's
    own default list is used (preserves existing builds verbatim).

    When ``wants_interpolation`` is True (user asked for grid→point
    interpolation or Data Viewer / Spatial Display output), the resolver
    also emits the postprocess template and one interpolation workflow
    per NWP import so the gridded data lands as point time series."""
    param_rows, unrecognised = _data_types_to_parameter_rows(data_types)
    if unrecognised:
        # Surface to stderr so the configurator notices; the chat agent
        # picks this up via its turn log. Not raising — graceful
        # degradation is better than refusing the whole resolve.
        print(
            f"warning: unrecognised data_types skipped: {unrecognised}",
            file=sys.stderr,
        )

    out: list[dict] = []
    for imp in imports or []:
        entry = _IMPORT_PATTERN_MAP.get(imp)
        if not entry:
            continue
        path, label_var = entry
        if path not in catalog_paths:
            continue
        # Some patterns expect the variable's value to be a literal
        # filename root (e.g. NAM → ImportNAMGrids), not the import name
        # itself. Apply override map when present.
        value = _IMPORT_VALUE_OVERRIDES.get(imp, imp)
        instance: dict[str, Any] = {label_var: value}
        if param_rows and path in _PARAMETERIZED_NWP_PATTERNS:
            instance["parameters"] = list(param_rows)
            # Tell the pattern to also contribute these parameter rows
            # to Parameters.xml — without this the new IDs would be
            # referenced in timeSeriesSet but not declared anywhere.
            instance["contribute_parameters"] = True
        # NOAA GFS publishes at 0p25/0p50/1p00; plumb the configurator's
        # choice into the pattern instance so the DODS URL points at the
        # right dataset.
        if grid_resolution and path == "auto/nwp_grid_noaa":
            instance["grid_resolution"] = grid_resolution
        # Forecast horizon (hours) — when set, the NOAA pattern emits a
        # relativeViewPeriod on the SpatialDisplay timeSeriesSet so the
        # plot shows just that window instead of the full forecast.
        if forecast_horizon_hours and path == "auto/nwp_grid_noaa":
            instance["forecast_horizon_hours"] = forecast_horizon_hours
        existing = next((p for p in out if p["pattern"] == path), None)
        if existing:
            existing["instances"].append(instance)
        else:
            out.append({"pattern": path, "instances": [instance]})
    # Aggregator: a project with any NOAA import gets the parent
    # ImportNOAAGrids workflow that triggers GFS+NAM+SREF together.
    # The pattern has no variables; one empty instance fires it.
    noaa_imports = {"GFS", "NAM", "SREF"}
    if (
        any(imp in noaa_imports for imp in (imports or []))
        and "auto/wf_import_noaa_grids" in catalog_paths
    ):
        out.append({
            "pattern": "auto/wf_import_noaa_grids",
            "instances": [{"template_name": "ImportNOAAGrids"}],
        })

    # Interpolation path. The user asked to land the gridded data as
    # point time series (Data Viewer) — emit the postprocess template
    # plus one interpolation workflow per NWP import. Currently scoped
    # to NOAA GFS because that's the only NWP whose nwp_grid_* pattern
    # accepts user-selected parameters. Future ECCC parameterization
    # widens this set.
    if wants_interpolation and param_rows:
        nwp_imports = [imp for imp in (imports or [])
                       if imp in {"GFS"}]
        if nwp_imports:
            if "auto/tpl_postprocess_to_station" in catalog_paths:
                # Override the locationId to match the bare NWP import
                # (which writes locationId=<NWP>, not $MODELNAME1$Grid).
                out.append({
                    "pattern": "auto/tpl_postprocess_to_station",
                    "instances": [{
                        "template_name":
                            "PostprocessModelOutputToStationTemplate",
                        "grid_locationid": nwp_imports[0],
                    }],
                })
            if "auto/wf_interpolate_nwp_to_stations" in catalog_paths:
                out.append({
                    "pattern": "auto/wf_interpolate_nwp_to_stations",
                    "instances": [
                        {"nwp_name": imp, "parameters": list(param_rows)}
                        for imp in nwp_imports
                    ],
                })

    # Visualization path. The user asked to view/plot the imported grids
    # (Spatial Display / Data Viewer). Emit one standalone display config
    # per NWP grid import — these reliably register locationId=<name> and
    # moduleInstanceId=Import<name>, which the visualize pattern points at.
    if wants_visualization and "auto/spatial_display_grid" in catalog_paths:
        viz_instances: list[dict] = []
        for imp in (imports or []):
            entry = _IMPORT_PATTERN_MAP.get(imp)
            if not entry:
                continue
            path, _ = entry
            if not path.startswith("auto/nwp_grid_"):
                continue
            inst: dict[str, Any] = {"source_name": imp}
            if param_rows:
                # Pass the selected parameter rows through; the visualize
                # pattern reads only `id` from each (extra keys ignored).
                inst["parameters"] = [{"id": r["id"]} for r in param_rows]
            if forecast_horizon_hours:
                inst["forecast_horizon_hours"] = forecast_horizon_hours
            viz_instances.append(inst)
        if viz_instances:
            out.append({
                "pattern": "auto/spatial_display_grid",
                "instances": viz_instances,
            })
    return out


def _resolve_basin_pattern(
    adapter: str | None, basin: str | None, catalog_paths: set[str],
) -> list[dict]:
    """Adapter + basin → list with a single basin pattern instance."""
    if not adapter or not basin:
        return []
    path = _ADAPTER_PATTERN_MAP.get(adapter)
    if not path or path not in catalog_paths:
        return []
    return [{"pattern": path, "instances": [{"basin_name": basin}]}]


def _basins_list(slots: dict[str, Any]) -> list[dict[str, str]]:
    """Resolve ``slots['basins']`` (list) with single-basin fallback."""
    basins = slots.get("basins") or []
    if basins:
        return basins
    name, adapter = slots.get("basin_name"), slots.get("model_adapter")
    if name and adapter:
        return [{"basin_name": name, "model_adapter": adapter}]
    return []


# Shared preprocess / postprocess templates used by every
# forecasting project. Each is a single-instance pattern whose label
# variable is the template's canonical name. The pattern path → its
# instance value mapping is fixed (these are 1:1 patterns derived
# from named tutorial files).
_FORECASTING_SHARED_TEMPLATES: dict[str, dict[str, str]] = {
    "auto/tpl_accumulate_forecast_precip":
        {"template_name": "AccumulateForecastPrecipTemplate"},
    "auto/tpl_merge_e2o_precip":
        {"template_name": "MergeE2OPrecip"},
    "auto/tpl_merge_forecast_grids_det":
        {"template_name": "MergeForecastGridsDetTemplate"},
    "auto/tpl_merge_forecast_grids_ens":
        {"template_name": "MergeForecastGridsEnsTemplate"},
    "auto/tpl_modify_forecast_grids":
        {"template_name": "ModifyForecastGridsTemplate"},
    "auto/tpl_modify_historic_grids":
        {"template_name": "ModifyHistoricGridsTemplate"},
    "auto/tpl_postprocess_to_station":
        {"template_name": "PostprocessModelOutputToStationTemplate"},
    "auto/tpl_preprocess_accumulated_nwp":
        {"template_name": "PreprocessAccumulatedParametersNWPTemplate"},
    "auto/tpl_preprocess_e2o_raven":
        {"template_name": "PreprocessE2ORavenTemplate"},
    "auto/tpl_preprocess_eccc_scalar":
        {"template_name": "PreprocessECCCScalar"},
    "auto/tpl_preprocess_instantaneous_nwp":
        {"template_name": "PreprocessInstantaneousParametersNWPTemplate"},
    "auto/tpl_preprocess_nwp_raven":
        {"template_name": "PreprocessNWPRavenTemplate"},
    # Standalone workflows commonly bundled with forecasting projects.
    "auto/wf_import_eo_grids":      {"template_name": "ImportEOGrids"},
    "auto/wf_merge_historic_grids": {"template_name": "MergeHistoricGrids"},
    "auto/wf_modify_forecast_grids": {"template_name": "ModifyForecastGrids"},
    "auto/wf_update_historic_grids": {"template_name": "UpdateHistoricGrids"},
}


def _resolve_forecasting_patterns(
    slots: dict[str, Any], catalog_paths: set[str],
) -> list[dict]:
    """Forecasting project = imports + N basin models + shared templates."""
    out = _resolve_import_patterns(
        slots.get("imports", []), catalog_paths,
        data_types=slots.get("data_types"),
        wants_interpolation=bool(slots.get("wants_interpolation")),
        grid_resolution=slots.get("grid_resolution"),
        forecast_horizon_hours=slots.get("forecast_horizon_hours"),
        wants_visualization=bool(slots.get("wants_visualization")),
    )
    for b in _basins_list(slots):
        out.extend(
            _resolve_basin_pattern(
                b.get("model_adapter"), b.get("basin_name"), catalog_paths,
            )
        )
    # Auto-include shared template patterns with their fixed instance
    # variable values.
    for tpl_path, instance in _FORECASTING_SHARED_TEMPLATES.items():
        if tpl_path in catalog_paths:
            out.append({"pattern": tpl_path, "instances": [dict(instance)]})
    return out


def _resolve_data_import_only_patterns(
    slots: dict[str, Any], catalog_paths: set[str],
) -> list[dict]:
    """Data-import-only project = just the import patterns. No basin, no model."""
    return _resolve_import_patterns(
        slots.get("imports", []), catalog_paths,
        data_types=slots.get("data_types"),
        wants_interpolation=bool(slots.get("wants_interpolation")),
        grid_resolution=slots.get("grid_resolution"),
        forecast_horizon_hours=slots.get("forecast_horizon_hours"),
        wants_visualization=bool(slots.get("wants_visualization")),
    )


def _resolve_basin_only_patterns(
    slots: dict[str, Any], catalog_paths: set[str],
) -> list[dict]:
    """Basin-only project = N basin patterns. No imports."""
    out: list[dict] = []
    for b in _basins_list(slots):
        out.extend(
            _resolve_basin_pattern(
                b.get("model_adapter"), b.get("basin_name"), catalog_paths,
            )
        )
    return out


_COMMON_SLOT_QUESTIONS = {
    "basins": (
        "Which basin(s) and what model adapter does each use? "
        "Format: 'Liard uses raven' or 'Liard with raven, Snare with wflow'."
    ),
    "basin_name": "What basin is this project for? (e.g. Liard, Snare, ...)",
    "model_adapter": (
        "Which model adapter does this basin use? "
        "Options: raven, wflow, hbv96, mesh, delft3d."
    ),
    "imports": (
        "Which data sources do you import? "
        "(e.g. HRDPS, GDPS, GFS, GPM, GLOBSNOW, ...)"
    ),
    "geoDatum": "What geographic datum do your locations use? "
                "(default: WGS 1984)",
    "locations_source": (
        "How are you providing station data? "
        "(csv | yaml | I'll add later)"
    ),
    "region": (
        "Which geographic region or area is this project for? "
        "(e.g. Gulf of Guinea, North Sea, Mediterranean — used to crop "
        "imported grids and orient the Spatial Display map.)"
    ),
}


INTENTS: dict[str, Intent] = {
    "build_forecasting_project": Intent(
        name="build_forecasting_project",
        description="Build a complete flood / hydrological forecasting "
                    "project for one or more basins: imports + models + workflows.",
        keywords=[
            "forecast", "forecasting", "flood", "hydrological",
            "operational", "daily forecast", "predict",
        ],
        required_slots=["basins", "imports"],
        optional_slots=["geoDatum", "locations_source", "region"],
        slot_questions=dict(_COMMON_SLOT_QUESTIONS),
        resolver=_resolve_forecasting_patterns,
    ),

    "build_data_import_only": Intent(
        name="build_data_import_only",
        description="Set up data imports only (no model, no basin). "
                    "For data-engineering work where the model is "
                    "configured separately or already exists.",
        keywords=[
            "import only", "imports only", "just imports", "data import",
            "ingest data", "data ingestion", "fetch data",
            "no model", "without model",
        ],
        required_slots=["imports"],
        optional_slots=["geoDatum", "locations_source", "region"],
        slot_questions=dict(_COMMON_SLOT_QUESTIONS),
        resolver=_resolve_data_import_only_patterns,
    ),

    "build_basin_model_only": Intent(
        name="build_basin_model_only",
        description="Configure one or more basins' hydrological models "
                    "(forecast + historic templates + run workflows) "
                    "without setting up data imports. Imports are added "
                    "separately.",
        keywords=[
            "basin model only", "model only", "configure model",
            "set up the model", "model setup", "model config",
            "no imports", "without imports", "just the model",
        ],
        required_slots=["basins"],
        optional_slots=["geoDatum"],
        slot_questions=dict(_COMMON_SLOT_QUESTIONS),
        resolver=_resolve_basin_only_patterns,
    ),
}


# ---------------------------------------------------------------------------
# Intent classification (LLM)
# ---------------------------------------------------------------------------

def heuristic_intent_from_slots(
    slot_values: dict[str, Any],
) -> str | None:
    """Pick the most likely intent based on which slots are filled.

    Defaults to ``build_forecasting_project`` whenever the slots aren't
    a clean fit for one of the narrower intents — including the "no
    slots at all" case. The reasoning: in a demo / first-time use,
    the full forecasting build is what colleagues will want 90%+ of
    the time, and the failure mode of "too few files emitted because
    we picked a narrower intent" is worse than "extra slot prompt
    asking about imports". The narrower intents only fire when the
    LLM classifier picks them explicitly based on "only / no imports /
    just the model"-style phrasing.
    """
    has_basin = bool(
        slot_values.get("basins")
        or (slot_values.get("basin_name") and slot_values.get("model_adapter"))
    )
    has_imports = bool(slot_values.get("imports"))
    if has_imports and not has_basin:
        return "build_data_import_only"
    # Both (basin + imports) → forecasting; basin alone → forecasting
    # (the configurator will get prompted for imports next); nothing →
    # forecasting. The narrower basin-only path is reachable only via
    # an explicit LLM classification.
    return "build_forecasting_project"


def classify_intent(
    prose: str,
    skill_results: dict[str, Any],
    provider: OllamaProvider | None = None,
    model: str = "qwen2.5:7b-instruct",
) -> dict[str, Any]:
    """Pick the user's intent + extract entities the skills missed.

    The skills already found most structured facts. The LLM's job is
    smaller: pick which intent matches the prose, optionally fill in
    missing entities (e.g. basin name for an unrecognised basin).
    """
    if provider is None:
        from .providers.factory import get_provider_or_ollama
        provider = get_provider_or_ollama(model)

    intent_descriptions = "\n".join(
        f"- {i.name}: {i.description}\n  keywords: {', '.join(i.keywords)}"
        for i in INTENTS.values()
    )
    skills_text = "\n".join(
        f"  {k}: {v}" for k, v in skill_results.items() if v
    ) or "  (none)"

    system = (
        "Classify a configurator's project intent and confirm extracted "
        "entities. RULES:\n"
        "- Pick exactly one intent from the list (or 'unknown' if none "
        "fits).\n"
        "- DEFAULT to build_forecasting_project. Only pick the narrower "
        "  build_basin_model_only or build_data_import_only when the "
        "  user EXPLICITLY says they want just one half — e.g. "
        "  'imports only', 'model only', 'no imports yet', 'without a "
        "  model', 'just data ingestion'. A mention of a basin without "
        "  imports is NOT enough to pick the narrower intent.\n"
        "- ALSO prefer build_data_import_only when the user describes a "
        "  pure data pipeline — they mention interpolating gridded data "
        "  to locations/stations/points, viewing imported series in the "
        "  Data Viewer, or displaying grids in the Spatial Display — "
        "  AND they do NOT mention a hydrological model, basin, "
        "  watershed, forecast workflow, or model adapter (raven, wflow, "
        "  hbv96). Visualization + interpolation in the absence of any "
        "  model reference signals data engineering, not forecasting.\n"
        "- The deterministic skills already found the entities listed; "
        "if you spot any the skills missed, add them. Don't override "
        "what the skills found unless the user explicitly contradicted.\n"
        "- Output ONLY the JSON the schema asks for."
    )
    user = (
        f"Configurator prose:\n  {prose!r}\n\n"
        f"Skills already extracted:\n{skills_text}\n\n"
        f"Available intents:\n{intent_descriptions}\n\n"
        f"Pick the intent and fill in any entities the skills missed."
    )
    schema = {
        "type": "object",
        "properties": {
            "intent": {"type": "string"},
            "entities": {
                "type": "object",
                "additionalProperties": True,
            },
            "reasoning": {"type": "string"},
        },
        "required": ["intent"],
    }
    resp = provider.generate_json(system=system, user=user, schema=schema)
    data = resp.data or {}
    data.setdefault("intent", "unknown")
    data.setdefault("entities", {})
    data.setdefault("reasoning", "")

    # Default-to-forecasting bias: the narrower build_*_only intents
    # are easy for a small LLM to overfit to when the user's prose
    # mentions a basin without imports (or imports without a basin)
    # — even if no explicit "only / just / no model / no imports"
    # signal is present. Demote a narrower pick to forecasting when
    # the prose contains no narrowing keyword. This preserves the
    # narrower intents for cases where the user is explicit
    # ("set up imports only", "model only — no NWP yet") but defaults
    # to the richer build in ambiguous cases.
    picked = data.get("intent") or ""
    if picked in {"build_basin_model_only", "build_data_import_only"}:
        if not _prose_signals_narrower_intent(prose):
            data["intent"] = "build_forecasting_project"
            note = (
                f"promoted {picked} → build_forecasting_project "
                "(no explicit 'only' / 'no imports' / 'model only' "
                "signal in prose; default-to-forecasting policy)"
            )
            data["reasoning"] = (
                f"{data['reasoning']}\n{note}" if data["reasoning"] else note
            )
    elif picked not in INTENTS and picked != "unknown":
        # LLM made up an intent name not in the registry. Treat as
        # ambiguous and default to forecasting.
        data["intent"] = "build_forecasting_project"

    return data


# Words/phrases that signal the user *deliberately* wants a narrower
# intent. When present in the prose, the default-to-forecasting bias
# in ``classify_intent`` stands down. Order matters only for human
# readability — matching is substring-based, case-insensitive.
_NARROWING_PHRASES: tuple[str, ...] = (
    "only", "just the", "just imports", "just import", "just data",
    "just the model", "just model",
    "no model", "without model", "without a model",
    # Basin-negation phrases. "no basin model" does NOT contain the
    # substring "no model" (a "basin " sits between), so these must be
    # listed explicitly. Kept in lockstep with chat_step's
    # _INTENT_OVERRIDE_PHRASES so turn-1 demotion and mid-chat override
    # agree on what counts as a data-import-only signal.
    "no basin", "no basin model", "without a basin", "without basin",
    "no imports", "without imports", "without nwp",
    "no nwp", "no forecast",
    "model only", "model-only", "imports only", "import only",
    "import-only", "model only.", "model only,",
    "data only", "data ingestion only",
    # Phrases that imply a pure data pipeline (import + view) with no
    # basin model in scope. Mentioning the FEWS Data Viewer or Spatial
    # Display panels, or a grid → point interpolation step, is a strong
    # signal the user wants build_data_import_only even when they don't
    # say "only" explicitly.
    "data viewer", "spatial display",
    "interpolate the grid", "interpolate the gridded",
    "interpolate gridded", "interpolate to locations",
    "interpolate to stations", "interpolate to points",
)


def _prose_signals_narrower_intent(prose: str) -> bool:
    """True if the user's prose contains an explicit narrowing signal.

    Substring match, case-insensitive. False-positive risk is low —
    "only" is a strong content word; bare appearances like "the only
    basin" still count and that's the intended bias (when in doubt,
    take the user at their word that they want a narrower build).
    """
    lower = (prose or "").lower()
    return any(phrase in lower for phrase in _NARROWING_PHRASES)


# ---------------------------------------------------------------------------
# Slot elicitation
# ---------------------------------------------------------------------------

def next_unfilled_question(
    intent: Intent, slots: dict[str, Any],
) -> str | None:
    """Find the most important unfilled REQUIRED slot and return its question."""
    for slot_name in intent.required_slots:
        value = slots.get(slot_name)
        if value is None or (isinstance(value, list) and not value):
            return intent.slot_questions.get(
                slot_name, f"Please provide {slot_name}."
            )
    return None


def is_intent_ready(intent: Intent, slots: dict[str, Any]) -> bool:
    """All required slots filled?"""
    for slot_name in intent.required_slots:
        value = slots.get(slot_name)
        if value is None or (isinstance(value, list) and not value):
            return False
    return True


# ---------------------------------------------------------------------------
# Compose all slot fills from any text
# ---------------------------------------------------------------------------

def fill_slots_from_text(
    text: str, slots: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Apply skills to text, merge into slots additively.

    Returns ``(updated_slots, notes)``. Lists merge unioned; scalars fill
    only when the slot is empty (so we never overwrite an explicit user
    value with a later skill match).
    """
    extracted = extract_skills(text)
    new_slots = dict(slots)
    notes: list[str] = []
    for k, v in extracted.items():
        if v is None or v == []:
            continue
        existing = new_slots.get(k)
        if isinstance(v, list):
            merged = list(existing or [])
            for item in v:
                if item not in merged:
                    merged.append(item)
                    notes.append(f"+{k}={item}")
            new_slots[k] = merged
        else:
            if existing is None:
                new_slots[k] = v
                notes.append(f"+{k}={v}")
    return new_slots, notes


# ---------------------------------------------------------------------------
# Input directory awareness
# ---------------------------------------------------------------------------

# Per-intent expectations of what should live in the project's inputs/.
# CSVs are the canonical tabular set; yamls are project-specific
# singletons (highly recommended but project-defined).
INTENT_INPUT_EXPECTATIONS: dict[str, dict[str, list[str]]] = {
    "build_forecasting_project": {
        "required_csvs": [
            "locations.csv", "parameters.csv",
        ],
        "recommended_csvs": [
            "qualifiers.csv", "thresholdWarningLevels.csv",
        ],
        # Project-specific yamls the configurator must author themselves.
        # These encode operational/UI policy that no automation can
        # responsibly invent.
        "recommended_yamls_examples": [
            "modifierTypes.yaml", "modifierDisplay.yaml",
            "locationIcons.yaml",
        ],
        # Yamls the runner auto-generates — configurator does NOT need
        # to author these. Surfaced to the reply LLM so it doesn't
        # falsely ask for them.
        "auto_generated_yamls": [
            "filtersFile.yaml (LLM-drafted)",
            "topology.yaml (auto from workflows)",
            "displayGroupsFile.yaml (bundled + project-trimmed)",
            "gridsFile.yaml (bundled + project-trimmed)",
            "locationSetsFile.yaml (id-stub from references)",
            "moduleInstanceDescriptors.yaml (auto-derived)",
            "workflowDescriptors.yaml (auto-derived)",
            "idMap*.yaml (bundled + project-trimmed)",
            "timeSteps.yaml (bundled standard)",
            "import/exportUnitConversions.yaml (bundled standard)",
        ],
    },
    "build_data_import_only": {
        "required_csvs": ["locations.csv", "parameters.csv"],
        "recommended_csvs": [],
        "recommended_yamls_examples": [],
        "auto_generated_yamls": [
            "idMap*.yaml (bundled + project-trimmed)",
            "moduleInstanceDescriptors.yaml (auto-derived)",
            "workflowDescriptors.yaml (auto-derived)",
            "timeSteps.yaml (bundled standard)",
        ],
    },
    "build_basin_model_only": {
        "required_csvs": [],
        "recommended_csvs": [],
        "recommended_yamls_examples": [
            "idImportRaven.yaml", "idExportRaven.yaml",
            "idImportwflow.yaml", "idExportwflow.yaml",
            "ravenParameters.yaml",
        ],
        "auto_generated_yamls": [
            "moduleInstanceDescriptors.yaml (auto-derived)",
            "workflowDescriptors.yaml (auto-derived)",
        ],
    },
}


def scan_inputs(inputs_dir: Any) -> dict[str, list[str]]:
    """Walk an inputs directory; return what's present.

    ``inputs_dir`` is a Path or None. Missing directory = empty.
    """
    from pathlib import Path
    out = {"csvs": [], "yamls": []}
    if not inputs_dir or not Path(inputs_dir).is_dir():
        return out
    p = Path(inputs_dir)
    out["csvs"] = sorted(f.name for f in p.glob("*.csv"))
    out["yamls"] = sorted(f.name for f in p.glob("*.yaml"))
    out["yamls"] += sorted(f.name for f in p.glob("*.yml"))
    return out


def compute_input_status(
    intent_name: str | None,
    scan: dict[str, list[str]],
    slots: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare scan against intent's expectations. Return a status dict.

    Keys returned:
      - csvs_present: list[str]
      - csvs_required_missing: list[str]
      - csvs_recommended_missing: list[str]
      - yamls_present_count: int
      - yamls_recommended_examples: list[str]  # for hints in the reply
      - extra_notes: list[str]                 # slot-conditional reminders
    """
    expectations = INTENT_INPUT_EXPECTATIONS.get(intent_name or "", {})
    required = set(expectations.get("required_csvs", []))
    recommended = set(expectations.get("recommended_csvs", []))
    present_csvs = set(scan.get("csvs", []))
    present_yamls = scan.get("yamls", [])

    # Slot-conditional reminders the reply LLM should surface.
    extra_notes: list[str] = []
    if slots and slots.get("wants_interpolation"):
        extra_notes.append(
            "Interpolation requested: locations.csv must list the "
            "stations (with lat/lon) where the gridded data should be "
            "interpolated TO. Without it the interpolation step has no "
            "targets."
        )
    if (slots and slots.get("imports") and not slots.get("region")):
        extra_notes.append(
            "No region set. Imported grids will use the bundled default "
            "extent (MacKenzie-shaped). Mention a region (Gulf of "
            "Guinea, North Sea, Mediterranean, ...) to crop the NWP "
            "grids and orient the Spatial Display map for this project."
        )

    return {
        "csvs_present": sorted(present_csvs),
        "csvs_required_missing": sorted(required - present_csvs),
        "csvs_recommended_missing": sorted(recommended - present_csvs),
        "yamls_present_count": len(present_yamls),
        "yamls_recommended_examples": list(
            expectations.get("recommended_yamls_examples", [])
        ),
        "auto_generated_yamls": list(
            expectations.get("auto_generated_yamls", [])
        ),
        "extra_notes": extra_notes,
    }


# ---------------------------------------------------------------------------
# Conversational reply
# ---------------------------------------------------------------------------

def compose_reply(
    user_message: str,
    state: dict[str, Any],
    intent: Intent | None,
    slots: dict[str, Any],
    notes: list[str],
    next_question: str | None,
    is_ready: bool,
    new_patterns: list[str],
    input_status: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
    recent_edit: str | None = None,
    provider: OllamaProvider | None = None,
    model: str = "qwen2.5:7b-instruct",
) -> str:
    """LLM composes the agent's user-facing reply.

    The deterministic engine already updated state. The LLM's only
    job is to PHRASE a natural acknowledgment + question + optional
    remark. It can't change state — anything it says is just text.

    Concerns the LLM is encouraged to raise (with explicit examples
    in the prompt):
      - Unusual adapter / basin pairings (Snare typically uses wflow,
        not raven; flag if user said otherwise).
      - Missing CSV / yaml hints (suggest dropping locations.csv).
      - Apparent contradictions between turns.

    Style: 1-3 sentences, plain English, no JSON, no bullet lists.
    """
    if provider is None:
        from .providers.factory import get_provider_or_ollama
        provider = get_provider_or_ollama(model)

    intent_name = intent.name if intent else "(none)"

    # Split slots into known/unknown so the LLM can't accidentally
    # mention an empty one as if it were filled.
    slot_keys_for_intent: list[str] = []
    if intent:
        slot_keys_for_intent = list(
            (intent.required_slots or []) + (intent.optional_slots or [])
        )
    # Also include any extra keys present in slots but not declared by
    # the intent (e.g. cross-cutting `geoDatum`, `location`).
    for k in slots:
        if k not in slot_keys_for_intent:
            slot_keys_for_intent.append(k)

    known_lines: list[str] = []
    unknown_lines: list[str] = []
    known_values_flat: list[str] = []  # for the post-LLM guard
    for k in slot_keys_for_intent:
        v = slots.get(k)
        if v is None or v == [] or v == "":
            unknown_lines.append(k)
        else:
            known_lines.append(f"{k} = {_format_slot_value(v)}")
            known_values_flat.extend(_flatten_slot_value(v))
    # Highlight basins/imports in a natural form the LLM can read directly,
    # to discourage "should I add Snare?" when Snare is already present.
    basins_in_state = slots.get("basins") or []
    if basins_in_state and isinstance(basins_in_state, list) and isinstance(basins_in_state[0], dict):
        basin_phrases = [
            f"{b.get('basin_name')} ({b.get('model_adapter')})"
            for b in basins_in_state if b.get("basin_name")
        ]
        if basin_phrases:
            known_lines.insert(
                0,
                f"Basins already in project: {', '.join(basin_phrases)}",
            )
    imports_in_state = slots.get("imports") or []
    if isinstance(imports_in_state, list) and imports_in_state:
        known_lines.insert(
            0 if not basins_in_state else 1,
            f"Imports already in project: {', '.join(imports_in_state)}",
        )
    known_text = "\n".join(f"  - {ln}" for ln in known_lines) or "  (none)"
    unknown_text = ", ".join(unknown_lines) or "(none)"

    new_pat_text = (
        ", ".join(p.split("/")[-1] for p in new_patterns)
        if new_patterns else "(none new)"
    )

    # Render input status compactly for the prompt.
    if input_status:
        present_csvs = input_status.get("csvs_present", [])
        missing_required = input_status.get("csvs_required_missing", [])
        missing_recommended = input_status.get("csvs_recommended_missing", [])
        n_yamls = input_status.get("yamls_present_count", 0)
        yaml_examples = input_status.get("yamls_recommended_examples", [])
        auto_yamls = input_status.get("auto_generated_yamls", [])
        input_text = (
            f"  inputs/ has: {len(present_csvs)} CSV(s) "
            f"({', '.join(present_csvs) or 'none'}), "
            f"{n_yamls} yaml(s)\n"
        )
        if missing_required:
            input_text += (
                f"  REQUIRED CSVs missing: {', '.join(missing_required)}\n"
            )
        if missing_recommended:
            input_text += (
                f"  Recommended CSVs missing: {', '.join(missing_recommended)}\n"
            )
        if yaml_examples:
            input_text += (
                f"  Configurator-required yamls (must author): "
                f"{', '.join(yaml_examples)}\n"
            )
        if auto_yamls:
            input_text += (
                f"  AUTO-GENERATED (don't ask user for these): "
                f"{', '.join(auto_yamls[:5])}{'...' if len(auto_yamls) > 5 else ''}\n"
            )
        extra_notes = input_status.get("extra_notes") or []
        for note in extra_notes:
            input_text += f"  Note: {note}\n"
    else:
        input_text = "  (input directory not scanned)\n"

    system = (
        "You are a helpful assistant guiding a configurator through "
        "authoring a Delft-FEWS project ONE MODULE AT A TIME (an import, "
        "a basin model, a visualization) — not by generating the whole "
        "project in one shot. The configurator can edit the in-progress "
        "project mid-chat: add a module, remove a module, or change a "
        "variable (e.g. grid resolution, forecast horizon), either with "
        "slash commands (/add, /remove, /set, /build, /list) or in plain "
        "language ('also drop RDPS', 'make GFS half-degree').\n"
        "The deterministic engine has ALREADY applied any such edit and "
        "updated state before you reply — your job is to PHRASE a natural "
        "reply. You do not mutate state yourself; you acknowledge what the "
        "engine already did, ask the next question, or suggest a next "
        "step.\n"
        "\n"
        "ANTI-FABRICATION RULE — read carefully:\n"
        "Only reference values that appear under KNOWN. Treat values "
        "under UNKNOWN as unstated by the user. NEVER fill in a value "
        "from your own training. If `model_adapter` is in UNKNOWN, do "
        "NOT mention raven/wflow/hbv/etc. — even if they sound "
        "plausible for that basin. If `imports` is in UNKNOWN, do NOT "
        "name HRDPS/GFS/etc. The user said what they said; don't "
        "extrapolate.\n"
        "\n"
        "Bad reply (fabricated): 'Mackenzie uses raven.' (when "
        "model_adapter is in UNKNOWN)\n"
        "Good reply: 'Got it — Mackenzie basin. Which hydrological "
        "model adapter does it use (raven, wflow, hbv96)?'\n"
        "\n"
        "ACTIONS — offers vs. completed edits (read carefully):\n"
        "You do NOT mutate state yourself, and you must NEVER make a "
        "phantom OFFER that waits on a 'yes' — phrases like 'Would you "
        "like me to add…?', 'Shall I include…?', 'Want me to remove…?'. "
        "If the user said 'yes' to such an offer, nothing would happen "
        "and they'd be confused. The only engine-wired yes/no flow is a "
        "pattern-removal proposal that appears in Engine notes (you "
        "don't invent it).\n"
        "BUT: when a RECENT EDIT line is present below, the engine has "
        "ALREADY performed that edit this turn — acknowledge it as DONE, "
        "in the past tense ('Removed RDPS', 'Set GFS to half-degree'), "
        "and never re-offer it. When the user wants a change that has "
        "NOT happened, don't ask permission — tell them the exact "
        "phrasing to use ('say \"also drop RDPS\"', 'say \"make GFS "
        "half-degree\"', or use /remove, /set).\n"
        "\n"
        "Bad (phantom offer): 'Would you like me to add the Snare "
        "basin?' (nothing happens on 'yes')\n"
        "Good (not yet done): 'Snare isn't in the project yet — to add "
        "it, say \"also add the Snare basin using raven\".'\n"
        "Good (RECENT EDIT confirms it): 'Done — removed RDPS. Build "
        "the next import with /build <name>, or keep adding modules.'\n"
        "\n"
        "RULES:\n"
        "1) Reply in 1-3 sentences. Plain English. No JSON, no "
        "   bullets, no emoji.\n"
        "2) Reference KNOWN values BY NAME (e.g. 'Mackenzie basin', "
        "   'HRDPS and GFS'). Don't say 'your basin' when you know "
        "   the name.\n"
        "3) Never ask the configurator for any file listed under "
        "   AUTO-GENERATED — those are produced by the runner. Only "
        "   ask for files under 'Configurator-required yamls' or in "
        "   'REQUIRED CSVs missing'.\n"
        "4) If a `next_question` is given, ask it naturally. If "
        "   `is_ready` is true AND no required CSVs missing, "
        "   encourage 'done'. If `is_ready` but CSVs missing, mention "
        "   which.\n"
        "5) Flag concerns ONLY when warranted by the data: "
        "   contradictions across turns, or unusual basin/adapter "
        "   pairings AMONG KNOWN VALUES. Don't invent concerns.\n"
        "6) If nothing was understood (KNOWN is empty), ask for "
        "   clarification — don't pretend.\n"
        "7) WARNINGS are LOUD FAILURES — if any are listed below, you "
        "   MUST mention each one verbatim or paraphrased, and ask the "
        "   user to confirm, correct, or 'continue anyway'. Never bury "
        "   a warning. Never silently accept inputs that are flagged.\n"
        "8) Don't make a phantom OFFER that waits on a 'yes' "
        "   ('Want me to…?', 'Shall I…?'). Two allowed moves instead: "
        "   (a) if a RECENT EDIT line is present, acknowledge that edit "
        "   as already DONE (past tense); (b) for a change the user "
        "   hasn't requested yet, tell them the exact phrasing or slash "
        "   command to use. The only engine-wired yes/no is a "
        "   pattern-removal proposal in Engine notes.\n"
        "9) NEVER ask whether to add/include something that is "
        "   ALREADY in KNOWN. If a basin or import appears under "
        "   'Basins already in project' or 'Imports already in "
        "   project', it is DONE — do not ask 'should I also add "
        "   X?'. The engine already added it. You MAY, however, "
        "   suggest how to remove or change it ('to drop it, say "
        "   \"remove X\"').\n"
        "10) STEPWISE: after acknowledging, nudge toward ONE concrete "
        "   next step — build the module just configured (/build "
        "   <name>), add the next module, or (if ready) 'done' to "
        "   assemble. Prefer one small module over pushing the whole "
        "   project at once.\n"
        "11) Output JSON {\"reply\": \"...\"}, nothing else."
    )

    warnings_text = ""
    if warnings:
        warnings_text = "\nWARNINGS (must be surfaced in the reply):\n" + "\n".join(
            f"  - {w}" for w in warnings
        ) + "\n"

    recent_edit_text = ""
    if recent_edit:
        recent_edit_text = (
            f"\nRECENT EDIT (engine ALREADY applied this — acknowledge as "
            f"DONE, past tense; do NOT re-offer it):\n  {recent_edit}\n"
        )

    user = (
        f"User just said: {user_message!r}\n"
        f"Active intent: {intent_name}\n"
        f"\n"
        f"KNOWN (filled slots — safe to reference):\n{known_text}\n"
        f"UNKNOWN (empty slots — DO NOT mention values for these): "
        f"{unknown_text}\n"
        f"{warnings_text}"
        f"{recent_edit_text}"
        f"\n"
        f"New patterns added this turn: {new_pat_text}\n"
        f"Engine notes: {'; '.join(notes) or '(none)'}\n"
        f"Input directory status:\n{input_text}"
        f"Next deterministic question: {next_question or '(none)'}\n"
        f"Ready to write: {is_ready}\n\n"
        f"Compose the reply."
    )

    schema = {
        "type": "object",
        "properties": {"reply": {"type": "string"}},
        "required": ["reply"],
    }

    try:
        resp = provider.generate_json(system=system, user=user, schema=schema)
        text = (resp.data or {}).get("reply", "").strip()
        if text:
            cleaned = _strip_fabricated_add_offers(text, known_values_flat)
            if cleaned:
                return cleaned
            # cleaned came back None → reply was entirely a fabricated
            # offer; fall through to the deterministic template.
    except Exception:
        pass

    # Fallback: deterministic template if LLM fails.
    parts = []
    if new_patterns:
        parts.append(
            f"Got it — added {len(new_patterns)} pattern(s): "
            f"{', '.join(p.split('/')[-1] for p in new_patterns)}."
        )
    elif notes:
        parts.append("Updated.")
    if next_question:
        parts.append(next_question)
    elif is_ready:
        parts.append("Project looks complete. Type 'done' to write project.yaml.")
    return " ".join(parts) if parts else "I didn't catch that — could you rephrase?"


def _format_slot_value(v: Any) -> str:
    """Compact display of a slot value for the LLM prompt."""
    if isinstance(v, list):
        if not v:
            return "[]"
        if v and isinstance(v[0], dict):
            return "[" + ", ".join(
                "+".join(str(x) for x in d.values()) for d in v
            ) + "]"
        return "[" + ", ".join(str(x) for x in v[:8]) + ("...]" if len(v) > 8 else "]")
    return str(v)


def _flatten_slot_value(v: Any) -> list[str]:
    """Yield individual referenceable tokens from a slot value.

    Used by the post-LLM guard to detect "should I add <X>?" leaks
    where <X> is already in state — feeds the case-insensitive match
    against the LLM's reply.
    """
    out: list[str] = []
    if isinstance(v, list):
        for item in v:
            if isinstance(item, dict):
                for x in item.values():
                    if x:
                        out.append(str(x))
            elif item:
                out.append(str(item))
    elif v:
        out.append(str(v))
    return out


# Matches "should I add Snare", "want me to include HRDPS", "shall I
# add Liard basin", etc. Captures the named entity for the case-
# insensitive membership check against KNOWN values.
_FABRICATED_ADD_OFFER = re.compile(
    r"(?:should I|shall I|would you like (?:me )?to|want me to|do you want (?:me )?to)"
    r"\s+(?:also\s+)?(?:add|include|set up|register)\s+"
    r"(?:the\s+)?(?P<name>[A-Z][A-Za-z0-9]+)",
    re.IGNORECASE,
)


def _strip_fabricated_add_offers(reply: str, known_values: list[str]) -> str | None:
    """Return cleaned reply, or None if the reply still leaks.

    If the LLM asks "should I add <X>?" and <X> is already in KNOWN,
    we strip the offending sentence. If that empties the reply, the
    caller falls back to the deterministic template.
    """
    if not reply or not known_values:
        return reply
    known_lower = {v.lower() for v in known_values}
    kept: list[str] = []
    leaked = False
    # Split on sentence boundaries cheaply; we only care about whole
    # sentences that contain the offer.
    parts = re.split(r"(?<=[.!?])\s+", reply.strip())
    for part in parts:
        m = _FABRICATED_ADD_OFFER.search(part)
        if m and m.group("name").lower() in known_lower:
            leaked = True
            continue
        kept.append(part)
    if not leaked:
        return reply
    cleaned = " ".join(kept).strip()
    return cleaned or None


# ---------------------------------------------------------------------------
# Meta intent: status-check
# ---------------------------------------------------------------------------
#
# Unlike the build intents above, `status_check` doesn't generate
# patterns or own a slot ontology — it answers meta-questions about
# the current project state ("what's missing?", "summarise", "what
# files do I still need?"). It runs per-turn before the normal
# pipeline and never overwrites `state["intent"]`, so the
# configurator can interleave status queries with build messages
# without losing track of which build intent they're in.
#
# Deterministic tools (scan_inputs, compute_input_status,
# build_status_report) supply the data; compose_status_reply
# paraphrases it. The LLM is told the report is the SOLE source of
# truth — it cannot invent slots, files, or patterns.

# Phrases that strongly suggest a status meta-query rather than a
# new build input. Matched case-insensitive against the stripped
# message. Keep high-precision — better to miss (user rephrases)
# than to mis-route a real config message into status mode.
_STATUS_PHRASES: tuple[str, ...] = (
    "what is missing", "what's missing", "whats missing",
    "what am i missing", "what is still missing",
    "what do i need", "what do i still need", "what else do i need",
    "what is needed", "what's needed", "whats needed",
    "what files do i need", "which files do i need",
    "what's left", "whats left", "what is left",
    "what do we have", "what have we got", "what's done",
    "show status", "show me the status", "current status",
    "project status", "status check", "status report",
    "where are we", "where do we stand",
    "summarize", "summarise",
)

# Single-token messages that count as status queries by themselves.
# Both bare and slash forms — '/status' is the canonical slash command,
# 'status' / 'summary' / '?' are friendly aliases.
_STATUS_TOKENS: frozenset[str] = frozenset({
    "status", "/status", "summary", "?",
})


def detect_status_query(text: str) -> bool:
    """True iff the message looks like a meta-query about project state."""
    lower = text.strip().lower().rstrip("?.!,").strip()
    if not lower:
        return False
    if lower in _STATUS_TOKENS:
        return True
    return any(phrase in lower for phrase in _STATUS_PHRASES)


def build_status_report(
    state: dict[str, Any],
    input_status: dict[str, Any] | None,
) -> dict[str, Any]:
    """Snapshot project state for prose synthesis or diagnostic dump.

    Pure function over ``state`` + ``input_status`` (the latter
    typically produced by ``compute_input_status(scan_inputs(...))``).
    No LLM calls, no disk I/O — safe to invoke on every turn.
    """
    intent_name = state.get("intent") or ""
    intent = INTENTS.get(intent_name)
    slots = state.get("slots") or {}

    required_filled: list[str] = []
    required_missing: list[str] = []
    if intent:
        for slot_name in intent.required_slots:
            v = slots.get(slot_name)
            if v is None or v == [] or v == "":
                required_missing.append(slot_name)
            else:
                required_filled.append(slot_name)
    optional_filled = [
        s for s in (intent.optional_slots if intent else [])
        if slots.get(s) not in (None, [], "")
    ]

    patterns = state.get("patterns") or []
    pattern_names = [
        str(p.get("pattern", "")).rsplit("/", 1)[-1] for p in patterns
    ]

    return {
        "intent": intent_name or None,
        "project_name": state.get("name"),
        "filled_slots": {k: v for k, v in slots.items() if v},
        "required_slots_filled": required_filled,
        "required_slots_missing": required_missing,
        "optional_slots_filled": optional_filled,
        "patterns_count": len(patterns),
        "patterns": pattern_names,
        "warnings": list(state.get("warnings") or []),
        "csvs_present": list((input_status or {}).get("csvs_present") or []),
        "csvs_required_missing": list(
            (input_status or {}).get("csvs_required_missing") or []
        ),
        "csvs_recommended_missing": list(
            (input_status or {}).get("csvs_recommended_missing") or []
        ),
        "yamls_present_count": (input_status or {}).get("yamls_present_count", 0),
        "yamls_recommended_examples": list(
            (input_status or {}).get("yamls_recommended_examples") or []
        ),
        "auto_generated_yamls": list(
            (input_status or {}).get("auto_generated_yamls") or []
        ),
        "ready": bool(intent) and not required_missing,
    }


def status_prose_fallback(report: dict[str, Any]) -> str:
    """Deterministic prose summary — used when the LLM is unavailable."""
    parts: list[str] = []
    intent_name = report.get("intent")
    if intent_name:
        parts.append(f"Intent: {intent_name}.")
    else:
        parts.append(
            "I haven't classified your project intent yet — tell me what "
            "you want to build (e.g. 'forecasting project for the Liard "
            "basin using Raven with HRDPS and GFS imports')."
        )
    if report.get("required_slots_filled"):
        parts.append(
            "Filled: " + ", ".join(report["required_slots_filled"]) + "."
        )
    if report.get("required_slots_missing"):
        parts.append(
            "Still need: " + ", ".join(report["required_slots_missing"]) + "."
        )
    if report.get("csvs_required_missing"):
        parts.append(
            "Missing required CSVs (drop into inputs/): "
            + ", ".join(report["csvs_required_missing"]) + "."
        )
    if report.get("csvs_recommended_missing"):
        parts.append(
            "Recommended CSVs not yet provided: "
            + ", ".join(report["csvs_recommended_missing"]) + "."
        )
    yamls = report.get("yamls_recommended_examples") or []
    if yamls:
        parts.append(
            "Configurator-authored yamls you may want: "
            + ", ".join(yamls[:4]) + "."
        )
    if report.get("warnings"):
        parts.append(
            "Open warnings: " + "; ".join(report["warnings"][:3]) + "."
        )
    if report.get("patterns_count"):
        parts.append(f"Patterns resolved so far: {report['patterns_count']}.")
    if report.get("ready") and not report.get("csvs_required_missing"):
        parts.append("Ready to write — type 'done'.")
    return " ".join(parts)


def compose_status_reply(
    user_message: str,
    report: dict[str, Any],
    provider: OllamaProvider | None = None,
    model: str = "qwen2.5:7b-instruct",
) -> str:
    """LLM-composed prose summary of the current project state.

    The ``report`` (from ``build_status_report``) is the SOLE source of
    truth — the LLM is instructed to paraphrase it and nothing more.
    Falls back to ``status_prose_fallback`` if the LLM is unavailable.
    """
    if provider is None:
        from .providers.factory import get_provider_or_ollama
        provider = get_provider_or_ollama(model)

    system = (
        "You answer a configurator's status question about a Delft-FEWS "
        "project. You are given a STATUS REPORT — a snapshot of project "
        "state produced by deterministic tools. Your only job is to "
        "paraphrase its contents in prose.\n"
        "\n"
        "RULES:\n"
        "1) Use ONLY values from the report. Do not invent file names, "
        "   slot values, basins, patterns, or warnings.\n"
        "2) 2-5 sentences, plain English. No bullet lists, no JSON in "
        "   the reply body, no emoji.\n"
        "3) Mention concretely what is filled and what is still needed. "
        "   If CSVs are missing, name them. If required slots are "
        "   missing, name them.\n"
        "4) Never ask the configurator for any file listed under "
        "   `auto_generated_yamls` — those are produced by the runner.\n"
        "5) End by gently nudging the user toward the most impactful "
        "   next step (provide a missing CSV, fill a missing slot, type "
        "   'done', etc).\n"
        "6) If `intent` is null, ask the user to describe what they want "
        "   to build — don't speculate.\n"
        "7) Output JSON {\"reply\": \"...\"}, nothing else."
    )
    user = (
        f"User question: {user_message!r}\n\n"
        f"Status report:\n{json.dumps(report, indent=2, default=str)}\n\n"
        f"Compose the status reply."
    )
    schema = {
        "type": "object",
        "properties": {"reply": {"type": "string"}},
        "required": ["reply"],
    }
    try:
        resp = provider.generate_json(system=system, user=user, schema=schema)
        text = (resp.data or {}).get("reply", "").strip()
        if text:
            return text
    except Exception:
        pass
    return status_prose_fallback(report)


# ---------------------------------------------------------------------------
# Meta intent: help / explain-concept
# ---------------------------------------------------------------------------
#
# Answers system-meta questions like "what is a slot?", "explain
# patterns", "what does done do?". Served from a curated static
# glossary — deterministic, no LLM, no fabrication risk. New
# configurators don't yet know what a "slot" or "pattern" means in
# this system; without this path they get a vacuous reply.
#
# Routing: this intent fires only when the message contains BOTH
# a help phrase ("what is", "explain", "tell me about", ...) AND
# a known concept word (slot, pattern, intent, blueprint, ...).
# That makes it mutually exclusive with `status_check` —
# "what is missing?" has a help phrase but no concept, so it
# falls through to status; "what is a slot?" has both, so it
# routes here.

_HELP_PHRASES: tuple[str, ...] = (
    "what is", "what's", "whats", "what are",
    "what does", "what do",
    "explain", "explain me",
    "how do i", "how does", "how do",
    "help me understand", "tell me about",
    "define", "meaning of",
)

_HELP_TOKENS: frozenset[str] = frozenset({"help", "/help"})


# Canonical concept → chat-ready explanation. Keys are normalised
# (singular, lowercase, no punctuation). Bodies are written in 2-3
# sentences of plain English suitable for a configurator who's
# never seen this system before.
_CONCEPT_ENTRIES: dict[str, dict[str, str]] = {
    "slot": {
        "title": "Slot",
        "body": (
            "A typed parameter I collect during chat — for example "
            "basin_name, model_adapter, imports, geoDatum. Required "
            "slots must be filled before I can write project.yaml; "
            "optional ones are nice-to-have. I extract slot values "
            "from your prose using deterministic regex skills first, "
            "and only ask the LLM to fill gaps."
        ),
    },
    "intent": {
        "title": "Intent",
        "body": (
            "The kind of project you want to build. Three build "
            "intents: build_forecasting_project (imports + basin "
            "model + workflows), build_data_import_only (just data "
            "ingest), build_basin_model_only (just the model, no "
            "imports). Plus two meta intents that don't build "
            "anything — status_check (summarise current state) and "
            "help (explain concepts)."
        ),
    },
    "pattern": {
        "title": "Pattern",
        "body": (
            "A reusable bundle of FEWS XML files for one capability "
            "— e.g. 'import HRDPS forecasts' or 'run a Raven basin "
            "model'. Lives in patterns/auto/<name>/pattern.yaml. One "
            "pattern, many instances — the Raven pattern handles "
            "Liard, Snare, Athabasca, etc. as different values "
            "plugged into {{ basin_name }}."
        ),
    },
    "blueprint": {
        "title": "Blueprint (project.yaml)",
        "body": (
            "The list of patterns to instantiate with which variable "
            "values, plus singleton seeds. Written to your session "
            "folder when you type 'done'. This is the only "
            "project-level artefact you need to keep in version "
            "control — everything else gets re-rendered from it."
        ),
    },
    "session": {
        "title": "Session folder",
        "body": (
            "sessions/<username>_<datetime>/ holds your chat state "
            "(.chat_state.json), history (.chat_history.json), "
            "markdown transcript (_conversation.md), app log "
            "(_app.log), uploaded input files (inputs/), and the "
            "final project.yaml once you type 'done'. Reopen the "
            "same folder from the sidebar to resume."
        ),
    },
    "inputs": {
        "title": "Inputs folder",
        "body": (
            "The 'Project inputs' uploader in the sidebar drops "
            "files into your session's inputs/ folder. The agent "
            "scans this every turn so it knows what's still missing. "
            "Accepted: CSV, yaml, shapefile parts "
            "(.shp/.dbf/.shx/.prj/.cpg), json, txt."
        ),
    },
    "csv": {
        "title": "CSV files",
        "body": (
            "Tabular inputs the configurator provides. For a "
            "forecasting project the required CSVs are locations.csv "
            "(station metadata) and parameters.csv (parameter "
            "definitions). Recommended: qualifiers.csv, "
            "thresholdWarningLevels.csv. Drop them into the inputs/ "
            "folder via the sidebar uploader."
        ),
    },
    "yaml": {
        "title": "YAML inputs",
        "body": (
            "Configurator-authored singletons that encode "
            "project-specific policy — modifierTypes.yaml "
            "(operator interventions), locationIcons.yaml (map "
            "icons), modifierDisplay.yaml. Optional but recommended. "
            "Many other yamls (filtersFile, gridsFile, idMaps, "
            "timeSteps, ...) are auto-generated — you don't have to "
            "author those."
        ),
    },
    "shapefile": {
        "title": "Shapefile",
        "body": (
            "Basin geometry (Watersheds + Extent). Loaded by FEWS "
            "at runtime, not parsed by the agent. Upload all "
            "components together (.shp, .dbf, .shx, .prj, .cpg) — "
            "the agent just stages them in inputs/."
        ),
    },
    "import": {
        "title": "Import",
        "body": (
            "A data source the agent imports into FEWS. Known ECCC: "
            "HRDPS, GDPS, RDPS, REPS, HRDPA, RDPA. NOAA: GFS, NAM, "
            "SREF. Satellite precip: GPM, GSMAP. Snow: GLOBSNOW, "
            "SNODAS. Each maps to a pattern in the library."
        ),
    },
    "adapter": {
        "title": "Model adapter",
        "body": (
            "Which hydrological model code FEWS calls to run the "
            "basin simulation. Supported: raven, wflow, hbv96, mesh, "
            "delft3d. Each basin in the project gets exactly one "
            "adapter."
        ),
    },
    "basin": {
        "title": "Basin",
        "body": (
            "The watershed being modelled. Tutorial basins are Liard "
            "and Snare; any other capitalised name is treated as a "
            "project-specific basin (e.g. 'Mackenzie basin', "
            "'Saskatchewan watershed')."
        ),
    },
    "warning": {
        "title": "Warning",
        "body": (
            "A loud failure surfaced when an input looks wrong — "
            "e.g. an import name with no matching pattern in the "
            "library, or a basin name that looks like an English "
            "word. 'done' is refused while warnings are open; use "
            "'force-done' to override or send a correction."
        ),
    },
    "deriver": {
        "title": "Deterministic deriver",
        "body": (
            "Code that walks already-rendered XMLs and produces a "
            "single file (Topology, ModuleInstanceDescriptors, "
            "WorkflowDescriptors, LocationSets stub, "
            "sa_global.Properties) without any LLM call. Fires only "
            "when no configurator yaml or bundled standard already "
            "produced its target file."
        ),
    },
    "done": {
        "title": "'done' command",
        "body": (
            "Writes project.yaml into your session folder. Refused "
            "if required slots are unfilled, or if warnings are "
            "open. Use 'force-done' to write anyway."
        ),
    },
    "status": {
        "title": "'status' command",
        "body": (
            "Asks me to summarise the current project state — "
            "filled vs missing slots, present vs missing CSVs, "
            "resolved patterns, open warnings. Doesn't change "
            "state; just reports."
        ),
    },
    "edit": {
        "title": "'/edit' command",
        "body": (
            "Starts an interactive editor for a yaml input file. "
            "Example: '/edit modifierTypes.yaml'. Send '/cancel-edit' "
            "to abort the session."
        ),
    },
    "agent": {
        "title": "What this agent does",
        "body": (
            "I help you author a Delft-FEWS configuration through "
            "chat. You describe the project; I extract structured "
            "facts (skills + LLM), pick the right patterns from the "
            "library, and write a project.yaml blueprint. A separate "
            "build step renders the ~50-file FEWS config "
            "deterministically from that blueprint."
        ),
    },
}

# Aliases — different ways the user might refer to a concept.
# Map alias → canonical key in _CONCEPT_ENTRIES.
_CONCEPT_ALIASES: dict[str, str] = {
    "slots": "slot",
    "intents": "intent",
    "patterns": "pattern",
    "blueprint.yaml": "blueprint",
    "project.yaml": "blueprint",
    "project yaml": "blueprint",
    "session folder": "session",
    "sessions": "session",
    "inputs folder": "inputs",
    "input folder": "inputs",
    "inputs/": "inputs",
    "input directory": "inputs",
    "csvs": "csv",
    "csv files": "csv",
    "csv file": "csv",
    "yamls": "yaml",
    "yaml files": "yaml",
    "shp": "shapefile",
    "shapefiles": "shapefile",
    "imports": "import",
    "model adapter": "adapter",
    "model adapters": "adapter",
    "adapters": "adapter",
    "model": "adapter",
    "basins": "basin",
    "watershed": "basin",
    "watersheds": "basin",
    "warnings": "warning",
    "derivers": "deriver",
    "deterministic deriver": "deriver",
    "done command": "done",
    "status command": "status",
    "edit command": "edit",
    "this agent": "agent",
    "the agent": "agent",
    "this tool": "agent",
    "this system": "agent",
}


# Short follow-up phrases that, on their own, are too weak to route to
# help — but when the previous turn WAS a help reply, they strongly
# signal "say more about what we were just discussing".
_HELP_FOLLOWUP_PHRASES: tuple[str, ...] = (
    "more", "tell me more", "say more",
    "go on", "continue", "details", "in detail", "more detail",
    "more details", "elaborate",
    "example", "an example", "give an example",
    "give me an example", "for instance", "concretely",
    "and?", "really?", "why?", "how?",
)

# Comparative / structural words that signal a deeper question
# (e.g. "compare slots and intents", "X vs Y", "difference between X").
_HELP_COMPARATIVE_PHRASES: tuple[str, ...] = (
    "difference between", "differences between",
    "compare", "vs", "versus",
    "how do they differ", "what's the diff",
    "relationship between", "how does", "how do",
    "why do", "why is", "why are",
)


def detect_help_query(text: str, prev_was_help: bool = False) -> bool:
    """True iff the message asks about the system (explain / follow-up).

    Three positive cases:
      1. Help phrase + glossary concept: "what is a slot?", "explain
         patterns". Strict — needs both signals to avoid grabbing
         status queries like "what is missing?".
      2. Comparative phrase + concept: "compare slots and intents",
         "how does the model adapter work".
      3. Follow-up in a help thread: "more", "give an example",
         "elaborate" — only counts when ``prev_was_help`` is true,
         so a bare "more" in a build conversation doesn't hijack.

    The bare tokens "help" / "/help" always qualify.
    """
    lower = text.strip().lower().rstrip("?.!,").strip()
    if not lower:
        return False
    if lower in _HELP_TOKENS:
        return True

    has_phrase = any(
        lower.startswith(phrase + " ") or f" {phrase} " in lower
        for phrase in _HELP_PHRASES
    )
    has_concept = lookup_concept(text) is not None

    if has_phrase and has_concept:
        return True

    has_comparative = any(c in lower for c in _HELP_COMPARATIVE_PHRASES)
    if has_comparative and has_concept:
        return True

    if prev_was_help:
        if lower in _HELP_FOLLOWUP_PHRASES:
            return True
        if any(
            lower.startswith(p + " ") or lower == p or f" {p}" in lower
            for p in _HELP_FOLLOWUP_PHRASES
        ):
            return True
        # Short concept-only follow-up: "what about patterns?",
        # "and intents?". Cap length so a full build message
        # mentioning a concept doesn't get pulled in.
        if has_concept and len(lower.split()) <= 6:
            return True

    return False


def lookup_concept(text: str) -> tuple[str, dict[str, str]] | None:
    """Find the glossary entry the user is asking about.

    Returns ``(canonical_key, entry)`` or ``None``. Aliases checked
    first (longest first to avoid partial-match collisions like
    'csv' inside 'csv files'); then canonical keys.
    """
    lower = text.lower()
    for alias in sorted(_CONCEPT_ALIASES, key=lambda k: -len(k)):
        if re.search(rf"(?:^|[^a-z]){re.escape(alias)}(?:$|[^a-z])", lower):
            canonical = _CONCEPT_ALIASES[alias]
            return canonical, _CONCEPT_ENTRIES[canonical]
    for key in sorted(_CONCEPT_ENTRIES, key=lambda k: -len(k)):
        if re.search(rf"\b{re.escape(key)}\b", lower):
            return key, _CONCEPT_ENTRIES[key]
    return None


# Canonical command catalogue — single source of truth for the
# bare '/help' reply. The chatter's command dispatcher recognises the
# names + aliases listed here; if you add a new command there, mirror
# it in this table so '/help' surfaces it. Grouped to match the
# sidebar legend in app/web_app.py.
COMMANDS: list[dict[str, str]] = [
    # Project commands — drive the build pipeline
    {
        "name": "/done",
        "aliases": "done, quit",
        "group": "Project",
        "description": (
            "Write project.yaml and run the validation build. "
            "Refused if required slots are unfilled, required CSVs "
            "are missing, or warnings are open."
        ),
    },
    {
        "name": "/force-done",
        "aliases": "force-done",
        "group": "Project",
        "description": (
            "Write project.yaml even with missing CSVs or open "
            "warnings. Still hard-refused on unfilled required slots."
        ),
    },
    {
        "name": "/preview",
        "aliases": "preview",
        "group": "Project",
        "description": (
            "Dry-run what /done would write — prints the project.yaml "
            "as a fenced YAML block, no file created."
        ),
    },
    # Inspect commands — read-only views of agent + project state
    {
        "name": "/help",
        "aliases": "help",
        "group": "Inspect",
        "description": (
            "Show this command list plus the glossary of concepts I "
            "can explain. Follow up with e.g. *'what is a pattern?'*."
        ),
    },
    {
        "name": "/status",
        "aliases": "status, summary",
        "group": "Inspect",
        "description": (
            "Snapshot of the current project state — intent, filled "
            "vs missing slots, patterns chosen, CSVs detected, "
            "warnings, /done readiness."
        ),
    },
    # State commands — roll back / clear / file edits
    {
        "name": "/undo",
        "aliases": "",
        "group": "State",
        "description": (
            "Roll back the last turn's state changes (intent, slots, "
            "patterns). Up to 10 levels deep. History is not erased."
        ),
    },
    {
        "name": "/reset",
        "aliases": "",
        "group": "State",
        "description": (
            "Clear all project state but keep the session folder and "
            "history. Asks for yes/no confirmation."
        ),
    },
    {
        "name": "/edit <file>",
        "aliases": "",
        "group": "State",
        "description": (
            "Open an interactive edit-mode against a per-spec yaml "
            "input (e.g. modifierTypes.yaml)."
        ),
    },
    {
        "name": "/cancel-edit",
        "aliases": "",
        "group": "State",
        "description": "Exit /edit mode without saving.",
    },
    {
        "name": "yes / no",
        "aliases": "",
        "group": "State",
        "description": (
            "Confirm or cancel a pending action — e.g. an "
            "agent-proposed pattern removal, or a /reset prompt."
        ),
    },
]


def _commands_section() -> str:
    """Render COMMANDS as a grouped markdown bullet list for /help."""
    out: list[str] = ["**Available commands**"]
    seen_groups: list[str] = []
    by_group: dict[str, list[dict[str, str]]] = {}
    for cmd in COMMANDS:
        by_group.setdefault(cmd["group"], []).append(cmd)
        if cmd["group"] not in seen_groups:
            seen_groups.append(cmd["group"])
    for group in seen_groups:
        out.append(f"\n*{group}*")
        for cmd in by_group[group]:
            alias_part = (
                f" (aliases: {cmd['aliases']})" if cmd["aliases"] else ""
            )
            out.append(f"- `{cmd['name']}`{alias_part} — {cmd['description']}")
    return "\n".join(out)


def _glossary_topic_list_reply() -> str:
    """Static reply for bare 'help' / '/help'.

    Two sections: (1) the command catalogue from ``COMMANDS`` (most
    actionable thing a fresh user needs), then (2) the glossary topic
    list so they can ask 'what is X?' next.
    """
    topics = sorted(_CONCEPT_ENTRIES.keys())
    return (
        _commands_section()
        + "\n\n---\n\n**Concepts I can explain**: "
        + ", ".join(topics)
        + ".\n\nAsk me e.g. *'what is a pattern?'*, *'explain "
        "intents'*, *'how does the chat agent work?'*, or follow up "
        "after any explanation with *'tell me more'*, *'give an "
        "example'*, *'compare it to X'*."
    )


def _glossary_static_reply(user_message: str) -> str:
    """Deterministic glossary reply — used as fallback when LLM is down."""
    hit = lookup_concept(user_message)
    if hit is None:
        return (
            "I don't have a glossary entry for that, and the LLM is "
            "unavailable for a longer explanation. Try 'help' to see "
            "what canonical concepts I can describe."
        )
    _key, entry = hit
    return f"**{entry['title']}** — {entry['body']}"


def compose_help_reply(
    user_message: str,
    history: list[dict] | None = None,
    docs: str | None = None,
    provider: OllamaProvider | None = None,
    model: str = "qwen2.5:7b-instruct",
) -> str:
    """Answer an explain-the-system question.

    Two paths:

      1. **Bare 'help'** → static topic list. No LLM call.
      2. **Everything else** → LLM grounded in ``docs`` (CLAUDE.md
         content) plus the matching glossary entry as the canonical
         seed, plus recent ``history`` for follow-up context. The
         LLM is told to answer ONLY from the provided text — no
         fabrication.

    Falls back to the static glossary entry (or a "ask 'help' for
    topics" stub) when ``docs`` is empty or the LLM call fails.
    Keeping the glossary as a deterministic floor means the agent
    still gives accurate canonical answers when Ollama is down.
    """
    lower = user_message.strip().lower().rstrip("?.!,").strip()
    if lower in _HELP_TOKENS:
        return _glossary_topic_list_reply()

    if not docs:
        return _glossary_static_reply(user_message)

    if provider is None:
        from .providers.factory import get_provider_or_ollama
        provider = get_provider_or_ollama(model)

    hit = lookup_concept(user_message)
    glossary_seed = ""
    if hit is not None:
        _key, entry = hit
        glossary_seed = (
            "\n=== CANONICAL GLOSSARY ENTRY (preferred phrasing for "
            f"this concept) ===\n{entry['title']}: {entry['body']}\n"
        )

    # Trim history to the last few turns — full history would
    # dilute the LLM's focus and inflate the prompt. Six turns
    # ≈ three user/agent exchanges, enough to resolve "tell me
    # more" and "what about X" pronouns.
    recent_turns = (history or [])[-6:]
    recent_text = "\n".join(
        f"{h.get('role', '?')}: {h.get('message', '')}"
        for h in recent_turns
    ) or "(no prior turns)"

    system = (
        "You are a documentation assistant for the Delft-FEWS "
        "configurator agent. A configurator is asking how the system "
        "works. Answer their question using ONLY the documentation "
        "and glossary entry below.\n"
        "\n"
        "RULES:\n"
        "1) Answer ONLY from the provided documentation. Never invent "
        "   file paths, function names, behaviours, or examples that "
        "   aren't in the docs. If something isn't covered, say "
        "   'that isn't documented' — don't guess.\n"
        "2) Be conversational and concrete. 2-6 sentences for simple "
        "   questions; up to a substantial paragraph for nuanced "
        "   ones. Plain English. No bullet lists unless the user "
        "   explicitly asks. No emoji.\n"
        "3) For canonical concepts, treat the glossary entry below as "
        "   the preferred starting point — paraphrase it, then expand "
        "   with docs detail if helpful.\n"
        "4) For follow-up questions ('tell me more', 'give an "
        "   example', 'and that?'), use the RECENT CONVERSATION to "
        "   resolve what 'it', 'that', 'more' refer to.\n"
        "5) For comparative questions ('X vs Y', 'difference between "
        "   X and Y'), explain how the concepts relate using docs "
        "   content for both.\n"
        '6) Output JSON {"reply": "..."}, nothing else.\n'
        f"\n=== DOCUMENTATION (CLAUDE.md) ===\n{docs}\n"
        f"{glossary_seed}"
    )
    user = (
        f"=== RECENT CONVERSATION ===\n{recent_text}\n\n"
        f"User asks: {user_message!r}\n\n"
        f"Compose the help reply."
    )
    schema = {
        "type": "object",
        "properties": {"reply": {"type": "string"}},
        "required": ["reply"],
    }
    try:
        resp = provider.generate_json(system=system, user=user, schema=schema)
        text = (resp.data or {}).get("reply", "").strip()
        if text:
            return text
    except Exception:
        pass
    return _glossary_static_reply(user_message)


__all__ = [
    "COMMANDS",
    "Intent",
    "INTENTS",
    "INTENT_INPUT_EXPECTATIONS",
    "REGION_BBOX",
    "build_status_report",
    "classify_intent",
    "compose_help_reply",
    "compose_reply",
    "compose_status_reply",
    "compute_input_status",
    "detect_basin",
    "detect_geo_datum",
    "detect_help_query",
    "detect_imports",
    "detect_custom_bbox",
    "detect_forecast_horizon_hours",
    "detect_grid_resolution",
    "detect_locations_source",
    "detect_model_adapter",
    "detect_region",
    "detect_status_query",
    "extract_skills",
    "fill_slots_from_text",
    "heuristic_intent_from_slots",
    "is_intent_ready",
    "lookup_concept",
    "next_unfilled_question",
    "scan_inputs",
    "status_prose_fallback",
    "unrecognised_data_types",
]
