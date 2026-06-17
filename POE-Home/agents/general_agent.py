from agno.agent import Agent

from .dual_output import DualOutput
from .local_model import get_local_model
from .persona import SYSTEM_PROMPT

_agent = Agent(
    model=get_local_model(),
    description=SYSTEM_PROMPT,
    output_schema=DualOutput,
    use_json_mode=True,
)


async def run(user_text: str) -> DualOutput:
    try:
        result = await _agent.arun(user_text)
        return result.content
    except Exception:
        return DualOutput(
            verbal="Una lieve frammentazione degli archivi mi impedisce di "
                   "rispondere in questo momento, Signore.",
            visual=None,
        )
