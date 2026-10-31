from __future__ import annotations

from xml.etree import ElementTree as ET

from .generator import BPMN_NS


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
