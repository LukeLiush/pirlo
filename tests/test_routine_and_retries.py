from __future__ import annotations

import inspect
import sys
from pathlib import Path
from typing import Annotated, Any
from unittest.mock import AsyncMock, patch

import pytest

from pirlo.core.decorators import play
from pirlo.core.models.parameters import Parameter
from pirlo.core.ports.play import Play
from pirlo.infrastructure.adapters.cli.argument_parser_builder import (
    ArgumentParserBuilder,
)
from pirlo.infrastructure.adapters.orchestrator.prefect.models import (
    PrefectLink,
    PrefectRoutineRegistration,
)
from pirlo.infrastructure.adapters.storage.json_orchestrator_repository import (
    JsonOrchestratorRepository,
)


@play(
    name="resilient_mock",
    description="Play with retries and timeout",
    retries=3,
    retry_delay=15,
    timeout=120,
)
class ResilientMockPlay(Play[dict[str, Any]]):
    async def execute(
        self,
        task: Annotated[str, Parameter(help="Task prompt")] = "Default Task",
    ) -> dict[str, Any]:
        return {"routine": self.routine, "task": task}


def test_play_decorator_attributes() -> None:
    assert ResilientMockPlay.play_retries == 3
    assert ResilientMockPlay.play_retry_delay == 15
    assert ResilientMockPlay.play_timeout == 120


def test_play_routine_property() -> None:
    # 1. Default routine is None
    p1 = ResilientMockPlay()
    assert p1.routine is None

    # 2. Routine passed in __init__
    p2 = ResilientMockPlay(routine="0 9 * * *")
    assert p2.routine == "0 9 * * *"


def test_argument_parser_builder_has_routine_and_orchestrator() -> None:
    builder = ArgumentParserBuilder(ResilientMockPlay)
    parser = builder.build_parser("resilient_mock")

    args = parser.parse_args(["--routine", "daily", "--orchestrator", "prod"])
    assert args.routine == "daily"
    assert args.orchestrator == "prod"


@pytest.mark.anyio
async def test_cli_runner_with_routine_and_orchestrator(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PIRLO_WORKSPACE", str(tmp_path))

    # Save a link named "prod"
    repo = JsonOrchestratorRepository(tmp_path / "orchestrators.json")
    repo.save(
        PrefectLink(
            name="prod",
            server_url="http://prefect:4200/api",
            work_pool="custom-pool",
        )
    )

    with (
        patch.object(
            sys,
            "argv",
            [
                "pirlo",
                "resilient_mock",
                "--task",
                "Scrape News",
                "--routine",
                "daily",
                "--orchestrator",
                "prod",
            ],
        ),
        patch(
            "pirlo.infrastructure.adapters.orchestrator.prefect_runner.PrefectRunner.run",
            new_callable=AsyncMock,
        ) as mock_run,
    ):
        mock_run.return_value = PrefectRoutineRegistration(
            registration_id="dep-999",
            play_name="resilient_mock",
            routine="0 9 * * *",
            dashboard_url="http://prefect:4200/deployments/dep-999",
            work_pool="custom-pool",
        )

        result = ResilientMockPlay.cli("resilient_mock")
        if inspect.isawaitable(result):
            result = await result

        assert result is not None
        mock_run.assert_called_once()
        _, run_kwargs = mock_run.call_args
        assert run_kwargs["routine"] == "daily"
        blueprint = mock_run.call_args[0][0]
        assert blueprint.routine == "daily"
        assert blueprint.nodes[0].static_kwargs["task"] == "Scrape News"
