"""Runner wiring: stub-scripted end-to-end run into a real session dir."""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from fews_agent.agent.providers.base import ToolCall

from runners.react import run_react as runner

from .conftest import StubProvider, final, tool_use

STANDARDS = (Path(__file__).resolve().parents[2]
             / "fews_agent" / "agent" / "standard_inputs")


def test_main_scripted_run(tmp_path, monkeypatch, capsys):
    timesteps = yaml.safe_load(
        (STANDARDS / "timeSteps.yaml").read_text(encoding="utf-8"))
    provider = StubProvider(script=[
        tool_use(ToolCall(id="a", name="write_config_file",
                          arguments={"spec_name": "timeSteps",
                                     "data": timesteps})),
        final("Wrote the time steps file."),
    ])
    monkeypatch.setattr(runner, "PROJECTS_ROOT", tmp_path)
    monkeypatch.setattr(runner, "get_provider",
                        lambda name, model: provider)

    exit_code = runner.main(["--project", "demo", "--prompt", "go",
                             "--engine", "native"])
    assert exit_code == 0

    out = capsys.readouterr().out
    assert "[TOOL] write_config_file" in out
    assert "xsd_failures=0" in out

    session = next((tmp_path / "demo").iterdir())
    assert (session / "generated" / "RegionConfigFiles"
            / "TimeSteps.xml").is_file()
    log_lines = [json.loads(line) for line in
                 (session / "react_log.jsonl")
                 .read_text(encoding="utf-8").splitlines()]
    kinds = [entry["kind"] for entry in log_lines]
    assert kinds == ["user", "assistant", "tool_result", "assistant",
                     "stop"]


def test_main_fails_loudly_on_guard_stop(tmp_path, monkeypatch, capsys):
    provider = StubProvider(script=[
        tool_use(ToolCall(id=f"c{i}", name="list_project_files",
                          arguments={}))
        for i in range(5)
    ])
    monkeypatch.setattr(runner, "PROJECTS_ROOT", tmp_path)
    monkeypatch.setattr(runner, "get_provider",
                        lambda name, model: provider)

    exit_code = runner.main(["--project", "demo", "--prompt", "go",
                             "--engine", "native",
                             "--max-iterations", "2"])
    assert exit_code == 1
    assert "max_iterations" in capsys.readouterr().out


def test_main_langgraph_engine_default(tmp_path, monkeypatch, capsys):
    pytest = __import__("pytest")
    pytest.importorskip("langgraph")
    from langchain_core.messages import AIMessage

    from fews_agent.react import lg_agent

    from .test_lg_agent import ScriptedChatModel

    timesteps = yaml.safe_load(
        (STANDARDS / "timeSteps.yaml").read_text(encoding="utf-8"))
    model = ScriptedChatModel(script=[
        AIMessage(content="", tool_calls=[
            {"name": "write_config_file", "id": "a",
             "args": {"spec_name": "timeSteps", "data": timesteps}},
        ]),
        AIMessage(content="done via langgraph"),
    ])
    monkeypatch.setattr(runner, "PROJECTS_ROOT", tmp_path)
    monkeypatch.setattr(
        runner, "get_provider",
        lambda name, model_arg: type("P", (), {"model": "stub"})())
    monkeypatch.setattr(lg_agent, "default_chat_model", lambda m: model)

    exit_code = runner.main(["--project", "demo", "--prompt", "go"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "[ENGINE] langgraph" in out
    assert "[LANGSMITH]" in out
    assert "done via langgraph" in out
    session = next((tmp_path / "demo").iterdir())
    assert (session / "generated" / "RegionConfigFiles"
            / "TimeSteps.xml").is_file()
