# tests/test_fanout_log_isolation.py
from __future__ import annotations

import asyncio
import logging

import pytest

from pirlo.core.decorators import play
from pirlo.core.logging_context import (
    generate_short_run_id,
    workflow_logging_context,
)
from pirlo.core.models.blueprint import PlayBlueprint, PlayOutput
from pirlo.core.ports.play import Play, requires
from pirlo.core.services.blueprint_extractor import BlueprintExtractor
from pirlo.infrastructure.adapters.orchestrator.prefect_compiler import (
    PrefectCompiler,
)

TAGS = ["alpha", "bravo", "charlie"]


class TagsOutput(PlayOutput):
    tags: list[str]


class TagOutput(PlayOutput):
    tag: str


class AllTagsOutput(PlayOutput):
    tags: list[str]


@play(name="iso_select_tags")
class SelectTagsPlay(Play[TagsOutput]):
    async def execute(self) -> TagsOutput:
        return TagsOutput(tags=TAGS)


@play(name="iso_log_tag")
class LogTagPlay(Play[TagOutput]):
    tag: str = requires(SelectTagsPlay, each="tags")

    async def execute(self) -> TagOutput:
        # Interleave with sibling instances so their handlers overlap in time
        for i in range(5):
            self.logger.info("marker-%s-%d", self.tag, i)
            await asyncio.sleep(0.05)
        return TagOutput(tag=self.tag)


@play(name="iso_collect_tags")
class CollectTagsPlay(Play[AllTagsOutput]):
    items: list[TagOutput] = requires(LogTagPlay)

    async def execute(self) -> AllTagsOutput:
        return AllTagsOutput(tags=sorted(i.tag for i in self.items))


@pytest.mark.anyio
async def test_fanout_play_logs_stay_in_their_own_task():
    blueprint: PlayBlueprint = BlueprintExtractor.extract_from_play(CollectTagsPlay)
    from pirlo.infrastructure.adapters.orchestrator.prefect_run_repository import (
        PrefectRunRepository,
    )
    from pirlo.infrastructure.adapters.orchestrator.prefect_runner import (
        PrefectRunner,
    )

    run_id = generate_short_run_id()
    with workflow_logging_context(run_id):
        result = await PrefectRunner(compiler=PrefectCompiler()).run(blueprint)
    assert result.tags == sorted(TAGS)

    repo = PrefectRunRepository()
    run_record = await repo.get_by_id(run_id)
    assert run_record is not None
    tag_runs = [r for r in run_record.play_runs if r.play_id.startswith("iso_log_tag")]
    assert len(tag_runs) == len(TAGS)

    leaks: dict[str, list[str]] = {}
    for play_run in tag_runs:
        text = ""
        for _ in range(30):
            logs = [
                line
                async for line in repo.stream_play_logs(
                    run_id, play_id=play_run.play_id, tail_lines=500
                )
            ]
            text = "\n".join(logs)
            if "Play SUCCESS" in text:
                break
            await asyncio.sleep(0.1)
        own = [t for t in TAGS if f"marker-{t}-" in text]
        assert len(own) >= 1, f"{play_run.play_id} logged no markers:\n{text}"
        if len(own) > 1:
            leaks[play_run.play_id] = own

    assert not leaks, f"Task logs contain sibling markers: {leaks}"


@pytest.mark.anyio
async def test_fanout_restores_play_logger_propagate():
    play_logger = logging.getLogger("pirlo.play.iso_log_tag")
    play_logger.propagate = True
    blueprint = BlueprintExtractor.extract_from_play(CollectTagsPlay)
    from pirlo.infrastructure.adapters.orchestrator.prefect_runner import (
        PrefectRunner,
    )

    with workflow_logging_context(generate_short_run_id()):
        await PrefectRunner(compiler=PrefectCompiler()).run(blueprint, force=True)

    assert play_logger.propagate is True
    assert play_logger.handlers == []
