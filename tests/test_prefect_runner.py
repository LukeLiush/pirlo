# tests/test_prefect_runner.py
from __future__ import annotations

import pytest

from pirlo.core.decorators import play
from pirlo.core.models.blueprint import PlayBlueprint, PlayOutput
from pirlo.core.ports.play import Play, requires
from pirlo.infrastructure.adapters.orchestrator.prefect_compiler import (
    PrefectCompiler,
)
from pirlo.infrastructure.adapters.orchestrator.prefect_runner import (
    PrefectRunner,
)
from pirlo.infrastructure.adapters.orchestrator.prefect_settings import (
    PrefectServerSettings,
)
from pirlo.infrastructure.adapters.orchestrator.prefect_target import (
    Execution,
    PrefectTarget,
)
from pirlo.infrastructure.adapters.runner_factory import PlayRunnerFactory


def _server_target(
    url: str, execution: Execution = Execution.IN_PROCESS, **kwargs
) -> PrefectTarget:
    return PrefectTarget(PrefectServerSettings.resolve(url), execution, **kwargs)


class StepOneOutput(PlayOutput):
    token: str


class StepTwoOutput(PlayOutput):
    message: str


@play(name="runner_test_step_one")
class StepOnePlay(Play[StepOneOutput]):
    async def execute(self, token_prefix: str = "tok") -> StepOneOutput:
        return StepOneOutput(token=f"{token_prefix}_123")


@play(name="runner_test_step_two")
class StepTwoPlay(Play[StepTwoOutput]):
    step1: StepOneOutput = requires(StepOnePlay)

    async def execute(self) -> StepTwoOutput:
        return StepTwoOutput(message=f"Received {self.step1.token}")


@pytest.mark.anyio
async def test_prefect_runner_ephemeral_execution():
    play_instance = StepTwoPlay()
    blueprint: PlayBlueprint = play_instance.extract_blueprint()

    compiler = PrefectCompiler()
    runner = PrefectRunner(compiler=compiler)
    result = await runner.run(blueprint)

    assert isinstance(result, StepTwoOutput)
    assert result.message == "Received tok_123"


@pytest.mark.anyio
async def test_prefect_runner_via_factory():
    play_instance = StepTwoPlay()
    blueprint: PlayBlueprint = play_instance.extract_blueprint()

    runner = PlayRunnerFactory.get_runner()
    result = await runner.run(blueprint)

    assert isinstance(result, StepTwoOutput)
    assert result.message == "Received tok_123"


def test_prefect_runner_get_dashboard_url_ephemeral():
    compiler = PrefectCompiler()
    runner = PrefectRunner(compiler=compiler)
    assert runner.get_dashboard_url("test_run_123") is None


def test_prefect_runner_get_dashboard_url_server(monkeypatch):
    compiler = PrefectCompiler()
    runner = PrefectRunner(
        compiler=compiler,
        target=_server_target("http://prefect.internal:4200/api"),
    )
    monkeypatch.setattr(runner, "_find_flow_run_id", lambda name: "uuid-1")
    assert (
        runner.get_dashboard_url("test_run_123")
        == "http://prefect.internal:4200/runs/flow-run/uuid-1"
    )


def test_prefect_runner_sync_environ():
    import os

    from prefect.settings import PREFECT_API_URL

    compiler = PrefectCompiler()
    runner = PrefectRunner(
        compiler=compiler,
        target=_server_target("http://test.url:4200/api"),
    )

    assert "PREFECT_API_URL" not in os.environ
    settings = {PREFECT_API_URL: "http://test.url:4200/api"}
    with runner._sync_environ(settings):
        assert os.environ["PREFECT_API_URL"] == "http://test.url:4200/api"
    assert "PREFECT_API_URL" not in os.environ


@pytest.mark.anyio
async def test_prefect_runner_server_mode_dispatches_to_submit_remote_run():
    from unittest.mock import AsyncMock, patch

    from pirlo.infrastructure.adapters.orchestrator.prefect.models import (
        PrefectRoutineRegistration,
    )

    play_instance = StepTwoPlay()
    blueprint: PlayBlueprint = play_instance.extract_blueprint()

    compiler = PrefectCompiler()
    runner = PrefectRunner(
        compiler=compiler,
        target=_server_target(
            "http://prefect.internal:4200/api",
            Execution.WORK_POOL,
            work_pool="custom-pool",
        ),
    )

    mock_reg = PrefectRoutineRegistration(
        registration_id="run-uuid-123",
        play_name="runner_test_step_two",
        routine=None,
        dashboard_url="http://prefect.internal:4200/flow-runs?name=run-uuid-123",
        work_pool="custom-pool",
    )

    with patch.object(
        runner, "_submit_remote_run", new_callable=AsyncMock
    ) as mock_submit:
        mock_submit.return_value = mock_reg
        res = await runner.run(blueprint)

        mock_submit.assert_awaited_once()
        assert res == mock_reg
        assert res.routine is None


@pytest.mark.anyio
async def test_prefect_runner_submit_remote_run():
    from unittest.mock import AsyncMock, MagicMock, patch

    from pirlo.infrastructure.adapters.orchestrator.prefect.models import (
        PrefectRoutineRegistration,
    )

    play_instance = StepTwoPlay()
    blueprint: PlayBlueprint = play_instance.extract_blueprint()

    compiler = PrefectCompiler()
    runner = PrefectRunner(
        compiler=compiler,
        target=_server_target(
            "http://prefect.internal:4200/api",
            Execution.WORK_POOL,
            work_pool="pirlo-pool",
            code_storage="in_memory",
        ),
    )

    mock_deployment = MagicMock()
    mock_deployment.apply = AsyncMock(return_value="deployment-uuid-456")

    mock_flow_run = MagicMock()
    mock_flow_run.id = "run-uuid-789"
    mock_flow_run.name = "dashing-otter"

    workflow = compiler.compile(blueprint)

    with (
        patch(
            "pirlo.infrastructure.adapters.orchestrator.prefect_entrypoint.run_play_remote.to_deployment",
            new_callable=AsyncMock,
            return_value=mock_deployment,
        ),
        patch(
            "prefect.deployments.run_deployment",
            new_callable=AsyncMock,
            return_value=mock_flow_run,
        ),
    ):
        result = await runner._submit_remote_run(workflow)
        assert isinstance(result, PrefectRoutineRegistration)
        assert result.registration_id == "run-uuid-789"
        assert result.routine is None
        assert result.work_pool == "pirlo-pool"
        assert (
            result.dashboard_url
            == "http://prefect.internal:4200/runs/flow-run/run-uuid-789"
        )


@pytest.mark.anyio
async def test_run_play_remote_execution():
    from prefect.settings import (
        PREFECT_API_URL,
        PREFECT_SERVER_ALLOW_EPHEMERAL_MODE,
        temporary_settings,
    )

    from pirlo.infrastructure.adapters.orchestrator.prefect_entrypoint import (
        run_play_remote,
    )

    with temporary_settings(
        {
            PREFECT_SERVER_ALLOW_EPHEMERAL_MODE: True,
            PREFECT_API_URL: None,
        }
    ):
        result = await run_play_remote(
            play_name="runner_test_step_two",
            parameters={},
            code_ref=None,
        )
    assert isinstance(result, StepTwoOutput)
    assert result.message == "Received tok_123"


# --- routing: where a run's state goes and where its code executes ---------


def test_default_runner_is_ephemeral():
    from prefect.settings import PREFECT_API_URL, PREFECT_SERVER_ALLOW_EPHEMERAL_MODE

    overrides = PrefectRunner()._get_override_settings()

    assert overrides[PREFECT_API_URL] is None
    assert overrides[PREFECT_SERVER_ALLOW_EPHEMERAL_MODE] is True


@pytest.mark.anyio
async def test_in_process_target_runs_in_process():
    from unittest.mock import AsyncMock, patch

    from prefect.settings import PREFECT_API_URL

    runner = PrefectRunner(target=_server_target("http://h:4200"))

    with (
        patch.object(runner, "_run_immediate_once", new_callable=AsyncMock) as local,
        patch.object(runner, "_submit_remote_run", new_callable=AsyncMock) as remote,
    ):
        await runner.run(StepTwoPlay().extract_blueprint())

    local.assert_awaited_once()
    remote.assert_not_awaited()
    assert runner._get_override_settings()[PREFECT_API_URL] == "http://h:4200/api"


@pytest.mark.parametrize(
    "raw",
    ["http://h:4200", "http://h:4200/", "http://h:4200/api", "http://h:4200/api/"],
)
def test_server_url_is_normalized_to_api(raw):
    from prefect.settings import PREFECT_API_URL

    runner = PrefectRunner(target=_server_target(raw))

    assert runner._get_override_settings()[PREFECT_API_URL] == "http://h:4200/api"
    assert runner.get_deployment_url("d1") == "http://h:4200/deployments/deployment/d1"


# --- deployments: what routines and work-pool runs send to Prefect ---------


def _stub_deployment(deployment_id: str = "dep-123"):
    from unittest.mock import AsyncMock, MagicMock

    deployment = MagicMock()
    deployment.apply = AsyncMock(return_value=deployment_id)
    return deployment


def _work_pool_runner(work_pool: str) -> PrefectRunner:
    return PrefectRunner(
        target=_server_target(
            "http://h:4200",
            Execution.WORK_POOL,
            work_pool=work_pool,
            code_storage="in_memory",
        )
    )


@pytest.mark.anyio
async def test_deploy_routine_registers_a_cron_deployment():
    from unittest.mock import AsyncMock, patch

    runner = _work_pool_runner("nightly-pool")
    workflow = runner.compiler.compile(StepTwoPlay().extract_blueprint())

    with (
        patch(
            "pirlo.infrastructure.services.code_bundler.create_tarball_bytes",
            return_value=b"code",
        ),
        patch(
            "pirlo.infrastructure.adapters.orchestrator.prefect_entrypoint.run_play_remote.to_deployment",
            new_callable=AsyncMock,
            return_value=_stub_deployment("dep-123"),
        ) as to_deployment,
    ):
        reg = await runner._deploy_routine(workflow, "daily", x=1)

    kwargs = to_deployment.call_args.kwargs
    assert kwargs["name"] == "pirlo-runner_test_step_two-daily"
    assert kwargs["cron"] == "0 9 * * *"
    assert kwargs["work_pool_name"] == "nightly-pool"
    assert kwargs["enforce_parameter_schema"] is False
    assert "command" in kwargs["job_variables"]
    assert kwargs["parameters"] == {
        "play_name": "runner_test_step_two",
        "parameters": {"x": 1},
        "code_ref": "Y29kZQ==",
        "storage_type": "in_memory",
        "force": False,
        "show_logs": False,
    }
    assert reg.registration_id == "dep-123"
    assert reg.routine == "0 9 * * *"
    assert reg.work_pool == "nightly-pool"
    assert reg.dashboard_url == "http://h:4200/deployments/deployment/dep-123"


@pytest.mark.anyio
async def test_submit_remote_run_builds_a_one_off_deployment():
    from unittest.mock import AsyncMock, MagicMock, patch

    runner = _work_pool_runner("pirlo-pool")
    workflow = runner.compiler.compile(StepTwoPlay().extract_blueprint())
    flow_run = MagicMock()
    flow_run.id = "run-1"
    flow_run.name = "brisk-heron"

    with (
        patch(
            "pirlo.infrastructure.services.code_bundler.create_tarball_bytes",
            return_value=b"code",
        ),
        patch(
            "pirlo.infrastructure.adapters.orchestrator.prefect_entrypoint.run_play_remote.to_deployment",
            new_callable=AsyncMock,
            return_value=_stub_deployment(),
        ) as to_deployment,
        patch(
            "prefect.deployments.run_deployment",
            new_callable=AsyncMock,
            return_value=flow_run,
        ) as run_deployment,
    ):
        await runner._submit_remote_run(workflow, force=True, x=1)

    kwargs = to_deployment.call_args.kwargs
    assert kwargs["name"] == "pirlo-runner_test_step_two"
    assert "cron" not in kwargs
    assert kwargs["work_pool_name"] == "pirlo-pool"
    payload = kwargs["parameters"]
    assert payload["parameters"] == {"x": 1}
    assert (payload["force"], payload["show_logs"]) == (True, False)
    run_deployment.assert_called_once_with(
        name="pirlo_remote_runner/pirlo-runner_test_step_two",
        parameters=payload,
        timeout=0,
    )


# --- dashboard links ----------------------------------------------------------


def test_deployment_and_run_links_are_none_when_ephemeral():
    runner = PrefectRunner()

    assert runner.get_dashboard_url("r1") is None
    assert runner.get_deployment_url("d1") is None


def test_dashboard_url_falls_back_to_a_runs_search(monkeypatch):
    runner = PrefectRunner(target=_server_target("http://h:4200"))
    monkeypatch.setattr(runner, "_find_flow_run_id", lambda name: None)

    assert runner.get_dashboard_url("8efd 6618") == (
        "http://h:4200/runs?flow-run-search=8efd%206618"
    )


def test_unreachable_server_lookup_warns_and_falls_back(caplog):
    import logging
    import time

    runner = PrefectRunner(target=_server_target("http://127.0.0.1:59999"))

    started = time.monotonic()
    with caplog.at_level(logging.WARNING):
        url = runner.get_dashboard_url("r1")

    assert url == "http://127.0.0.1:59999/runs?flow-run-search=r1"
    assert "Couldn't look up flow run r1" in caplog.text
    assert time.monotonic() - started < 5
