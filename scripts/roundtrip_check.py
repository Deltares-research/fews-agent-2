"""Round-trip fidelity check: parse each XML via xml_ingest, re-render
via its template, and report XSD validity + a normalized text diff.

Usage:
    python scripts/roundtrip_check.py FILE:SchemaClass [FILE:SchemaClass ...]
"""
from __future__ import annotations

import sys
from pathlib import Path

from lxml import etree

from fews_agent.agent.blueprint import schema_class_for, template_for_schema
from fews_agent.generators.base import render
from fews_agent.pattern_farm.xml_ingest import parse_xml


def canon(xml_text: str) -> str:
    parser = etree.XMLParser(remove_blank_text=True, remove_comments=True)
    root = etree.fromstring(xml_text.encode("utf-8"), parser)
    return etree.tostring(root, pretty_print=True).decode("utf-8")


def main() -> int:
    rc = 0
    for arg in sys.argv[1:]:
        path_str, schema_name = arg.rsplit(":", 1)
        path = Path(path_str)
        print(f"\n=== {path.name}  ({schema_name}) ===")
        cls = schema_class_for(schema_name)
        try:
            data = parse_xml(path, cls)
        except Exception as exc:
            print(f"  PARSE FAILED: {exc}")
            rc = 1
            continue
        print(f"  parsed OK -> {cls.__name__}")
        try:
            model = cls.model_validate(data)
            xml = render(template_for_schema(cls), model)
        except Exception as exc:
            print(f"  RENDER FAILED: {exc}")
            rc = 1
            continue
        # Compare canonicalized forms (ignore comments + whitespace)
        try:
            orig_c = canon(path.read_text(encoding="utf-8"))
            new_c = canon(xml)
        except Exception as exc:
            print(f"  CANON FAILED: {exc}")
            rc = 1
            continue
        if orig_c == new_c:
            print("  ROUND-TRIP: byte-equivalent (canonicalized)")
        else:
            import difflib
            ol = orig_c.splitlines(keepends=True)
            nl = new_c.splitlines(keepends=True)
            d = list(difflib.unified_diff(ol, nl, "orig", "rendered", n=1))
            adds = sum(1 for l in d if l.startswith("+") and not l.startswith("+++"))
            dels = sum(1 for l in d if l.startswith("-") and not l.startswith("---"))
            print(f"  ROUND-TRIP: DIVERGES (+{adds}/-{dels} lines); first 40 diff lines:")
            for line in d[:40]:
                sys.stdout.write("    " + line)
    return rc


if __name__ == "__main__":
    sys.exit(main())
