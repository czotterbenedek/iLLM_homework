# Multi-Agent BPMN Chatbot

A Streamlit chatbot that uses the GitHub Copilot SDK with a local Ollama model to generate and modify BPMN 2.0 XML, validates it, and renders it with bpmn-js.

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
streamlit run app.py
```

Configure Ollama in `.env`:

```env
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2:3b
OLLAMA_API_KEY=ollama
```

The application creates one in-memory Copilot SDK session per Streamlit browser
session. The SDK session retains the conversation context across turns, while
`enable_session_store=False` and `memory={"enabled": False}` prevent persistent
conversation or long-term memory storage.

The system and agent prompts are in:

- [Supervisor instructions](./agents/supervisor.py)
- [BPMN builder prompt](./agents/bpmn_builder.py)
- [BPMN validator prompt](./agents/bpmn_validator.py)

The SDK custom agents and correction loop are configured in
[copilot_orchestrator.py](./agents/copilot_orchestrator.py).

## Tests

```bash
pytest
```

The viewer uses bpmn-js directly in the browser, fits imported diagrams to the viewport, reports import failures, and returns SVG to Streamlit for download.
