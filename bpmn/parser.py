from __future__ import annotations

from xml.etree import ElementTree as ET

from models.schemas import NODE_TYPES, Flow, Lane, Node, ProcessSpec

from .generator import BPMN_NS

_TRIGGERS = {
    "messageEventDefinition": "message",
    "timerEventDefinition": "timer",
    "signalEventDefinition": "signal",
    "conditionalEventDefinition": "conditional",
    "errorEventDefinition": "error",
    "terminateEventDefinition": "terminate",
}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def xml_to_spec(xml: str) -> ProcessSpec | None:
    """Extract the layout-free process structure from BPMN XML; ``None`` if there is no process."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return None
    process = next((element for element in root.iter() if _local(element.tag) == "process"), None)
    if process is None:
        return None
    participant = next((element for element in root.iter() if _local(element.tag) == "participant"), None)
    name = process.attrib.get("name") or (participant.attrib.get("name") if participant is not None else "") or "Process"

    lanes: list[Lane] = []
    lane_of: dict[str, str] = {}
    for lane in (element for element in process.iter() if _local(element.tag) == "lane"):
        lanes.append(Lane(lane.attrib.get("id", ""), lane.attrib.get("name", "")))
        for ref in lane:
            if _local(ref.tag) == "flowNodeRef" and ref.text:
                lane_of[ref.text.strip()] = lane.attrib.get("id", "")

    nodes: list[Node] = []
    flows: list[Flow] = []
    for element in process:
        kind = _local(element.tag)
        if kind == "sequenceFlow":
            flows.append(
                Flow(element.attrib.get("sourceRef", ""), element.attrib.get("targetRef", ""), element.attrib.get("name", ""))
            )
        elif kind in NODE_TYPES:
            trigger = next((_TRIGGERS[_local(child.tag)] for child in element if _local(child.tag) in _TRIGGERS), None)
            node_id = element.attrib.get("id", "")
            nodes.append(Node(node_id, kind, element.attrib.get("name", ""), lane_of.get(node_id), trigger))
    return ProcessSpec(name=name, nodes=nodes, flows=flows, lanes=lanes)


def task_names(xml: str) -> list[str]:
    root = ET.fromstring(xml)
    return [
        element.attrib.get("name", "")
        for element in root.iter(f"{{{BPMN_NS}}}task")
    ]


def rename_first_task(xml: str, name: str) -> str:
    root = ET.fromstring(xml)
    task = next(root.iter(f"{{{BPMN_NS}}}task"), None)
    if task is None:
        raise ValueError("The diagram does not contain a task.")
    task.set("name", name.strip())
    return ET.tostring(root, encoding="unicode", xml_declaration=True)
