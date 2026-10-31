from __future__ import annotations

import asyncio
import os
import re
import threading

from copilot import CopilotClient
from dotenv import load_dotenv

from agents.bpmn_builder import BPMN_BUILDER_PROMPT, BPMN_BUILDER_TOOL
from agents.bpmn_validator import BPMN_VALIDATOR_PROMPT, BPMN_VALIDATOR_TOOL
from agents.supervisor import SUPERVISOR_AGENT, SUPERVISOR_PROMPT
from bpmn.validator import validate_bpmn
from bpmn.normalizer import ensure_renderable_bpmn
from models.schemas import AgentResponse

MAX_CORRECTIONS = 3
load_dotenv()


def _agents() -> list[dict[str, object]]:
    return [
        SUPERVISOR_AGENT,
        {
            "name": "BPMN_builder",
            "display_name": "BPMN builder",
            "description": "Creates and modifies BPMN XML with BPMN DI layout.",
            "prompt": BPMN_BUILDER_PROMPT,
            "tools": ["bpmn_builder_finalize"],
            "infer": True,
        },
        {
            "name": "BPMN_validator",
            "display_name": "BPMN validator",
            "description": "Validates BPMN XML and reports structural or layout errors.",
            "prompt": BPMN_VALIDATOR_PROMPT,
            "tools": ["validate_bpmn_xml"],
            "infer": True,
        },
    ]


def _extract_xml(content: str) -> str:
    match = re.search(r"(<(?:[\w.-]+:)?definitions\b[\s\S]*?</(?:[\w.-]+:)?definitions>)", content)
    if not match:
        raise ValueError("The Copilot response did not contain a complete BPMN definitions document.")
    return match.group(1)


class CopilotSupervisor:
    """Owns one in-memory Copilot session per Streamlit browser session."""

    def __init__(self) -> None:
        self._generation_lock = threading.Lock()
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        self._client = self._run(self._create_session())

    async def _create_session(self):
        model = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
        client = CopilotClient(log_level="error")
        await client.start()
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
        if base_url.endswith("/v1"):
            base_url = base_url[:-3].rstrip("/")
        provider = {
            "type": "openai",
            "wire_api": "completions",
            "model_provider": "ollama",
            "base_url": f"{base_url}/v1",
            "api_key": os.getenv("OLLAMA_API_KEY", "ollama"),
            "model_id": model,
            "wire_model": model,
        }
        session = await client.create_session(
            model=model,
            provider=provider,
            custom_agents=_agents(),
            agent="supervisor",
            tools=[BPMN_BUILDER_TOOL, BPMN_VALIDATOR_TOOL],
            system_message={"mode": "append", "content": SUPERVISOR_PROMPT},
            enable_session_store=False,
            memory={"enabled": False},
            custom_agents_local_only=True,
        )
        return client, session

    def _run(self, coroutine):
        return asyncio.run_coroutine_threadsafe(coroutine, self._loop).result(timeout=180)

    async def _send(self, prompt: str):
        _, session = self._client
        return await session.send_and_wait(prompt, timeout=180)

    def handle(self, instruction: str, current_xml: str | None = None) -> AgentResponse:
        with self._generation_lock:
            return self._handle(instruction, current_xml)

    def _handle(self, instruction: str, current_xml: str | None = None) -> AgentResponse:
        context = instruction
        if current_xml:
            context += f"\n\nCurrent BPMN XML to preserve or modify:\n{current_xml}"
        last_error = None
        last_xml = None
        last_result = None
        for attempt in range(MAX_CORRECTIONS + 1):
            if attempt:
                context = (
                    "Correction pass. The previous draft was rejected. "
                    "Delegate this correction to BPMN_builder, then delegate "
                    "the result to BPMN_validator. Return a corrected complete "
                    "BPMN 2.0 XML document, not a description. "
                    f"Validator errors: {last_error}\n\n{context}"
                )
            event = self._run(self._send(context))
            content = getattr(getattr(event, "data", None), "content", None) if event else None
            if not content:
                raise RuntimeError("Copilot returned no assistant response.")
            try:
                xml = _extract_xml(content)
            except ValueError as exc:
                xml = ensure_renderable_bpmn("", instruction)
                last_error = str(exc)
            else:
                xml = ensure_renderable_bpmn(xml, instruction)
            result = validate_bpmn(xml)
            last_xml = xml
            last_result = result
            if result.valid:
                return AgentResponse(content.split("<bpmn_xml>", 1)[0].strip() or "BPMN diagram updated.", xml, result)
            last_error = "; ".join(result.errors)
        message = "A draft was generated, but it still has validation issues."
        if last_result and last_result.errors:
            message += " " + " ".join(last_result.errors)
        return AgentResponse(message, last_xml, last_result)
