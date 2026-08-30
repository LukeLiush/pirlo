import hashlib
import logging
from typing import Any

from duckduckgo_search import DDGS
from prefect import task
from pydantic_ai import Agent, RunContext

from pirlo.core.models.plan import DecomposerPlan
from pirlo.core.ports.decomposer import DecomposerPort

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
    model_name: str = "google-gla:gemini-1.5-flash",
    api_key: str | None = None,
    base_url: str | None = None,
) -> Agent[None, DecomposerPlan]:
    """Create and return a PydanticAI Agent with tools and system prompt."""
    import os

    if base_url:
        from pydantic_ai.models.openai import OpenAIModel
        from pydantic_ai.providers.openai import OpenAIProvider

        endpoint = base_url.rstrip("/")
        if not endpoint.endswith("/v1"):
            endpoint = f"{endpoint}/v1"

        provider = OpenAIProvider(base_url=endpoint, api_key=api_key or "ollama")
        model: Any = OpenAIModel(model_name, provider=provider)
    else:
        if api_key:
            os.environ["GOOGLE_API_KEY"] = api_key
            os.environ["GEMINI_API_KEY"] = api_key
        elif "GEMINI_API_KEY" in os.environ and "GOOGLE_API_KEY" not in os.environ:
            os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]
        model = model_name or "google-gla:gemini-1.5-flash"

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


async def _fallback_llm_client_decompose(
    user_prompt: str,
    model_name: str,
    api_key: str | None = None,
    base_url: str | None = None,
) -> DecomposerPlan:
    """Fallback JSON decomposition using LlmClient for models incompatible with PydanticAI schema tools."""
    from pirlo.core.models.link import LlmLink
    from pirlo.core.utils.text_sanitizer import clean_llm_response
    from pirlo.infrastructure.services.llm_client import LlmClient

    link = LlmLink(
        name="decomposer-fallback",
        provider="ollama" if base_url else "openai",
        model=model_name,
        api_key=api_key or "",
        base_url=base_url,
    )

    prompt = (
        f"{DECOMPOSER_SYSTEM_PROMPT}\n\n"
        f"User Request: {user_prompt}\n\n"
        "Return ONLY a valid JSON object matching the DecomposerPlan structure:\n"
        "{\n"
        '  "subtasks": [\n'
        "    {\n"
        '      "subtask_id": "subtask_1",\n'
        '      "target_site": "Gemini",\n'
        '      "target_url": "https://gemini.google.com/app",\n'
        '      "task_prompt": "Ask what is the capital of UK",\n'
        '      "extraction_targets": ["capital of UK"]\n'
        "    }\n"
        "  ],\n"
        '  "aggregation_prompt": "Combine the answers"\n'
        "}\n"
    )

    raw_response = await LlmClient.acompletion(
        link=link, prompt=prompt, temperature=0.0
    )
    cleaned_json = clean_llm_response(raw_response)
    return DecomposerPlan.model_validate_json(cleaned_json)


@task(name="Run PydanticAI Decomposer Task")
async def run_decomposer_pydantic_ai_task(
    user_prompt: str,
    model_name: str = "google-gla:gemini-1.5-flash",
    api_key: str | None = None,
    base_url: str | None = None,
) -> DecomposerPlan:
    """Prefect Task wrapper executing PydanticAI Agent with full Prefect tracking & logging."""
    plan_id = hashlib.sha256(user_prompt.encode()).hexdigest()[:16]
    try:
        agent = get_decomposer_agent(model_name, api_key=api_key, base_url=base_url)
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
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "PydanticAI agent decomposition failed (%s). Falling back to LlmClient JSON decomposition...",
            e,
        )
        plan = await _fallback_llm_client_decompose(
            user_prompt, model_name=model_name, api_key=api_key, base_url=base_url
        )

    plan.plan_id = plan_id
    plan.original_prompt = user_prompt
    return plan


class PydanticAiDecomposer(DecomposerPort):
    """Decomposer Adapter delegating to Prefect-wrapped PydanticAI Agent."""

    def __init__(
        self,
        model_name: str = "google-gla:gemini-1.5-flash",
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.model_name = model_name
        self.api_key = api_key
        self.base_url = base_url

    async def decompose(self, user_prompt: str) -> DecomposerPlan:
        return await run_decomposer_pydantic_ai_task(
            user_prompt,
            model_name=self.model_name,
            api_key=self.api_key,
            base_url=self.base_url,
        )
