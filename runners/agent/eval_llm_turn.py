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
        """PDF 2: 'you still need locations.csv...' re-appended after the user
        CLOSED the topic ("cool, thanks"). Under the GPS, moving to the next
        route step on a decline is fine — the nag is re-listing gaps after the
        user signals they're done. The reply to "cool, thanks" must be a short
        acknowledgement, not another gap dump."""
        last_msg, last_reply = transcript[-1]
        r = last_reply.lower()
        problems = []
        if "locations.csv" in r or "parameters.csv" in r:
            problems.append("re-listed missing files after the user closed "
                            f"the topic: {last_reply[:100]}")
        if len(last_reply) > 240:
            problems.append("verbose reply to a topic-closing 'thanks'")
        return problems

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

    def no_premature_assembly(state, transcript):
        """Route says NOT ready to assemble (no input CSVs) — the agent must
        not steer toward done/assembly. GPS behaviour: guide the open steps."""
        reply = transcript[-1][1].lower()
        bad = ("say done", "type done", "ready to assemble", "assemble the",
               "shall i assemble", "want me to build", "should i build")
        hits = [b for b in bad if b in reply]
        return [f"steered to assembly/build early: {hits}"] if hits else []

    def routes_in_order(state, transcript):
        """After variables are chosen, 'what's next' points at the NEXT route
        step (map area / input files), not a build or a status dump."""
        reply = transcript[-1][1].lower()
        if any(w in reply for w in ("map area", "region", "locations.csv",
                                    "parameters.csv", "input file", "station")):
            return []
        return [f"didn't name the next route step: {reply[:100]}"]

    def reroute_follows_driver(state, transcript):
        """GPS re-routes: mid-flow the driver changes direction (adds a basin
        instead of answering the variables question). The agent follows —
        both the source and the basin end up configured, not stuck on GFS."""
        s = state["slots"]
        problems = []
        if s.get("imports") != ["GFS"]:
            problems.append(f"lost GFS: {s.get('imports')}")
        if s.get("basins") != [{"basin_name": "Rhine",
                                "model_adapter": "wflow"}]:
            problems.append(f"basin not added on reroute: {s.get('basins')}")
        return problems

    def eccc_no_variables_question(state, transcript):
        """Adding an ECCC source must NOT ask 'which weather variables?' —
        their set is fixed (found driving the API: HRDPS was asked). It should
        move to the map area instead."""
        reply = transcript[-1][1].lower()
        problems = []
        if "which" in reply and ("variable" in reply or "carry" in reply):
            problems.append(f"asked to choose ECCC variables: {reply[:90]}")
        return problems

    def basin_one_message(state, transcript):
        """'a wflow model for the rhine basin' names BOTH pieces in one
        message — add now, don't ask to confirm the name (found testing the
        GPS myself: this phrasing hesitated and silently dropped the basin)."""
        b = state["slots"].get("basins") or []
        return ([] if b == [{"basin_name": "Rhine", "model_adapter": "wflow"}]
                else [f"basin not added from one-message add: {b}"])

    def adapter_first(state, transcript):
        """Adapter given in turn 1, basin named in turn 2 — must combine, not
        re-ask (live tester: 'wflow' forgotten after 'rhine basin')."""
        b = state["slots"].get("basins") or []
        return ([] if b == [{"basin_name": "Rhine", "model_adapter": "wflow"}]
                else [f"basins wrong or re-asked: {b}"])

    def horizon_days(state, transcript):
        """A bare '14 forecast horizon' means 14 DAYS (336h), not 14 hours."""
        ov = (state["slots"].get("import_overrides") or {}).get("GFS") or {}
        h = ov.get("forecast_horizon_hours")
        return [] if h == 336 else [f"horizon={h}, expected 336 (14 days)"]

    def delete_defaulted_var(state, transcript):
        """Delete a weather variable from a DEFAULTED import — params must
        drop it (live tester: 'delete air temperature' no-op'd)."""
        inst = [i for p in (state.get("patterns") or [])
                if p["pattern"] == "auto/nwp_grid_noaa"
                for i in p["instances"] if i.get("nwp_name") == "GFS"]
        ids = [x.get("id")
               for x in (inst[0].get("parameters", []) if inst else [])]
        return [] if ids == ["PC.nwp"] else [
            f"GFS params={ids}, expected [PC.nwp]"]

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
        ("nag-throttle", [
            "add GFS", "no, leave the variables", "cool, thanks",
        ], nag),
        ("eccc-fixed-resolution", [
            "add HRDPS", "can i change the resolution of HRDPS?",
        ], eccc_fixed),
        ("station-write", [
            "add GFS",
            'add a station: location name "A", coordinates x=1, y=1',
        ], station_write),
        ("scoped-build-not-refused", ["add GFS", "build it"], scoped_build),
        ("elicit-before-build", ["add GFS"], elicit_first),
        ("adapter-given-first", [
            "I want a forecasting system using wflow", "rhine basin",
        ], adapter_first),
        ("horizon-bare-number-is-days", [
            "create a noaa gfs import", "14 forecast horizon",
        ], horizon_days),
        ("delete-defaulted-variable", [
            "import gfs", "I don't need air temperature, delete it",
        ], delete_defaulted_var),
        ("no-premature-assembly", ["import gfs"], no_premature_assembly),
        ("routes-in-order", [
            "import gfs", "precipitation and temperature", "what's next?",
        ], routes_in_order),
        ("reroute-follows-driver", [
            "import gfs", "actually, add a wflow model for the rhine basin",
        ], reroute_follows_driver),
        ("basin-both-in-one-message", [
            "let's also add a wflow model for the rhine basin",
        ], basin_one_message),
        ("eccc-no-variables-question", ["add HRDPS"],
         eccc_no_variables_question),
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
