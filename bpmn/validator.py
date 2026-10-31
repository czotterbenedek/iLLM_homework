from __future__ import annotations

from collections import Counter
from xml.etree import ElementTree as ET

from models.schemas import NODE_TYPES, TASK_TYPES, ProcessSpec, ValidationResult

from .generator import BPMN_NS, BPMNDI_NS, DC_NS, DI_NS


def _label(node) -> str:
    return f"'{node.name or node.id}'"


def validate_spec(spec: ProcessSpec) -> ValidationResult:
    """Check the BPMN semantics of a process spec (connectivity, events, gateways, lanes)."""
    errors: list[str] = []
    warnings: list[str] = []
    if not spec.nodes:
        return ValidationResult(False, ["The process has no elements."])

    duplicates = [node_id for node_id, count in Counter(node.id for node in spec.nodes).items() if count > 1]
    if duplicates:
        errors.append(f"Element ids must be unique: {', '.join(duplicates)}.")
    nodes = {node.id: node for node in spec.nodes}
    incoming: dict[str, list] = {node_id: [] for node_id in nodes}
    outgoing: dict[str, list] = {node_id: [] for node_id in nodes}
    for flow in spec.flows:
        if flow.source not in nodes or flow.target not in nodes:
            errors.append(f"Flow {flow.source} -> {flow.target} references an unknown element.")
            continue
        outgoing[flow.source].append(flow)
        incoming[flow.target].append(flow)

    starts = [node for node in spec.nodes if node.type == "startEvent"]
    if not starts:
        errors.append("The process needs a start event.")
    if not any(node.type == "endEvent" for node in spec.nodes):
        errors.append("The process needs at least one end event.")

    lane_ids = {lane.id for lane in spec.lanes}
    for node in spec.nodes:
        ins, outs = incoming[node.id], outgoing[node.id]
        if node.type == "startEvent":
            if ins:
                errors.append(f"Start event {_label(node)} must not have incoming flows.")
            if not outs:
                errors.append(f"Start event {_label(node)} has no outgoing flow.")
        elif node.type == "endEvent":
            if outs:
                errors.append(f"End event {_label(node)} must not have outgoing flows.")
            if not ins:
                errors.append(f"End event {_label(node)} has no incoming flow.")
        else:
            if not ins:
                errors.append(f"{_label(node)} has no incoming flow.")
            if not outs:
                errors.append(f"{_label(node)} has no outgoing flow (dead end); connect it or add an end event.")
        if node.is_gateway:
            if len(ins) <= 1 and len(outs) <= 1 and ins and outs:
                warnings.append(f"Gateway {_label(node)} neither splits nor merges the flow.")
            if node.type in ("exclusiveGateway", "inclusiveGateway") and len(outs) > 1:
                if any(not flow.name for flow in outs):
                    warnings.append(f"Label every outgoing flow of gateway {_label(node)} with its condition.")
            if node.type == "eventBasedGateway":
                if any(nodes[flow.target].type not in ("intermediateCatchEvent", "receiveTask") for flow in outs):
                    warnings.append(f"Event-based gateway {_label(node)} must lead to catch events or receive tasks.")
        elif node.type in TASK_TYPES:
            if not node.name:
                warnings.append(f"Task {node.id} has no name.")
            if len(outs) > 1:
                warnings.append(f"{_label(node)} splits the flow implicitly; use a gateway instead.")
        if spec.lanes and node.lane not in lane_ids:
            errors.append(f"{_label(node)} is not assigned to a known lane.")

    reachable: set[str] = set()
    pending = [node.id for node in starts]
    while pending:
        current = pending.pop()
        if current in reachable:
            continue
        reachable.add(current)
        pending.extend(flow.target for flow in outgoing[current])
    unreachable = [_label(node) for node in spec.nodes if node.id not in reachable]
    if starts and unreachable:
        errors.append(f"Not reachable from the start event: {', '.join(unreachable)}.")

    can_finish: set[str] = set()
    pending = [node.id for node in spec.nodes if node.type == "endEvent"]
    while pending:
        current = pending.pop()
        if current in can_finish:
            continue
        can_finish.add(current)
        pending.extend(flow.source for flow in incoming[current])
    trapped = [_label(node) for node in spec.nodes if node.id in reachable and node.id not in can_finish]
    if trapped and not errors:
        warnings.append(f"These elements can never reach an end event: {', '.join(trapped)}.")
    return ValidationResult(not errors, errors, warnings)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _valid_bounds(bounds: ET.Element) -> bool:
    try:
        values = [float(bounds.attrib[key]) for key in ("x", "y", "width", "height")]
    except (KeyError, ValueError):
        return False
    return values[2] > 0 and values[3] > 0


def validate_bpmn(xml: str) -> ValidationResult:
    """Check BPMN 2.0 XML structure and its diagram interchange (DI) layout."""
    errors: list[str] = []
    warnings: list[str] = []
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        return ValidationResult(False, [f"Invalid XML: {exc}"])
    if root.tag != f"{{{BPMN_NS}}}definitions":
        return ValidationResult(False, ["The root element must be bpmn:definitions in the BPMN 2.0 namespace."])

    ids = [element.attrib["id"] for element in root.iter() if "id" in element.attrib]
    duplicates = sorted(element_id for element_id, count in Counter(ids).items() if count > 1)
    if duplicates:
        errors.append(f"Duplicate ids: {', '.join(duplicates)}.")
    known_ids = set(ids)

    process = root.find(f"{{{BPMN_NS}}}process")
    flow_nodes: list[ET.Element] = []
    flows: list[ET.Element] = []
    if process is None:
        errors.append("Missing BPMN process.")
    else:
        flow_nodes = [element for element in process if _local(element.tag) in NODE_TYPES]
        flows = process.findall(f"{{{BPMN_NS}}}sequenceFlow")
        if not flow_nodes:
            warnings.append("The process is empty.")
        if not any(_local(node.tag) == "startEvent" for node in flow_nodes):
            errors.append("Process must have a start event.")
        if not any(_local(node.tag) == "endEvent" for node in flow_nodes):
            errors.append("Process must have an end event.")
        node_ids = {node.attrib.get("id") for node in flow_nodes}
        if not flows:
            errors.append("Process must have at least one sequence flow.")
        for flow in flows:
            if flow.attrib.get("sourceRef") not in node_ids or flow.attrib.get("targetRef") not in node_ids:
                errors.append(f"Sequence flow {flow.attrib.get('id', '?')} must reference existing process elements.")
        for participant in root.iter(f"{{{BPMN_NS}}}participant"):
            if participant.attrib.get("processRef") != process.attrib.get("id"):
                errors.append("The pool (participant) must reference the process.")

    plane = root.find(f".//{{{BPMNDI_NS}}}BPMNPlane")
    if plane is None:
        errors.append("Missing BPMN diagram layout (BPMNPlane).")
        return ValidationResult(False, errors, warnings)
    if plane.attrib.get("bpmnElement") not in known_ids:
        errors.append("The diagram plane must reference the process or collaboration.")
    shapes = {}
    for shape in plane.findall(f"{{{BPMNDI_NS}}}BPMNShape"):
        bounds = shape.find(f"{{{DC_NS}}}Bounds")
        if bounds is None or not _valid_bounds(bounds):
            errors.append(f"Shape for {shape.attrib.get('bpmnElement', '?')} needs numeric bounds.")
        shapes[shape.attrib.get("bpmnElement")] = shape
    edges = {}
    for edge in plane.findall(f"{{{BPMNDI_NS}}}BPMNEdge"):
        if len(edge.findall(f"{{{DI_NS}}}waypoint")) < 2:
            errors.append(f"Edge for {edge.attrib.get('bpmnElement', '?')} needs at least two waypoints.")
        edges[edge.attrib.get("bpmnElement")] = edge
    dangling = sorted(ref for ref in [*shapes, *edges] if ref not in known_ids)
    if dangling:
        errors.append(f"Diagram elements reference unknown ids: {', '.join(map(str, dangling))}.")
    missing_shapes = [node.attrib.get("id", "?") for node in flow_nodes if node.attrib.get("id") not in shapes]
    if missing_shapes:
        errors.append(f"Missing diagram shapes for: {', '.join(missing_shapes)}.")
    missing_edges = [flow.attrib.get("id", "?") for flow in flows if flow.attrib.get("id") not in edges]
    if missing_edges:
        errors.append(f"Missing diagram edges for: {', '.join(missing_edges)}.")
    return ValidationResult(not errors, errors, warnings)
