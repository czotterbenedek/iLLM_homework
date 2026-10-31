"""Copilot tool that checks a process model against BPMN modeling rules."""

from __future__ import annotations

import json
from collections.abc import Callable

from copilot import Tool, ToolInvocation, ToolResult

from bpmn.spec import normalize_spec
from bpmn.validator import validate_bpmn, validate_spec
from models.schemas import PROCESS_SPEC_SCHEMA, ProcessSpec

from .generate_bpmn import spec_from_arguments

VALIDATE_TOOL_NAME = "validate_process_model"

__all__ = ["VALIDATE_TOOL_NAME", "create_validate_tool", "validate_bpmn"]


def create_validate_tool(latest_spec: Callable[[], ProcessSpec | None]) -> Tool:
    def handler(invocation: ToolInvocation) -> ToolResult:
        arguments = invocation.arguments if isinstance(invocation.arguments, dict) else {}
        if arguments.get("xml"):
            result = validate_bpmn(arguments["xml"])
        else:
            try:
                spec = spec_from_arguments(invocation.arguments) if arguments.get("spec") else latest_spec()
            except (ValueError, TypeError) as exc:
                spec, error = None, str(exc)
            else:
                error = "No process model has been built yet. Call build_process_model first."
            if spec is None:
                return ToolResult(
                    text_result_for_llm=json.dumps({"valid": False, "errors": [error]}),
                    result_type="failure",
                    error=error,
                )
            result = validate_spec(normalize_spec(spec)[0])
        payload = {"valid": result.valid, "errors": result.errors, "warnings": result.warnings}
        return ToolResult(text_result_for_llm=json.dumps(payload), session_log="Process model validated.")

    return Tool(
        name=VALIDATE_TOOL_NAME,
        description=(
            "Validate a process model against BPMN rules. Without arguments it validates the model "
            "most recently built with build_process_model."
        ),
        handler=handler,
        parameters={
            "type": "object",
            "properties": {"spec": PROCESS_SPEC_SCHEMA},
        },
        skip_permission=True,
    )
