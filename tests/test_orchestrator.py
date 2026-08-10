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


class DummyAutopassPitch(TerminalPitch):
    """Mock Autopass pitch for testing."""

    task = "Search Google for OpenAI"

    def _resolve_playbook_name(self) -> str:
        return "autopass"

    async def on_play(self) -> RunResult[Any]:
        return RunResult(run_id=self.run_id)


@pytest.mark.anyio
async def test_smart_prefect_orchestrator_execution(tmp_path, monkeypatch):
    monkeypatch.setenv("PIRLO_WORKSPACE", str(tmp_path))

    pitch = DummyAutopassPitch(run_id="test-run-12345")

    orchestrator = SmartPrefectTaskOrchestrator()

    mock_worker = AsyncMock(return_value="Automation successful!")

    from prefect.testing.utilities import prefect_test_harness

    with (
        prefect_test_harness(),
        patch(
            "pirlo.infrastructure.adapters.orchestrator.prefect_orchestrator.discover_prefect_server_url",
            return_value=None,
        ),
    ):
        result = await orchestrator.execute(
            pitch,
            worker_fn=mock_worker,
        )

        assert result == "Automation successful!"

    # Verify run record pre-registration and status update in pirlo.db
    db_path = tmp_path / "pirlo.db"
    assert db_path.exists()
    conn = sqlite3.connect(str(db_path))
    repo = SqliteRunHistoryRepository(conn)
    runs = repo.list_runs(playbook="autopass")
    assert len(runs) == 1
    assert runs[0].status == RunStatus.COMPLETED

    run_dir = tmp_path / "autopass" / "runs" / runs[0].run_id
    log_file = run_dir / "run.log"
    assert log_file.exists()
    log_content = log_file.read_text(encoding="utf-8")

    assert "Running in Prefect Ephemeral Mode" in log_content

    conn.close()


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
