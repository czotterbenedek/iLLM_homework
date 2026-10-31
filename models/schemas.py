from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

EVENT_TYPES = ("startEvent", "endEvent", "intermediateCatchEvent", "intermediateThrowEvent")
TASK_TYPES = (
    "task",
    "userTask",
    "serviceTask",
    "sendTask",
    "receiveTask",
    "manualTask",
    "scriptTask",
    "businessRuleTask",
    "subProcess",
    "callActivity",
)
GATEWAY_TYPES = ("exclusiveGateway", "parallelGateway", "inclusiveGateway", "eventBasedGateway")
NODE_TYPES = EVENT_TYPES + TASK_TYPES + GATEWAY_TYPES
EVENT_TRIGGERS = ("none", "message", "timer", "signal", "conditional", "error", "terminate")


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class Lane:
    id: str
    name: str = ""


@dataclass
class Node:
    id: str
    type: str = "task"
    name: str = ""
    lane: str | None = None
    trigger: str | None = None

    @property
    def is_event(self) -> bool:
        return self.type in EVENT_TYPES

    @property
    def is_gateway(self) -> bool:
        return self.type in GATEWAY_TYPES


@dataclass
class Flow:
    source: str
    target: str
    name: str = ""
    id: str | None = None


@dataclass
class ProcessSpec:
    """Layout-free description of a process; XML and diagram layout are derived from it."""

    name: str = "Process"
    nodes: list[Node] = field(default_factory=list)
    flows: list[Flow] = field(default_factory=list)
    lanes: list[Lane] = field(default_factory=list)

    def node(self, node_id: str) -> Node | None:
        return next((node for node in self.nodes if node.id == node_id), None)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"name": self.name}
        if self.lanes:
            data["lanes"] = [{"id": lane.id, "name": lane.name} for lane in self.lanes]
        data["nodes"] = []
        for node in self.nodes:
            item: dict[str, Any] = {"id": node.id, "type": node.type, "name": node.name}
            if node.lane:
                item["lane"] = node.lane
            if node.trigger and node.trigger != "none":
                item["trigger"] = node.trigger
            data["nodes"].append(item)
        data["flows"] = []
        for flow in self.flows:
            item = {"source": flow.source, "target": flow.target}
            if flow.name:
                item["name"] = flow.name
            data["flows"].append(item)
        return data


@dataclass
class AgentResponse:
    message: str
    bpmn_xml: str | None = None
    validation: ValidationResult | None = None
    spec: ProcessSpec | None = None
    changes: list[str] = field(default_factory=list)


PROCESS_SPEC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "Complete process model. Never include coordinates or XML.",
    "properties": {
        "name": {"type": "string", "description": "Short process name."},
        "lanes": {
            "type": "array",
            "description": "Optional swimlanes (roles, departments, systems). Omit when no roles are mentioned.",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "name": {"type": "string"}},
                "required": ["id", "name"],
            },
        },
        "nodes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "Unique, stable id such as Task_CheckOrder."},
                    "type": {"type": "string", "enum": list(NODE_TYPES)},
                    "name": {"type": "string"},
                    "lane": {"type": "string", "description": "Lane id; required when lanes are used."},
                    "trigger": {"type": "string", "enum": list(EVENT_TRIGGERS)},
                },
                "required": ["id", "type", "name"],
            },
        },
        "flows": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "Source node id."},
                    "target": {"type": "string", "description": "Target node id."},
                    "name": {"type": "string", "description": "Condition label, e.g. 'Yes' after a gateway."},
                },
                "required": ["source", "target"],
            },
        },
    },
    "required": ["name", "nodes", "flows"],
}

