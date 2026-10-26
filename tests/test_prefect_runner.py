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


def test_prefect_runner_get_dashboard_url_server():
    compiler = PrefectCompiler()
    runner = PrefectRunner(
        compiler=compiler,
        target=_server_target("http://prefect.internal:4200/api"),
    )
    assert (
        runner.get_dashboard_url("test_run_123")
        == "http://prefect.internal:4200/flow-runs?name=test_run_123"
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
            == "http://prefect.internal:4200/flow-runs?name=dashing-otter"
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
    assert runner.get_dashboard_url("r1") == "http://h:4200/flow-runs?name=r1"
