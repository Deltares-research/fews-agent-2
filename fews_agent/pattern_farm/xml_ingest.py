"""XML → InstanceInput ingest.

Given N example FEWS XML files, parse each into the ``{schema,
output, data}`` dict shape the farmer consumes.

Two-stage parsing:

  1. **Generic XML → dict.** Strip the FEWS namespace, fold
     attributes into the dict, group same-tag siblings into lists,
     coerce numeric/boolean strings to native types.
  2. **Schema-aware normalization.** Walk the Pydantic model's
     declared fields; wherever a field is typed as ``list[X]`` but
     the parser produced a singleton (because the XML had exactly one
     occurrence), wrap it in a list. Finally ``model_validate`` to
     canonicalize — the validated ``model_dump()`` is the dict shape
     the farmer expects.

Two CLI entrypoints:

  - ``parse_instance_config(yaml_path)`` — read a config describing
    instances + per-output schema choices and produce a list of
    ``InstanceInput``.
  - ``parse_xml(path, schema_class)`` — one-shot for single-output
    instances.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, get_args, get_origin

import yaml
from lxml import etree
from pydantic import BaseModel
from pydantic.fields import FieldInfo

from .ir import InstanceInput, InstanceOutput


_NS_STRIP = re.compile(r"^\{[^}]+\}")


def parse_xml(xml_path: Path, schema_class: type[BaseModel]) -> dict[str, Any]:
    """Parse one FEWS XML file into the dict shape the schema expects.

    Returns a ``model_dump(exclude_none=True)`` of the validated
    Pydantic instance — guaranteed to match the canonical shape the
    farmer (and downstream renderer) uses.
    """
    tree = etree.parse(str(xml_path))
    root = tree.getroot()
    raw = _element_to_value(root)
    if not isinstance(raw, dict):
        raw = {"__root__": raw}
    normalized = _normalize_for_schema(raw, schema_class)
    try:
        model = schema_class.model_validate(normalized)
    except Exception as exc:
        raise ValueError(
            f"{xml_path}: parsed dict does not match {schema_class.__name__}: "
            f"{exc}\nparsed: {normalized!r}"
        )
    return model.model_dump(
        mode="python",
        exclude_none=True,
        exclude_defaults=True,
        by_alias=True,
    )


def parse_instance_config(config_path: Path) -> list[InstanceInput]:
    """Read a YAML/JSON manifest, parse each instance's XMLs.

    Manifest shape::

        instances:
          - label: HRDPS
            variable_hints: {nwp_name: HRDPS}
            outputs:
              - path: examples/.../ImportHRDPS.xml
                schema: TimeSeriesImportRun
                output: ModuleConfigFiles/Import/ECCCGrids/ImportHRDPS.xml
              - path: examples/.../ImportHRDPSGrids.xml
                schema: Workflow
                output: WorkflowFiles/Import/ECCCGrids/ImportHRDPSGrids.xml
          - label: GFS
            ...

    ``output`` is optional — if omitted, the input path stem is used.
    Path strings are resolved relative to the config file's directory.
    """
    from fews_agent.agent.blueprint import schema_class_for

    cfg_dir = config_path.parent.resolve()
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    instances_raw = raw.get("instances") or []
    if not instances_raw:
        raise ValueError(f"{config_path}: 'instances:' is empty or missing")

    instances: list[InstanceInput] = []
    for inst in instances_raw:
        outputs: list[InstanceOutput] = []
        for out in inst.get("outputs") or []:
            xml_path = Path(out["path"])
            if not xml_path.is_absolute():
                xml_path = (cfg_dir / xml_path).resolve()
            schema_name = out["schema"]
            schema_class = schema_class_for(schema_name)
            data = parse_xml(xml_path, schema_class)
            output_relpath = out.get("output") or _default_output_path(xml_path)
            outputs.append(
                InstanceOutput(
                    schema=schema_name,
                    output=str(output_relpath),
                    data=data,
                )
            )
        instances.append(
            InstanceInput(
                label=inst["label"],
                variable_hints=dict(inst.get("variable_hints") or {}),
                outputs=outputs,
            )
        )
    return instances


def _default_output_path(xml_path: Path) -> str:
    """Best-effort path: just the filename (callers can override)."""
    return xml_path.name


# --- XML walker --------------------------------------------------------

def _element_to_value(el: etree._Element) -> Any:
    """Generic XML element → Python value.

    Rules:
      - Element with attributes only (no children, no text) → dict of attrs.
      - Element with text only → coerced scalar.
      - Element with children → dict; same-tag siblings group into lists.
      - Attributes mix into the same dict as child elements.
      - Namespaced attributes (xmlns, xsi:schemaLocation) are dropped —
        they are XML metadata, not part of the data model.
    """
    children = [c for c in el if not _is_comment(c)]
    text = (el.text or "").strip()
    attribs = {k: v for k, v in el.attrib.items() if not _is_ns_attr(k)}

    if not children:
        if attribs:
            d: dict[str, Any] = {k: _coerce_scalar(v) for k, v in attribs.items()}
            if text:
                d["__text__"] = _coerce_scalar(text)
            return d
        return _coerce_scalar(text) if text else None

    out: dict[str, Any] = {}
    for k, v in attribs.items():
        out[k] = _coerce_scalar(v)

    grouped: dict[str, list[etree._Element]] = {}
    for c in children:
        tag = _strip_ns(c.tag)
        grouped.setdefault(tag, []).append(c)

    for tag, els in grouped.items():
        if len(els) == 1:
            out[tag] = _element_to_value(els[0])
        else:
            out[tag] = [_element_to_value(e) for e in els]

    return out


def _strip_ns(tag: str) -> str:
    return _NS_STRIP.sub("", tag)


def _is_ns_attr(key: str) -> bool:
    """True for namespaced attributes like xsi:schemaLocation."""
    return key.startswith("{") or key.startswith("xmlns")


def _is_comment(el: Any) -> bool:
    return isinstance(el, etree._Comment)


def _coerce_scalar(s: str) -> Any:
    s = s.strip() if isinstance(s, str) else s
    if not s:
        return s
    if s in {"true", "True"}:
        return True
    if s in {"false", "False"}:
        return False
    if _looks_like_int(s):
        return int(s)
    if _looks_like_float(s):
        try:
            return float(s)
        except ValueError:
            pass
    return s


def _looks_like_int(s: str) -> bool:
    return bool(re.fullmatch(r"-?\d+", s))


def _looks_like_float(s: str) -> bool:
    return bool(re.fullmatch(r"-?\d+\.\d+", s))


# --- Schema-aware normalization ----------------------------------------

def _normalize_for_schema(raw: Any, schema_class: type[BaseModel]) -> Any:
    """Wrap singletons in lists where the model expects list[X]."""
    if not isinstance(raw, dict):
        return raw
    out: dict[str, Any] = {}
    for field_name, field_info in schema_class.model_fields.items():
        key = _field_input_key(field_name, field_info)
        if key not in raw:
            continue
        annot = field_info.annotation
        out[field_name] = _normalize_field(raw[key], annot)
    # Carry over any keys the model doesn't declare — pydantic will
    # complain at validate-time if they're spurious, which is the
    # right loud-failure signal.
    for k, v in raw.items():
        if k not in {_field_input_key(f, fi) for f, fi in schema_class.model_fields.items()}:
            out[k] = v
    return out


def _field_input_key(field_name: str, field_info: FieldInfo) -> str:
    """The dict key the field reads from (alias-aware)."""
    if field_info.alias:
        return field_info.alias
    if field_info.validation_alias:
        # Pydantic's validation_alias can be str or AliasChoices
        v = field_info.validation_alias
        return getattr(v, "choices", [v])[0] if hasattr(v, "choices") else str(v)
    return field_name


def _normalize_field(value: Any, annot: Any) -> Any:
    """Recursively coerce parsed value to match field annotation."""
    origin = get_origin(annot)
    args = get_args(annot)

    if origin in (list, tuple):
        item_type = args[0] if args else Any
        if isinstance(value, list):
            return [_normalize_field(v, item_type) for v in value]
        # Singleton → wrap in list
        return [_normalize_field(value, item_type)]

    if origin is dict:
        if not isinstance(value, dict):
            return value
        val_type = args[1] if len(args) >= 2 else Any
        return {k: _normalize_field(v, val_type) for k, v in value.items()}

    # Union / Optional — try the first non-None arg
    if origin is not None and args:
        for a in args:
            if a is type(None):
                continue
            return _normalize_field(value, a)

    if isinstance(annot, type) and issubclass(annot, BaseModel):
        if isinstance(value, dict):
            return _normalize_for_schema(value, annot)

    # Scalar coercion to match the declared annotation. The parser
    # aggressively converts "1" → 1 and "1.1" → 1.1, but the model
    # may declare the field as str (FEWS often does — `version` is a
    # str, property values are str). Reverse the coercion here.
    if annot is str and isinstance(value, (int, float, bool)):
        if isinstance(value, bool):
            return "true" if value else "false"
        # int/float — preserve original string form when possible
        if isinstance(value, int):
            return str(value)
        # float — strip trailing .0 to mimic source ("1.1" stays "1.1")
        s = str(value)
        return s

    return value
