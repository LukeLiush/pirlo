import inspect
import sys
from typing import Annotated
from unittest.mock import AsyncMock, patch

import pytest

from pirlo.core.decorators import playbook
from pirlo.core.models.parameters import Parameter
from pirlo.core.models.run_result import AutopassRunOutput, RunResult
from pirlo.infrastructure.adapters.cli.terminal_pitch import TerminalPitch


@playbook(name="mock", description="Mock session for testing CLI subcommands.")
class MockSubcommandSession(TerminalPitch):
    """Mock session for testing CLI subcommands."""

    async def on_play(
        self,
        task: Annotated[str, Parameter(help="Task prompt")] = "Test Task",
        *args,
        **kwargs,
    ) -> RunResult[AutopassRunOutput]:
        return RunResult(
            run_id=(await self.prepared_run()).run_id,
            data=AutopassRunOutput(task_prompt=task, final_message="Done"),
        )


@pytest.mark.anyio
async def test_subcommand_default_orchestrator(monkeypatch, tmp_path):
    monkeypatch.setenv("PIRLO_WORKSPACE", str(tmp_path))
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

        result = MockSubcommandSession.cli("mock")
        if inspect.isawaitable(result):
            await result

        mock_factory.assert_called_once_with(
            name="prefect",
            config_path=None,
        )


@pytest.mark.anyio
async def test_subcommand_orchestrator_override(monkeypatch, tmp_path):
    monkeypatch.setenv("PIRLO_WORKSPACE", str(tmp_path))
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

        result = MockSubcommandSession.cli("mock")
        if inspect.isawaitable(result):
            await result

        mock_factory.assert_called_once_with(
            name="prefect",
            config_path=None,
            server_url="http://localhost:4200/api",
            work_pool="my-pool",
        )
