from __future__ import annotations

from xml.etree import ElementTree as ET

from models.schemas import ValidationResult

from .generator import BPMN_NS, BPMNDI_NS, DC_NS, DI_NS


def validate_bpmn(xml: str) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        return ValidationResult(False, [f"Invalid XML: {exc}"])
    process = root.find(f"{{{BPMN_NS}}}process")
    if process is None:
        errors.append("Missing BPMN process.")
    else:
        nodes = list(process)
        if not any(node.tag.endswith("startEvent") for node in nodes):
            errors.append("Process must have a start event.")
        if not any(node.tag.endswith("endEvent") for node in nodes):
            errors.append("Process must have an end event.")
        flows = {flow.attrib.get("id") for flow in process.findall(f"{{{BPMN_NS}}}sequenceFlow")}
        refs = {ref for flow in process.findall(f"{{{BPMN_NS}}}sequenceFlow") for ref in (flow.attrib.get("sourceRef"), flow.attrib.get("targetRef"))}
        ids = {node.attrib.get("id") for node in nodes}
        if None in refs or not refs.issubset(ids):
            errors.append("Sequence flows must reference existing process elements.")
        if not flows:
            errors.append("Process must have at least one sequence flow.")
    plane = root.find(f".//{{{BPMNDI_NS}}}BPMNPlane")
    if plane is None:
        errors.append("Missing BPMN diagram layout (BPMNPlane).")
    else:
        for shape in plane.findall(f"{{{BPMNDI_NS}}}BPMNShape"):
            if shape.find(f"{{{DC_NS}}}Bounds") is None:
                errors.append("Every BPMN shape must have bounds.")
        for edge in plane.findall(f"{{{BPMNDI_NS}}}BPMNEdge"):
            if len(edge.findall(f"{{{DI_NS}}}waypoint")) < 2:
                errors.append("Every BPMN edge must have at least two waypoints.")
    if process is not None and not list(process):
        warnings.append("The process is empty.")
    return ValidationResult(not errors, errors, warnings)
