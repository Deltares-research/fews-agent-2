"""End-to-end generator runner.

Loads examples/config-tutorial-input.json, runs every spec in
`fews_agent.generators.SPECS`, writes XML to
examples/generated-config-tutorial/, and verifies each against the
tutorial original via XML canonicalization (C14N, comments stripped).

Exit 0 = every file generated and canonically equal to the tutorial.
Exit 1 = any mismatch or error; a unified diff of the canonical forms is
printed to stderr for each failing file.
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import sys
from decimal import Decimal
from pathlib import Path

from fews_agent.generators import SPECS, GeneratorSpec
from fews_agent.generators.base import canonicalize

# Green check / red X with ANSI color in interactive terminals; plain tags
# when piped/redirected/CI. Windows 10+ terminals honor ANSI by default.
#
# Detection: stdout.isatty() is the standard check, but PyCharm's pydev
# console reports False for isatty() while still rendering ANSI (pycharm
# wraps stdout). We also trust PYCHARM_HOSTED=1 (set by any PyCharm-hosted
# Python run). NO_COLOR=1 forces plain output per the informal convention.
_COLOR = (
    os.environ.get("NO_COLOR") is None
    and (sys.stdout.isatty() or os.environ.get("PYCHARM_HOSTED") == "1")
)
_OK = "\033[32m✔\033[0m" if _COLOR else "[OK]  "
_FAIL = "\033[31m✘\033[0m" if _COLOR else "[FAIL]"

REPO_ROOT = Path(__file__).resolve().parents[2]
INPUT_JSON = REPO_ROOT / "examples" / "config-tutorial-input.json"
TUTORIAL_DIR = REPO_ROOT / "examples" / "config-tutorial"
OUT_DIR = REPO_ROOT / "examples" / "generated-config-tutorial"


_FEWS_NS = "http://www.wldelft.nl/fews"


def _is_fews_xml(path: Path) -> bool:
    """True if `path` is a tutorial XML the generator is expected to emit.

    Excludes ArcGIS/GDAL shapefile sidecars, wflow/GDAL internal config
    XMLs under ModuleDataSetFiles, and ArcGIS `<metadata>` sidecars
    (detected by root namespace, not path — some sit under MapLayerFiles
    without the .shp.xml suffix).
    """
    name = path.name
    if name.endswith(".shp.xml") or name.endswith(".map.aux.xml"):
        return False
    parts = path.relative_to(TUTORIAL_DIR).parts
    if "wflowBinaries" in parts:
        return False
    if "gdal-data" in parts:
        return False
    # Root-element sniff: FEWS configs live in the FEWS namespace (or its
    # PI sibling); ArcGIS/GDAL sidecars don't.
    try:
        head = path.read_bytes()[:4096]
        # Find the root open-tag; check for xmlns="...fews..." or fews/PI.
        if b"http://www.wldelft.nl/fews" in head:
            return True
    except OSError:
        return False
    return False


def _tutorial_fews_files() -> set[Path]:
    """All FEWS-eligible tutorial XML files, as paths relative to TUTORIAL_DIR."""
    return {
        p.relative_to(TUTORIAL_DIR)
        for p in TUTORIAL_DIR.rglob("*.xml")
        if _is_fews_xml(p)
    }


def _canonical_diff(generated: bytes, reference: bytes, name: str) -> list[str]:
    """Unified diff of canonical forms; first ~40 lines."""
    diff = list(
        difflib.unified_diff(
            reference.decode("utf-8", errors="replace").splitlines(keepends=True),
            generated.decode("utf-8", errors="replace").splitlines(keepends=True),
            fromfile=f"tutorial/{name}",
            tofile=f"generated/{name}",
            n=3,
        )
    )
    return diff[:40]


def _run_spec(spec: GeneratorSpec, input_data: dict) -> tuple[bool, str]:
    """Returns (ok, message). Writes the XML file as a side effect."""
    if spec.input_key not in input_data:
        return False, f"input JSON has no key '{spec.input_key}'"

    model = spec.model_class.model_validate(input_data[spec.input_key])
    xml_str = spec.generate(model)

    out_path = OUT_DIR / spec.output_relpath
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(xml_str, encoding="utf-8")

    tutorial_path = TUTORIAL_DIR / spec.output_relpath
    if not tutorial_path.exists():
        return False, f"tutorial file missing: {tutorial_path}"

    generated_canon = canonicalize(out_path.read_bytes())
    reference_canon = canonicalize(tutorial_path.read_bytes())

    if generated_canon == reference_canon:
        return True, "C14N match"

    diff = _canonical_diff(generated_canon, reference_canon, str(spec.output_relpath))
    sys.stderr.write(f"\n--- DIFF for {spec.output_relpath} ---\n")
    sys.stderr.writelines(diff)
    sys.stderr.write("--- end diff ---\n")
    return False, "C14N mismatch"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        help="Comma-separated spec names to run (default: all).",
        default=None,
    )
    args = parser.parse_args(argv)

    only = {s.strip() for s in args.only.split(",")} if args.only else None
    specs = [s for s in SPECS if only is None or s.name in only]
    if not specs:
        print("No specs selected.", file=sys.stderr)
        return 1

    # parse_float=Decimal preserves numeric precision as it appeared in the
    # JSON source text. Critical for values like 0.00000000000000000001 which
    # round-trip through Python float as "1e-20" and break C14N equality.
    with INPUT_JSON.open(encoding="utf-8") as f:
        input_data = json.load(f, parse_float=Decimal)

    results: list[tuple[GeneratorSpec, bool, str]] = []
    for spec in specs:
        try:
            ok, msg = _run_spec(spec, input_data)
        except Exception as exc:
            ok, msg = False, f"error: {type(exc).__name__}: {exc}"
        results.append((spec, ok, msg))
        tag = _OK if ok else _FAIL
        print(f"{tag} {spec.output_relpath}    ({msg})")

    # Coverage = passing specs out of all FEWS tutorial XML files.
    # Independent of --only: an unrun spec doesn't help coverage.
    tutorial_files = _tutorial_fews_files()
    registered = {s.output_relpath for s in SPECS}
    passing = {s.output_relpath for s, ok, _ in results if ok}
    passing_count = len(passing & tutorial_files)
    total_tutorial = len(tutorial_files)
    pct = (passing_count / total_tutorial * 100) if total_tutorial else 0.0
    not_registered = tutorial_files - registered

    all_ok = all(ok for _, ok, _ in results)
    if all_ok:
        print(f"\nAll {len(results)} files generated and verified against tutorial.")
    fails = [s.name for s, ok, _ in results if not ok]

    print(
        f"Coverage: {passing_count} of {total_tutorial} tutorial FEWS XML "
        f"files ({pct:.1f}%)"
    )
    if not_registered:
        print(f"  {len(not_registered)} not registered: "
              f"{', '.join(sorted(str(p) for p in list(not_registered)[:5]))}"
              f"{' ...' if len(not_registered) > 5 else ''}")

    if not all_ok:
        print(f"\n{len(fails)} failure(s): {', '.join(fails)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
