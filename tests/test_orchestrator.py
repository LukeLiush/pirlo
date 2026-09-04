from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from pirlo.core.decorators import playbook
from pirlo.core.models.run import PreparedRun
from pirlo.core.models.run_result import RunResult
from pirlo.core.ports.playbook import Playbook
from pirlo.infrastructure.adapters.orchestrator.factory import OrchestratorFactory
from pirlo.infrastructure.adapters.orchestrator.prefect_orchestrator import (
    SmartPrefectTaskOrchestrator,
)


@playbook(name="autopass", description="Mock Autopass pitch for testing.")
class DummyAutopassPlaybook(Playbook):
    """Mock Autopass pitch for testing."""

    task = "Search Google for OpenAI"

    async def play(self, *args, **kwargs) -> RunResult[Any]:
        return RunResult(run_id=(await self.prepared_run()).run_id)


@pytest.mark.anyio
async def test_smart_prefect_orchestrator_execution(tmp_path, monkeypatch):
    monkeypatch.setenv("PIRLO_WORKSPACE", str(tmp_path))

    run_dir = tmp_path / "autopass" / "runs" / "test-run-12345"
    run_dir.mkdir(parents=True, exist_ok=True)

    from pirlo.core.models.link import LlmLink

    test_link = LlmLink(
        name="test-link",
        provider="gemini",
        model="gemini-2.5-flash",
        api_key="test",
    )
    orchestrator = SmartPrefectTaskOrchestrator(decomposer_link=test_link)
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
            prepared_run=prepared_run,
            worker_fn=mock_worker,
            task="Search Google for OpenAI",
        )

        assert result == "Automation successful!"


def test_parse_cli_options_direct_contract():
    orchestrator = OrchestratorFactory.create_from_invocation(
        name="prefect",
        playbook_name="autopass",
        orchestrator_flags=[
            "--server-url",
            "http://localhost:4200/api",
            "--work-pool",
            "my-pool",
        ],
    )

    assert orchestrator.server_url == "http://localhost:4200/api"
    assert orchestrator.work_pool == "my-pool"


def test_orchestrator_fails_loud_without_decomposer_link():
    orchestrator = SmartPrefectTaskOrchestrator()
    with (
        patch(
            "pirlo.infrastructure.adapters.storage.composite_link_repository.CompositeLinkRepository.get_by_name",
            return_value=None,
        ),
        pytest.raises(
            ValueError, match="No active LLM link found in playbook parameters"
        ),
    ):
        orchestrator._get_decomposer_link(
            PreparedRun(
                run_name="test",
                run_id="test-id",
                playbook_name="autopass",
                workspace=Path("/tmp"),
                parameters={},
            )
        )


def test_orchestrator_auto_detects_playmaker_link(tmp_path):
    from pirlo.core.models.link import LlmLink

    playmaker_link = LlmLink(
        name="my-playmaker",
        provider="openai",
        model="gpt-4o",
        api_key="test",
    )
    orchestrator = SmartPrefectTaskOrchestrator()
    prepared_run = PreparedRun(
        run_name="test",
        run_id="test-id",
        playbook_name="autopass",
        workspace=tmp_path,
        parameters={"playmaker": playmaker_link},
    )

    resolved = orchestrator._get_decomposer_link(prepared_run)
    assert resolved.name == "my-playmaker"
    assert resolved.model == "gpt-4o"


def test_orchestrator_aggregator_link_uses_default_link(tmp_path):
    from pirlo.core.models.link import LlmLink

    default_ollama_link = LlmLink(
        name="serve-ollama",
        provider="ollama",
        model="llama3.1:8b",
        api_key="ollama",
        base_url="http://127.0.0.1:11434",
        is_default=True,
    )
    orchestrator = SmartPrefectTaskOrchestrator()

    with patch(
        "pirlo.infrastructure.adapters.storage.composite_link_repository.CompositeLinkRepository.get_default_link",
        return_value=default_ollama_link,
    ):
        agg_link = orchestrator._get_aggregator_link()
        assert agg_link.name == "serve-ollama"
        assert agg_link.is_default is True


def test_orchestrator_decorator_enforcement():
    from pirlo.core.decorators import orchestrator
    from pirlo.core.ports.orchestrator import TaskOrchestrator

    class UndecoratedOrchestrator(TaskOrchestrator):
        async def execute(self, *args, **kwargs):
            pass

    with pytest.raises(TypeError, match="missing the @orchestrator decorator"):
        UndecoratedOrchestrator()

    @orchestrator(
        name="custom_test",
        description="Custom test orchestrator",
        version="1.0.0",
    )
    class DecoratedOrchestrator(TaskOrchestrator):
        async def execute(self, *args, **kwargs):
            pass

    instance = DecoratedOrchestrator()
    assert instance.info.name == "custom_test"
    assert instance.info.description == "Custom test orchestrator"
    assert instance.info.extra == {"version": "1.0.0"}
    assert DecoratedOrchestrator.info.name == "custom_test"
