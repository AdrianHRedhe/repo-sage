from typing import Any

from anthropic import Anthropic

from reposage.llm.client import Message, ToolCall

DEFAULT_ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_MAX_TOKENS = 1024


def _to_anthropic_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "name": t["function"]["name"],
            "description": t["function"]["description"],
            "input_schema": t["function"]["parameters"],
        }
        for t in tools
    ]


def _to_anthropic_message(message: Message) -> dict[str, Any]:
    if message.role == "tool":
        return {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": message.tool_call_id, "content": message.content}],
        }

    if message.role == "assistant" and message.tool_calls:
        content: list[dict[str, Any]] = []
        if message.content:
            content.append({"type": "text", "text": message.content})
        content.extend(
            {"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments} for tc in message.tool_calls
        )
        return {"role": "assistant", "content": content}

    return {"role": message.role, "content": message.content}


def _from_anthropic_response(content_blocks: list[Any]) -> Message:
    text = "".join(block.text for block in content_blocks if block.type == "text")
    tool_calls = tuple(
        ToolCall(id=block.id, name=block.name, arguments=block.input)
        for block in content_blocks
        if block.type == "tool_use"
    )
    return Message(role="assistant", content=text, tool_calls=tool_calls)


class AnthropicClient:
    """Thin wrapper around the Anthropic Messages API, translating the
    provider-agnostic Message shape (reposage/llm/client.py) into
    Anthropic's content-block format and back.

    max_tokens is required by the API (unlike Ollama, where it's an
    optional generation cap) - defaults to DEFAULT_MAX_TOKENS as a
    deliberate cost guard, since every response here is billed."""

    def __init__(self, model: str, api_key: str, max_tokens: int = DEFAULT_MAX_TOKENS) -> None:
        self._model = model
        self._max_tokens = max_tokens
        self._client = Anthropic(api_key=api_key)

    def chat(self, messages: list[Message], tools: list[dict[str, Any]] | None = None) -> Message:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": [_to_anthropic_message(m) for m in messages],
        }
        if tools:
            kwargs["tools"] = _to_anthropic_tools(tools)

        response = self._client.messages.create(**kwargs)
        return _from_anthropic_response(response.content)
