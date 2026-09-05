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
from pirlo.infrastructure.adapters.runner_factory import PlayRunnerFactory


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
    runner = PrefectRunner(compiler=compiler, mode="ephemeral")
    result = await runner.run(blueprint)

    assert isinstance(result, StepTwoOutput)
    assert result.message == "Received tok_123"


@pytest.mark.anyio
async def test_prefect_runner_via_factory():
    play_instance = StepTwoPlay()
    blueprint: PlayBlueprint = play_instance.extract_blueprint()

    runner = PlayRunnerFactory.get_runner("prefect", mode="ephemeral")
    result = await runner.run(blueprint)

    assert isinstance(result, StepTwoOutput)
    assert result.message == "Received tok_123"
