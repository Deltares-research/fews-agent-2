"""Parametrized generic writer: any FEWS root tag + pinned XSD, dict body.

The 7 registered generic specs pin a fixed (root_tag, xsd) pair each;
this generalizes the same `generic_root.xml.j2` + `dict_to_xml` path to
all 259 pinned XSDs so the ReAct agent can emit file types without a
registered spec — still deterministic dict->XML, still XSD-gated by the
schemaLocation the macro writes.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field

from fews_agent.generators.base import render
from fews_agent.schema.common import FewsModel
from fews_agent.validation.xsd import SCHEMAS_DIR


class AnyGenericXmlFile(FewsModel):
    """Root tag + XSD basename + dict/list body (``@key`` = attribute)."""

    root_tag: str
    xsd_basename: str
    version: str | None = None
    body: list[dict[str, Any]] | dict[str, Any] = Field(default_factory=dict)


def known_xsd(xsd_basename: str) -> bool:
    name = Path(xsd_basename).name
    return name == xsd_basename and (SCHEMAS_DIR / name).is_file()


def render_generic(
    root_tag: str,
    xsd_basename: str,
    body: list[dict[str, Any]] | dict[str, Any],
    version: str | None = None,
) -> str:
    model = AnyGenericXmlFile(
        root_tag=root_tag,
        xsd_basename=xsd_basename,
        version=version,
        body=body,
    )
    return render("generic_any.xml.j2", model)
