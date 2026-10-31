from __future__ import annotations

import re
from collections.abc import Iterable
from xml.etree import ElementTree as ET

from .generator import (
    BPMN_NS,
    BPMNDI_NS,
    DC_NS,
    DI_NS,
    generate_bpmn,
)

SUPPORTED_NODES = {
    "startEvent": "startEvent",
    "endEvent": "endEvent",
    "task": "task",
    "userTask": "userTask",
    "serviceTask": "serviceTask",
    "sendTask": "sendTask",
    "receiveTask": "receiveTask",
    "manualTask": "manualTask",
    "scriptTask": "scriptTask",
    "businessRuleTask": "businessRuleTask",
    "exclusiveGateway": "exclusiveGateway",
    "parallelGateway": "parallelGateway",
    "inclusiveGateway": "inclusiveGateway",
}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _safe_id(value: str, prefix: str, used: set[str]) -> str:
    candidate = re.sub(r"[^A-Za-z0-9_.-]", "_", value or "")
    if not candidate or not re.match(r"[A-Za-z_]", candidate):
        candidate = f"{prefix}_{candidate}"
    original = candidate
    index = 2
    while candidate in used:
        candidate = f"{original}_{index}"
        index += 1
    used.add(candidate)
    return candidate


def _fallback(labels: Iterable[str] | str) -> str:
    return generate_bpmn(labels)


def ensure_renderable_bpmn(xml: str, fallback_labels: str = "Process task") -> str:
    """Return canonical BPMN XML that bpmn-js can import.

    The function intentionally preserves recognizable user content but repairs
    structural and DI defects. It does not attempt to decide whether the
    process matches the user's business requirements.
    """
    try:
        source = ET.fromstring(xml)
    except ET.ParseError:
        return _fallback(fallback_labels)

    source_process = next((element for element in source.iter() if _local(element.tag) == "process"), None)
    if source_process is None:
        return _fallback(fallback_labels)

    used: set[str] = set()
    definitions = ET.Element(
        f"{{{BPMN_NS}}}definitions",
        {"id": _safe_id(source.attrib.get("id", ""), "Definitions", used), "targetNamespace": "http://example.com/bpmn"},
    )
    process = ET.SubElement(
        definitions,
        f"{{{BPMN_NS}}}process",
        {
            "id": _safe_id(source_process.attrib.get("id", ""), "Process", used),
            "name": source_process.attrib.get("name", "Generated process"),
            "isExecutable": "false",
        },
    )

    node_ids: dict[str, str] = {}
    nodes: list[tuple[ET.Element, str]] = []
    for element in list(source_process):
        kind = SUPPORTED_NODES.get(_local(element.tag))
        if not kind:
            continue
        node_id = _safe_id(element.attrib.get("id", ""), kind, used)
        node_ids[element.attrib.get("id", "")] = node_id
        attributes = {"id": node_id}
        if element.attrib.get("name"):
            attributes["name"] = element.attrib["name"]
        if kind.endswith("Gateway"):
            attributes["gatewayDirection"] = element.attrib.get("gatewayDirection", "Unspecified")
        node = ET.SubElement(process, f"{{{BPMN_NS}}}{kind}", attributes)
        nodes.append((node, kind))

    if not any(kind == "startEvent" for _, kind in nodes):
        node = ET.Element(f"{{{BPMN_NS}}}startEvent", {"id": _safe_id("", "StartEvent", used), "name": "Start"})
        process.insert(0, node)
        nodes.insert(0, (node, "startEvent"))
    if not any(kind == "endEvent" for _, kind in nodes):
        node = ET.SubElement(process, f"{{{BPMN_NS}}}endEvent", {"id": _safe_id("", "EndEvent", used), "name": "End"})
        nodes.append((node, "endEvent"))

    flow_pairs: list[tuple[str, str, str]] = []
    for element in list(source_process):
        if _local(element.tag) != "sequenceFlow":
            continue
        source_id = node_ids.get(element.attrib.get("sourceRef", ""))
        target_id = node_ids.get(element.attrib.get("targetRef", ""))
        if source_id and target_id and source_id != target_id:
            flow_pairs.append((source_id, target_id, element.attrib.get("name", "")))

    node_id_list = [node.attrib["id"] for node, _ in nodes]
    if not flow_pairs:
        flow_pairs = [(left, right, "") for left, right in zip(node_id_list, node_id_list[1:])]
    else:
        connected = {source for source, _, _ in flow_pairs} | {target for _, target, _ in flow_pairs}
        for left, right in zip(node_id_list, node_id_list[1:]):
            if left not in connected and (left, right, "") not in flow_pairs:
                flow_pairs.append((left, right, ""))

    flows: list[tuple[ET.Element, str, str]] = []
    for source_id, target_id, name in flow_pairs:
        attributes = {
            "id": _safe_id("", "Flow", used),
            "sourceRef": source_id,
            "targetRef": target_id,
        }
        if name:
            attributes["name"] = name
        flow = ET.SubElement(process, f"{{{BPMN_NS}}}sequenceFlow", attributes)
        flows.append((flow, source_id, target_id))

    diagram = ET.SubElement(definitions, f"{{{BPMNDI_NS}}}BPMNDiagram", {"id": _safe_id("", "BPMNDiagram", used)})
    plane = ET.SubElement(
        diagram,
        f"{{{BPMNDI_NS}}}BPMNPlane",
        {"id": _safe_id("", "BPMNPlane", used), "bpmnElement": process.attrib["id"]},
    )
    positions: dict[str, tuple[float, float, float, float]] = {}
    for index, (node, kind) in enumerate(nodes):
        width, height = (36, 36) if kind.endswith("Event") else ((50, 50) if kind.endswith("Gateway") else (120, 80))
        x, y = 100 + index * 180, 160
        if kind.endswith("Gateway"):
            y = 175
        positions[node.attrib["id"]] = (x, y, width, height)
        shape = ET.SubElement(
            plane,
            f"{{{BPMNDI_NS}}}BPMNShape",
            {"id": _safe_id("", "Shape", used), "bpmnElement": node.attrib["id"]},
        )
        ET.SubElement(shape, f"{{{DC_NS}}}Bounds", {"x": str(x), "y": str(y), "width": str(width), "height": str(height)})
    for flow, source_id, target_id in flows:
        source_x, source_y, source_width, source_height = positions[source_id]
        target_x, target_y, _, target_height = positions[target_id]
        edge = ET.SubElement(
            plane,
            f"{{{BPMNDI_NS}}}BPMNEdge",
            {"id": _safe_id("", "Edge", used), "bpmnElement": flow.attrib["id"]},
        )
        ET.SubElement(edge, f"{{{DI_NS}}}waypoint", {"x": str(source_x + source_width), "y": str(source_y + source_height / 2)})
        ET.SubElement(edge, f"{{{DI_NS}}}waypoint", {"x": str(target_x), "y": str(target_y + target_height / 2)})
    return ET.tostring(definitions, encoding="unicode", xml_declaration=True)
