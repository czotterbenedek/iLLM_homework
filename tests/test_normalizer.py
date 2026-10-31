from bpmn.normalizer import ensure_renderable_bpmn
from bpmn.validator import validate_bpmn


def test_normalizer_repairs_incomplete_llm_xml():
    xml = ensure_renderable_bpmn(
        "<definitions><process id='p'><startEvent id='start'/><task id='task' name='Check'/><endEvent id='end'/></process></definitions>"
    )
    result = validate_bpmn(xml)
    assert result.valid


def test_normalizer_falls_back_for_malformed_xml():
    xml = ensure_renderable_bpmn("<definitions>", "Handle customer order")
    result = validate_bpmn(xml)
    assert result.valid
