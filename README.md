# Multi-Agent BPMN Chatbot

A Streamlit chatbot that uses the GitHub Copilot SDK with a local Ollama model to create and
refine BPMN 2.0 process models from natural language, validates them, and renders them with
bpmn-js (zoom, pan, SVG/BPMN download).

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
ollama pull qwen2.5:7b
streamlit run app.py
```

Configure Ollama in `.env` (see [.env.example](./.env.example)):

```env
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b
OLLAMA_API_KEY=ollama
COPILOT_TIMEOUT=300
BPMN_MAX_CORRECTIONS=2
```

## How it works

1. The **Supervisor** agent classifies the message (new process, change, question, unclear) and
   delegates to **BPMN_builder** and **BPMN_validator**.
2. Agents never write XML. They exchange a compact, layout-free **process spec** (JSON with
   `nodes`, `flows` and optional `lanes`) through the `build_process_model` and
   `validate_process_model` tools.
3. Python normalizes the spec (type aliases, ids, missing start/end events, lanes), checks BPMN
   rules, and runs up to `BPMN_MAX_CORRECTIONS` correction rounds with the validator feedback.
4. The final spec is rendered to BPMN 2.0 XML with an automatic left-to-right layout
   (branches, loops, pools and swimlanes). Only the plain-language answer is shown in the chat.

The application creates one in-memory Copilot SDK session per Streamlit browser session
(`enable_session_store=False`, `memory={"enabled": False}`). **New process** starts a fresh
session. Built-in Copilot tools (shell, files) are rejected by the permission handler.

## Agent configuration

System instructions live in YAML files and can be edited without touching code:

- [Supervisor](./agents/config/supervisor.yaml) – workflow, request handling, answer format and turn templates
- [BPMN builder](./agents/config/bpmn_builder.yaml) – modeling procedure and checklist
- [BPMN validator](./agents/config/bpmn_validator.yaml) – review procedure and report format
- [Shared snippets](./agents/config/shared.yaml) – process spec format and BPMN modeling guidelines,
  included in prompts via `{{snippet_name}}`

They are loaded by [config_loader.py](./agents/config_loader.py); the session and correction loop
are in [copilot_orchestrator.py](./agents/copilot_orchestrator.py).

## Project layout

| Path | Purpose |
| --- | --- |
| [app.py](./app.py) | Streamlit UI (chat, diagram panel, sidebar) |
| [components/bpmn_viewer](./components/bpmn_viewer) | bpmn-js viewer with zoom, pan, fit and downloads |
| [tools](./tools) | Copilot tools `build_process_model` and `validate_process_model` |
| [bpmn/spec.py](./bpmn/spec.py) | Parsing, repair and diffing of process specs |
| [bpmn/layout.py](./bpmn/layout.py) | Automatic diagram layout |
| [bpmn/generator.py](./bpmn/generator.py) | BPMN 2.0 XML + DI generation |
| [bpmn/validator.py](./bpmn/validator.py) | Semantic (spec) and structural (XML/DI) validation |
| [bpmn/parser.py](./bpmn/parser.py) | BPMN XML → process spec |

## Tests

```bash
pytest
```
