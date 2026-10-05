"""Live-model eval: the GFS one-shot oracle.

    python -m runners.react.eval_react            # live model + network

Opt-in (costs tokens, needs the configured provider + outbound HTTP).
Mirrors eval_llm_turn conventions: asserts on produced STATE (files,
XSD, semantic refs, station CSV), never on reply wording. Exit 0 only
if every check passes. The session (with react_log.jsonl transcript)
is kept under projects/_eval_react/ as the baseline to diff prompt
iterations against.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

from fews_agent.agent.providers.factory import get_provider  # noqa: E402
from fews_agent.react import prompts  # noqa: E402
from fews_agent.react.context import ToolContext  # noqa: E402
from fews_agent.react.loop import run_react  # noqa: E402
from fews_agent.react.tools import build_registry  # noqa: E402
from fews_agent.react.tools.validate_tools import VALIDATE_PROJECT  # noqa: E402

from .run_react import _load_env, _result_digest, new_session_dir  # noqa: E402

MIN_FILES = 15
MIN_STATION_ROWS = 5
MAX_ITERATIONS = 80
TOKEN_BUDGET = 2_000_000


def _check(ok: bool, label: str, detail: str = "") -> bool:
    tag = "[OK]  " if ok else "[FAIL]"
    print(f"{tag} {label}" + (f" — {detail}" if detail else ""))
    return ok


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=("langgraph", "native"),
                        default="langgraph")
    args = parser.parse_args()

    _load_env()
    provider = get_provider()
    session_dir = new_session_dir("_eval_react")
    ctx = ToolContext.for_session(session_dir)
    registry = build_registry(ctx)
    system = prompts.load("react.system")
    user_prompt = prompts.load("eval_gfs.user")
    log_path = session_dir / "react_log.jsonl"

    print(f"[SESSION] {session_dir}")
    print(f"[MODEL] {provider.model}")
    print(f"[ENGINE] {args.engine}")
    if args.engine == "langgraph":
        from fews_agent.react.lg_agent import langsmith_status
        print(f"[LANGSMITH] {langsmith_status()}")

    def on_event(kind: str, data: dict) -> None:
        import json
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"kind": kind, **data}, default=str) + "\n")
        if kind == "assistant":
            for call in data.get("tool_calls", []):
                print(f"[TOOL] {call['name']}", flush=True)
        elif kind == "tool_result":
            print(f"       -> {_result_digest(data['content'])}", flush=True)

    if args.engine == "langgraph":
        from fews_agent.react.lg_agent import default_chat_model, run_react_lg
        result = run_react_lg(default_chat_model(provider.model), system,
                              user_prompt, registry, ctx,
                              max_iterations=MAX_ITERATIONS,
                              on_event=on_event)
    else:
        result = run_react(provider, system, user_prompt, registry, ctx,
                           max_iterations=MAX_ITERATIONS,
                           token_budget=TOKEN_BUDGET, on_event=on_event)

    report = VALIDATE_PROJECT.handler(ctx, {})
    unresolved = report["semantic"]["unresolved"]
    locations_csv = ctx.inputs_dir / "locations.csv"
    station_rows = (
        max(0, len(locations_csv.read_text(encoding="utf-8")
                   .strip().splitlines()) - 1)
        if locations_csv.is_file() else 0
    )
    paths = list(ctx.rendered)

    # Content checks born from the reference-config comparison: XSD +
    # semantic can pass while the config moves no data.
    import_files = [p for p in paths if "ModuleConfigFiles/Import" in p]
    imports_sourced = bool(import_files) and all(
        "<serverUrl>" in ctx.rendered[p].content
        or ("<folder>" in ctx.rendered[p].content
            and "<failedFolder>" in ctx.rendered[p].content)
        for p in import_files
    )
    workflow_stems = [Path(p).stem for p in paths
                      if p.startswith("WorkflowFiles/")]
    topology = ctx.rendered.get("RegionConfigFiles/Topology.xml")
    topology_wired = topology is not None and all(
        f"<workflowId>{stem}</workflowId>" in topology.content
        for stem in workflow_stems
    )
    no_forecast_search = not any(
        "<forecastSearchPeriod" in ctx.rendered[p].content
        for p in import_files
    )
    activities_independent = not any(
        "<runIndependent>false<" in ctx.rendered[p].content
        for p in paths if p.startswith("WorkflowFiles/")
    )

    print()
    checks = [
        _check(result.stopped == "final",
               "loop finished without interaction",
               f"stopped={result.stopped}, iterations={result.iterations}"),
        _check(report["files"] >= MIN_FILES,
               f">= {MIN_FILES} files produced", f"{report['files']} files"),
        _check(not report["xsd_failures"], "all files XSD-valid",
               "; ".join(f["path"] for f in report["xsd_failures"][:5])),
        _check(report["semantic"]["unresolved_count"] == 0,
               "0 unresolved semantic refs",
               "; ".join(f"{u['id_type']}:{u['value']}"
                         for u in unresolved[:8])),
        _check(station_rows >= MIN_STATION_ROWS,
               f"locations.csv has >= {MIN_STATION_ROWS} self-discovered "
               f"stations", f"{station_rows} rows"),
        _check(any("ModuleConfigFiles/Import" in p for p in paths),
               "an import module config exists"),
        _check(any(p.startswith("WorkflowFiles/") for p in paths),
               "a workflow exists"),
        _check(any(p.startswith("IdMapFiles/") for p in paths),
               "an idMap exists"),
        _check(imports_sourced,
               "every import has a data source (serverUrl, or folder + "
               "failedFolder)"),
        _check(topology_wired,
               "topology carries a node for every workflow",
               f"workflows={workflow_stems}"),
        _check(not report["undefined_properties"],
               "no undefined $PROPERTY$ placeholders",
               "; ".join(u["property"]
                         for u in report["undefined_properties"][:6])),
        _check(not report["expression_issues"],
               "no unsupported expression functions (ATAN2/MOD/PI)",
               "; ".join(f"{e['path']}: {e['unsupported']}"
                         for e in report["expression_issues"][:4])),
        _check(no_forecast_search,
               "no version-gated forecastSearchPeriod in imports"),
        _check(activities_independent,
               "every workflow activity is runIndependent"),
        _check(ctx.usage.total() < TOKEN_BUDGET,
               "token budget respected", f"{ctx.usage.total()} tokens"),
    ]
    print()
    print(f"[TOKENS] prompt={ctx.usage.prompt_tokens} "
          f"completion={ctx.usage.completion_tokens} "
          f"llm_calls={ctx.usage.llm_calls} "
          f"tool_calls={ctx.usage.tool_calls}")
    if result.final_text:
        print()
        print(result.final_text)
    return 0 if all(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
