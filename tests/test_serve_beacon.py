from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest

from pirlo.infrastructure.adapters.orchestrator.serve_beacon import (
    ServeBeacon,
    ServeRecord,
)

_HEALTH = "pirlo.infrastructure.adapters.orchestrator.serve_beacon.is_prefect_healthy"


@pytest.fixture
def beacon(tmp_path: Path) -> ServeBeacon:
    return ServeBeacon(tmp_path / "serve" / "serve.json")


def _record(pid: int) -> ServeRecord:
    return ServeRecord(
        pid=pid,
        port=4201,
        api_url="http://127.0.0.1:4201/api",
        worker="desk",
        started_at="2026-10-26T09:00:00+00:00",
    )


def test_write_read_forget(beacon):
    assert beacon.read() is None

    beacon.write(_record(123))
    assert beacon.read() == _record(123)

    beacon.forget()
    assert beacon.read() is None
    beacon.forget()


def test_default_path_is_in_the_workspace(monkeypatch, tmp_path):
    monkeypatch.setenv("PIRLO_WORKSPACE", str(tmp_path))
    assert ServeBeacon().path == tmp_path / "serve" / "serve.json"


@pytest.mark.parametrize("content", ["not json", "[]", '{"pid": 1}'])
def test_unreadable_record_is_ignored_with_a_warning(beacon, caplog, content):
    beacon.path.parent.mkdir(parents=True)
    beacon.path.write_text(content)

    with caplog.at_level(logging.WARNING):
        assert beacon.read() is None
    assert "Ignoring unreadable" in caplog.text


def test_running_needs_a_live_serve_and_an_answering_server(beacon, monkeypatch):
    healthy = {"value": True}
    monkeypatch.setattr(_HEALTH, lambda url, timeout_seconds=0.3: healthy["value"])

    beacon.write(_record(os.getpid()))
    assert beacon.running() == _record(os.getpid())

    healthy["value"] = False
    assert beacon.running() is None

    healthy["value"] = True
    beacon.write(_record(2**22 + 12345))  # above macOS/Linux default pid ranges
    assert beacon.running() is None
