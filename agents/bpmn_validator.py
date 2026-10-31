from __future__ import annotations

import json

from copilot import Tool, ToolInvocation, ToolResult

from bpmn.validator import validate_bpmn

BPMN_VALIDATOR_PROMPT = """You are BPMN_validator, a strict BPMN quality specialist.
Validate the XML produced by BPMN_builder by calling validate_bpmn_xml. Check XML
well-formedness, process events, sequence-flow references, BPMN DI bounds, and
edge waypoints. Report every error precisely. If invalid, send the errors back
to the supervisor so it can delegate a correction to BPMN_builder. Never silently
accept invalid XML."""


def _validate(invocation: ToolInvocation) -> ToolResult:
    xml = invocation.arguments.get("xml", "") if isinstance(invocation.arguments, dict) else ""
    result = validate_bpmn(xml)
    payload = json.dumps({
        "valid": result.valid,
        "errors": result.errors,
        "warnings": result.warnings,
    })
    return ToolResult(
        text_result_for_llm=payload,
        result_type="success" if result.valid else "failure",
        error="; ".join(result.errors) if result.errors else None,
        session_log="BPMN_validator checked the process model.",
    )


BPMN_VALIDATOR_TOOL = Tool(
    name="validate_bpmn_xml",
    description="Validate BPMN XML and its diagram interchange layout.",
    handler=_validate,
    parameters={
        "type": "object",
        "properties": {"xml": {"type": "string", "description": "Complete BPMN 2.0 XML."}},
        "required": ["xml"],
    },
    skip_permission=True,
)
