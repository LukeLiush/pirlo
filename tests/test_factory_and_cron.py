from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from pirlo.core.ports.orchestrator import TaskOrchestrator
from pirlo.infrastructure.adapters.orchestrator.factory import OrchestratorFactory
from pirlo.infrastructure.adapters.orchestrator.prefect_orchestrator import (
    SmartPrefectTaskOrchestrator,
)


class CustomMockOrchestrator(TaskOrchestrator):
    def __init__(self, custom_setting: str = "default"):
        self.custom_setting = custom_setting

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


from pirlo.core.models.run_result import RunResult
from pirlo.infrastructure.adapters.cli.terminal_pitch import TerminalPitch


class DummyPitch(TerminalPitch):
    """Dummy Pitch for orchestrator cron testing."""

    async def on_play(self) -> RunResult[Any]:
        return RunResult(run_id=self.run_id)


@pytest.mark.anyio
async def test_cron_schedule_requires_active_server(tmp_path, monkeypatch):
    monkeypatch.setenv("PIRLO_WORKSPACE", str(tmp_path))

    pitch = DummyPitch()
    pitch.run_id = "cron-test-1"
    pitch.schedule = "daily"

    orchestrator = SmartPrefectTaskOrchestrator(server_url=None)

    with (
        patch(
            "pirlo.infrastructure.adapters.orchestrator.prefect_orchestrator.discover_prefect_server_url",
            return_value=None,
        ),
        pytest.raises(RuntimeError, match="Prefect Server is required for --schedule"),
    ):
        await orchestrator.execute(
            pitch,
            worker_fn=lambda: AsyncMock(return_value="ok")(),
        )


@pytest.mark.anyio
async def test_cron_schedule_creates_deployment_when_server_active(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("PIRLO_WORKSPACE", str(tmp_path))

    pitch = DummyPitch()
    pitch.run_id = "cron-test-2"
    pitch.schedule = "daily"

    orchestrator = SmartPrefectTaskOrchestrator(
        server_url="http://localhost:4200/api", work_pool="test-pool"
    )

    mock_to_deployment = AsyncMock(return_value="mock-deployment-obj")

    with patch(
        "pirlo.infrastructure.adapters.orchestrator.prefect_orchestrator.pirlo_generic_flow.to_deployment",
        mock_to_deployment,
    ):
        result = await orchestrator.execute(
            pitch,
            worker_fn=lambda: AsyncMock(return_value="ok")(),
        )

        assert result == "mock-deployment-obj"
        mock_to_deployment.assert_called_once()
        call_kwargs = mock_to_deployment.call_args.kwargs
        assert call_kwargs["name"] == "pirlo-scheduled-cron-test-2"
        assert call_kwargs["work_pool_name"] == "test-pool"
        assert call_kwargs["schedule"].cron == "0 9 * * *"
