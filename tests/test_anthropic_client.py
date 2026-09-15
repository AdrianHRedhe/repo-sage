from types import SimpleNamespace

from reposage.llm.anthropic_client import _from_anthropic_response, _to_anthropic_message, _to_anthropic_tools
from reposage.llm.client import Message, ToolCall


def _text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def _tool_use_block(id_: str, name: str, input_: dict) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=input_)


def test_to_anthropic_tools_translates_schema_shape() -> None:
    tools = [
        {
            "type": "function",
            "function": {"name": "read_file", "description": "reads a file", "parameters": {"type": "object"}},
        }
    ]

    assert _to_anthropic_tools(tools) == [
        {"name": "read_file", "description": "reads a file", "input_schema": {"type": "object"}}
    ]


def test_to_anthropic_message_plain_user_turn() -> None:
    assert _to_anthropic_message(Message(role="user", content="hi")) == {"role": "user", "content": "hi"}


def test_to_anthropic_message_assistant_with_tool_calls() -> None:
    message = Message(
        role="assistant",
        content="checking the file",
        tool_calls=(ToolCall(id="toolu_1", name="read_file", arguments={"path": "a.py"}),),
    )

    assert _to_anthropic_message(message) == {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "checking the file"},
            {"type": "tool_use", "id": "toolu_1", "name": "read_file", "input": {"path": "a.py"}},
        ],
    }


def test_to_anthropic_message_tool_result_uses_tool_use_id() -> None:
    message = Message(role="tool", content="file contents", tool_call_id="toolu_1")

    assert _to_anthropic_message(message) == {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "file contents"}],
    }


def test_from_anthropic_response_concatenates_text_blocks() -> None:
    result = _from_anthropic_response([_text_block("part one. "), _text_block("part two.")])

    assert result == Message(role="assistant", content="part one. part two.", tool_calls=())


def test_from_anthropic_response_extracts_tool_use_blocks() -> None:
    result = _from_anthropic_response(
        [_text_block("let me check"), _tool_use_block("toolu_1", "read_file", {"path": "a.py"})]
    )

    assert result.content == "let me check"
    assert result.tool_calls == (ToolCall(id="toolu_1", name="read_file", arguments={"path": "a.py"}),)
