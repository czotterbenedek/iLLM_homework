"""bpmn-js viewer component with zoom, pan and download controls."""

from __future__ import annotations

from pathlib import Path

from streamlit.components.v1 import declare_component

_component = declare_component("bpmn_viewer", path=str(Path(__file__).parent / "frontend"))


def bpmn_viewer(xml: str | None, *, height: int = 600, file_name: str = "process", key: str | None = None) -> None:
    """Render BPMN XML. The iframe only re-imports the diagram when ``xml`` changes, so zoom survives reruns."""
    _component(xml=xml, height=height, file_name=file_name, key=key, default=None)
