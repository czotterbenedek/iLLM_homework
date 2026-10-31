import json
from types import SimpleNamespace

from agents.config_loader import custom_agent, load_agent_config, render
from agents.copilot_orchestrator import clean_message, extract_spec
from bpmn.generator import generate_bpmn
from tools.generate_bpmn import create_build_tool
from tools.validate_bpmn import create_validate_tool

SPEC = {
    "name": "Mini",
    "nodes": [
        {"id": "Start", "type": "startEvent", "name": "Request received"},
        {"id": "Task_Review", "type": "userTask", "name": "Review request"},
        {"id": "End", "type": "endEvent", "name": "Request handled"},
    ],
    "flows": [{"source": "Start", "target": "Task_Review"}, {"source": "Task_Review", "target": "End"}],
}


def test_agent_configs_render_all_placeholders():
    for name in ("supervisor", "bpmn_builder", "bpmn_validator"):
        agent = custom_agent(name)
        assert agent["prompt"] and "{{" not in agent["prompt"]
        assert agent["tools"]
    templates = load_agent_config("supervisor")["templates"]
    prompt = render(templates["modify_model"], {"instruction": "Add {braces}", "current_spec": "{}"})
    assert "Add {braces}" in prompt and "{{" not in prompt


def test_extract_spec_from_tagged_fenced_bare_json_and_xml():
    payload = json.dumps(SPEC)
    for content in (
        f"Done.\n<process_spec>{payload}</process_spec>",
        f"Here you go:\n```json\n{payload}\n```",
        f"Model: {payload}",
        f"Unterminated <process_spec>{payload}",
        generate_bpmn(["Review request"]),
    ):
        spec = extract_spec(content)
        assert spec is not None and any(node.name == "Review request" for node in spec.nodes)
    assert extract_spec("Which department handles refunds? <no_change/>") is None


def test_clean_message_never_shows_xml_or_json():
    content = (
        "I added a review step.\n\nHere is the model:\n"
        f"<process_spec>{json.dumps(SPEC)}</process_spec>\n"
        f"```xml\n{generate_bpmn(['A'])}\n```\n{generate_bpmn(['B'])}"
    )
    assert clean_message(content) == "I added a review step."
    assert clean_message("Sure! <no_change/>") == "Sure!"


def test_build_and_validate_tools_share_the_latest_model():
    built = []
    build = create_build_tool(lambda spec, report: built.append((spec, report)))
    result = build.handler(SimpleNamespace(arguments={"spec": json.dumps(SPEC)}))
    payload = json.loads(result.text_result_for_llm)
    assert payload["status"] == "built" and built[0][1].valid
    assert "<" not in result.text_result_for_llm

    validate = create_validate_tool(lambda: built[-1][0])
    payload = json.loads(validate.handler(SimpleNamespace(arguments={})).text_result_for_llm)
    assert payload["valid"] is True

    rejected = build.handler(SimpleNamespace(arguments={"spec": "not json"}))
    assert rejected.result_type == "failure"
