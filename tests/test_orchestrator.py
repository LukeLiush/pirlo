import sqlite3
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from pirlo.core.models.run import RunStatus
from pirlo.core.models.run_result import RunResult
from pirlo.infrastructure.adapters.cli.terminal_pitch import TerminalPitch
from pirlo.infrastructure.adapters.db.sqlite_run_history_repository import (
    SqliteRunHistoryRepository,
)
from pirlo.infrastructure.adapters.orchestrator.prefect_orchestrator import (
    SmartPrefectTaskOrchestrator,
)


from pirlo.core.models.run import PreparedRun


class DummyAutopassPitch(TerminalPitch):
    """Mock Autopass pitch for testing."""

    task = "Search Google for OpenAI"

    async def on_play(self) -> RunResult[Any]:
        return RunResult(run_id=self._prepared_run.run_id)


@pytest.mark.anyio
async def test_smart_prefect_orchestrator_execution(tmp_path, monkeypatch):
    monkeypatch.setenv("PIRLO_WORKSPACE", str(tmp_path))

    run_dir = tmp_path / "autopass" / "runs" / "test-run-12345"
    run_dir.mkdir(parents=True, exist_ok=True)

    orchestrator = SmartPrefectTaskOrchestrator()
    prepared_run = PreparedRun(
        playbook_name="autopass",
        run_name="test-run-12345",
        run_id="test-run-12345",
        workspace=tmp_path,
        parameters={"schedule": None},
    )

    mock_worker = AsyncMock(return_value="Automation successful!")

    from prefect.testing.utilities import prefect_test_harness

    with (
        prefect_test_harness(),
        patch(
            "pirlo.infrastructure.adapters.orchestrator.prefect_settings.discover_prefect_server_url",
            return_value=None,
        ),
        patch(
            "pirlo.infrastructure.services.decomposed_workflow.DecomposedWorkflowRunner.run",
            new_callable=AsyncMock,
            return_value="Automation successful!",
        ),
    ):
        result = await orchestrator.execute(
            task="Search Google for OpenAI",
            prepared_run=prepared_run,
            worker_fn=mock_worker,
        )

        assert result == "Automation successful!"



def test_parse_cli_options_direct_contract():
    options = SmartPrefectTaskOrchestrator.parse_cli_options(
        playbook_name="autopass",
        orchestrator_flags=[
            "--server-url",
            "http://localhost:4200/api",
            "--work-pool",
            "my-pool",
        ],
    )

    assert options == {
        "server_url": "http://localhost:4200/api",
        "work_pool": "my-pool",
    }
