from typing import Annotated, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pirlo.core.decorators import orchestrator
from pirlo.core.models.parameters import Parameter
from pirlo.core.ports.orchestrator import TaskOrchestrator
from pirlo.infrastructure.adapters.orchestrator.factory import OrchestratorFactory
from pirlo.infrastructure.adapters.orchestrator.prefect_orchestrator import (
    SmartPrefectTaskOrchestrator,
)


@orchestrator(name="custom")
class CustomMockOrchestrator(TaskOrchestrator):
    def __init__(self, custom_setting: str = "default") -> None:
        self.custom_setting = custom_setting

    async def execute(
        self,
        prepared_run: Any = None,
        worker_fn: Any = None,
        custom_setting: Annotated[str, Parameter(help="Custom setting")] = "default",
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        return f"executed with {custom_setting}"


def test_factory_creates_prefect_default():
    orchestrator_obj = OrchestratorFactory.create("prefect")
    assert isinstance(orchestrator_obj, SmartPrefectTaskOrchestrator)


def test_factory_merges_overrides():
    orchestrator_obj = OrchestratorFactory.create(
        "prefect",
        server_url="http://custom-prefect:4200/api",
        work_pool="custom-pool",
    )
    assert isinstance(orchestrator_obj, SmartPrefectTaskOrchestrator)
    assert orchestrator_obj.server_url == "http://custom-prefect:4200/api"
    assert orchestrator_obj.work_pool == "custom-pool"


def test_factory_toml_configuration(tmp_path):
    config_file = tmp_path / "pirlo.toml"
    config_file.write_text(
        """
[pirlo.orchestrator.prefect]
server_url = "http://toml-server:4200/api"
work_pool = "toml-pool"
"""
    )
    orchestrator_obj = OrchestratorFactory.create("prefect", config_path=config_file)
    assert isinstance(orchestrator_obj, SmartPrefectTaskOrchestrator)
    assert orchestrator_obj.server_url == "http://toml-server:4200/api"
    assert orchestrator_obj.work_pool == "toml-pool"


def test_factory_cli_override_beats_toml(tmp_path):
    config_file = tmp_path / "pirlo.toml"
    config_file.write_text(
        """
[pirlo.orchestrator.prefect]
server_url = "http://toml-server:4200/api"
work_pool = "toml-pool"
"""
    )
    orchestrator_obj = OrchestratorFactory.create(
        "prefect",
        config_path=config_file,
        server_url="http://cli-override:4200/api",
    )
    assert isinstance(orchestrator_obj, SmartPrefectTaskOrchestrator)
    assert orchestrator_obj.server_url == "http://cli-override:4200/api"
    assert orchestrator_obj.work_pool == "toml-pool"


def test_factory_dynamic_registration():
    OrchestratorFactory.register("custom", CustomMockOrchestrator)
    orchestrator_obj = OrchestratorFactory.create(
        "custom", custom_setting="override_val"
    )
    assert isinstance(orchestrator_obj, CustomMockOrchestrator)
    assert orchestrator_obj.custom_setting == "override_val"


def test_factory_unknown_orchestrator_raises_error():
    with pytest.raises(ValueError, match="Unknown orchestrator backend 'nonexistent'"):
        OrchestratorFactory.create("nonexistent")


from pirlo.core.models.run import PreparedRun
from pirlo.core.models.run_result import RunResult
from pirlo.infrastructure.adapters.cli.terminal_pitch import TerminalPitch


class DummyPitch(TerminalPitch):
    """Dummy Pitch for orchestrator cron testing."""

    async def on_play(self, *args, **kwargs) -> RunResult[Any]:
        return RunResult(run_id=(await self.prepared_run()).run_id)


@pytest.mark.anyio
async def test_cron_schedule_requires_active_server(tmp_path, monkeypatch):
    monkeypatch.setenv("PIRLO_WORKSPACE", str(tmp_path))

    run_dir = tmp_path / "autopass" / "runs" / "cron-test-1"
    run_dir.mkdir(parents=True, exist_ok=True)

    orchestrator_obj = SmartPrefectTaskOrchestrator()
    orchestrator_obj.server_url = None
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
        await orchestrator_obj.execute(
            prepared_run=prepared_run,
            worker_fn=lambda: AsyncMock(return_value="ok")(),
            task="Do work",
            schedule="0 9 * * *",
        )


@pytest.mark.anyio
async def test_cron_schedule_creates_deployment_when_server_active(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("PIRLO_WORKSPACE", str(tmp_path))

    run_dir = tmp_path / "autopass" / "runs" / "cron-test-2"
    run_dir.mkdir(parents=True, exist_ok=True)

    orchestrator_obj = SmartPrefectTaskOrchestrator()
    orchestrator_obj.server_url = "http://localhost:4200/api"
    orchestrator_obj.work_pool = "test-pool"
    prepared_run = PreparedRun(
        playbook_name="autopass",
        run_name="cron-test-2",
        run_id="cron-test-2",
        workspace=tmp_path,
        parameters={},
    )

    mock_plan = MagicMock()
    mock_plan.model_dump.return_value = {"subtasks": []}
    mock_decomposer = MagicMock()
    mock_decomposer.decompose = AsyncMock(return_value=mock_plan)
    orchestrator_obj._build_decomposer = MagicMock(return_value=mock_decomposer)
    orchestrator_obj._get_decomposer_link = MagicMock(return_value=MagicMock())

    mock_deployment = MagicMock()
    mock_deployment.apply = AsyncMock(return_value="mock-deployment-id-123")
    mock_to_deployment = AsyncMock(return_value=mock_deployment)

    with patch(
        "pirlo.infrastructure.adapters.orchestrator.prefect_orchestrator.pirlo_decomposed_flow.to_deployment",
        mock_to_deployment,
    ):
        result = await orchestrator_obj.execute(
            prepared_run=prepared_run,
            worker_fn=lambda: AsyncMock(return_value="ok")(),
            task="Do work",
            schedule="0 9 * * *",
        )

        assert "pirlo-scheduled-autopass-" in result
        assert "mock-deployment-id-123" in result
        assert (
            "🔗 View deployment in Prefect UI: http://localhost:4200/deployments/deployment/mock-deployment-id-123"
            in result
        )
        mock_to_deployment.assert_called_once()
        mock_deployment.apply.assert_called_once()
        call_kwargs = mock_to_deployment.call_args.kwargs
        assert call_kwargs["name"].startswith("pirlo-scheduled-autopass-")
        assert call_kwargs["work_pool_name"] == "test-pool"
        assert call_kwargs["schedule"].cron == "0 9 * * *"
        assert call_kwargs["parameters"]["playbook"] == "autopass"


def test_dynamic_schedule_help_text():
    from pirlo.core.services.schedule_resolver import get_schedule_help_text

    help_text = get_schedule_help_text()
    assert "'daily'" in help_text
    assert "'hourly'" in help_text
    assert "'weekly'" in help_text
    assert "'monthly'" in help_text


@pytest.mark.anyio
async def test_cron_schedule_preset_resolution(tmp_path, monkeypatch):
    monkeypatch.setenv("PIRLO_WORKSPACE", str(tmp_path))

    run_dir = tmp_path / "autopass" / "runs" / "cron-test-preset"
    run_dir.mkdir(parents=True, exist_ok=True)

    orchestrator_obj = SmartPrefectTaskOrchestrator()
    orchestrator_obj.server_url = "http://localhost:4200/api"
    orchestrator_obj.work_pool = "test-pool"
    prepared_run = PreparedRun(
        playbook_name="autopass",
        run_name="cron-test-preset",
        run_id="cron-test-preset",
        workspace=tmp_path,
        parameters={},
    )

    mock_plan = MagicMock()
    mock_plan.model_dump.return_value = {"subtasks": []}
    mock_decomposer = MagicMock()
    mock_decomposer.decompose = AsyncMock(return_value=mock_plan)
    orchestrator_obj._build_decomposer = MagicMock(return_value=mock_decomposer)
    orchestrator_obj._get_decomposer_link = MagicMock(return_value=MagicMock())

    mock_deployment = MagicMock()
    mock_deployment.apply = AsyncMock(return_value="mock-deployment-id-456")
    mock_to_deployment = AsyncMock(return_value=mock_deployment)

    with patch(
        "pirlo.infrastructure.adapters.orchestrator.prefect_orchestrator.pirlo_decomposed_flow.to_deployment",
        mock_to_deployment,
    ):
        result = await orchestrator_obj.execute(
            prepared_run=prepared_run,
            worker_fn=lambda: AsyncMock(return_value="ok")(),
            task="Do work",
            schedule="daily",
        )

        assert "pirlo-scheduled-autopass-" in result
        assert "mock-deployment-id-456" in result
        assert (
            "🔗 View deployment in Prefect UI: http://localhost:4200/deployments/deployment/mock-deployment-id-456"
            in result
        )
        mock_to_deployment.assert_called_once()
        mock_deployment.apply.assert_called_once()
        call_kwargs = mock_to_deployment.call_args.kwargs
        assert call_kwargs["schedule"].cron == "0 9 * * *"
        assert call_kwargs["schedule"].timezone is not None


def test_orchestrator_factory_parses_schedule_flag():
    orchestrator = OrchestratorFactory.create_from_invocation(
        name="prefect",
        playbook_name="autopass",
        orchestrator_flags=["prefect", "-s", "*/10 * * * *"],
    )
    assert getattr(orchestrator, "schedule", None) == "*/10 * * * *"
