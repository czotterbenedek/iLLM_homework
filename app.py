from __future__ import annotations

from pathlib import Path

import streamlit as st
from copilot._jsonrpc import JsonRpcError
from streamlit.components.v1 import declare_component

from agents.copilot_orchestrator import CopilotSupervisor

st.set_page_config(page_title="Process diagram builder", layout="wide")

if "messages" not in st.session_state:
    st.session_state.messages = []
if "bpmn_xml" not in st.session_state:
    st.session_state.bpmn_xml = None
if "generation_active" not in st.session_state:
    st.session_state.generation_active = False
if "pending_prompt" not in st.session_state:
    st.session_state.pending_prompt = None
if "validation" not in st.session_state:
    st.session_state.validation = None
if "supervisor" not in st.session_state:
    try:
        st.session_state.supervisor = CopilotSupervisor()
    except (JsonRpcError, RuntimeError, OSError, TimeoutError) as exc:
        st.session_state.supervisor = None
        st.session_state.copilot_error = str(exc)

if st.session_state.get("copilot_error"):
    st.error(f"Unable to start the process assistant: {st.session_state.copilot_error}")

has_model = bool(st.session_state.bpmn_xml)
if has_model:
    chat_column, diagram_column = st.columns([0.42, 0.58], gap="large")
else:
    chat_column = st.container()
    diagram_column = None

with chat_column:
    st.title("Describe a process")
    st.write("Create a BPMN diagram or ask for changes to the current process.")
    with st.container(height=620, border=False):
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.write(message["content"])

if diagram_column is not None:
    with diagram_column:
        st.title("Process preview")
        with st.container(height=700, border=True):
            validation = st.session_state.validation
            if validation and not validation.valid:
                st.warning("The latest draft has validation issues. You can still preview or ask for corrections.")
                for error in validation.errors:
                    st.caption(f"• {error}")
            viewer = declare_component(
                "bpmn_viewer",
                path=str(Path(__file__).parent / "components" / "bpmn_viewer" / "frontend"),
            )
            export_svg = viewer(
                xml=st.session_state.bpmn_xml,
                key=f"bpmn-{hash(st.session_state.bpmn_xml)}",
            )
            if isinstance(export_svg, dict) and export_svg.get("error"):
                st.error(f"Preview error: {export_svg['error']}")
            elif export_svg:
                st.download_button(
                    "Download preview",
                    export_svg,
                    "process.svg",
                    "image/svg+xml",
                    disabled=st.session_state.generation_active,
                )

if st.session_state.pending_prompt is None:
    prompt = st.chat_input(
        "Describe the process or request a change...",
        disabled=st.session_state.supervisor is None or st.session_state.generation_active,
    )
    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        st.session_state.pending_prompt = prompt
        st.session_state.generation_active = True
        st.rerun()
else:
    st.chat_input(
        "Generating the process...",
        disabled=True,
    )
    with st.status("Building and checking the process...", expanded=False):
        try:
            response = st.session_state.supervisor.handle(
                st.session_state.pending_prompt,
                st.session_state.bpmn_xml,
            )
        except Exception as exc:
            st.session_state.messages.append(
                {"role": "assistant", "content": f"Process assistant error: {exc}"}
            )
        else:
            if response.bpmn_xml:
                st.session_state.bpmn_xml = response.bpmn_xml
            st.session_state.validation = response.validation
            st.session_state.messages.append(
                {"role": "assistant", "content": response.message}
            )
        finally:
            st.session_state.pending_prompt = None
            st.session_state.generation_active = False
    st.rerun()
