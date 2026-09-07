# tests/test_prefect_caching.py
from __future__ import annotations

import asyncio

from pirlo.core.decorators import play
from pirlo.core.models.blueprint import PlayOutput
from pirlo.core.ports.play import Play

_EXECUTION_COUNTER: dict[str, int] = {}


class CachingTestOutput(PlayOutput):
    invocations: int
    val: str


@play(name="caching_play_v1", version="1.0")
class CachingPlayV1(Play[CachingTestOutput]):
    async def execute(self, key: str = "default") -> CachingTestOutput:
        _EXECUTION_COUNTER["v1"] = _EXECUTION_COUNTER.get("v1", 0) + 1
        return CachingTestOutput(invocations=_EXECUTION_COUNTER["v1"], val=key)


@play(name="caching_play_v1", version="1.1")
class CachingPlayV2(Play[CachingTestOutput]):
    async def execute(self, key: str = "default") -> CachingTestOutput:
        _EXECUTION_COUNTER["v2"] = _EXECUTION_COUNTER.get("v2", 0) + 1
        return CachingTestOutput(invocations=_EXECUTION_COUNTER["v2"], val=key)


def test_play_caching_and_force():
    import uuid

    _EXECUTION_COUNTER.clear()
    test_key = f"key_{uuid.uuid4().hex[:8]}"

    # 1. First run with version 1.0 -> Executes function
    res1: CachingTestOutput = asyncio.run(CachingPlayV1.run_play(key=test_key))
    assert res1.invocations == 1
    assert _EXECUTION_COUNTER["v1"] == 1

    # 2. Second run with same inputs and version 1.0 -> Cached (skipped execution!)
    res2: CachingTestOutput = asyncio.run(CachingPlayV1.run_play(key=test_key))
    assert res2.invocations == 1  # Reused from cache
    assert _EXECUTION_COUNTER["v1"] == 1  # Function body did NOT run

    # 3. Third run with version 1.1 (version bump) -> Executes because cache key changed
    res3: CachingTestOutput = asyncio.run(CachingPlayV2.run_play(key=test_key))
    assert res3.invocations == 1
    assert _EXECUTION_COUNTER["v2"] == 1

    # 4. Fourth run with version 1.0 and force=True -> Bypasses cache and executes
    res4: CachingTestOutput = asyncio.run(
        CachingPlayV1.run_play(key=test_key, force=True)
    )
    assert _EXECUTION_COUNTER["v1"] == 2
    assert res4.invocations == 2
