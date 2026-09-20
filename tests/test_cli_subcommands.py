import inspect
import sys
from typing import Annotated, Any
from unittest.mock import AsyncMock, patch

import pytest

from pirlo.core.decorators import play
from pirlo.core.models.parameters import Parameter
from pirlo.core.ports.play import Play


@play(name="mock", description="Mock play for testing CLI subcommands.")
class MockSubcommandPlay(Play[dict[str, Any]]):
    """Mock play for testing CLI subcommands."""

    async def execute(
        self,
        task: Annotated[str, Parameter(help="Task prompt")] = "Test Task",
    ) -> dict[str, Any]:
        return {"task_prompt": task, "final_message": "Done"}


@pytest.mark.anyio
async def test_subcommand_cli_execution(monkeypatch, tmp_path):
    monkeypatch.setenv("PIRLO_WORKSPACE", str(tmp_path))
    with (
        patch.object(sys, "argv", ["pirlo mock", "--task", "Search Google"]),
        patch(
            "pirlo.infrastructure.adapters.orchestrator.prefect_runner.PrefectRunner.run",
            new_callable=AsyncMock,
        ) as mock_run,
    ):
        mock_run.return_value = {
            "task_prompt": "Search Google",
            "final_message": "Done",
        }

        result = MockSubcommandPlay.cli("mock")
        if inspect.isawaitable(result):
            result = await result

        assert result is not None
        mock_run.assert_called_once()
        blueprint = mock_run.call_args[0][0]
        assert blueprint.name == "mock"
        assert blueprint.nodes[0].static_kwargs["task"] == "Search Google"


@pytest.mark.anyio
async def test_subcommand_cli_remote_submission_panel(monkeypatch, tmp_path):
    from pirlo.infrastructure.adapters.orchestrator.prefect.models import (
        PrefectRoutineRegistration,
    )

    monkeypatch.setenv("PIRLO_WORKSPACE", str(tmp_path))
    reg = PrefectRoutineRegistration(
        registration_id="run-789",
        play_name="mock",
        routine=None,
        dashboard_url="http://shua-and-ethan.local:4200/flow-runs?name=run-789",
        work_pool="pirlo-pool",
    )

    with (
        patch.object(sys, "argv", ["pirlo mock", "--task", "Search Google"]),
        patch(
            "pirlo.infrastructure.adapters.orchestrator.prefect_runner.PrefectRunner.run",
            new_callable=AsyncMock,
            return_value=reg,
        ),
        patch("rich.console.Console.print") as mock_print,
    ):
        result = MockSubcommandPlay.cli("mock")
        if inspect.isawaitable(result):
            result = await result

        assert result is not None
        assert result.data == reg
        mock_print.assert_called()
        panel = mock_print.call_args[0][0]
        assert "Remote Flow Run Submitted" in panel.title
        panel_text = panel.renderable
        assert "Run ID:" in panel_text
        assert "Routine:" not in panel_text
        assert "run-789" in panel_text
        assert "pirlo-pool" in panel_text
