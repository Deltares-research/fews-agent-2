"""Golden-transcript eval for the LLM-first turn — run against the LIVE model.

Prompt engineering without evals is superstition: every prompt tweak is a
blind bet until the failure conversations that motivated it are replayed.
This replays them, asserting on the PATCH (ops present/absent — the part that
must not drift) and on banned internal vocabulary in replies — never on exact
wording, so the eval doesn't rot when phrasing varies.

Usage (needs the provider configured, e.g. .env with azure_ai/gpt-5.4-mini):

    python -m runners.agent.eval_llm_turn

Exit code 0 = all scenarios pass. This is OPT-IN (live LLM, costs tokens);
the deterministic oracle remains tests/test_llm_turn.py.
"""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

# Words from our internals that must never reach a user-facing reply.
BANNED_VOCAB = (
    "slot", "resolver", "auto-generated", "auto_generated", "runner",
    "intent", "patch", "digest", "moduleinstanceid",
)


def _scenarios():
    """Each: (name, turns, check(state, transcript) -> list[str] problems)."""

    def rhine(state, transcript):
        problems = []
        basins = state["slots"].get("basins") or []
        if basins != [{"basin_name": "Rhine", "model_adapter": "hbv96"}]:
            problems.append(f"basins wrong: {basins}")
        # The adapter question must have been asked BEFORE the user gave it.
        pre = " ".join(r for m, r in transcript[:3]).lower()
        if not any(a in pre for a in ("raven", "wflow", "hbv96")):
            problems.append("never asked which adapter Rhine uses")
        if state.get("current_module") == "root":
            problems.append("misrouted focus to root")
        return problems

    def compound(state, transcript):
        problems = []
        if state["slots"].get("imports") != ["ECMWF"]:
            problems.append(f"imports: {state['slots'].get('imports')}")
        ov = (state["slots"].get("import_overrides") or {}).get("ECMWF") or {}
        if ov.get("grid_resolution") != "0p50":
            problems.append(f"resolution: {ov}")
        return problems

    def unknown(state, transcript):
        problems = []
        if state["slots"].get("imports"):
            problems.append("added something for an unknown source")
        reply = transcript[-1][1].lower()
        if "mysterymodel" not in reply and "don't have" not in reply \
                and "not" not in reply:
            problems.append("didn't tell the user the source is unknown")
        return problems

    def gap(state, transcript):
        reply = transcript[-1][1].lower()
        return [] if "locations.csv" in reply else [
            "didn't name the missing locations.csv"
        ]

    return [
        ("rhine-basin", [
            "add GFS", "i need it for the rhine basin",
            "use the Rhine basin", "it runs on hbv96",
        ], rhine),
        ("compound-swap", [
            "add GFS", "swap GFS for ECMWF and make it half degree",
        ], compound),
        ("unknown-source", ["add the MysteryModel grids"], unknown),
        ("gap-report", [
            "add GFS with precipitation", "whats left to build?",
        ], gap),
    ]


def main() -> int:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env", override=True)

    from fews_agent.agent.llm_turn import run_llm_turn
    from fews_agent.agent.project_chat import build_pattern_catalog
    from fews_agent.agent.providers.factory import get_provider

    provider = get_provider(model=os.environ.get("FEWS_AGENT_MODEL"))
    catalog = build_pattern_catalog(REPO / "fews_agent" / "patterns")
    print(f"model: {os.environ.get('FEWS_AGENT_MODEL')}")

    failures = 0
    for name, turns, check in _scenarios():
        state = {"slots": {}, "current_module": "processing",
                 "intent": "build_data_import_only"}
        history: list[dict] = []
        transcript: list[tuple[str, str]] = []
        for msg in turns:
            history.append({"role": "user", "message": msg})
            res = run_llm_turn(state, msg, catalog, provider=provider,
                               history=history)
            history.append({"role": "agent", "message": res.reply})
            transcript.append((msg, res.reply))

        problems = check(state, transcript)
        for _, reply in transcript:
            low = reply.lower()
            for word in BANNED_VOCAB:
                if word in low:
                    problems.append(f"banned vocab {word!r} in: {reply[:90]}")
        status = "PASS" if not problems else "FAIL"
        print(f"\n[{status}] {name}")
        for m, r in transcript:
            print(f"   > {m}\n     {r[:140]}")
        for p in problems:
            print(f"   !! {p}")
        failures += bool(problems)

    print(f"\n{'=' * 50}\n{len(_scenarios()) - failures}/{len(_scenarios())} "
          f"scenarios passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
