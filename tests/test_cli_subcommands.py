import inspect
import sys
from unittest.mock import AsyncMock, patch

import pytest

from pirlo.core.models.run_result import AutopassRunOutput, RunResult
from pirlo.core.ports.pitch import Parameter
from pirlo.infrastructure.adapters.cli.terminal_pitch import TerminalPitch


class MockSubcommandSession(TerminalPitch):
    """Mock session for testing CLI subcommands."""

    task = Parameter(str, default="Test Task", help="Task prompt")

    async def on_play(self) -> RunResult[AutopassRunOutput]:
        return RunResult(
            run_id=self.run_id,
            data=AutopassRunOutput(task_prompt=self.task, final_message="Done"),
        )


@pytest.mark.anyio
async def test_subcommand_default_orchestrator():
    with (
        patch.object(sys, "argv", ["pirlo mock", "--task", "Search Google"]),
        patch(
            "pirlo.infrastructure.adapters.orchestrator.factory.OrchestratorFactory.create"
        ) as mock_factory,
    ):
        mock_orchestrator = AsyncMock()
        mock_orchestrator.execute = AsyncMock(
            return_value=RunResult(run_id="test-run", data="Success")
        )
        mock_factory.return_value = mock_orchestrator

        result = MockSubcommandSession.cli()
        if inspect.isawaitable(result):
            await result

        mock_factory.assert_called_once_with(
            name="prefect",
        )


@pytest.mark.anyio
async def test_subcommand_orchestrator_override():
    with (
        patch.object(
            sys,
            "argv",
            [
                "pirlo mock",
                "--task",
                "Search Google",
                "--",
                "prefect",
                "--server-url",
                "http://localhost:4200/api",
                "--work-pool",
                "my-pool",
            ],
        ),
        patch(
            "pirlo.infrastructure.adapters.orchestrator.factory.OrchestratorFactory.create"
        ) as mock_factory,
    ):
        mock_orchestrator = AsyncMock()
        mock_orchestrator.execute = AsyncMock(
            return_value=RunResult(run_id="test-run", data="Success")
        )
        mock_factory.return_value = mock_orchestrator

        result = MockSubcommandSession.cli()
        if inspect.isawaitable(result):
            await result

        mock_factory.assert_called_once_with(
            name="prefect",
            server_url="http://localhost:4200/api",
            work_pool="my-pool",
        )
