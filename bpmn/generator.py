from __future__ import annotations

import re
from collections.abc import Iterable
from xml.etree import ElementTree as ET

from models.schemas import Flow, Node, ProcessSpec

from .layout import Bounds, compute_layout

BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
BPMNDI_NS = "http://www.omg.org/spec/BPMN/20100524/DI"
DC_NS = "http://www.omg.org/spec/DD/20100524/DC"
DI_NS = "http://www.omg.org/spec/DD/20100524/DI"
ET.register_namespace("bpmn", BPMN_NS)
ET.register_namespace("bpmndi", BPMNDI_NS)
ET.register_namespace("dc", DC_NS)
ET.register_namespace("di", DI_NS)

_TRIGGER_ELEMENTS = {
    "message": "messageEventDefinition",
    "timer": "timerEventDefinition",
    "signal": "signalEventDefinition",
    "conditional": "conditionalEventDefinition",
    "error": "errorEventDefinition",
    "terminate": "terminateEventDefinition",
}


def _unique(value: str, used: set[str]) -> str:
    candidate = re.sub(r"[^A-Za-z0-9_.-]+", "_", value)
    original, index = candidate, 2
    while candidate in used:
        candidate = f"{original}_{index}"
        index += 1
    used.add(candidate)
    return candidate


def _bounds(parent: ET.Element, bounds: Bounds, tag: str = "Bounds") -> None:
    ET.SubElement(
        parent,
        f"{{{DC_NS}}}{tag}",
        {"x": f"{bounds.x:g}", "y": f"{bounds.y:g}", "width": f"{bounds.width:g}", "height": f"{bounds.height:g}"},
    )


def build_bpmn_xml(spec: ProcessSpec) -> str:
    """Render a normalized ProcessSpec as BPMN 2.0 XML including a generated diagram layout."""
    layout = compute_layout(spec)
    used = {node.id for node in spec.nodes} | {lane.id for lane in spec.lanes}
    definitions = ET.Element(
        f"{{{BPMN_NS}}}definitions",
        {
            "id": _unique("Definitions_1", used),
            "targetNamespace": "http://bpmn.io/schema/bpmn",
            "exporter": "BPMN Process Assistant",
        },
    )
    process_id = _unique("Process_1", used)
    collaboration = None
    if spec.lanes:
        collaboration = ET.SubElement(definitions, f"{{{BPMN_NS}}}collaboration", {"id": _unique("Collaboration_1", used)})
        participant_id = _unique("Participant_1", used)
        ET.SubElement(
            collaboration,
            f"{{{BPMN_NS}}}participant",
            {"id": participant_id, "name": spec.name, "processRef": process_id},
        )
    process = ET.SubElement(
        definitions,
        f"{{{BPMN_NS}}}process",
        {"id": process_id, "name": spec.name, "isExecutable": "false"},
    )
    if spec.lanes:
        lane_set = ET.SubElement(process, f"{{{BPMN_NS}}}laneSet", {"id": _unique("LaneSet_1", used)})
        for lane in spec.lanes:
            lane_element = ET.SubElement(lane_set, f"{{{BPMN_NS}}}lane", {"id": lane.id, "name": lane.name})
            for node in spec.nodes:
                if node.lane == lane.id:
                    ET.SubElement(lane_element, f"{{{BPMN_NS}}}flowNodeRef").text = node.id

    flow_ids = [_unique(f"Flow_{flow.source}_{flow.target}", used) for flow in spec.flows]
    for node in spec.nodes:
        attributes = {"id": node.id}
        if node.name:
            attributes["name"] = node.name
        if node.type == "subProcess":
            attributes["triggeredByEvent"] = "false"
        element = ET.SubElement(process, f"{{{BPMN_NS}}}{node.type}", attributes)
        for flow_id, flow in zip(flow_ids, spec.flows):
            if flow.target == node.id:
                ET.SubElement(element, f"{{{BPMN_NS}}}incoming").text = flow_id
        for flow_id, flow in zip(flow_ids, spec.flows):
            if flow.source == node.id:
                ET.SubElement(element, f"{{{BPMN_NS}}}outgoing").text = flow_id
        if node.trigger in _TRIGGER_ELEMENTS:
            ET.SubElement(
                element,
                f"{{{BPMN_NS}}}{_TRIGGER_ELEMENTS[node.trigger]}",
                {"id": _unique(f"{node.id}_{node.trigger}", used)},
            )
    for flow_id, flow in zip(flow_ids, spec.flows):
        attributes = {"id": flow_id, "sourceRef": flow.source, "targetRef": flow.target}
        if flow.name:
            attributes["name"] = flow.name
        ET.SubElement(process, f"{{{BPMN_NS}}}sequenceFlow", attributes)

    diagram = ET.SubElement(definitions, f"{{{BPMNDI_NS}}}BPMNDiagram", {"id": _unique("BPMNDiagram_1", used)})
    plane = ET.SubElement(
        diagram,
        f"{{{BPMNDI_NS}}}BPMNPlane",
        {
            "id": _unique("BPMNPlane_1", used),
            "bpmnElement": collaboration.attrib["id"] if collaboration is not None else process_id,
        },
    )
    if layout.pool is not None:
        shape = ET.SubElement(
            plane,
            f"{{{BPMNDI_NS}}}BPMNShape",
            {"id": f"{participant_id}_di", "bpmnElement": participant_id, "isHorizontal": "true"},
        )
        _bounds(shape, layout.pool)
    for lane in spec.lanes:
        shape = ET.SubElement(
            plane,
            f"{{{BPMNDI_NS}}}BPMNShape",
            {"id": _unique(f"{lane.id}_di", used), "bpmnElement": lane.id, "isHorizontal": "true"},
        )
        _bounds(shape, layout.lanes[lane.id])
    for node in spec.nodes:
        attributes = {"id": _unique(f"{node.id}_di", used), "bpmnElement": node.id}
        if node.type == "exclusiveGateway":
            attributes["isMarkerVisible"] = "true"
        if node.type == "subProcess":
            attributes["isExpanded"] = "false"
        shape = ET.SubElement(plane, f"{{{BPMNDI_NS}}}BPMNShape", attributes)
        _bounds(shape, layout.shapes[node.id])
        if node.id in layout.shape_labels:
            _bounds(ET.SubElement(shape, f"{{{BPMNDI_NS}}}BPMNLabel"), layout.shape_labels[node.id])
    for flow_id, points, label in zip(flow_ids, layout.edges, layout.labels):
        edge = ET.SubElement(
            plane,
            f"{{{BPMNDI_NS}}}BPMNEdge",
            {"id": _unique(f"{flow_id}_di", used), "bpmnElement": flow_id},
        )
        for x, y in points:
            ET.SubElement(edge, f"{{{DI_NS}}}waypoint", {"x": f"{x:g}", "y": f"{y:g}"})
        if label is not None:
            _bounds(ET.SubElement(edge, f"{{{BPMNDI_NS}}}BPMNLabel"), label)
    ET.indent(definitions)
    return ET.tostring(definitions, encoding="unicode", xml_declaration=True)


def _labels_from_text(text: str) -> list[str]:
    quoted = re.findall(r"""['"]([^'"]+)['"]""", text)
    if quoted:
        return quoted
    cleaned = re.sub(r"(?i)\b(create|a|an|process|for|handling|with|and)\b", " ", text)
    words = re.sub(r"\s+", " ", cleaned).strip()
    return [part.strip().capitalize() for part in re.split(r",| then | and ", words) if part.strip()]


def _normalise_labels(labels: Iterable[str]) -> list[str]:
    result = [label.strip() for label in labels if label.strip()]
    return result or ["Process task"]


def generate_bpmn(labels: Iterable[str] | str, process_name: str = "Generated process") -> str:
    """Create BPMN 2.0 XML for a linear process with one task per label."""
    if isinstance(labels, str):
        labels = _labels_from_text(labels)
    labels = _normalise_labels(labels)
    nodes = [Node("StartEvent_1", "startEvent", "Start")]
    nodes.extend(Node(f"Task_{index}", "task", label) for index, label in enumerate(labels, start=1))
    nodes.append(Node("EndEvent_1", "endEvent", "End"))
    flows = [Flow(left.id, right.id) for left, right in zip(nodes, nodes[1:])]
    return build_bpmn_xml(ProcessSpec(name=process_name, nodes=nodes, flows=flows))
