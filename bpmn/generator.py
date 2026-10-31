from __future__ import annotations

import re
import uuid
from collections.abc import Iterable
from xml.etree import ElementTree as ET

BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
BPMNDI_NS = "http://www.omg.org/spec/BPMN/20100524/DI"
DC_NS = "http://www.omg.org/spec/DD/20100524/DC"
DI_NS = "http://www.omg.org/spec/DD/20100524/DI"
ET.register_namespace("bpmn", BPMN_NS)
ET.register_namespace("bpmndi", BPMNDI_NS)
ET.register_namespace("dc", DC_NS)
ET.register_namespace("di", DI_NS)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


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
    """Create BPMN 2.0 XML with a deterministic horizontal layout."""
    if isinstance(labels, str):
        labels = _labels_from_text(labels)
    labels = _normalise_labels(labels)
    definitions = ET.Element(
        f"{{{BPMN_NS}}}definitions",
        {"id": _id("Definitions"), "targetNamespace": "http://example.com/bpmn"},
    )
    process = ET.SubElement(definitions, f"{{{BPMN_NS}}}process", {"id": _id("Process"), "name": process_name, "isExecutable": "false"})
    start = ET.SubElement(process, f"{{{BPMN_NS}}}startEvent", {"id": _id("StartEvent"), "name": "Start"})
    tasks = [
        ET.SubElement(process, f"{{{BPMN_NS}}}task", {"id": _id("Task"), "name": label})
        for label in labels
    ]
    end = ET.SubElement(process, f"{{{BPMN_NS}}}endEvent", {"id": _id("EndEvent"), "name": "End"})
    nodes = [start, *tasks, end]
    flows = []
    for source, target in zip(nodes, nodes[1:]):
        flow = ET.SubElement(process, f"{{{BPMN_NS}}}sequenceFlow", {"id": _id("Flow"), "sourceRef": source.attrib["id"], "targetRef": target.attrib["id"]})
        flows.append(flow)

    diagram = ET.SubElement(definitions, f"{{{BPMNDI_NS}}}BPMNDiagram", {"id": _id("BPMNDiagram")})
    plane = ET.SubElement(diagram, f"{{{BPMNDI_NS}}}BPMNPlane", {"id": _id("BPMNPlane"), "bpmnElement": process.attrib["id"]})
    shapes = [(start, 100, 180, 36, 36)]
    shapes.extend((task, 180 + index * 160, 170, 100, 80) for index, task in enumerate(tasks))
    shapes.append((end, 200 + len(tasks) * 160, 180, 36, 36))
    for element, x, y, width, height in shapes:
        shape = ET.SubElement(plane, f"{{{BPMNDI_NS}}}BPMNShape", {"id": _id("Shape"), "bpmnElement": element.attrib["id"]})
        ET.SubElement(shape, f"{{{DC_NS}}}Bounds", {"x": str(x), "y": str(y), "width": str(width), "height": str(height)})
    for index, flow in enumerate(flows):
        edge = ET.SubElement(plane, f"{{{BPMNDI_NS}}}BPMNEdge", {"id": _id("Edge"), "bpmnElement": flow.attrib["id"]})
        source_x = shapes[index][1] + shapes[index][3]
        source_y = shapes[index][2] + shapes[index][4] / 2
        target_x = shapes[index + 1][1]
        target_y = shapes[index + 1][2] + shapes[index + 1][4] / 2
        ET.SubElement(edge, f"{{{DI_NS}}}waypoint", {"x": str(source_x), "y": str(source_y)})
        ET.SubElement(edge, f"{{{DI_NS}}}waypoint", {"x": str(target_x), "y": str(target_y)})
    return ET.tostring(definitions, encoding="unicode", xml_declaration=True)
