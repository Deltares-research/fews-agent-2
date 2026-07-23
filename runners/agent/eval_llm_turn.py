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
import tempfile
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

    def nag(state, transcript):
        """PDF 2: 'you still need locations.csv...' re-appended after every
        turn, including two straight declines. One mention is fine; the same
        reminder after BOTH "no"s is the nag."""
        declines = [r.lower() for m, r in transcript if m == "no"]
        if len(declines) >= 2 and all("locations.csv" in r for r in declines):
            return ["repeated the locations.csv reminder after every decline"]
        return []

    def eccc_fixed(state, transcript):
        """PDF 1: claimed HRDPS's resolution is changeable — it's fixed."""
        problems = []
        ov = (state["slots"].get("import_overrides") or {}).get("HRDPS") or {}
        if "grid_resolution" in ov:
            problems.append("applied a resolution override to ECCC HRDPS")
        reply = transcript[-1][1].lower()
        if not any(w in reply for w in ("fixed", "native", "cannot", "can't",
                                        "isn't", "not")):
            problems.append("didn't say HRDPS's resolution is fixed")
        return problems

    def station_write(state, transcript):
        """PDF 2: the agent collected a station and had nowhere to put it.
        Now the data must land in inputs/locations.csv."""
        path = state["_eval_inputs_dir"] / "locations.csv"
        if not path.is_file():
            return ["locations.csv was not written"]
        text = path.read_text(encoding="utf-8")
        return [] if "A" in text else [f"station A missing: {text[:80]}"]

    def scoped_build(state, transcript):
        """PDF 1: refused 'build it' over missing CSVs — scoped builds don't
        need them."""
        reply = transcript[-1][1].lower()
        bad = ("can't build", "cannot build", "couldn't build", "couldn't b")
        return (["refused a scoped build over missing CSVs"]
                if any(b in reply for b in bad) else [])

    def elicit_first(state, transcript):
        """After a bare 'add GFS' the follow-up must elicit its variables,
        not push a build (live report: 'keeps pushing to build')."""
        reply = transcript[-1][1].lower()
        problems = []
        if not any(w in reply for w in ("variable", "precipitation",
                                        "temperature", "carry")):
            problems.append("didn't ask about the import's weather variables")
        if "build" in reply.split("?")[0][:80]:
            problems.append(f"led with a build push: {reply[:90]}")
        return problems

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
        ("nag-throttle", ["add GFS", "no", "no"], nag),
        ("eccc-fixed-resolution", [
            "add HRDPS", "can i change the resolution of HRDPS?",
        ], eccc_fixed),
        ("station-write", [
            "add GFS",
            'add a station: location name "A", coordinates x=1, y=1',
        ], station_write),
        ("scoped-build-not-refused", ["add GFS", "build it"], scoped_build),
        ("elicit-before-build", ["add GFS"], elicit_first),
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
        inputs_dir = Path(tempfile.mkdtemp(prefix="eval_inputs_"))
        state["_eval_inputs_dir"] = inputs_dir     # for scenario checks
        history: list[dict] = []
        transcript: list[tuple[str, str]] = []
        for msg in turns:
            history.append({"role": "user", "message": msg})
            res = run_llm_turn(state, msg, catalog, provider=provider,
                               history=history, inputs_dir=inputs_dir)
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
