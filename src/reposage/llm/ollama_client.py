from typing import Any

import requests

from reposage.llm.client import Message, ToolCall

DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"


def _to_ollama_message(message: Message) -> dict[str, Any]:
    if message.role == "assistant" and message.tool_calls:
        return {
            "role": "assistant",
            "content": message.content,
            "tool_calls": [{"function": {"name": tc.name, "arguments": tc.arguments}} for tc in message.tool_calls],
        }
    # Ollama correlates tool results to calls by position, not id.
    return {"role": message.role, "content": message.content}


def _from_ollama_message(raw: dict[str, Any]) -> Message:
    tool_calls = tuple(
        ToolCall(id=f"call_{i}", name=tc["function"]["name"], arguments=tc["function"].get("arguments") or {})
        for i, tc in enumerate(raw.get("tool_calls") or [])
    )
    return Message(role="assistant", content=raw.get("content", ""), tool_calls=tool_calls)


class OllamaClient:
    """Thin wrapper around a local Ollama server's chat API, translating
    the provider-agnostic Message shape (reposage/llm/client.py) into
    Ollama's own request/response format and back."""

    def __init__(self, model: str, base_url: str = DEFAULT_OLLAMA_BASE_URL, max_tokens: int | None = None) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._max_tokens = max_tokens

    def chat(self, messages: list[Message], tools: list[dict[str, Any]] | None = None) -> Message:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [_to_ollama_message(m) for m in messages],
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
        if self._max_tokens:
            # num_predict caps response length - a cost/runaway-generation
            # guard that costs nothing when running fully local, but keeps
            # behavior consistent with a hosted provider's max_tokens.
            payload["options"] = {"num_predict": self._max_tokens}

        try:
            response = requests.post(f"{self._base_url}/api/chat", json=payload, timeout=300)
            response.raise_for_status()
        except requests.ConnectionError as e:
            raise RuntimeError(
                f"Could not reach Ollama at {self._base_url}. Is it running "
                f"(`ollama serve`) with the '{self._model}' model pulled "
                f"(`ollama pull {self._model}`)?"
            ) from e

        return _from_ollama_message(response.json()["message"])
