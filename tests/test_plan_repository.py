import tempfile
from pathlib import Path

from pirlo.core.models.plan import DecomposerPlan, SubtaskSpec
from pirlo.infrastructure.repository.json_file_plan_repository import (
    JsonFilePlanRepository,
)


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
