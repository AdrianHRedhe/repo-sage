from reposage.llm.client import Message, ToolCall
from reposage.llm.ollama_client import _from_ollama_message, _to_ollama_message


def test_to_ollama_message_plain_user_turn() -> None:
    assert _to_ollama_message(Message(role="user", content="hi")) == {"role": "user", "content": "hi"}


def test_to_ollama_message_assistant_with_tool_calls() -> None:
    message = Message(
        role="assistant",
        content="",
        tool_calls=(ToolCall(id="call_0", name="read_file", arguments={"repo": "x", "path": "a.py"}),),
    )

    assert _to_ollama_message(message) == {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"function": {"name": "read_file", "arguments": {"repo": "x", "path": "a.py"}}}],
    }


def test_to_ollama_message_tool_result_ignores_tool_call_id() -> None:
    message = Message(role="tool", content="file contents", tool_call_id="call_0")

    assert _to_ollama_message(message) == {"role": "tool", "content": "file contents"}


def test_from_ollama_message_without_tool_calls() -> None:
    result = _from_ollama_message({"role": "assistant", "content": "the answer"})

    assert result == Message(role="assistant", content="the answer", tool_calls=())


def test_from_ollama_message_assigns_synthetic_ids_to_tool_calls() -> None:
    raw = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {"function": {"name": "list_files", "arguments": {"repo": "x"}}},
            {"function": {"name": "read_file", "arguments": {"repo": "x", "path": "a.py"}}},
        ],
    }

    result = _from_ollama_message(raw)

    assert result.tool_calls == (
        ToolCall(id="call_0", name="list_files", arguments={"repo": "x"}),
        ToolCall(id="call_1", name="read_file", arguments={"repo": "x", "path": "a.py"}),
    )
