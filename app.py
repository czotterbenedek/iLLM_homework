from __future__ import annotations

from pathlib import Path

import streamlit as st
from copilot._jsonrpc import JsonRpcError
from streamlit.components.v1 import declare_component

from agents.copilot_orchestrator import CopilotSupervisor

st.set_page_config(page_title="Process diagram builder", layout="wide")
st.markdown(
    """
    <style>
    :root {
        --panel-border: #d9dee8;
        --panel-radius: 14px;
        --panel-background: #ffffff;
    }

    [data-testid="stAppViewContainer"] .main .block-container {
        max-width: 1500px;
        padding: 2rem 2.5rem 6rem;
    }

    [data-testid="stHorizontalBlock"] {
        align-items: flex-start;
        gap: 1.5rem;
    }

    [data-testid="stVerticalBlockBorderWrapper"] {
        border: 1px solid var(--panel-border);
        border-radius: var(--panel-radius);
        background: var(--panel-background);
        overflow: hidden;
    }

    [data-testid="stChatMessage"] {
        margin: 0.35rem 0;
        padding: 0.7rem 0.85rem;
        border-radius: 10px;
    }

    [data-testid="stChatInput"] {
        padding-bottom: 0.75rem;
    }

    [data-testid="stStatusWidget"] {
        margin: 0.75rem 0;
    }

    @media (max-width: 900px) {
        [data-testid="stAppViewContainer"] .main .block-container {
            padding: 1rem 1rem 5rem;
        }

        [data-testid="stHorizontalBlock"] {
            flex-direction: column;
            gap: 1rem;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

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
    st.subheader("Describe a process")
    st.caption("Create a BPMN diagram or ask for changes to the current process.")
    with st.container(height=560 if has_model else 400, border=has_model):
        if not st.session_state.messages:
            st.info("Start by describing the process you want to create.")
        else:
            for message in st.session_state.messages:
                with st.chat_message(message["role"]):
                    st.write(message["content"])

if diagram_column is not None:
    with diagram_column:
        st.subheader("Process preview")
        with st.container(height=680, border=True):
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
