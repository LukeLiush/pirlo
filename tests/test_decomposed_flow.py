import tempfile
from pathlib import Path

import pytest

from pirlo.core.models.plan import DecomposerPlan, SubtaskSpec
from pirlo.core.ports.decomposer import DecomposerPort
from pirlo.infrastructure.repository.json_file_plan_repository import (
    JsonFilePlanRepository,
)
from pirlo.infrastructure.services.decomposed_workflow import (
    DecomposedWorkflowRunner,
)
from pirlo.playbooks.autopass.core.use_cases import slugify as generate_plan_id


def test_decomposer_plan_repository():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = JsonFilePlanRepository(directory=Path(tmpdir))
        plan_id = "test_plan_123"

        assert not repo.exists(plan_id)

        sample_plan = DecomposerPlan(
            plan_id=plan_id,
            original_prompt="Compare iPhone 16 on JD and Taobao",
            subtasks=[
                SubtaskSpec(
                    subtask_id="st_1",
                    target_site="JD",
                    target_url="https://www.jd.com",
                    task_prompt="Go to https://www.jd.com and search iPhone 16",
                    extraction_targets=["title", "price"],
                ),
                SubtaskSpec(
                    subtask_id="st_2",
                    target_site="Taobao",
                    target_url="https://www.taobao.com",
                    task_prompt="Go to https://www.taobao.com and search iPhone 16",
                    extraction_targets=["title", "price"],
                ),
            ],
            aggregation_prompt="Synthesize into a markdown comparison table.",
        )

        repo.save(sample_plan)
        assert repo.exists(plan_id)

        loaded_plan = repo.load(plan_id)
        assert loaded_plan.plan_id == plan_id
        assert loaded_plan.original_prompt == "Compare iPhone 16 on JD and Taobao"
        assert len(loaded_plan.subtasks) == 2
        assert loaded_plan.subtasks[0].target_site == "JD"
        assert loaded_plan.subtasks[1].target_site == "Taobao"


class DummyDecomposer(DecomposerPort):
    def __init__(self):
        self.call_count = 0

    async def decompose(self, user_prompt: str) -> DecomposerPlan:
        self.call_count += 1
        return DecomposerPlan(
            plan_id=generate_plan_id(user_prompt),
            original_prompt=user_prompt,
            subtasks=[
                SubtaskSpec(
                    subtask_id="st_dummy",
                    target_site="Gemini",
                    target_url="https://gemini.google.com/app",
                    task_prompt="Ask Gemini",
                )
            ],
            aggregation_prompt="Summarize output",
        )


@pytest.mark.anyio
async def test_decomposed_runner_cache_hit_and_miss():
    from prefect.testing.utilities import prefect_test_harness

    with prefect_test_harness():
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = JsonFilePlanRepository(directory=Path(tmpdir))
        decomposer = DummyDecomposer()

        async def dummy_worker(task_prompt: str, site: str) -> str:
            return f"Result for {site}: {task_prompt}"

        async def dummy_aggregator(prompt: str) -> str:
            return "Aggregated Report"

        runner = DecomposedWorkflowRunner(
            plan_repository=repo,
            decomposer=decomposer,
            subtask_runner_fn=dummy_worker,
            aggregator_llm=dummy_aggregator,
        )

        prompt = "Compare prices across sites"

        # 1. First run: Cache MISS -> calls decomposer
        result1 = await runner.run(prompt)
        assert "Aggregated Report" in result1
        assert decomposer.call_count == 1
        assert repo.exists(prompt)

        # 2. Second run: Cache HIT -> does NOT call decomposer
        result2 = await runner.run(prompt)
        assert "Aggregated Report" in result2
        assert decomposer.call_count == 1  # Still 1 because loaded from cache!
