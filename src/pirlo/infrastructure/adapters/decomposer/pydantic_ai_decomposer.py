import hashlib
import logging

from duckduckgo_search import DDGS
from prefect import task
from pydantic_ai import Agent, RunContext

from pirlo.core.models.link import LlmLink
from pirlo.core.models.plan import DecomposerPlan
from pirlo.core.ports.decomposer import DecomposerPort
from pirlo.infrastructure.adapters.decomposer.pydantic_ai_adapters import (
    PydanticAiAdapterRegistry,
)

logger = logging.getLogger(__name__)

DECOMPOSER_SYSTEM_PROMPT = """\
You are Pirlo's Task Decomposer Engine, an expert at breaking down multi-source web requests into independent subtasks.

### Core Instructions:
1. Identify target platforms/websites referenced in the user request.
2. If exact entrypoint URLs are unknown, use the `search_web` tool to find the official entry URL first.
3. Generate self-contained, atomic subtask prompts. Each subtask prompt MUST include:
   - Target entrypoint URL
   - Specific search, lookup, or navigation action
   - Explicit target data to extract
4. Keep subtask prompts standardized to maximize cache hit rates across subtasks.
5. Provide clear aggregation instructions for synthesizing the final output.
"""


def get_decomposer_agent(
    link: LlmLink,
) -> Agent[None, DecomposerPlan]:
    """Create and return a PydanticAI Agent with tools and system prompt."""
    model = PydanticAiAdapterRegistry.to_model(link)

    agent: Agent[None, DecomposerPlan] = Agent[None, DecomposerPlan](
        model=model,
        output_type=DecomposerPlan,
        system_prompt=DECOMPOSER_SYSTEM_PROMPT,
    )

    @agent.tool
    async def search_web(ctx: RunContext[None], query: str) -> str:
        """Search DuckDuckGo to resolve official homepage or entrypoint URLs for a platform."""
        logger.info(f"Decomposer Search Tool querying DuckDuckGo: '{query}'")
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=3))
                return str(results)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"DuckDuckGo search failed: {e}")
            return f"Search error: {e}"

    return agent


@task(name="Run PydanticAI Decomposer Task")
async def run_decomposer_pydantic_ai_task(
    user_prompt: str,
    link: LlmLink,
) -> DecomposerPlan:
    """Prefect Task wrapper executing PydanticAI Agent with full Prefect tracking & logging."""
    plan_id = hashlib.sha256(user_prompt.encode()).hexdigest()[:16]
    agent = get_decomposer_agent(link=link)

    result = await agent.run(f"Decompose this multi-source request: {user_prompt}")

    data = getattr(result, "data", None)
    if data is None:
        data = getattr(result, "output", None)

    if isinstance(data, DecomposerPlan):
        plan = data
    elif isinstance(data, dict):
        plan = DecomposerPlan.model_validate(data)
    elif isinstance(data, str):
        plan = DecomposerPlan.model_validate_json(data)
    else:
        raise TypeError(
            f"Unexpected result from PydanticAI decomposer agent: {type(data or result)}"
        )

    plan.plan_id = plan_id
    plan.original_prompt = user_prompt
    return plan


class PydanticAiDecomposer(DecomposerPort):
    """Decomposer Adapter delegating to Prefect-wrapped PydanticAI Agent."""

    def __init__(self, link: LlmLink) -> None:
        self.link = link

    async def decompose(self, user_prompt: str) -> DecomposerPlan:
        return await run_decomposer_pydantic_ai_task(user_prompt, link=self.link)
