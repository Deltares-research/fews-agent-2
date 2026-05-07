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

import re
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


def detect_imports(text: str) -> list[str]:
    """Return canonical import names mentioned in the text (in input order)."""
    found = []
    seen = set()
    upper = text.upper()
    # Sort by length desc so 'WSCHistoric' matches before 'WSC'.
    for name in sorted(_IMPORT_NAMES, key=lambda n: -len(n)):
        if re.search(rf"\b{re.escape(name.upper())}\b", upper):
            if name not in seen:
                found.append(name)
                seen.add(name)
    return found


# ---------------------------------------------------------------------------
# Skill 3: basin detection
# ---------------------------------------------------------------------------

_KNOWN_BASINS = {"liard", "snare"}  # canonical basins from the tutorial

# Generic regex for "X basin" or "basin X" in a sentence.
_BASIN_PATTERN = re.compile(
    r"(?P<n>[A-Z][a-zA-Z]+)\s+basin\b|\bbasin\s+(?P<m>[A-Z][a-zA-Z]+)",
    re.IGNORECASE,
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
            return name[:1].upper() + name[1:].lower()
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
            if canonical not in found:
                found.append(canonical)
    return found


def detect_basins_with_adapters(text: str) -> list[dict[str, str]]:
    """Pair each basin found in text with its closest adapter mention.

    Heuristic: find every basin position and every adapter position in
    the lowercased text. For each basin, pair it with the nearest
    unused adapter within ~120 characters. Returns a list of dicts
    ``{basin_name, model_adapter}`` for cleanly-paired entries; basins
    whose adapter we couldn't infer are omitted (the runner asks).
    """
    lower = text.lower()
    basins_found: list[tuple[int, str]] = []
    for known in _KNOWN_BASINS:
        for m in re.finditer(rf"\b{known}\b", lower):
            basins_found.append((m.start(), known.title()))
    # Process leftmost basin first so each gets its closest adapter
    # before the next basin starts grabbing them.
    basins_found.sort(key=lambda x: x[0])

    adapters_found: list[tuple[int, str]] = []
    for adapter, phrases in _ADAPTER_PHRASES.items():
        for phrase in phrases:
            for m in re.finditer(rf"\b{re.escape(phrase)}\b", lower):
                adapters_found.append((m.start(), adapter))
    adapters_found.sort(key=lambda x: x[0])

    pairs: list[dict[str, str]] = []
    used_basins: set[str] = set()
    used_adapter_positions: set[int] = set()
    for b_pos, b_name in basins_found:
        if b_name in used_basins:
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
            used_basins.add(b_name)
            used_adapter_positions.add(a_pos)
    return pairs


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
    "NAM":  ("auto/wf_import_nam_grids", "workflow_name"),
    "SREF": ("auto/wf_import_sref_grids", "workflow_name"),
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


def _resolve_import_patterns(
    imports: list[str], catalog_paths: set[str],
) -> list[dict]:
    """Map import names to pattern instances using each pattern's own
    label variable name. Dedups by path."""
    out: list[dict] = []
    for imp in imports or []:
        entry = _IMPORT_PATTERN_MAP.get(imp)
        if not entry:
            continue
        path, label_var = entry
        if path not in catalog_paths:
            continue
        instance = {label_var: imp}
        existing = next((p for p in out if p["pattern"] == path), None)
        if existing:
            existing["instances"].append(instance)
        else:
            out.append({"pattern": path, "instances": [instance]})
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
    out = _resolve_import_patterns(slots.get("imports", []), catalog_paths)
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
    return _resolve_import_patterns(slots.get("imports", []), catalog_paths)


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
        optional_slots=["geoDatum", "locations_source"],
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
        optional_slots=["geoDatum", "locations_source"],
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
    """Pick the most likely intent based on which slots are filled."""
    has_basin = bool(
        slot_values.get("basins")
        or (slot_values.get("basin_name") and slot_values.get("model_adapter"))
    )
    has_imports = bool(slot_values.get("imports"))
    if has_basin and has_imports:
        return "build_forecasting_project"
    if has_imports and not has_basin:
        return "build_data_import_only"
    if has_basin and not has_imports:
        return "build_basin_model_only"
    return None


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
        provider = OllamaProvider(model=model)

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
    return data


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
        # Common yamls for tutorial-shaped projects. These aren't
        # strictly required (the build will succeed without them and
        # singletons fall back to empty/default), but they're the
        # files most projects need.
        "recommended_yamls_examples": [
            "filtersFile.yaml", "topology.yaml", "displayGroupsFile.yaml",
            "locationSetsFile.yaml", "gridsFile.yaml",
        ],
    },
    "build_data_import_only": {
        "required_csvs": ["locations.csv", "parameters.csv"],
        "recommended_csvs": [],
        "recommended_yamls_examples": [],
    },
    "build_basin_model_only": {
        "required_csvs": [],
        "recommended_csvs": [],
        "recommended_yamls_examples": [
            "idImportRaven.yaml", "idExportRaven.yaml",
            "idImportwflow.yaml", "idExportwflow.yaml",
            "ravenParameters.yaml",
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
) -> dict[str, Any]:
    """Compare scan against intent's expectations. Return a status dict.

    Keys returned:
      - csvs_present: list[str]
      - csvs_required_missing: list[str]
      - csvs_recommended_missing: list[str]
      - yamls_present_count: int
      - yamls_recommended_examples: list[str]  # for hints in the reply
    """
    expectations = INTENT_INPUT_EXPECTATIONS.get(intent_name or "", {})
    required = set(expectations.get("required_csvs", []))
    recommended = set(expectations.get("recommended_csvs", []))
    present_csvs = set(scan.get("csvs", []))
    present_yamls = scan.get("yamls", [])

    return {
        "csvs_present": sorted(present_csvs),
        "csvs_required_missing": sorted(required - present_csvs),
        "csvs_recommended_missing": sorted(recommended - present_csvs),
        "yamls_present_count": len(present_yamls),
        "yamls_recommended_examples": list(
            expectations.get("recommended_yamls_examples", [])
        ),
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
        provider = OllamaProvider(model=model)

    intent_name = intent.name if intent else "(none)"
    slots_text = ", ".join(
        f"{k}={_format_slot_value(v)}" for k, v in slots.items() if v
    ) or "(empty)"
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
        if n_yamls == 0 and yaml_examples:
            input_text += (
                f"  No yamls dropped yet. Common ones for this intent: "
                f"{', '.join(yaml_examples[:3])} ...\n"
            )
    else:
        input_text = "  (input directory not scanned)\n"

    system = (
        "You are a friendly assistant helping a configurator author a "
        "FEWS project. The deterministic engine has ALREADY updated the "
        "project state based on the user's message — your job is only "
        "to phrase a natural reply. RULES:\n"
        "1) Reply in 1-3 sentences. Plain English. No JSON, no bullets.\n"
        "2) Briefly acknowledge what was understood this turn (refer to "
        "the new patterns or slot values).\n"
        "3) If REQUIRED CSVs are missing or no yamls have been dropped, "
        "MENTION that — point the user at what to drop into inputs/.\n"
        "4) If a `next_question` is given, ask it naturally. If "
        "`is_ready` is true AND inputs look complete, encourage 'done'. "
        "If `is_ready` but inputs are missing, suggest staging them first.\n"
        "5) Optionally flag concerns: unusual adapter/basin pairings, "
        "contradictions across turns.\n"
        "6) If nothing was understood, ask for clarification.\n"
        "7) Output JSON {\"reply\": \"...\"}, nothing else."
    )

    user = (
        f"User just said: {user_message!r}\n"
        f"Active intent: {intent_name}\n"
        f"Current slots: {slots_text}\n"
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
            return text
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


__all__ = [
    "Intent",
    "INTENTS",
    "INTENT_INPUT_EXPECTATIONS",
    "classify_intent",
    "compose_reply",
    "compute_input_status",
    "detect_basin",
    "detect_geo_datum",
    "detect_imports",
    "detect_locations_source",
    "detect_model_adapter",
    "extract_skills",
    "fill_slots_from_text",
    "heuristic_intent_from_slots",
    "is_intent_ready",
    "next_unfilled_question",
    "scan_inputs",
]
