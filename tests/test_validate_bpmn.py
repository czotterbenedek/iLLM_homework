from bpmn.generator import generate_bpmn
from bpmn.validator import validate_bpmn


def test_generated_bpmn_is_valid():
    result = validate_bpmn(generate_bpmn(["Receive order"]))
    assert result.valid
    assert not result.errors


def test_invalid_xml_is_reported():
    result = validate_bpmn("<not-bpmn>")
    assert not result.valid
    assert result.errors
