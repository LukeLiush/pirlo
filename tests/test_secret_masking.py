# tests/test_secret_masking.py
from __future__ import annotations

import asyncio
from typing import Annotated

import pytest

from pirlo.core.decorators import play
from pirlo.core.logging_context import (
    generate_short_run_id,
    workflow_logging_context,
)
from pirlo.core.models.blueprint import PlayOutput
from pirlo.core.models.link import LlmLink
from pirlo.core.models.parameters import LinkParameter, Parameter
from pirlo.core.ports.play import Play
from pirlo.core.services.blueprint_extractor import BlueprintExtractor
from pirlo.core.services.masking import sensitive_parameter_names
from pirlo.infrastructure.adapters.orchestrator.prefect_compiler import (
    PrefectCompiler,
)

API_KEY = "sk-live-NEVER-STORE-ME-123456"
PIN = "4321-not-a-secret-looking-name"


class MaskedOutput(PlayOutput):
    provider: str


@play(name="mask_sample_play")
class MaskSamplePlay(Play[MaskedOutput]):
    async def execute(
        self,
        llm: Annotated[LlmLink, LinkParameter(help="LLM link")],
        region_pin: Annotated[str, Parameter(help="PIN", sensitive=True)],
        region: Annotated[str, Parameter(help="Region")] = "eu",
    ) -> MaskedOutput:
        return MaskedOutput(provider=llm.provider)


def test_sensitive_parameter_names_reads_the_sensitive_flag():
    assert sensitive_parameter_names(MaskSamplePlay) == frozenset({"region_pin"})


@pytest.mark.anyio
async def test_run_history_and_task_log_never_contain_secrets():
    from pirlo.infrastructure.adapters.orchestrator.prefect_run_repository import (
        PrefectRunRepository,
    )
    from pirlo.infrastructure.adapters.orchestrator.prefect_runner import (
        PrefectRunner,
    )

    params = {
        "llm": LlmLink(name="g", provider="gemini", api_key=API_KEY),
        "region_pin": PIN,
        "region": "us",
    }
    blueprint = BlueprintExtractor.extract_from_play(MaskSamplePlay, user_kwargs=params)

    run_id = generate_short_run_id()
    with workflow_logging_context(run_id):
        # Same call shape as the CLI: resolved parameters are passed to run()
        result = await PrefectRunner(compiler=PrefectCompiler()).run(
            blueprint, force=True, **params
        )
    assert result.provider == "gemini"  # the play still received the real link

    repo = PrefectRunRepository()
    run_record = await repo.get_by_id(run_id)
    assert run_record is not None
    snapshot = repr(run_record.parameters)
    assert API_KEY not in snapshot
    assert PIN not in snapshot
    assert "'region': 'us'" in snapshot  # non-secret values stay readable

    play_run = run_record.play_runs[0]
    log_text = ""
    for _ in range(30):
        log_text = "\n".join(
            [
                line
                async for line in repo.stream_play_logs(
                    run_id, play_id=play_run.play_id, tail_lines=200
                )
            ]
        )
        if "Play START" in log_text:
            break
        await asyncio.sleep(0.1)
    assert "Play START" in log_text
    assert API_KEY not in log_text
    assert PIN not in log_text
