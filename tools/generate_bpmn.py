"""Copilot tool that turns a layout-free process spec into a validated BPMN model."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from copilot import Tool, ToolInvocation, ToolResult

from bpmn.generator import generate_bpmn
from bpmn.spec import normalize_spec, parse_spec, summarize_spec
from bpmn.validator import validate_spec
from models.schemas import PROCESS_SPEC_SCHEMA, ProcessSpec, ValidationResult

BUILD_TOOL_NAME = "build_process_model"

__all__ = ["BUILD_TOOL_NAME", "create_build_tool", "generate_bpmn", "spec_from_arguments"]


def spec_from_arguments(arguments: Any) -> ProcessSpec:
    """Read a process spec from tool arguments, tolerating common small-model mistakes."""
    if isinstance(arguments, str):
        arguments = json.loads(arguments)
    if not isinstance(arguments, dict):
        raise ValueError("Arguments must be a JSON object with a 'spec' field.")
    return parse_spec(arguments.get("spec", arguments))


def create_build_tool(on_built: Callable[[ProcessSpec, ValidationResult], None]) -> Tool:
    def handler(invocation: ToolInvocation) -> ToolResult:
        try:
            spec = spec_from_arguments(invocation.arguments)
        except (ValueError, TypeError) as exc:
            message = f"Could not read the process spec: {exc}. Send {{\"spec\": {{\"name\", \"nodes\", \"flows\"}}}}."
            return ToolResult(
                text_result_for_llm=json.dumps({"status": "rejected", "errors": [message]}),
                result_type="failure",
                error=message,
            )
        spec, repairs = normalize_spec(spec)
        report = validate_spec(spec)
        on_built(spec, report)
        payload: dict[str, Any] = {
            "status": "built" if report.valid else "needs_fixes",
            "summary": f"{spec.name}: {summarize_spec(spec)}",
            "errors": report.errors,
            "warnings": report.warnings,
        }
        if repairs:
            payload["repairs"] = repairs
            payload["normalized_spec"] = spec.to_dict()
        return ToolResult(text_result_for_llm=json.dumps(payload), session_log="Process model built.")

    return Tool(
        name=BUILD_TOOL_NAME,
        description=(
            "Build the complete process model from a layout-free JSON spec. The diagram layout and "
            "BPMN XML are generated automatically. Returns errors/warnings to fix."
        ),
        handler=handler,
        parameters={"type": "object", "properties": {"spec": PROCESS_SPEC_SCHEMA}, "required": ["spec"]},
        skip_permission=True,
    )
