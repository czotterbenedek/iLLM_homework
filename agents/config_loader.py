"""Load agent definitions and prompts from agents/config/*.yaml."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(__file__).with_name("config")
_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")
_AGENT_KEYS = ("name", "display_name", "description", "prompt", "tools", "infer")


def render(template: str, values: dict[str, str]) -> str:
    """Replace {{name}} placeholders; unknown placeholders raise KeyError to surface config typos."""

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            raise KeyError(f"Unknown prompt placeholder '{{{{{key}}}}}'.")
        return values[key]

    return _PLACEHOLDER.sub(replace, template)


def _read(file_name: str) -> dict[str, Any]:
    path = CONFIG_DIR / file_name
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping.")
    return data


@lru_cache(maxsize=None)
def load_agent_config(name: str) -> dict[str, Any]:
    data = _read(f"{name}.yaml")
    if not data.get("name") or not data.get("prompt"):
        raise ValueError(f"agents/config/{name}.yaml needs 'name' and 'prompt'.")
    shared = {key: str(value).strip() for key, value in _read("shared.yaml").items()}
    for key in ("prompt", "system_message"):
        if data.get(key):
            data[key] = render(data[key], shared).strip()
    return data


def custom_agent(name: str) -> dict[str, Any]:
    """Return the agent definition in the shape expected by the Copilot SDK."""
    config = load_agent_config(name)
    return {key: config[key] for key in _AGENT_KEYS if key in config}
