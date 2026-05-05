"""Subprocess driver: feed pre-canned answers into ``build_project``.

This is the smoke-test for the user-facing builder. It spawns
``python -m runners.agent.build_project`` as a child process and pipes
a list of one-line answers into its stdin. Each ``Prompt.ask`` /
``Confirm.ask`` call inside the wizard reads exactly one line from
stdin, so every prompt the wizard issues must be matched by exactly
one entry in the answer list.

**Single-line bulk caveat.** The wizard's section-level bulk-ask is
designed for "describe many items in one reply". When driven via
stdin, each item-list reply must fit on a single line (`input()` in
the child reads to the newline). The LLM parser still extracts
multiple items from that one line — it doesn't need bullets. Use
delimiters like ``; `` between items.

Compared to ``replay.py`` (which monkey-patches ``Prompt.ask`` in the
same Python process), this driver exercises the ACTUAL CLI entry
point — argparse, stdin reading, console output. It's the right tool
when you want to verify "is the public command working end-to-end?"
rather than "does the wizard module behave?".

Usage::

    # Use the built-in tutorial demo (3 locations, fast).
    python -m runners.agent.auto_build_project

    # Drive it from a JSON file shaped like
    #   {"project_name": ..., "specs": "...", "answers": ["...", ...]}
    python -m runners.agent.auto_build_project --plan plans/my_demo.json

    # Override target build_project flags.
    python -m runners.agent.auto_build_project --provider anthropic
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Plan:
    """Hard-canned recipe for an automated build_project run."""

    project_name: str
    specs: str               # comma-separated; passed as --specs
    answers: list[str]
    description: str = ""
    extra_args: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Built-in demo plan
# ---------------------------------------------------------------------------

# Tiny dataset — 3 locations, 2 qualifiers, 2 warning levels — chosen
# so each section's items fit comfortably in one line. The LLM parser
# pulls items apart from the ``; ``-separated string. With small
# inputs we don't need chunking and the 7B parser is reliable.

_LOCATIONS_LINE = (
    "id RDPS, name Regional Deterministic Prediction System, x -142.8968, y 18.1429; "
    "id GDPS, name Global Deterministic Prediction System, x -180, y -90; "
    "id GFS, name GFS Forecast, x 0, y 0"
)

_QUALIFIERS_LINE = (
    'id "mean", name "mean"; '
    'id "max", name "max"'
)

_LEVELS_LINE = (
    "id 0, name No threshold exceeded, color green, "
    "iconName default1.gif, historicOverlayIconName historicwarninglevel1.gif, "
    "forecastOverlayIconName historicwarninglevel1.gif; "
    "id 1, name Alert Level, color orange, "
    "iconName warninglevel1.gif, historicOverlayIconName historicwarninglevel1.gif, "
    "forecastOverlayIconName forecastwarninglevel1.gif"
)


DEMO_PLAN = Plan(
    project_name="auto_demo",
    specs="locations,qualifiers,thresholdWarningLevels",
    description=(
        "Tiny 3-spec demo driving build_project end-to-end via stdin. "
        "Each bulk reply is one line; the LLM parser splits items."
    ),
    answers=[
        # --- locations -------------------------------------------------
        "WGS 1984",            # geoDatum (file-level)
        _LOCATIONS_LINE,       # locations bulk
        # --- qualifiers ------------------------------------------------
        "false",               # allowReferencingUndefinedQualifiers
        _QUALIFIERS_LINE,      # qualifier bulk
        "skip",                # csvFile section — none
        # --- thresholdWarningLevels -----------------------------------
        _LEVELS_LINE,          # warningLevel bulk
    ],
)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def drive(
    plan: Plan,
    *,
    provider: str | None = None,
    model: str | None = None,
    output_root: Path | None = None,
    fixture_root: Path | None = None,
    timeout: float = 600.0,
    quiet: bool = False,
) -> dict:
    """Spawn build_project, pipe ``plan.answers`` to stdin, return summary."""
    args = [
        sys.executable,
        "-m",
        "runners.agent.build_project",
        "--project-name",
        plan.project_name,
        "--specs",
        plan.specs,
        "--no-confirm",
        "--no-markdown",
    ]
    if provider:
        args += ["--provider", provider]
    if model:
        args += ["--model", model]
    if output_root:
        args += ["--output-root", str(output_root)]
    if fixture_root:
        args += ["--fixture-root", str(fixture_root)]
    if quiet:
        args += ["--quiet"]
    args += plan.extra_args

    env = {**__import__("os").environ}
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUNBUFFERED", "1")

    t0 = time.monotonic()
    sys.stderr.write(f"[auto] spawning: {' '.join(args)}\n")
    sys.stderr.write(f"[auto] feeding {len(plan.answers)} answer(s) via stdin\n")

    # ``encoding="utf-8"`` is what makes the rich ✓/— bytes emitted by
    # the child decode cleanly on Windows; ``errors="replace"`` is a
    # belt-and-braces guard against any stray cp1252 bytes from libc /
    # ollama plumbing.
    proc = subprocess.run(
        args,
        input="\n".join(plan.answers) + "\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        cwd=str(REPO_ROOT),
        env=env,
    )
    elapsed = time.monotonic() - t0

    sys.stderr.write(f"[auto] exit={proc.returncode}  elapsed={elapsed:.1f}s\n")
    if not quiet:
        if proc.stderr:
            sys.stderr.write("--- child stderr ---\n")
            sys.stderr.write(proc.stderr)
            sys.stderr.write("\n--------------------\n")

    # build_project writes its summary as the trailing JSON object on
    # stdout (after the rich tables). Rather than parse stdout, locate
    # summary.json inside the latest run directory and read it back.
    summary = _locate_latest_summary(plan.project_name, output_root)
    summary_payload = (
        json.loads(summary.read_text(encoding="utf-8")) if summary else None
    )
    return {
        "exit_code": proc.returncode,
        "elapsed_s": round(elapsed, 2),
        "stdout_len": len(proc.stdout),
        "summary": summary_payload,
    }


def _locate_latest_summary(
    project_name: str, output_root: Path | None
) -> Path | None:
    """Find the most-recent ``validation/<project>/<ts>/summary.json``."""
    root = output_root or (REPO_ROOT / "validation")
    proj = root / project_name
    if not proj.exists():
        return None
    runs = sorted([p for p in proj.iterdir() if p.is_dir()])
    for run in reversed(runs):
        candidate = run / "summary.json"
        if candidate.is_file():
            return candidate
    return None


def load_plan(path: Path) -> Plan:
    data = json.loads(path.read_text(encoding="utf-8"))
    return Plan(
        project_name=data["project_name"],
        specs=data["specs"],
        answers=list(data["answers"]),
        description=data.get("description", ""),
        extra_args=list(data.get("extra_args", [])),
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--plan",
        default=None,
        help="JSON plan file. Skip to use the built-in 3-spec demo.",
    )
    parser.add_argument("--provider", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--output-root", default=None)
    parser.add_argument("--fixture-root", default=None)
    parser.add_argument("--quiet", "-q", action="store_true")
    parser.add_argument(
        "--timeout", type=float, default=600.0,
        help="Seconds before the child process is killed.",
    )
    args = parser.parse_args(argv)

    plan = load_plan(Path(args.plan)) if args.plan else DEMO_PLAN

    result = drive(
        plan,
        provider=args.provider,
        model=args.model,
        output_root=Path(args.output_root) if args.output_root else None,
        fixture_root=Path(args.fixture_root) if args.fixture_root else None,
        timeout=args.timeout,
        quiet=args.quiet,
    )

    print(json.dumps(result, indent=2, default=str))
    if result["exit_code"] != 0:
        return result["exit_code"]
    summary = result.get("summary") or {}
    return 0 if summary.get("ok") else 2


if __name__ == "__main__":
    sys.exit(main())
