# POE-Home/tests/test_general_agent.py
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from agents import general_agent
from agents.general_agent import _extract_visual, run


def _tool_exec(name, result, args=None, error=None):
    return SimpleNamespace(
        tool_name=name, tool_args=args or {}, result=result, tool_call_error=error,
    )


def test_agent_has_general_tools_attached():
    names = set()
    for t in general_agent._agent.tools:
        if hasattr(t, "functions"):
            names.update(t.functions.keys())
        else:
            names.add(getattr(t, "__name__", str(t)))
    assert "get_weather" in names
    assert "web_search" in names
    assert "search_news" in names
    assert "add" in names and "multiply" in names
    assert "factorial" not in names  # include_tools limita la calcolatrice


def test_run_injects_real_date_into_prompt():
    import datetime as _dt
    captured = {}

    async def _fake_arun(prompt):
        captured["prompt"] = prompt
        return SimpleNamespace(content="ok", tools=[])

    with patch.object(general_agent._agent, "arun", new=_fake_arun):
        asyncio.run(run("che giorno e'?"))
    assert str(_dt.datetime.now().year) in captured["prompt"]
    assert "che giorno e'?" in captured["prompt"]


def test_run_is_async():
    assert asyncio.iscoroutinefunction(run)


def test_extract_visual_none_without_tools():
    assert _extract_visual(None) is None
    assert _extract_visual([]) is None


def test_extract_visual_none_for_light_tool():
    tools = [_tool_exec("get_weather", '{"temperatura_c": "18"}')]
    assert _extract_visual(tools) is None


def test_extract_visual_for_heavy_tool_with_raw_results():
    results = [{"title": "Notizia", "href": "https://x.it", "body": "snippet"}]
    tools = [_tool_exec("web_search", json.dumps(results),
                        args={"query": "cybersecurity"})]
    visual = _extract_visual(tools)
    assert visual is not None
    assert visual.type == "search_results"
    assert visual.data["results"] == results
    assert visual.data["query"] == "cybersecurity"


def test_extract_visual_skips_failed_heavy_tool():
    tools = [_tool_exec("web_search", "rate limited", error=True)]
    assert _extract_visual(tools) is None


def test_extract_visual_nonjson_result_passed_as_string():
    tools = [_tool_exec("search_news", "testo non json")]
    visual = _extract_visual(tools)
    assert visual.data["results"] == "testo non json"


def test_run_returns_dual_output_with_visual():
    results = [{"title": "T", "href": "https://x.it", "body": "B"}]
    fake = SimpleNamespace(
        content="Sir, ecco le notizie:",
        tools=[_tool_exec("search_news", json.dumps(results), args={"query": "q"})],
    )
    with patch.object(general_agent._agent, "arun", new=AsyncMock(return_value=fake)):
        out = asyncio.run(run("che news ci sono?"))
    assert out.verbal == "Sir, ecco le notizie:"
    assert out.visual.type == "search_results"


def test_run_falls_back_to_glitch_message_on_error():
    with patch.object(general_agent._agent, "arun",
                      new=AsyncMock(side_effect=RuntimeError("boom"))):
        out = asyncio.run(run("ciao"))
    assert "frammentazione" in out.verbal
    assert out.visual is None


def test_get_system_status_is_attached_and_light():
    names = set()
    for t in general_agent._agent.tools:
        if hasattr(t, "functions"):
            names.update(t.functions.keys())
        else:
            names.add(getattr(t, "__name__", str(t)))
    assert "get_system_status" in names
    assert "get_system_status" not in general_agent.HEAVY_TOOLS


def test_now_line_has_current_year():
    import datetime as _dt
    line = general_agent._now_line()
    assert str(_dt.datetime.now().year) in line


def test_run_updates_last_tool_used():
    fake = SimpleNamespace(
        content="ok",
        tools=[_tool_exec("get_weather", '{"temperatura_c": "18"}', args={"city": "Meda"})],
    )
    with patch.object(general_agent._agent, "arun", new=AsyncMock(return_value=fake)):
        asyncio.run(run("che tempo fa?"))
    assert general_agent.last_tool_used == "get_weather"
