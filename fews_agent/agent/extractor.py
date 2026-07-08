"""LLM operation extractor for module-mode (P2).

When a configurator has a FEWS module in focus (see ``modules.py`` /
``module_focus.py``) and types plain language — "add the ECCC high-res grids
with precip", "make it half-degree", "let's do the display module now" — this
turns that prose into ONE structured operation:

    extract_operation(message, focus_module=..., provider=...)
      -> ExtractedOperation(action, module, fields, dropped, raw)

**The trust boundary is the point.** The model extracts freely, but every
value it returns is then validated *deterministically* against the existing
catalog (import names + aliases, model adapters, parameter phrases, grid
resolutions, module keys). Anything not in the catalog is **dropped** into
``dropped`` and never applied — surfaced to the user as a warning, exactly
like the filter drafter dropping hallucinated ids. So a capable model gives
prose-robustness, without "trust the LLM blindly": a hallucinated ``GFS2``
is discarded, while a correct-but-unusual phrasing that maps to ``HRDPS`` is
kept.

``fields`` is deliberately the SAME slot-dict shape ``extract_skills``
produces, so an ``add``/``set`` operation flows through the existing additive
slot-fill + ``resolve_patterns`` untouched — this replaces the *regex* front
end for the focused-module case, not the downstream machinery.

The prompt lives in ``prompts/extract_operation.{system,user}.txt`` per the
standing rule; nothing here embeds prompt text.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .modules import Module, list_modules, normalize_module
from .project_intents import (
    _ADAPTER_PHRASES,
    _DATA_TYPE_TO_PARAMETER,
    _DATUM_PHRASES,
    _IMPORT_ALIASES,
    _IMPORT_NAMES,
    REGION_BBOX,
    detect_geo_datum,
    detect_grid_resolution,
)

# Valid actions the extractor may return.
_ACTIONS = frozenset({
    "add", "set", "remove", "select_module", "build", "list", "none",
})

# Grid-resolution slugs the NOAA pattern understands.
_RESOLUTIONS = frozenset({"0p25", "0p50", "1p00"})

# Below this confidence, an operation that WOULD change something is
# confirmed with the user instead of applied silently.
CONFIDENCE_THRESHOLD = 0.6


@dataclass
class ExtractedOperation:
    """One validated operation parsed from a configurator's prose."""

    action: str = "none"
    module: str | None = None            # normalized key, only for select_module
    fields: dict[str, Any] = field(default_factory=dict)
    dropped: list[str] = field(default_factory=list)   # invalid values discarded
    confidence: float = 1.0              # model self-report, 0..1
    raw: dict[str, Any] = field(default_factory=dict)  # the model's raw output


def _has_effect(op: "ExtractedOperation") -> bool:
    """True when applying ``op`` would actually change project state."""
    if op.action in ("add", "set"):
        return bool(op.fields)
    if op.action == "remove":
        return bool(op.fields.get("imports") or op.fields.get("basins"))
    if op.action == "select_module":
        return op.module is not None
    return False


def needs_confirmation(
    op: "ExtractedOperation", threshold: float = CONFIDENCE_THRESHOLD,
) -> bool:
    """Ask before applying? True when the op has an effect AND is uncertain.

    A low-confidence ``none``/``list``/``build`` needs no confirmation —
    there's nothing to undo. Only an operation that would mutate state and
    that the model wasn't sure about is worth a confirm round-trip.
    """
    return _has_effect(op) and op.confidence < threshold


def describe_operation(op: "ExtractedOperation") -> str:
    """A short human phrase for a confirmation prompt."""
    if op.action == "select_module":
        return f"switch to the {op.module} module"
    bits: list[str] = []
    if op.fields.get("imports"):
        bits.append("imports " + ", ".join(op.fields["imports"]))
    if op.fields.get("basins"):
        bits.append("basins " + ", ".join(
            b.get("basin_name", "?") for b in op.fields["basins"]
        ))
    if op.fields.get("data_types"):
        bits.append("parameters " + ", ".join(op.fields["data_types"]))
    for k in ("grid_resolution", "forecast_horizon_hours", "region",
              "geoDatum"):
        if k in op.fields:
            bits.append(f"{k}={op.fields[k]}")
    verb = {"add": "add", "set": "set", "remove": "remove"}.get(
        op.action, "apply"
    )
    return f"{verb} {', '.join(bits)}" if bits else op.action


def op_to_dict(op: "ExtractedOperation") -> dict[str, Any]:
    """JSON-serializable form for stashing a pending op in chat state."""
    return {
        "action": op.action, "module": op.module,
        "fields": op.fields, "dropped": op.dropped,
        "confidence": op.confidence,
    }


def op_from_dict(d: dict[str, Any]) -> "ExtractedOperation":
    return ExtractedOperation(
        action=d.get("action", "none"), module=d.get("module"),
        fields=d.get("fields") or {}, dropped=d.get("dropped") or [],
        confidence=float(d.get("confidence", 1.0)),
    )


# ---------------------------------------------------------------------------
# Catalog canonicalization (deterministic — the trust boundary)
# ---------------------------------------------------------------------------

def _canonical_import(name: str) -> str | None:
    """Map a model-supplied import token to a known canonical name, or None."""
    if not isinstance(name, str):
        return None
    up = name.strip().upper()
    if not up:
        return None
    # Alias table (case-insensitive keys).
    for alias, canonical in _IMPORT_ALIASES.items():
        if alias.upper() == up:
            return canonical
    for known in _IMPORT_NAMES:
        if known.upper() == up:
            return known
    return None


def _canonical_adapter(name: str) -> str | None:
    """Map an adapter token to a known adapter key, or None."""
    if not isinstance(name, str):
        return None
    low = name.strip().lower().replace(" ", "").replace("-", "")
    for adapter, phrases in _ADAPTER_PHRASES.items():
        if adapter == low:
            return adapter
        for p in phrases:
            if p.replace(" ", "").replace("-", "") == low:
                return adapter
    return None


def validate_fields(
    raw_fields: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Canonicalize + catalog-check the model's fields.

    Returns ``(clean_fields, dropped)``. ``clean_fields`` carries only values
    that resolve against the known catalog, in the same slot shape the rest
    of the pipeline consumes. ``dropped`` lists every value discarded so the
    caller can warn the user rather than silently ignore a hallucination.
    """
    clean: dict[str, Any] = {}
    dropped: list[str] = []

    if not isinstance(raw_fields, dict):
        return clean, dropped

    # imports -----------------------------------------------------------
    raw_imports = raw_fields.get("imports")
    if isinstance(raw_imports, list):
        keep: list[str] = []
        for item in raw_imports:
            canon = _canonical_import(item)
            if canon is None:
                dropped.append(f"import:{item}")
            elif canon not in keep:
                keep.append(canon)
        if keep:
            clean["imports"] = keep

    # basins (basin_name + model_adapter pairs) -------------------------
    raw_basins = raw_fields.get("basins")
    if isinstance(raw_basins, list):
        keep_b: list[dict[str, str]] = []
        for b in raw_basins:
            if not isinstance(b, dict):
                continue
            bname = str(b.get("basin_name") or "").strip()
            adapter = _canonical_adapter(b.get("model_adapter") or "")
            if not bname:
                continue
            if adapter is None:
                dropped.append(f"adapter:{b.get('model_adapter')}")
                continue
            keep_b.append({"basin_name": bname, "model_adapter": adapter})
        if keep_b:
            clean["basins"] = keep_b

    # data_types --------------------------------------------------------
    raw_dt = raw_fields.get("data_types")
    if isinstance(raw_dt, list):
        keep_dt: list[str] = []
        for dt in raw_dt:
            key = str(dt or "").strip().lower()
            if key in _DATA_TYPE_TO_PARAMETER:
                if dt not in keep_dt:
                    keep_dt.append(dt)
            else:
                dropped.append(f"data_type:{dt}")
        if keep_dt:
            clean["data_types"] = keep_dt

    # grid_resolution ---------------------------------------------------
    raw_res = raw_fields.get("grid_resolution")
    if raw_res is not None:
        res = str(raw_res).strip()
        if res in _RESOLUTIONS:
            clean["grid_resolution"] = res
        else:
            mapped = detect_grid_resolution(res)
            if mapped:
                clean["grid_resolution"] = mapped
            else:
                dropped.append(f"grid_resolution:{raw_res}")

    # forecast_horizon_hours -------------------------------------------
    raw_hor = raw_fields.get("forecast_horizon_hours")
    if raw_hor is not None:
        try:
            clean["forecast_horizon_hours"] = int(raw_hor)
        except (ValueError, TypeError):
            dropped.append(f"forecast_horizon_hours:{raw_hor}")

    # geoDatum ----------------------------------------------------------
    raw_datum = raw_fields.get("geoDatum")
    if raw_datum is not None:
        if raw_datum in _DATUM_PHRASES:
            clean["geoDatum"] = raw_datum
        else:
            mapped = detect_geo_datum(str(raw_datum))
            if mapped:
                clean["geoDatum"] = mapped
            else:
                dropped.append(f"geoDatum:{raw_datum}")

    # region (free-ish — a named gazetteer region is preferred but a
    # non-gazetteer name is kept; it simply won't get an auto bbox) -----
    raw_region = raw_fields.get("region")
    if isinstance(raw_region, str) and raw_region.strip():
        clean["region"] = raw_region.strip()

    # boolean intents ---------------------------------------------------
    for flag in ("wants_interpolation", "wants_visualization"):
        if flag in raw_fields:
            clean[flag] = bool(raw_fields[flag])

    return clean, dropped


# ---------------------------------------------------------------------------
# Vocabulary strings for the prompt (so the model draws from known values)
# ---------------------------------------------------------------------------

def _vocab_imports() -> str:
    names = sorted(set(_IMPORT_NAMES) | set(_IMPORT_ALIASES))
    return ", ".join(names)


def _vocab_adapters() -> str:
    return ", ".join(sorted(_ADAPTER_PHRASES))


def _vocab_data_types() -> str:
    return ", ".join(sorted(_DATA_TYPE_TO_PARAMETER))


def _vocab_modules() -> str:
    return ", ".join(f"{m.key} ({m.label})" for m in list_modules())


# ---------------------------------------------------------------------------
# The extraction call
# ---------------------------------------------------------------------------

_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string"},
        "module": {"type": ["string", "null"]},
        "fields": {"type": "object", "additionalProperties": True},
        "confidence": {"type": "number"},
        "reasoning": {"type": "string"},
    },
    "required": ["action"],
}


def _parse_confidence(raw: Any) -> float:
    """Coerce the model's confidence to a float in [0, 1]; default 1.0.

    A missing/garbage value defaults HIGH (apply) rather than low, so a
    model that doesn't report confidence behaves as before — the feature
    only engages when the model actively signals uncertainty.
    """
    try:
        c = float(raw)
    except (TypeError, ValueError):
        return 1.0
    return max(0.0, min(1.0, c))


def extract_operation(
    message: str,
    *,
    focus_module: Module,
    provider,
    model: str = "qwen2.5:7b-instruct",
) -> ExtractedOperation:
    """Parse ``message`` into one validated operation on ``focus_module``.

    The model proposes ``{action, module, fields}``; this then validates the
    action against the known set, normalizes any ``select_module`` target,
    and runs every field through :func:`validate_fields` so only
    catalog-resolvable values survive. Never raises for a bad model response
    — an unparseable or empty reply yields ``action="none"``.
    """
    from fews_agent.agent import prompts

    system = prompts.load("extract_operation.system")
    user = prompts.load(
        "extract_operation.user",
        message=repr(message),
        module_key=focus_module.key,
        module_label=focus_module.label,
        module_prompt=focus_module.prompt or focus_module.description,
        module_operations=", ".join(focus_module.operations),
        vocab_imports=_vocab_imports(),
        vocab_adapters=_vocab_adapters(),
        vocab_data_types=_vocab_data_types(),
        vocab_modules=_vocab_modules(),
    )

    try:
        resp = provider.generate_json(system=system, user=user, schema=_SCHEMA)
        raw = resp.data or {}
    except Exception:
        return ExtractedOperation(action="none")

    action = str(raw.get("action") or "none").strip().lower()
    if action not in _ACTIONS:
        action = "none"

    # An operation that names another module → normalize; if it doesn't
    # resolve, treat as no module switch.
    module_key = None
    if action == "select_module":
        module_key = normalize_module(raw.get("module"))
        if module_key is None:
            action = "none"

    clean_fields, dropped = validate_fields(raw.get("fields") or {})

    return ExtractedOperation(
        action=action,
        module=module_key,
        fields=clean_fields,
        dropped=dropped,
        confidence=_parse_confidence(raw.get("confidence")),
        raw=raw if isinstance(raw, dict) else {},
    )
