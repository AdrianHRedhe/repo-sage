from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Message:
    """One turn in a provider-agnostic conversation.

    role is "user", "assistant", or "tool". An assistant turn may carry
    tool_calls (a request to invoke tools); a tool turn carries the result
    of exactly one call, correlated back via tool_call_id. Each LLMClient
    is responsible for translating this shape into its own wire format
    (Ollama's flat message list, Anthropic's content blocks, ...) and
    translating its response back into it, so the rest of the app - the
    tool-use loop in answer.py - never needs to know which provider is
    running.
    """

    role: str
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = field(default_factory=tuple)
    tool_call_id: str | None = None


class LLMClient(Protocol):
    def chat(self, messages: list[Message], tools: list[dict[str, Any]] | None = None) -> Message: ...
