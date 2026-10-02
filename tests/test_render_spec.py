"""render_spec: typed intermediate representation → template XML → XSD."""
from __future__ import annotations

from fews_agent.validation.render_spec import render_spec
from fews_agent.validation.toolbelt import tool_explain_diagnostic, tool_render_spec


WORKFLOW_DATA = {
    "version": "1.1",
    "activity": [
        {"moduleInstanceId": "ImportGFS", "runIndependent": True},
    ],
}


def test_happy_path_renders_workflow_xsd_ok():
    result = render_spec("Workflow", WORKFLOW_DATA)
    assert result["ok"] is True
    assert result["spec"] == "Workflow"
    assert "<workflow" in result["xml"]
    assert "ImportGFS" in result["xml"]
    assert result["suggested_relpath"]
    assert result["suggested_relpath"].startswith("WorkflowFiles/")
    assert result["validation_errors"] == []


def test_unknown_spec_returns_known_names_sample():
    result = render_spec("NotARealSpec", {"activity": []})
    assert result["ok"] is False
    assert result["xml"] == ""
    assert result["known_specs_sample"]
    assert any(e["loc"] == ["spec"] for e in result["validation_errors"])


def test_bad_field_returns_structured_loc_msg():
    result = render_spec("Workflow", {"notAField": True, "activity": []})
    assert result["ok"] is False
    assert result["xml"] == ""
    assert result["validation_errors"]
    first = result["validation_errors"][0]
    assert "loc" in first
    assert "msg" in first


def test_empty_workflow_fails_pydantic_not_raise():
    result = render_spec("Workflow", {})
    assert result["ok"] is False
    assert result["validation_errors"]


def test_field_order_in_payload_does_not_change_xsd_sequence():
    a = render_spec("Workflow", {
        "activity": [{"runIndependent": True, "moduleInstanceId": "ImportGFS"}],
        "version": "1.1",
    })
    b = render_spec("Workflow", {
        "version": "1.1",
        "activity": [{"moduleInstanceId": "ImportGFS", "runIndependent": True}],
    })
    assert a["ok"] and b["ok"]
    assert a["xml"] == b["xml"]
    assert a["xml"].index("<moduleInstanceId>") < a["xml"].index("</activity>")


def test_toolbelt_wrapper_matches():
    assert tool_render_spec("Workflow", WORKFLOW_DATA)["ok"] is True


def test_explain_fews_config_and_exit():
    cfg = tool_explain_diagnostic("fews.config")
    assert cfg["rule_id"] == "fews.config"
    assert "fix_hint" in cfg
    ext = tool_explain_diagnostic("fews.exit")
    assert ext["rule_id"] == "fews.exit"
