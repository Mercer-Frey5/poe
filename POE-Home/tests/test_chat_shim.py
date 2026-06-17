# POE-Home/tests/test_chat_shim.py
import json

from chat_shim import normalize_messages, parse_tool_calls


def test_no_tool_call_returns_text_and_empty_list():
    text = "Certamente, Signore. La risposta e' quarantadue."
    content, calls = parse_tool_calls(text)
    assert content == text
    assert calls == []


def test_single_tool_call_parsed():
    text = (
        "<tool_call>\n<function=get_weather>\n<parameter=city>\nFirenze\n"
        "</parameter>\n</function>\n</tool_call>"
    )
    content, calls = parse_tool_calls(text)
    assert content is None
    assert len(calls) == 1
    assert calls[0]["id"] == "call_0"
    assert calls[0]["type"] == "function"
    assert calls[0]["function"]["name"] == "get_weather"
    assert json.loads(calls[0]["function"]["arguments"]) == {"city": "Firenze"}


def test_text_before_tool_call_becomes_content():
    text = (
        "Controllo subito, Signore.\n\n<tool_call>\n<function=web_search>\n"
        "<parameter=query>\nnotizie cybersecurity\n</parameter>\n</function>\n</tool_call>"
    )
    content, calls = parse_tool_calls(text)
    assert content == "Controllo subito, Signore."
    assert calls[0]["function"]["name"] == "web_search"


def test_multiple_tool_calls_get_incremental_ids():
    block = (
        "<tool_call>\n<function=add>\n<parameter=a>\n1\n</parameter>\n"
        "<parameter=b>\n2\n</parameter>\n</function>\n</tool_call>"
    )
    text = block + "\n" + block.replace("add", "multiply")
    _, calls = parse_tool_calls(text)
    assert [c["id"] for c in calls] == ["call_0", "call_1"]
    assert calls[0]["function"]["name"] == "add"
    assert json.loads(calls[0]["function"]["arguments"]) == {"a": "1", "b": "2"}
    assert calls[1]["function"]["name"] == "multiply"


def test_multiline_parameter_value_preserved():
    text = (
        "<tool_call>\n<function=diario_append>\n<parameter=text>\nriga uno\n"
        "riga due\n</parameter>\n</function>\n</tool_call>"
    )
    _, calls = parse_tool_calls(text)
    assert json.loads(calls[0]["function"]["arguments"]) == {"text": "riga uno\nriga due"}


def test_malformed_block_treated_as_text():
    text = "<tool_call>\n<function=rotto>\nsenza chiusura"
    content, calls = parse_tool_calls(text)
    assert calls == []
    assert content == text


def test_normalize_converts_arguments_string_to_dict():
    msgs = [
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "call_0", "type": "function",
             "function": {"name": "get_weather", "arguments": '{"city": "Firenze"}'}}
        ]},
        {"role": "tool", "content": "18 gradi", "tool_call_id": "call_0"},
    ]
    out = normalize_messages(msgs)
    assert out[0]["content"] == ""
    assert out[0]["tool_calls"][0]["function"]["arguments"] == {"city": "Firenze"}
    assert out[1]["content"] == "18 gradi"


def test_normalize_handles_invalid_arguments_json():
    msgs = [{"role": "assistant", "content": "x", "tool_calls": [
        {"id": "c", "type": "function", "function": {"name": "f", "arguments": "{rotto"}}
    ]}]
    out = normalize_messages(msgs)
    assert out[0]["tool_calls"][0]["function"]["arguments"] == {}
