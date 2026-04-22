"""XSD structural validation against the pinned FEWS v1.0 schemas in `schemas/`.

The generated XML already carries an `xsi:schemaLocation` pointing at
`http://fews.wldelft.nl/schemas/version1.0/<file>.xsd`. We strip that
URL prefix and load the same-named local file. `<xs:include>` /
`<xs:import>` chains resolve against the XSD's directory, so a single
`etree.XMLSchema` built from the entry XSD pulls in sharedTypes,
transformationTypes, topologyGroup, etc. automatically.

XSD catches shape violations (wrong element nesting, missing required
attributes, enum mismatches). It does not catch cross-file id reference
errors — for those, see `fews_agent/validation/semantic.py`.
"""
from __future__ import annotations

from pathlib import Path

from lxml import etree

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS_DIR = REPO_ROOT / "schemas"
BASE_URL = "http://fews.wldelft.nl/schemas/version1.0/"
XSI_NS = "{http://www.w3.org/2001/XMLSchema-instance}"

_schema_cache: dict[str, etree.XMLSchema] = {}


def _load_schema(xsd_rel: str) -> etree.XMLSchema:
    """Compile an XMLSchema from `schemas/<xsd_rel>`, caching per path.

    Compilation is non-trivial for the bigger FEWS XSDs (transformationTypes
    is ~700 KB and pulls in half the tree via includes). The cache keeps
    repeat validations cheap during a full run.
    """
    if xsd_rel not in _schema_cache:
        path = SCHEMAS_DIR / xsd_rel
        if not path.exists():
            raise FileNotFoundError(f"XSD not found: {path}")
        doc = etree.parse(str(path))
        _schema_cache[xsd_rel] = etree.XMLSchema(doc)
    return _schema_cache[xsd_rel]


def _xsd_rel_from_hint(xml_bytes: bytes) -> str | None:
    """Return the local XSD filename referenced by the doc's xsi:schemaLocation,
    or None if the hint is absent or points outside the pinned base URL.
    """
    try:
        root = etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError:
        return None
    hint = root.get(f"{XSI_NS}schemaLocation") or root.get(
        f"{XSI_NS}noNamespaceSchemaLocation"
    )
    if not hint:
        return None
    # `xsi:schemaLocation` alternates namespace / url pairs. Scan all urls.
    tokens = hint.split()
    urls = tokens[1::2] if root.get(f"{XSI_NS}schemaLocation") else tokens
    for url in urls:
        if url.startswith(BASE_URL):
            return url[len(BASE_URL):]
    return None


def validate_xsd(xml_bytes: bytes) -> tuple[bool, str]:
    """Validate `xml_bytes` against its self-declared XSD.

    Returns (ok, message). A missing or non-FEWS schema hint is treated
    as a skip (ok=True, message="no pinned XSD hint") rather than a
    failure — not every FEWS-namespace file in practice declares the
    hint, and we'd rather not false-positive.
    """
    xsd_rel = _xsd_rel_from_hint(xml_bytes)
    if xsd_rel is None:
        return True, "no pinned XSD hint"
    try:
        schema = _load_schema(xsd_rel)
    except Exception as exc:
        return False, f"XSD load failed ({xsd_rel}): {exc}"
    try:
        doc = etree.fromstring(xml_bytes)
        schema.assertValid(doc)
        return True, f"XSD {xsd_rel}"
    except etree.DocumentInvalid as exc:
        # error_log entries are ordered; first one is usually the root cause.
        first = exc.error_log[0] if exc.error_log else exc
        return False, f"XSD {xsd_rel}: {first}"
