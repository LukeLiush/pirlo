from unittest.mock import AsyncMock, patch

import pytest

from pirlo.core.models.plan import DecomposerPlan, SubtaskSpec
from pirlo.infrastructure.adapters.decomposer.pydantic_ai_decomposer import (
    PydanticAiDecomposer,
)


@pytest.mark.anyio
async def test_pydantic_ai_decomposer_mocked():
    """Test PydanticAiDecomposer mapping to DecomposerPlan."""
    sample_plan = DecomposerPlan(
        plan_id="mock_plan_1",
        original_prompt="Compare CD rates on Chase and Bank of America",
        subtasks=[
            SubtaskSpec(
                subtask_id="st_chase",
                target_site="Chase",
                target_url="https://www.chase.com",
                task_prompt="Go to https://www.chase.com, search for 3-year CD rates, extract APY",
                extraction_targets=["APY", "rate"],
            ),
            SubtaskSpec(
                subtask_id="st_bofa",
                target_site="Bank of America",
                target_url="https://www.bankofamerica.com",
                task_prompt="Go to https://www.bankofamerica.com, search for 3-year CD rates, extract APY",
                extraction_targets=["APY", "rate"],
            ),
        ],
        aggregation_prompt="Summarize the 3-year CD rates into a comparative markdown table.",
    )

    mock_run_result = AsyncMock()
    mock_run_result.data = sample_plan

    from prefect.testing.utilities import prefect_test_harness

    with (
        prefect_test_harness(),
        patch(
            "pirlo.infrastructure.adapters.decomposer.pydantic_ai_decomposer.get_decomposer_agent"
        ) as mock_get_agent,
    ):
        mock_agent = AsyncMock()
        mock_agent.run.return_value = mock_run_result
        mock_get_agent.return_value = mock_agent

        from pirlo.core.models.link import LlmLink

        link = LlmLink(
            name="test-link",
            provider="gemini",
            model="gemini-2.5-flash",
            api_key="test",
        )
        decomposer = PydanticAiDecomposer(link=link)
        prompt = "Compare CD rates on Chase and Bank of America"
        plan = await decomposer.decompose(prompt)

        assert plan.original_prompt == prompt
        assert len(plan.subtasks) == 2
        assert plan.subtasks[0].target_site == "Chase"
        assert plan.subtasks[1].target_site == "Bank of America"
        mock_agent.run.assert_called_once()
