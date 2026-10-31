from __future__ import annotations

import time
from concurrent.futures import Future, ThreadPoolExecutor

import streamlit as st

from agents.copilot_orchestrator import CopilotSupervisor
from bpmn.spec import summarize_spec
from components.bpmn_viewer import bpmn_viewer
from models.schemas import GATEWAY_TYPES, TASK_TYPES

st.set_page_config(
    page_title="BPMN Process Assistant",
    page_icon=":material/account_tree:",
    layout="wide",
    initial_sidebar_state="expanded",
)

CHAT_HEIGHT = 540
VIEWER_HEIGHT = 600
USER_AVATAR = ":material/person:"
ASSISTANT_AVATAR = ":material/smart_toy:"
EXAMPLES = {
    "Order handling": (
        "Create an order handling process. A customer places an order and sales checks it. "
        "If the order is valid, the warehouse picks and ships the goods while finance sends the invoice. "
        "Otherwise sales sends a rejection to the customer."
    ),
    "Expense approval": (
        "Model an expense approval process: an employee submits an expense report and the manager reviews it. "
        "If information is missing, the report goes back to the employee for rework. "
        "Approved reports are reimbursed by finance."
    ),
    "Employee onboarding": (
        "Model employee onboarding with HR, IT and the team lead. HR prepares the contract; afterwards IT sets up "
        "the laptop and accounts while the team lead plans the first week. Then the new employee starts."
    ),
    "Support ticket": (
        "Create an IT support ticket process: a ticket is received and first-level support tries to solve it. "
        "If it cannot be solved, it is escalated to second-level support. The customer is notified when it is closed."
    ),
}

st.markdown(
    """
    <style>
    .block-container { padding-top: 2.2rem; padding-bottom: 1.5rem; max-width: 1600px; }
    [data-testid="stHeaderActionElements"] { display: none; }
    [data-testid="stChatMessage"] { padding: 0.6rem 0.75rem; border-radius: 12px; }
    [data-testid="stChatMessageContent"] p:last-child { margin-bottom: 0; }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] li { margin-bottom: 0.15rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

DEFAULTS = {
    "messages": [],
    "spec": None,
    "bpmn_xml": None,
    "validation": None,
    "job": None,
    "job_started": 0.0,
    "supervisor": None,
    "supervisor_error": None,
}
for name, value in DEFAULTS.items():
    if name not in st.session_state:
        st.session_state[name] = value.copy() if isinstance(value, list) else value


@st.cache_resource
def _executor() -> ThreadPoolExecutor:
    return ThreadPoolExecutor(max_workers=4, thread_name_prefix="bpmn-agent")


def connect() -> None:
    st.session_state.supervisor_error = None
    try:
        st.session_state.supervisor = CopilotSupervisor()
    except Exception as exc:  # noqa: BLE001 - shown to the user, app stays usable
        st.session_state.supervisor = None
        st.session_state.supervisor_error = str(exc) or exc.__class__.__name__


def submit(prompt: str) -> None:
    prompt = (prompt or "").strip()
    supervisor = st.session_state.supervisor
    if not prompt or supervisor is None or st.session_state.job is not None:
        return
    st.session_state.messages.append({"role": "user", "content": prompt})
    st.session_state.job = _executor().submit(supervisor.handle, prompt, st.session_state.spec)
    st.session_state.job_started = time.monotonic()


def submit_chat_input() -> None:
    submit(st.session_state.get("chat_input") or "")


def new_process() -> None:
    st.session_state.messages = []
    st.session_state.spec = None
    st.session_state.bpmn_xml = None
    st.session_state.validation = None
    if st.session_state.supervisor is not None:
        try:
            st.session_state.supervisor.reset()
        except Exception as exc:  # noqa: BLE001
            st.session_state.supervisor = None
            st.session_state.supervisor_error = f"Could not start a new conversation: {exc}"


if st.session_state.supervisor is None and st.session_state.supervisor_error is None:
    with st.spinner("Starting the process assistant..."):
        connect()

supervisor: CopilotSupervisor | None = st.session_state.supervisor
busy = st.session_state.job is not None
spec = st.session_state.spec
has_model = bool(st.session_state.bpmn_xml)

# Sidebar -----------------------------------------------------------------------

with st.sidebar:
    st.markdown("### :material/account_tree: Process Assistant")
    st.button(
        "New process",
        icon=":material/add:",
        type="primary",
        width="stretch",
        on_click=new_process,
        disabled=busy or (not st.session_state.messages and not has_model),
    )

    if spec is not None:
        st.markdown("**Current model**")
        counts = (
            ("Tasks", sum(node.type in TASK_TYPES for node in spec.nodes)),
            ("Gateways", sum(node.type in GATEWAY_TYPES for node in spec.nodes)),
            ("Lanes", len(spec.lanes)),
        )
        for column, (label, count) in zip(st.columns(3), counts):
            column.metric(label, count)

    st.markdown("**Tips for good results**")
    st.markdown(
        "- Describe the steps in order and who performs them.\n"
        "- Use *if … otherwise …* for decisions and *meanwhile* for parallel work.\n"
        "- Name roles or departments to get swimlanes.\n"
        "- Refine step by step, e.g. *Add a credit check after “Check order”*."
    )
    st.markdown("**Diagram controls**")
    st.caption("Scroll to zoom, drag to pan, **F** to fit, **+ / −** to zoom. Download as SVG or BPMN from the toolbar.")

    st.divider()
    if supervisor is not None:
        st.caption(f":material/check_circle: Connected · `{supervisor.model}`  \n{supervisor.base_url}")
    else:
        st.caption(":material/error: Assistant offline")
        st.button("Retry connection", icon=":material/refresh:", on_click=connect, width="stretch")

# Header ------------------------------------------------------------------------

st.markdown("## BPMN Process Assistant")
st.caption(
    "Describe a business process in plain language. The assistant models it as a BPMN 2.0 diagram, "
    "checks it, and refines it with you."
)
if st.session_state.supervisor_error:
    st.error(
        f"The process assistant is not available: {st.session_state.supervisor_error}  \n"
        "Check that Ollama is running and the model is pulled, then use **Retry connection** in the sidebar.",
        icon=":material/error:",
    )


def render_message(message: dict) -> None:
    avatar = USER_AVATAR if message["role"] == "user" else ASSISTANT_AVATAR
    with st.chat_message(message["role"], avatar=avatar):
        if message.get("error"):
            st.error(message["content"], icon=":material/error:")
        else:
            st.markdown(message["content"])
        if message.get("changes"):
            st.caption(" · ".join(message["changes"]))


def render_welcome() -> None:
    with st.container(border=True):
        st.markdown("#### What process do you want to model?")
        st.markdown(
            "Explain the trigger, the steps, who does them and the decisions involved. "
            "You can then ask for changes, such as adding steps, decisions or swimlanes."
        )
        st.caption("Try an example")
        with st.container(horizontal=True, gap="small"):
            for title, prompt in EXAMPLES.items():
                st.button(
                    title,
                    help=prompt,
                    on_click=submit,
                    args=(prompt,),
                    disabled=busy or supervisor is None,
                    icon=":material/lightbulb:",
                )


def finish_job(job: Future) -> None:
    reply: dict = {"role": "assistant"}
    try:
        response = job.result()
    except TimeoutError:
        reply.update(error=True, content="The model took too long to answer. Try a shorter request or a faster model.")
    except Exception as exc:  # noqa: BLE001 - surfaced in the chat
        reply.update(error=True, content=f"Something went wrong while talking to the model: {exc}")
    else:
        reply.update(content=response.message, changes=response.changes)
        if response.bpmn_xml:
            st.session_state.bpmn_xml = response.bpmn_xml
            st.session_state.spec = response.spec
            st.session_state.validation = response.validation
    st.session_state.messages.append(reply)
    st.session_state.job = None


@st.fragment(run_every=1.0)
def render_progress() -> None:
    """Poll the background job; only this fragment reruns while the model is working."""
    job: Future | None = st.session_state.job
    if job is None:
        return
    if job.done():
        finish_job(job)
        st.rerun()
    elapsed = int(time.monotonic() - st.session_state.job_started)
    with st.chat_message("assistant", avatar=ASSISTANT_AVATAR):
        st.status(f"Modeling and checking the process… {elapsed}s", state="running")


def render_chat(height: int) -> None:
    with st.container(height=height, border=True, autoscroll=True):
        for message in st.session_state.messages:
            render_message(message)
        if busy:
            render_progress()
    render_chat_input()


def render_chat_input() -> None:
    st.chat_input(
        "Ask for a change…" if has_model else "Describe your process…",
        key="chat_input",
        on_submit=submit_chat_input,
        disabled=busy or supervisor is None,
        max_chars=4000,
    )


def render_diagram() -> None:
    validation = st.session_state.validation
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        st.markdown(f"**{spec.name if spec else 'Process'}**", help=summarize_spec(spec) if spec else None)
        if validation is not None:
            if not validation.valid:
                st.badge("Needs attention", icon=":material/error:", color="red")
            elif validation.warnings:
                count = len(validation.warnings)
                st.badge(f"{count} hint{'s' * (count != 1)}", icon=":material/info:", color="orange")
            else:
                st.badge("Valid BPMN", icon=":material/check_circle:", color="green")
    bpmn_viewer(
        st.session_state.bpmn_xml,
        height=VIEWER_HEIGHT,
        file_name=spec.name if spec else "process",
        key="process_viewer",
    )
    if validation is not None and (validation.errors or validation.warnings):
        with st.expander("Model check details", icon=":material/fact_check:"):
            for error in validation.errors:
                st.markdown(f":red[:material/error:] {error}")
            for warning in validation.warnings:
                st.markdown(f":orange[:material/info:] {warning}")
            st.caption("Ask the assistant to fix these, e.g. “Fix the issues in the model check”.")


# Main area ---------------------------------------------------------------------

if has_model:
    chat_column, diagram_column = st.columns([5, 7], gap="large")
    with chat_column:
        st.markdown("**Conversation**")
        render_chat(CHAT_HEIGHT)
    with diagram_column:
        render_diagram()
else:
    _, center, _ = st.columns([1, 4, 1])
    with center:
        if st.session_state.messages:
            render_chat(CHAT_HEIGHT - 60)
        else:
            render_welcome()
            render_chat_input()
