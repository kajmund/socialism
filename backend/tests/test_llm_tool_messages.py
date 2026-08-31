"""DeepSeek tool-call message serialization."""

from types import SimpleNamespace

from app.llm.tool_messages import (
    assistant_message_dict,
    normalize_messages_for_deepseek,
    tool_result_message,
)


def test_assistant_message_extracts_multipart_text():
    payload = assistant_message_dict(
        SimpleNamespace(content=[{"type": "text", "text": "Här är bolagen."}])
    )
    assert payload["content"] == "Här är bolagen."


def test_assistant_message_includes_tool_call_type_and_reasoning():
    call = SimpleNamespace(
        id="call_1",
        type=None,
        function=SimpleNamespace(name="get_run", arguments=None),
        index=0,
    )
    message = SimpleNamespace(
        content=None,
        reasoning_content="think first",
        tool_calls=[call],
    )
    payload = assistant_message_dict(message)
    assert payload["role"] == "assistant"
    assert payload["content"] == ""
    assert payload["reasoning_content"] == "think first"
    assert payload["tool_calls"] == [
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "get_run", "arguments": "{}"},
            "index": 0,
        }
    ]


def test_assistant_message_stringifies_object_arguments():
    call = SimpleNamespace(
        id="call_2",
        type="function",
        function=SimpleNamespace(name="get_weather", arguments={"city": "Uppsala"}),
    )
    payload = assistant_message_dict(SimpleNamespace(content="", tool_calls=[call]))
    assert payload["tool_calls"][0]["function"]["arguments"] == '{"city": "Uppsala"}'


def test_tool_result_message_stringifies_content():
    payload = tool_result_message(
        tool_call_id="call_1",
        content={"ok": True},
        name="get_run",
    )
    assert payload == {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": '{"ok": true}',
        "name": "get_run",
    }


def test_normalize_messages_fills_missing_tool_call_type():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "q"},
        {
            "role": "assistant",
            "content": None,
            "reasoning_content": "plan",
            "tool_calls": [
                {
                    "id": "call_9",
                    "function": {"name": "list_runs", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_9", "content": None},
    ]
    out = normalize_messages_for_deepseek(messages)
    assert out[2]["tool_calls"][0]["type"] == "function"
    assert out[2]["content"] == ""
    assert out[2]["reasoning_content"] == "plan"
    assert out[3]["content"] == ""
    assert out[3]["tool_call_id"] == "call_9"
