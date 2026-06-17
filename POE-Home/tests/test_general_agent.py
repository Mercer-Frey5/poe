import asyncio

from agents import general_agent
from agents.dual_output import DualOutput


def test_agent_uses_dual_output_schema_in_json_mode():
    assert general_agent._agent.output_schema is DualOutput
    assert general_agent._agent.use_json_mode is True


def test_run_is_async():
    assert asyncio.iscoroutinefunction(general_agent.run)


def test_run_falls_back_to_glitch_message_on_error(monkeypatch):
    async def boom(_user_text):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(general_agent._agent, "arun", boom)

    result = asyncio.run(general_agent.run("ciao"))

    assert isinstance(result, DualOutput)
    assert result.visual is None
    assert "archivi" in result.verbal or "glitch" in result.verbal
