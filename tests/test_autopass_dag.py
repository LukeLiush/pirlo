# tests/test_autopass_dag.py
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from pirlo.core.models.link import LlmLink
from pirlo.playbooks.autopass.main import AutopassPlay
from pirlo.playbooks.autopass.models import AutopassRunOutput, TaskDecompositionOutput


def test_autopass_dag_execution():
    decomp_result = TaskDecompositionOutput(
        task_prompts=["Step 1: Open store", "Step 2: Add keyboard to cart"],
        total_subtasks=2,
    )

    with (
        patch(
            "pirlo.playbooks.autopass.subplaybooks.DecomposeTaskPlay.execute",
            new_callable=AsyncMock,
            return_value=decomp_result,
        ),
        patch(
            "pirlo.playbooks.autopass.core.use_cases.RunAutopassUseCase.run",
            new_callable=AsyncMock,
            return_value="Step completed",
        ),
        patch(
            "pirlo.infrastructure.services.profile_manager.ProfileManager.exists",
            return_value=True,
        ),
        patch(
            "pirlo.infrastructure.services.profile_manager.ProfileManager.resolve_profile_path",
        ),
    ):
        mock_link = LlmLink(
            name="test_link", provider="ollama", model="qwen2.5:latest", api_key="dummy"
        )
        session = AutopassPlay()
        output: AutopassRunOutput = asyncio.run(
            session.run_play(
                task="Buy keyboard", profile="default", playmaker=mock_link
            )
        )

        assert isinstance(output, AutopassRunOutput)
        assert output.task_prompt == "Buy keyboard"
        assert len(output.subtask_results) == 2
        assert output.subtask_results[0].subtask_prompt == "Step 1: Open store"
        assert (
            output.subtask_results[1].subtask_prompt == "Step 2: Add keyboard to cart"
        )
