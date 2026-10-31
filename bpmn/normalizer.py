from __future__ import annotations

from collections.abc import Iterable

from .generator import build_bpmn_xml, generate_bpmn
from .parser import xml_to_spec
from .spec import normalize_spec, repair_connectivity


def ensure_renderable_bpmn(xml: str, fallback_labels: Iterable[str] | str = "Process task") -> str:
    """Return canonical BPMN XML with a fresh layout that bpmn-js can import.

    Recognizable process content is preserved; structural and DI defects are
    repaired by rebuilding the diagram from the extracted process structure.
    """
    spec = xml_to_spec(xml)
    if spec is None or not spec.nodes:
        return generate_bpmn(fallback_labels)
    spec, _ = normalize_spec(spec)
    repair_connectivity(spec)
    return build_bpmn_xml(spec)
