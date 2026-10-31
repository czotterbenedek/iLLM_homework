from __future__ import annotations

from xml.etree import ElementTree as ET

from copilot import Tool, ToolInvocation, ToolResult

BPMN_BUILDER_PROMPT = """You are BPMN_builder, a specialist sub-agent.
Interpret the user's natural-language process request and the current BPMN XML.
Create or modify a BPMN 2.0 model. The output must be complete XML with:
- a bpmn:definitions root and bpmn:process;
- start/end events, tasks, gateways when decisions are requested, and sequence flows;
- matching BPMN DI shapes, bounds, edges, and at least two waypoints per edge.
Preserve existing elements when the user asks for a modification. Do not invent
explanations in the XML. Before returning, call bpmn_builder_finalize with the
complete XML. Return the finalized XML only."""


def _finalize(invocation: ToolInvocation) -> ToolResult:
    xml = invocation.arguments.get("xml", "") if isinstance(invocation.arguments, dict) else ""
    if not xml.strip():
        return ToolResult(text_result_for_llm="The XML is empty.", result_type="failure", error="empty XML")
    try:
        ET.fromstring(xml)
    except ET.ParseError as exc:
        return ToolResult(text_result_for_llm=f"XML is not well formed: {exc}", result_type="failure", error=str(exc))
    return ToolResult(text_result_for_llm=xml, session_log="BPMN builder finalized an XML draft.")


BPMN_BUILDER_TOOL = Tool(
    name="bpmn_builder_finalize",
    description="Check and return the BPMN_builder's complete XML draft before handoff.",
    handler=_finalize,
    parameters={
        "type": "object",
        "properties": {"xml": {"type": "string", "description": "Complete BPMN 2.0 XML draft."}},
        "required": ["xml"],
    },
    skip_permission=True,
)
