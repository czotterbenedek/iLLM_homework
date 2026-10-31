from xml.etree import ElementTree as ET

from bpmn.generator import BPMN_NS, BPMNDI_NS, DC_NS, build_bpmn_xml
from bpmn.layout import compute_layout
from bpmn.parser import xml_to_spec
from bpmn.spec import describe_changes, normalize_spec, parse_spec, repair_connectivity
from bpmn.validator import validate_bpmn, validate_spec

ORDER_SPEC = {
    "name": "Order handling",
    "lanes": [{"id": "Lane_Sales", "name": "Sales"}, {"id": "Lane_Warehouse", "name": "Warehouse"}],
    "nodes": [
        {"id": "Start", "type": "startEvent", "name": "Order received", "lane": "Lane_Sales", "trigger": "message"},
        {"id": "Check", "type": "userTask", "name": "Check order", "lane": "Lane_Sales"},
        {"id": "Valid", "type": "exclusiveGateway", "name": "Order valid?", "lane": "Lane_Sales"},
        {"id": "Fix", "type": "task", "name": "Correct order", "lane": "Lane_Sales"},
        {"id": "Split", "type": "parallelGateway", "name": "", "lane": "Lane_Warehouse"},
        {"id": "Pick", "type": "manualTask", "name": "Pick goods", "lane": "Lane_Warehouse"},
        {"id": "Invoice", "type": "serviceTask", "name": "Send invoice", "lane": "Lane_Warehouse"},
        {"id": "Join", "type": "parallelGateway", "name": "", "lane": "Lane_Warehouse"},
        {"id": "End", "type": "endEvent", "name": "Order shipped", "lane": "Lane_Warehouse"},
    ],
    "flows": [
        {"source": "Start", "target": "Check"},
        {"source": "Check", "target": "Valid"},
        {"source": "Valid", "target": "Split", "name": "Yes"},
        {"source": "Valid", "target": "Fix", "name": "No"},
        {"source": "Fix", "target": "Check"},
        {"source": "Split", "target": "Pick"},
        {"source": "Split", "target": "Invoice"},
        {"source": "Pick", "target": "Join"},
        {"source": "Invoice", "target": "Join"},
        {"source": "Join", "target": "End"},
    ],
}


def _overlaps(a, b) -> bool:
    return a.x < b.right and b.x < a.right and a.y < b.bottom and b.y < a.bottom


def test_complex_spec_builds_valid_bpmn_with_lanes_and_loop():
    spec, repairs = normalize_spec(parse_spec(ORDER_SPEC))
    assert not repairs
    assert validate_spec(spec).valid
    xml = build_bpmn_xml(spec)
    result = validate_bpmn(xml)
    assert result.valid, result.errors
    root = ET.fromstring(xml)
    assert root.find(f"{{{BPMN_NS}}}collaboration") is not None
    assert len(root.findall(f".//{{{BPMN_NS}}}lane")) == 2
    assert root.find(f".//{{{BPMN_NS}}}messageEventDefinition") is not None
    assert len(root.findall(f".//{{{BPMNDI_NS}}}BPMNEdge/{{{BPMNDI_NS}}}BPMNLabel/{{{DC_NS}}}Bounds")) == 2


def test_layout_has_no_overlapping_shapes_and_respects_lanes():
    spec, _ = normalize_spec(parse_spec(ORDER_SPEC))
    layout = compute_layout(spec)
    shapes = list(layout.shapes.items())
    for index, (left_id, left) in enumerate(shapes):
        for right_id, right in shapes[index + 1:]:
            assert not _overlaps(left, right), (left_id, right_id)
    for node in spec.nodes:
        lane, shape = layout.lanes[node.lane], layout.shapes[node.id]
        assert lane.y <= shape.y and shape.bottom <= lane.bottom
    assert all(len(points) >= 2 for points in layout.edges)


def test_normalizer_accepts_aliases_name_references_and_missing_events():
    spec, repairs = normalize_spec(
        parse_spec(
            {
                "name": "Loose",
                "nodes": [
                    {"name": "Receive request", "type": "user", "role": "Clerk"},
                    {"name": "Approved?", "type": "xor", "role": "Manager"},
                    {"name": "Archive", "type": "weird", "role": "Clerk"},
                ],
                "flows": [
                    {"from": "Receive request", "to": "Approved?"},
                    {"from": "Approved?", "to": "Archive", "label": "Yes"},
                    {"from": "Approved?", "to": "Nowhere"},
                ],
            }
        )
    )
    types = [node.type for node in spec.nodes]
    assert types[0] == "startEvent" and types[-1] == "endEvent"
    assert "userTask" in types and "exclusiveGateway" in types and "task" in types
    assert [lane.name for lane in spec.lanes] == ["Clerk", "Manager"]
    assert any("unknown endpoint" in repair for repair in repairs)
    assert validate_spec(spec).valid


def test_validator_reports_dead_ends_and_unlabelled_decisions():
    spec, _ = normalize_spec(
        parse_spec(
            {
                "nodes": [
                    {"id": "S", "type": "startEvent"},
                    {"id": "G", "type": "exclusiveGateway", "name": "Ok?"},
                    {"id": "A", "type": "task", "name": "Do A"},
                    {"id": "B", "type": "task", "name": "Do B"},
                    {"id": "E", "type": "endEvent"},
                ],
                "flows": [
                    {"source": "S", "target": "G"},
                    {"source": "G", "target": "A"},
                    {"source": "G", "target": "B"},
                    {"source": "A", "target": "E"},
                ],
            }
        )
    )
    result = validate_spec(spec)
    assert not result.valid
    assert any("'Do B' has no outgoing flow" in error for error in result.errors)
    assert any("Label every outgoing flow" in warning for warning in result.warnings)
    repair_connectivity(spec)
    assert validate_spec(spec).valid


def test_xml_round_trip_preserves_structure():
    spec, _ = normalize_spec(parse_spec(ORDER_SPEC))
    parsed = xml_to_spec(build_bpmn_xml(spec))
    assert parsed is not None
    assert parsed.to_dict() == spec.to_dict()


def test_describe_changes_lists_added_removed_and_renamed_elements():
    old, _ = normalize_spec(parse_spec(ORDER_SPEC))
    data = parse_spec(ORDER_SPEC).to_dict()
    data["nodes"] = [node for node in data["nodes"] if node["id"] != "Fix"]
    data["nodes"][1]["name"] = "Review order"
    data["nodes"].append({"id": "Notify", "type": "sendTask", "name": "Notify customer", "lane": "Lane_Sales"})
    new, _ = normalize_spec(parse_spec(data))
    changes = describe_changes(old, new)
    assert any(change.startswith("Added 'Notify customer'") for change in changes)
    assert any(change.startswith("Removed 'Correct order'") for change in changes)
    assert any("'Check order' → 'Review order'" in change for change in changes)
