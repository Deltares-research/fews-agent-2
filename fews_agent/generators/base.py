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


_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(enabled_extensions=("xml", "j2")),
    trim_blocks=False,
    lstrip_blocks=False,
    keep_trailing_newline=True,
    undefined=StrictUndefined,
)
_env.filters["xmlstr"] = _xmlstr


def render(template_name: str, model: FewsModel) -> str:
    """Render `template_name` with the Pydantic model's fields as context.

    mode='python' (not 'json') keeps Decimal/StrEnum/bool as native types so
    the `xmlstr` filter can format them correctly. JSON mode would serialize
    Decimal to a string via str() — losing fixed-point notation.
    """
    template = _env.get_template(template_name)
    return template.render(**model.model_dump(mode="python", exclude_none=False))


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
