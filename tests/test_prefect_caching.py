# tests/test_prefect_caching.py
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from pirlo.core.decorators import play
from pirlo.core.models.blueprint import PlayOutput
from pirlo.core.ports.play import Play


def _get_counter_path(key: str) -> Path:
    return Path(tempfile.gettempdir()) / f"pirlo_caching_test_{key}.txt"


def _increment_counter(key: str) -> int:
    path = _get_counter_path(key)
    val = 0
    if path.exists():
        try:
            val = int(path.read_text().strip())
        except ValueError:
            val = 0
    val += 1
    path.write_text(str(val))
    return val


def _get_counter(key: str) -> int:
    path = _get_counter_path(key)
    if path.exists():
        try:
            return int(path.read_text().strip())
        except ValueError:
            return 0
    return 0


def _clear_counters() -> None:
    for k in ("v1", "v2"):
        p = _get_counter_path(k)
        if p.exists():
            p.unlink()


class CachingTestOutput(PlayOutput):
    invocations: int
    val: str


@play(name="caching_play_v1", version="1.0")
class CachingPlayV1(Play[CachingTestOutput]):
    async def execute(self, key: str = "default") -> CachingTestOutput:
        count = _increment_counter("v1")
        return CachingTestOutput(invocations=count, val=key)


@play(name="caching_play_v1", version="1.1")
class CachingPlayV2(Play[CachingTestOutput]):
    async def execute(self, key: str = "default") -> CachingTestOutput:
        count = _increment_counter("v2")
        return CachingTestOutput(invocations=count, val=key)


def test_play_caching_and_force():
    import uuid

    _clear_counters()
    test_key = f"key_{uuid.uuid4().hex[:8]}"

    # 1. First run with version 1.0 -> Executes function
    res1: CachingTestOutput = asyncio.run(CachingPlayV1.run_play(key=test_key))
    assert res1.invocations == 1
    assert _get_counter("v1") == 1

    # 2. Second run with same inputs and version 1.0 -> Cached (skipped execution!)
    res2: CachingTestOutput = asyncio.run(CachingPlayV1.run_play(key=test_key))
    assert res2.invocations == 1  # Reused from cache
    assert _get_counter("v1") == 1  # Function body did NOT run

    # 3. Third run with version 1.1 (version bump) -> Executes because cache key changed
    res3: CachingTestOutput = asyncio.run(CachingPlayV2.run_play(key=test_key))
    assert res3.invocations == 1
    assert _get_counter("v2") == 1

    # 4. Fourth run with version 1.0 and force=True -> Bypasses cache and executes
    res4: CachingTestOutput = asyncio.run(
        CachingPlayV1.run_play(key=test_key, force=True)
    )
    assert _get_counter("v1") == 2
    assert res4.invocations == 2

    _clear_counters()
