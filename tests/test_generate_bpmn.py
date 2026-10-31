from bpmn.generator import BPMN_NS, BPMNDI_NS, generate_bpmn
from xml.etree import ElementTree as ET


def test_generate_bpmn_contains_process_and_layout():
    root = ET.fromstring(generate_bpmn(["Receive order", "Check inventory"]))
    assert root.find(f".//{{{BPMN_NS}}}process") is not None
    assert root.find(f".//{{{BPMNDI_NS}}}BPMNPlane") is not None
    assert len(root.findall(f".//{{{BPMNDI_NS}}}BPMNShape")) == 4
