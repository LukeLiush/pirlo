# tests/test_idempotency.py
from __future__ import annotations

import asyncio

from pirlo.core.decorators import play
from pirlo.core.models.blueprint import PlayOutput
from pirlo.core.ports.play import Play
from pirlo.core.services.idempotency import compute_play_identity


class DummyPayload(PlayOutput):
    name: str
    count: int


def test_play_identity_key_order_invariance():
    dict1 = {"b": 2, "a": 1, "nested": {"z": 9, "y": 8}}
    dict2 = {"a": 1, "b": 2, "nested": {"y": 8, "z": 9}}

    id1 = compute_play_identity("my_play", dict1)
    id2 = compute_play_identity("my_play", dict2)

    assert id1.digest == id2.digest
    assert id1.full_id == id2.full_id
    assert id1.short_id == id2.short_id
    assert id1.full_id.startswith("my_play-")
    assert id1.short_id == f"my_play#{id1.digest[:6]}"


def test_play_identity_with_pydantic_models():
    model1 = DummyPayload(name="alpha", count=42)
    model2 = DummyPayload(name="alpha", count=42)

    id1 = compute_play_identity("model_play", {"payload": model1, "tag": "test"})
    id2 = compute_play_identity("model_play", {"tag": "test", "payload": model2})

    assert id1.digest == id2.digest
    assert id1.short_id == id2.short_id


def test_play_identity_distinct_inputs():
    id1 = compute_play_identity("play", {"month": "2026-06"})
    id2 = compute_play_identity("play", {"month": "2026-07"})

    assert id1.digest != id2.digest
    assert id1.short_id != id2.short_id


class IdTestOutput(PlayOutput):
    captured_id: str


@play(name="demo_id_play")
class IdTestPlay(Play[IdTestOutput]):
    async def execute(self, param: str = "val") -> IdTestOutput:
        return IdTestOutput(captured_id=self.play_id or "")


def test_play_id_attached_during_run():
    result: IdTestOutput = asyncio.run(IdTestPlay.run_play(param="test_123"))
    assert result.captured_id.startswith("demo_id_play-")
    assert len(result.captured_id) > 20
