import sqlite3
from unittest.mock import AsyncMock, patch

import pytest

from pirlo.core.models.link import LlmLink
from pirlo.core.models.run import RunStatus
from pirlo.core.ports.orchestrator import AutopassExecutionOptions
from pirlo.infrastructure.adapters.db.sqlite_run_history_repository import (
    SqliteRunHistoryRepository,
)
from pirlo.infrastructure.adapters.orchestrator.prefect_orchestrator import (
    SmartPrefectTaskOrchestrator,
)


@pytest.mark.anyio
async def test_smart_prefect_orchestrator_execution(tmp_path, monkeypatch):
    monkeypatch.setenv("PIRLO_WORKSPACE", str(tmp_path))

    playmaker = LlmLink(
        name="qwen-main",
        provider="openai",
        model="qwen-max",
        api_key="mock-key",
        base_url="http://mock",
    )
    analyst = LlmLink(
        name="qwen-analyst",
        provider="openai",
        model="qwen-turbo",
        api_key="mock-key",
        base_url="http://mock",
    )

    options = AutopassExecutionOptions(
        playmaker=playmaker,
        analyst=analyst,
        use_vision=False,
        max_failures=3,
        retry_delay=5,
    )

    orchestrator = SmartPrefectTaskOrchestrator()

    from prefect.testing.utilities import prefect_test_harness

    with (
        prefect_test_harness(),
        patch(
            "pirlo.infrastructure.adapters.orchestrator.prefect_orchestrator.discover_prefect_server_url",
            return_value=None,
        ),
        patch(
            "pirlo.infrastructure.adapters.orchestrator.prefect_orchestrator.run_self_healing_worker_task",
            new_callable=AsyncMock,
            return_value="Automation successful!",
        ),
    ):
        result = await orchestrator.execute(
            task_prompt="Search Google for OpenAI",
            profile_path=tmp_path / "profiles" / "default",
            options=options,
            headless=True,
            cdp_port=9222,
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
    conn.close()
