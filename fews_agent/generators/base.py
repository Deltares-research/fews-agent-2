"""Generator plumbing: Jinja rendering + XML canonicalization + spec dataclass."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from lxml import etree

from fews_agent.schema import FewsModel

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def _xmlstr(value: Any) -> str:
    """Render a value for inclusion in XML text.

    - Decimal: fixed-point notation (no scientific). Preserves source digits
      like '0.00000000000000000001' which str() would collapse to '1E-20'.
      Also emits integers as '-180' not '-180.0'.
    - Everything else: plain str().
    """
    if isinstance(value, Decimal):
        return f"{value:f}"
    return str(value)


def _dict_to_xml(data: Any) -> str:
    """Render a nested dict/list/scalar as an XML fragment.

    Convention used by Transformation bodies and generic-body files:
      - `"@key": "v"` becomes an XML attribute on the enclosing element
      - other keys become child elements
      - a dict *value* whose list repeats the parent tag
      - a list *at the position a dict would go* is a sequence of
        single-key dicts, emitted in order — use this when sibling
        element ordering matters (e.g. Grids.xml's interleaved
        `<regular>` / `<irregular>`).
      - bool scalars emit as lowercase 'true' / 'false'
      - None values are skipped
      - dict with only @attrs and no other keys self-closes
    """
    if isinstance(data, list):
        # Ordered sequence of elements — each list item is a single-key
        # dict {"tagName": <content>} or a scalar (rare).
        return "".join(_dict_to_xml(item) for item in data if item is not None)
    if not isinstance(data, dict):
        return _xmlstr(data) if data is not None else ""
    parts: list[str] = []
    for key, value in data.items():
        if key.startswith("@") or value is None:
            continue
        if isinstance(value, list) and value and not isinstance(value[0], dict):
            # list of scalars → repeated elements with scalar content
            for item in value:
                parts.append(_render_element(key, item))
        elif isinstance(value, list):
            # list of dicts → repeated elements with dict bodies
            for item in value:
                parts.append(_render_element(key, item))
        else:
            parts.append(_render_element(key, value))
    return "".join(parts)


def _render_element(tag: str, value: Any) -> str:
    """Emit `<tag attrs>inner</tag>` — or self-closing when inner is empty."""
    if isinstance(value, dict):
        attrs = "".join(
            f' {k[1:]}="{v}"' for k, v in value.items() if k.startswith("@")
        )
        inner = _dict_to_xml(value)
        if inner == "":
            return f"<{tag}{attrs}/>"
        return f"<{tag}{attrs}>{inner}</{tag}>"
    if isinstance(value, bool):
        return f"<{tag}>{'true' if value else 'false'}</{tag}>"
    return f"<{tag}>{_xmlstr(value)}</{tag}>"


_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(enabled_extensions=("xml", "j2")),
    trim_blocks=False,
    lstrip_blocks=False,
    keep_trailing_newline=True,
    undefined=StrictUndefined,
)
_env.filters["xmlstr"] = _xmlstr
_env.filters["dict_to_xml"] = _dict_to_xml


def _strip_blank_lines(xml: str) -> str:
    """Drop whitespace-only lines from rendered XML.

    Jinja `{% if %}` / `{% for %}` blocks that evaluate to nothing leave
    behind indented-but-empty lines (the env keeps block whitespace so that
    *present* optional elements stay cleanly indented). Cumulatively that
    makes some files majority blank lines. Removing whitespace-only lines
    collapses the noise without disturbing the indentation of real content.

    Safe by construction: inter-element whitespace is insignificant to XSD
    validation and to FEWS at runtime, and the byte-equivalence oracle
    canonicalizes blank lines away regardless (see `canonicalize`). FEWS
    templates carry no CDATA or multi-line text content, so no significant
    whitespace is at risk.
    """
    lines = [ln for ln in xml.splitlines() if ln.strip()]
    if not lines:
        return xml
    return "\n".join(lines) + "\n"


def render(template_name: str, model: FewsModel) -> str:
    """Render `template_name` with the Pydantic model's fields as context.

    mode='python' (not 'json') keeps Decimal/StrEnum/bool as native types so
    the `xmlstr` filter can format them correctly. JSON mode would serialize
    Decimal to a string via str() — losing fixed-point notation.
    """
    template = _env.get_template(template_name)
    data = model.model_dump(mode="python", exclude_none=False)
    # Pass both splat fields (legacy) and `_root` (for partials that accept
    # a single argument wrapping the whole model). `_root` can't collide
    # with a FEWS XSD field name because of the leading underscore.
    return _strip_blank_lines(template.render(_root=data, **data))


_PARSER = etree.XMLParser(remove_blank_text=True, remove_comments=True)


def canonicalize(xml_bytes: bytes) -> bytes:
    """Return a whitespace- and comment-insensitive canonical form.

    Steps:
      1. Parse with remove_blank_text=True (strips whitespace-only text
         nodes between elements — lxml only drops them when the parent
         has element children, so mixed content is preserved).
      2. remove_comments=True drops XML comments.
      3. C14N serialize the cleaned tree.

    Two inputs that produce identical bytes under canonicalize() are
    semantically equivalent: same elements, attributes, text, and child
    order. Cosmetic differences (indentation, blank lines, comments,
    attribute order, self-closing style) are normalized away.
    """
    root = etree.fromstring(xml_bytes, _PARSER)
    return etree.tostring(root.getroottree(), method="c14n")


@dataclass(frozen=True)
class GeneratorSpec:
    """Row in the generator registry. One per FEWS file type."""

    name: str
    input_key: str
    model_class: type[FewsModel]
    template_name: str
    generate: Callable[[FewsModel], str]
    output_relpath: Path
