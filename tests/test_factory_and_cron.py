from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from pirlo.core.ports.orchestrator import TaskOrchestrator
from pirlo.infrastructure.adapters.orchestrator.factory import OrchestratorFactory
from pirlo.infrastructure.adapters.orchestrator.prefect_orchestrator import (
    SmartPrefectTaskOrchestrator,
)


from pirlo.core.models.parameters import Parameter


class CustomMockOrchestrator(TaskOrchestrator):
    name: str = "custom"
    custom_setting = Parameter(str, default="default")

    async def execute(self, *args, **kwargs):
        return f"executed with {self.custom_setting}"


def test_factory_creates_prefect_default():
    orchestrator = OrchestratorFactory.create("prefect")
    assert isinstance(orchestrator, SmartPrefectTaskOrchestrator)


def test_factory_merges_overrides():
    orchestrator = OrchestratorFactory.create(
        "prefect",
        server_url="http://custom-prefect:4200/api",
        work_pool="custom-pool",
    )
    assert isinstance(orchestrator, SmartPrefectTaskOrchestrator)
    assert orchestrator.server_url == "http://custom-prefect:4200/api"
    assert orchestrator.work_pool == "custom-pool"


def test_factory_toml_configuration(tmp_path):
    config_file = tmp_path / "pirlo.toml"
    config_file.write_text(
        """
[pirlo.orchestrator.prefect]
server_url = "http://toml-server:4200/api"
work_pool = "toml-pool"
"""
    )
    orchestrator = OrchestratorFactory.create("prefect", config_path=config_file)
    assert isinstance(orchestrator, SmartPrefectTaskOrchestrator)
    assert orchestrator.server_url == "http://toml-server:4200/api"
    assert orchestrator.work_pool == "toml-pool"


def test_factory_cli_override_beats_toml(tmp_path):
    config_file = tmp_path / "pirlo.toml"
    config_file.write_text(
        """
[pirlo.orchestrator.prefect]
server_url = "http://toml-server:4200/api"
work_pool = "toml-pool"
"""
    )
    orchestrator = OrchestratorFactory.create(
        "prefect",
        config_path=config_file,
        server_url="http://cli-override:4200/api",
    )
    assert isinstance(orchestrator, SmartPrefectTaskOrchestrator)
    assert orchestrator.server_url == "http://cli-override:4200/api"
    assert orchestrator.work_pool == "toml-pool"


def test_factory_dynamic_registration():
    OrchestratorFactory.register("custom", CustomMockOrchestrator)
    orchestrator = OrchestratorFactory.create("custom", custom_setting="override_val")
    assert isinstance(orchestrator, CustomMockOrchestrator)
    assert orchestrator.custom_setting == "override_val"


def test_factory_unknown_orchestrator_raises_error():
    with pytest.raises(ValueError, match="Unknown orchestrator backend 'nonexistent'"):
        OrchestratorFactory.create("nonexistent")


from pirlo.core.models.run import PreparedRun
from pirlo.core.models.run_result import RunResult
from pirlo.infrastructure.adapters.cli.terminal_pitch import TerminalPitch


class DummyPitch(TerminalPitch):
    """Dummy Pitch for orchestrator cron testing."""

    async def on_play(self) -> RunResult[Any]:
        return RunResult(run_id=self._prepared_run.run_id)


@pytest.mark.anyio
async def test_cron_schedule_requires_active_server(tmp_path, monkeypatch):
    monkeypatch.setenv("PIRLO_WORKSPACE", str(tmp_path))

    run_dir = tmp_path / "autopass" / "runs" / "cron-test-1"
    run_dir.mkdir(parents=True, exist_ok=True)

    orchestrator = SmartPrefectTaskOrchestrator()
    orchestrator.server_url = None
    prepared_run = PreparedRun(
        playbook_name="autopass",
        run_name="cron-test-1",
        run_id="cron-test-1",
        workspace=tmp_path,
        parameters={},
    )

    with (
        patch(
            "pirlo.infrastructure.adapters.orchestrator.prefect_settings.discover_prefect_server_url",
            return_value=None,
        ),
        pytest.raises(RuntimeError, match="Prefect Server is required for --schedule"),
    ):
        await orchestrator.execute(
            task="Do work",
            prepared_run=prepared_run,
            worker_fn=lambda: AsyncMock(return_value="ok")(),
            schedule="0 9 * * *",
        )


@pytest.mark.anyio
async def test_cron_schedule_creates_deployment_when_server_active(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("PIRLO_WORKSPACE", str(tmp_path))

    run_dir = tmp_path / "autopass" / "runs" / "cron-test-2"
    run_dir.mkdir(parents=True, exist_ok=True)

    orchestrator = SmartPrefectTaskOrchestrator()
    orchestrator.server_url = "http://localhost:4200/api"
    orchestrator.work_pool = "test-pool"
    prepared_run = PreparedRun(
        playbook_name="autopass",
        run_name="cron-test-2",
        run_id="cron-test-2",
        workspace=tmp_path,
        parameters={},
    )

    mock_to_deployment = AsyncMock(return_value="mock-deployment-obj")

    with patch(
        "pirlo.infrastructure.adapters.orchestrator.prefect_orchestrator.pirlo_decomposed_flow.to_deployment",
        mock_to_deployment,
    ):
        result = await orchestrator.execute(
            task="Do work",
            prepared_run=prepared_run,
            worker_fn=lambda: AsyncMock(return_value="ok")(),
            schedule="0 9 * * *",
        )

        assert result == "mock-deployment-obj"
        mock_to_deployment.assert_called_once()
        call_kwargs = mock_to_deployment.call_args.kwargs
        assert call_kwargs["name"] == "pirlo-scheduled-cron-test-2"
        assert call_kwargs["work_pool_name"] == "test-pool"
        assert call_kwargs["schedule"].cron == "0 9 * * *"

