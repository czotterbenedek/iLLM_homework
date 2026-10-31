from __future__ import annotations

import asyncio
import json
import os
import re
import threading

from copilot import CopilotClient
from copilot.generated.rpc import PermissionDecisionReject
from dotenv import load_dotenv

from agents.config_loader import custom_agent, load_agent_config, render
from bpmn.generator import build_bpmn_xml
from bpmn.parser import xml_to_spec
from bpmn.spec import describe_changes, normalize_spec, parse_spec, repair_connectivity, summarize_spec
from bpmn.validator import validate_bpmn, validate_spec
from models.schemas import AgentResponse, ProcessSpec, ValidationResult
from tools.generate_bpmn import create_build_tool
from tools.validate_bpmn import create_validate_tool

load_dotenv()

MAX_CORRECTIONS = int(os.getenv("BPMN_MAX_CORRECTIONS", "2"))
REQUEST_TIMEOUT = float(os.getenv("COPILOT_TIMEOUT", "300"))
AGENT_CONFIGS = ("supervisor", "bpmn_builder", "bpmn_validator")

_SPEC_BLOCK = re.compile(r"<process_spec>\s*([\s\S]*?)\s*(?:</process_spec>|$)", re.IGNORECASE)
_FENCE = re.compile(r"```[\w-]*[ \t]*\n?([\s\S]*?)(?:```|$)")
_XML = re.compile(
    r"(?:<\?xml[\s\S]*?\?>\s*)?<(?:[\w.-]+:)?definitions\b[\s\S]*?(?:</(?:[\w.-]+:)?definitions>|$)"
)
_TAGS = re.compile(r"</?\s*(?:no_change|process_spec|current_spec|bpmn_xml)\s*/?>", re.IGNORECASE)
_NO_CHANGE = re.compile(r"<\s*no_change\s*/?\s*>", re.IGNORECASE)
_MODELING_VERBS = re.compile(
    r"\b(create|add|build|model|make|draw|design|generate|insert|remove|delete|rename|replace|change|"
    r"move|split|merge|connect|put|erstell\w*|füg\w*|lösch\w*|änder\w*|entfern\w*)\b",
    re.IGNORECASE,
)


def _loads(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return json.loads(re.sub(r",\s*([}\]])", r"\1", text))


def _json_objects(text: str):
    decoder = json.JSONDecoder()
    index = text.find("{")
    while index != -1:
        try:
            value, end = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            index = text.find("{", index + 1)
            continue
        yield value, index, end
        index = text.find("{", end)


def extract_spec(content: str) -> ProcessSpec | None:
    """Find a process spec in an assistant reply (tagged JSON, fenced JSON, bare JSON or BPMN XML)."""
    candidates = [match.group(1) for match in _SPEC_BLOCK.finditer(content)]
    candidates += [match.group(1) for match in _FENCE.finditer(content)]
    for candidate in candidates:
        try:
            data = _loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            spec = parse_spec(data)
            if spec.nodes:
                return spec
    for value, _, _ in _json_objects(content):
        if isinstance(value, dict) and ("nodes" in value or "spec" in value):
            spec = parse_spec(value)
            if spec.nodes:
                return spec
    match = _XML.search(content)
    return xml_to_spec(match.group(0)) if match else None


def clean_message(content: str) -> str:
    """Strip specs, XML, JSON and code blocks so only the conversational answer remains."""
    text = _SPEC_BLOCK.sub("", content)
    text = _FENCE.sub("", text)
    text = _XML.sub("", text)
    for value, start, end in reversed(list(_json_objects(text))):
        if isinstance(value, dict):
            text = text[:start] + text[end:]
    text = _TAGS.sub("", text)
    lines = [line.rstrip() for line in text.strip().splitlines()]
    while lines and (not lines[-1].strip() or lines[-1].strip().endswith(":")):
        lines.pop()
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _is_conversational(instruction: str) -> bool:
    return instruction.strip().endswith("?") and not _MODELING_VERBS.search(instruction)


def _reject_builtin_tools(request, invocation):
    return PermissionDecisionReject(feedback="Only the process-modeling tools are available in this assistant.")


class CopilotSupervisor:
    """Owns one in-memory Copilot session per Streamlit browser session."""

    def __init__(self) -> None:
        self.model = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
        self.base_url = base_url[:-3].rstrip("/") if base_url.endswith("/v1") else base_url
        self._templates = load_agent_config("supervisor")["templates"]
        self._generation_lock = threading.Lock()
        self._latest_build: tuple[ProcessSpec, ValidationResult] | None = None
        self._client: CopilotClient | None = None
        self._session = None
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        try:
            self._run(self._connect())
        except BaseException:
            self.close()
            raise

    # Copilot session lifecycle -------------------------------------------------

    async def _connect(self) -> None:
        self._client = CopilotClient(log_level="error")
        await self._client.start()
        self._session = await self._create_session()

    async def _create_session(self):
        supervisor = load_agent_config("supervisor")
        provider = {
            "type": "openai",
            "wire_api": "completions",
            "model_provider": "ollama",
            "base_url": f"{self.base_url}/v1",
            "api_key": os.getenv("OLLAMA_API_KEY", "ollama"),
            "model_id": self.model,
            "wire_model": self.model,
        }
        return await self._client.create_session(
            model=self.model,
            provider=provider,
            custom_agents=[custom_agent(name) for name in AGENT_CONFIGS],
            agent=supervisor["name"],
            tools=[create_build_tool(self._record_build), create_validate_tool(self._latest_spec)],
            system_message={"mode": "append", "content": supervisor.get("system_message", "")},
            on_permission_request=_reject_builtin_tools,
            enable_session_store=False,
            memory={"enabled": False},
            custom_agents_local_only=True,
        )

    async def _replace_session(self):
        if self._session is not None:
            try:
                await self._session.disconnect()
            except Exception:  # noqa: BLE001 - the old session is discarded either way
                pass
        self._session = await self._create_session()

    def reset(self) -> None:
        """Start a fresh conversation so earlier turns no longer influence the model."""
        with self._generation_lock:
            self._run(self._replace_session())

    def close(self) -> None:
        if self._client is not None:
            try:
                self._run(self._client.stop(), timeout=15)
            except Exception:  # noqa: BLE001 - best-effort shutdown
                pass
        self._loop.call_soon_threadsafe(self._loop.stop)

    def _run(self, coroutine, timeout: float = REQUEST_TIMEOUT + 30):
        return asyncio.run_coroutine_threadsafe(coroutine, self._loop).result(timeout=timeout)

    # Tool callbacks (run on the event-loop thread) ----------------------------

    def _record_build(self, spec: ProcessSpec, report: ValidationResult) -> None:
        self._latest_build = (spec, report)

    def _latest_spec(self) -> ProcessSpec | None:
        return self._latest_build[0] if self._latest_build else None

    # Conversation --------------------------------------------------------------

    def _ask(self, prompt: str) -> str:
        event = self._run(self._session.send_and_wait(prompt, timeout=REQUEST_TIMEOUT))
        content = getattr(getattr(event, "data", None), "content", None) if event else None
        if not content or not content.strip():
            raise RuntimeError("The assistant returned an empty response.")
        return content

    def _choose_spec(self, content: str) -> ProcessSpec | None:
        """Prefer a valid spec from the reply text, then the last model built through the tool."""
        text_spec = extract_spec(content)
        if text_spec is not None and validate_spec(normalize_spec(text_spec)[0]).valid:
            return text_spec
        if self._latest_build is not None and self._latest_build[1].valid:
            return self._latest_build[0]
        return text_spec or self._latest_spec()

    def handle(self, instruction: str, current_spec: ProcessSpec | None = None) -> AgentResponse:
        with self._generation_lock:
            return self._handle(instruction, current_spec)

    def _handle(self, instruction: str, current: ProcessSpec | None) -> AgentResponse:
        values = {
            "instruction": instruction.strip(),
            "current_spec": json.dumps(current.to_dict(), ensure_ascii=False) if current else "",
        }
        prompt = render(self._templates["modify_model" if current else "new_model"], values)
        first_message = ""
        best: tuple[ProcessSpec, ValidationResult, str] | None = None
        for attempt in range(MAX_CORRECTIONS + 1):
            self._latest_build = None
            content = self._ask(prompt)
            message = clean_message(content)
            first_message = first_message or message
            spec = self._choose_spec(content)
            if spec is None:
                if _NO_CHANGE.search(content) or (attempt == 0 and _is_conversational(instruction)):
                    return AgentResponse(message or "I left the process unchanged.")
                problems = "the answer did not contain a process spec in <process_spec>...</process_spec>."
            else:
                spec, _ = normalize_spec(spec)
                report = validate_spec(spec)
                best = (spec, report, message)
                if report.valid:
                    break
                problems = " ".join(report.errors)
            values["problems"] = problems
            values["current_context"] = render(self._templates["current_context"], values) if current else ""
            prompt = render(self._templates["correction"], values)

        if best is None:
            note = "I could not turn this into a process model. Please describe the steps in a bit more detail."
            return AgentResponse(f"{first_message}\n\n{note}" if first_message else note)

        spec, report, message = best
        auto_fixes = []
        if not report.valid:
            auto_fixes = repair_connectivity(spec)
            report = validate_spec(spec)
        xml = build_bpmn_xml(spec)
        xml_report = validate_bpmn(xml)
        validation = ValidationResult(
            report.valid and xml_report.valid,
            report.errors + xml_report.errors,
            [f"Auto-fixed: {fix}" for fix in auto_fixes] + report.warnings + xml_report.warnings,
        )
        if not message:
            verb = "Updated" if current else "Created"
            message = f"{verb} the process **{spec.name}** ({summarize_spec(spec)})."
        return AgentResponse(message, xml, validation, spec, describe_changes(current, spec))
