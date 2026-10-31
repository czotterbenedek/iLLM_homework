"""Parsing, repair and comparison of layout-free process specs."""

from __future__ import annotations

import json
import re
from typing import Any

from models.schemas import EVENT_TRIGGERS, GATEWAY_TYPES, NODE_TYPES, TASK_TYPES, Flow, Lane, Node, ProcessSpec

_TYPE_ALIASES = {
    "start": "startEvent",
    "startevent": "startEvent",
    "end": "endEvent",
    "endevent": "endEvent",
    "intermediateevent": "intermediateCatchEvent",
    "catchevent": "intermediateCatchEvent",
    "throwevent": "intermediateThrowEvent",
    "timer": "intermediateCatchEvent",
    "wait": "intermediateCatchEvent",
    "activity": "task",
    "step": "task",
    "user": "userTask",
    "human": "userTask",
    "service": "serviceTask",
    "system": "serviceTask",
    "automated": "serviceTask",
    "automatic": "serviceTask",
    "send": "sendTask",
    "receive": "receiveTask",
    "manual": "manualTask",
    "script": "scriptTask",
    "rule": "businessRuleTask",
    "businessrule": "businessRuleTask",
    "subprocess": "subProcess",
    "call": "callActivity",
    "gateway": "exclusiveGateway",
    "decision": "exclusiveGateway",
    "xor": "exclusiveGateway",
    "exclusive": "exclusiveGateway",
    "and": "parallelGateway",
    "parallel": "parallelGateway",
    "fork": "parallelGateway",
    "join": "parallelGateway",
    "or": "inclusiveGateway",
    "inclusive": "inclusiveGateway",
    "eventbased": "eventBasedGateway",
}
_CANONICAL = {name.lower(): name for name in NODE_TYPES}


def canonical_type(value: str | None) -> str | None:
    key = re.sub(r"[^a-z]", "", (value or "task").lower())
    if key.startswith("bpmn"):
        key = key[4:]
    return _CANONICAL.get(key) or _TYPE_ALIASES.get(key)


def safe_id(value: str, prefix: str, used: set[str]) -> str:
    candidate = re.sub(r"[^A-Za-z0-9_.-]+", "_", (value or "").strip()).strip("_")[:48]
    if not candidate or not re.match(r"[A-Za-z_]", candidate):
        candidate = f"{prefix}_{candidate}" if candidate else prefix
    original = candidate
    index = 2
    while candidate in used:
        candidate = f"{original}_{index}"
        index += 1
    used.add(candidate)
    return candidate


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _first(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if data.get(key) not in (None, ""):
            return data[key]
    return None


def parse_spec(data: Any) -> ProcessSpec:
    """Convert loosely structured LLM output (dict or JSON text) into a ProcessSpec."""
    if isinstance(data, str):
        data = json.loads(data)
    if not isinstance(data, dict):
        raise ValueError("The process spec must be a JSON object.")
    for wrapper in ("spec", "process", "model", "process_spec"):
        if isinstance(data.get(wrapper), dict) and not data.get("nodes"):
            data = data[wrapper]
    if isinstance(data.get("nodes") or data.get("elements"), str):
        data = {**data, "nodes": json.loads(data.get("nodes") or data["elements"])}

    lanes = []
    for item in data.get("lanes") or []:
        if isinstance(item, str):
            lanes.append(Lane(id="", name=item.strip()))
        elif isinstance(item, dict):
            lanes.append(Lane(id=_text(item.get("id")), name=_text(item.get("name"))))

    nodes = []
    for item in data.get("nodes") or data.get("elements") or []:
        if not isinstance(item, dict):
            continue
        nodes.append(
            Node(
                id=_text(item.get("id")),
                type=_text(_first(item, "type", "kind")) or "task",
                name=_text(_first(item, "name", "label")),
                lane=_text(_first(item, "lane", "laneId", "lane_id", "role")) or None,
                trigger=_text(_first(item, "trigger", "eventDefinition", "event")) or None,
            )
        )

    flows = []
    for item in data.get("flows") or data.get("sequenceFlows") or data.get("edges") or []:
        if not isinstance(item, dict):
            continue
        flows.append(
            Flow(
                source=_text(_first(item, "source", "sourceRef", "from")),
                target=_text(_first(item, "target", "targetRef", "to")),
                name=_text(_first(item, "name", "label", "condition")),
            )
        )
    name = _text(_first(data, "name", "process_name", "title")) or "Process"
    return ProcessSpec(name=name, nodes=nodes, flows=flows, lanes=lanes)


def _prefix(node_type: str) -> str:
    if node_type in GATEWAY_TYPES:
        return "Gateway"
    if node_type in TASK_TYPES:
        return "Task"
    return "Event"


def normalize_spec(spec: ProcessSpec) -> tuple[ProcessSpec, list[str]]:
    """Return a structurally consistent copy of ``spec`` and a list of repairs applied."""
    repairs: list[str] = []
    used: set[str] = set()

    lanes: list[Lane] = []
    lane_lookup: dict[str, str] = {}
    for lane in spec.lanes:
        label = lane.name or lane.id
        if not label:
            continue
        lane_id = safe_id(lane.id or f"Lane_{label}", "Lane", used)
        lanes.append(Lane(lane_id, lane.name or lane.id))
        for key in (lane.id, lane.name):
            if key:
                lane_lookup.setdefault(key.strip().lower(), lane_id)

    if not lanes and any(node.lane for node in spec.nodes):
        for node in spec.nodes:
            if node.lane and node.lane.lower() not in lane_lookup:
                lane_id = safe_id(f"Lane_{node.lane}", "Lane", used)
                lanes.append(Lane(lane_id, node.lane))
                lane_lookup[node.lane.lower()] = lane_id
        repairs.append("Created lanes from the roles referenced by the elements.")

    nodes: list[Node] = []
    by_id: dict[str, str] = {}
    by_name: dict[str, str] = {}
    for node in spec.nodes:
        node_type = canonical_type(node.type)
        label = node.name or node.id or node.type
        if node_type is None:
            repairs.append(f"Unknown element type '{node.type}' for '{label}' was modelled as a task.")
            node_type = "task"
        node_id = safe_id(node.id or node.name, _prefix(node_type), used)
        if node.id:
            by_id.setdefault(node.id, node_id)
            by_id.setdefault(node.id.lower(), node_id)
        if node.name:
            by_name.setdefault(node.name.lower(), node_id)
        trigger = (node.trigger or "").strip().lower() or None
        if trigger and (node_type not in ("startEvent", "endEvent", "intermediateCatchEvent", "intermediateThrowEvent")
                        or trigger not in EVENT_TRIGGERS):
            trigger = None
        lane = None
        if node.lane:
            lane = lane_lookup.get(node.lane.strip().lower())
            if lane is None and lanes:
                repairs.append(f"'{label}' referenced unknown lane '{node.lane}'.")
        nodes.append(Node(node_id, node_type, node.name, lane, trigger))

    def resolve(ref: str) -> str | None:
        if not ref:
            return None
        return by_id.get(ref) or by_id.get(ref.lower()) or by_name.get(ref.lower())

    flows: list[Flow] = []
    seen: set[tuple[str, str]] = set()
    for flow in spec.flows:
        source, target = resolve(flow.source), resolve(flow.target)
        if not source or not target:
            repairs.append(f"Removed a flow with an unknown endpoint ({flow.source or '?'} -> {flow.target or '?'}).")
            continue
        if source == target:
            repairs.append("Removed a flow that connected an element to itself.")
            continue
        if (source, target) in seen:
            continue
        seen.add((source, target))
        flows.append(Flow(source, target, flow.name))

    if not flows and len(nodes) > 1:
        flows = [Flow(left.id, right.id) for left, right in zip(nodes, nodes[1:])]
        repairs.append("No flows were given, so the elements were connected in the listed order.")

    result = ProcessSpec(name=spec.name.strip() or "Process", nodes=nodes, flows=flows, lanes=lanes)
    _ensure_start_and_end(result, used, repairs)

    if lanes:
        incoming = {flow.target: flow.source for flow in result.flows}
        for _ in range(len(result.nodes)):
            changed = False
            for node in result.nodes:
                if node.lane is None:
                    predecessor = result.node(incoming.get(node.id, ""))
                    if predecessor is not None and predecessor.lane:
                        node.lane = predecessor.lane
                        changed = True
            if not changed:
                break
        for node in result.nodes:
            if node.lane is None:
                node.lane = lanes[0].id
    return result, repairs


def _ensure_start_and_end(spec: ProcessSpec, used: set[str], repairs: list[str]) -> None:
    targets = {flow.target for flow in spec.flows}
    sources = {flow.source for flow in spec.flows}
    if not any(node.type == "startEvent" for node in spec.nodes):
        start = Node(safe_id("StartEvent", "Event", used), "startEvent", "Start")
        first = next((node for node in spec.nodes if node.id not in targets), spec.nodes[0] if spec.nodes else None)
        spec.nodes.insert(0, start)
        if first is not None:
            spec.flows.insert(0, Flow(start.id, first.id))
        repairs.append("Added a missing start event.")
    if not any(node.type == "endEvent" for node in spec.nodes):
        end = Node(safe_id("EndEvent", "Event", used), "endEvent", "End")
        dangling = [node for node in spec.nodes if node.id not in sources and node.type != "startEvent"]
        if not dangling and len(spec.nodes) > 1:
            dangling = [spec.nodes[-1]]
        spec.nodes.append(end)
        spec.flows.extend(Flow(node.id, end.id) for node in dangling)
        repairs.append("Added a missing end event.")


def repair_connectivity(spec: ProcessSpec) -> list[str]:
    """Last-resort repair that connects dangling elements so the model is at least renderable."""
    repairs: list[str] = []
    starts = {node.id for node in spec.nodes if node.type == "startEvent"}
    ends = {node.id for node in spec.nodes if node.type == "endEvent"}
    before = len(spec.flows)
    spec.flows = [flow for flow in spec.flows if flow.target not in starts and flow.source not in ends]
    if len(spec.flows) != before:
        repairs.append("Removed flows entering a start event or leaving an end event.")
    for index, node in enumerate(spec.nodes):
        if node.id not in starts and not any(flow.target == node.id for flow in spec.flows):
            previous = next((other for other in reversed(spec.nodes[:index]) if other.id not in ends), None)
            source = previous or next((other for other in spec.nodes if other.id in starts), None)
            if source is not None and source.id != node.id:
                spec.flows.append(Flow(source.id, node.id))
                repairs.append(f"Connected '{node.name or node.id}' to its preceding element.")
        if node.id not in ends and not any(flow.source == node.id for flow in spec.flows):
            following = next((other for other in spec.nodes[index + 1:] if other.id not in starts), None)
            target = following or next((other for other in spec.nodes if other.id in ends), None)
            if target is not None and target.id != node.id:
                spec.flows.append(Flow(node.id, target.id))
                repairs.append(f"Connected '{node.name or node.id}' to its following element.")
    return repairs


def summarize_spec(spec: ProcessSpec) -> str:
    tasks = sum(node.type in TASK_TYPES for node in spec.nodes)
    gateways = sum(node.type in GATEWAY_TYPES for node in spec.nodes)
    parts = [f"{tasks} task{'s' * (tasks != 1)}"]
    if gateways:
        parts.append(f"{gateways} gateway{'s' * (gateways != 1)}")
    if spec.lanes:
        parts.append(f"{len(spec.lanes)} lane{'s' * (len(spec.lanes) != 1)}")
    return ", ".join(parts)


def describe_changes(old: ProcessSpec | None, new: ProcessSpec) -> list[str]:
    if old is None:
        return []
    old_nodes = {node.id: node for node in old.nodes}
    new_nodes = {node.id: node for node in new.nodes}
    label = lambda node: f"'{node.name or node.id}'"  # noqa: E731
    added = [label(node) for node_id, node in new_nodes.items() if node_id not in old_nodes]
    removed = [label(node) for node_id, node in old_nodes.items() if node_id not in new_nodes]
    renamed = [
        f"{label(old_nodes[node_id])} → {label(node)}"
        for node_id, node in new_nodes.items()
        if node_id in old_nodes and old_nodes[node_id].name != node.name
    ]
    changes = []
    if added:
        changes.append("Added " + ", ".join(added))
    if removed:
        changes.append("Removed " + ", ".join(removed))
    if renamed:
        changes.append("Renamed " + ", ".join(renamed))
    old_flows = {(flow.source, flow.target, flow.name) for flow in old.flows}
    new_flows = {(flow.source, flow.target, flow.name) for flow in new.flows}
    if not changes and old_flows != new_flows:
        changes.append("Rewired the sequence flows")
    return changes
