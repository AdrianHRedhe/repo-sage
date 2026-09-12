from typing import Any

import requests

DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"


class OllamaClient:
    """Thin wrapper around a local Ollama server's chat API.

    Kept as the sole place that knows about Ollama's request/response shape,
    so swapping in a hosted provider later only means adding a client with
    the same `chat` method here, not touching the answer pipeline.
    """

    def __init__(self, model: str, base_url: str = DEFAULT_OLLAMA_BASE_URL) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")

    def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"model": self._model, "messages": messages, "stream": False}
        if tools:
            payload["tools"] = tools

        try:
            response = requests.post(f"{self._base_url}/api/chat", json=payload, timeout=300)
            response.raise_for_status()
        except requests.ConnectionError as e:
            raise RuntimeError(
                f"Could not reach Ollama at {self._base_url}. Is it running "
                f"(`ollama serve`) with the '{self._model}' model pulled "
                f"(`ollama pull {self._model}`)?"
            ) from e

        return response.json()["message"]
