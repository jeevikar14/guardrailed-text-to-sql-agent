"""
Ollama provider (optional, fully local -- no API key, no network dependency
at all beyond localhost). Requires the user to have Ollama installed and
`ollama pull <model>` run beforehand.

Uses httpx (already a project dependency) rather than adding the
`ollama` PyPI package, since Ollama's HTTP API is small and stable.
"""

from __future__ import annotations

import httpx

from app.core.config import settings
from app.llm.base import LLMProvider, LLMProviderError


class OllamaProvider(LLMProvider):
    def __init__(self) -> None:
        self._base_url = settings.ollama_base_url.rstrip("/")
        self._model_name = settings.ollama_model

    def _complete_once(self, system: str, user: str, json_mode: bool = False) -> str:
        payload: dict = {
            "model": self._model_name,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {"temperature": 0},
        }
        if json_mode:
            payload["format"] = "json"

        try:
            with httpx.Client(timeout=settings.query_timeout_seconds + 55) as client:
                response = client.post(f"{self._base_url}/api/chat", json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.ConnectError as e:
            raise LLMProviderError(
                f"Could not reach Ollama at {self._base_url}. Is `ollama serve` running, "
                f"and has `ollama pull {self._model_name}` been run?"
            ) from e
        except httpx.HTTPStatusError as e:
            raise LLMProviderError(f"Ollama returned {e.response.status_code}: {e.response.text}") from e

        content = data.get("message", {}).get("content")
        if not content:
            raise LLMProviderError(f"Ollama returned no message content: {data}")
        return content
