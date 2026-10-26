from __future__ import annotations

import json
import socket
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from pirlo.core.ports.local_server import LocalServerError
from pirlo.infrastructure.adapters.orchestrator.prefect_health import (
    is_prefect_healthy,
)
from pirlo.infrastructure.adapters.orchestrator.prefect_local_server import (
    PrefectLocalServer,
)

FAKE_SERVER = Path(__file__).with_name("fake_prefect_server.py")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _fake(delay: float = 0.0):
    return lambda port: [sys.executable, str(FAKE_SERVER), str(port), str(delay)]


@pytest.fixture
def server(tmp_path: Path) -> Iterator[PrefectLocalServer]:
    local = PrefectLocalServer(state_dir=tmp_path, command=_fake(), stop_timeout=3)
    yield local
    local.stop()


def test_start_runs_a_healthy_server_on_the_preferred_port(server):
    port = _free_port()

    status = server.start(port)

    assert status.port == port
    assert status.api_url == f"http://127.0.0.1:{port}/api"
    assert is_prefect_healthy(status.api_url)
    assert json.loads(server.state_path.read_text())["pid"] == status.pid
    assert server.status() == status


def test_second_start_reuses_the_running_server(server):
    first = server.start(_free_port())

    assert server.start(_free_port()).pid == first.pid


def test_stop_ends_the_server_and_forgets_it(server):
    status = server.start(_free_port())

    assert server.stop() is True

    assert not is_prefect_healthy(status.api_url)
    assert not server.state_path.exists()
    assert server.status() is None
    assert server.stop() is False


def test_busy_preferred_port_falls_back_to_another(server):
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        taken = busy.getsockname()[1]

        status = server.start(taken)

    assert status.port != taken
    assert is_prefect_healthy(status.api_url)


def test_server_that_exits_early_reports_its_log(tmp_path):
    crash = lambda port: [
        sys.executable,
        "-c",
        "print('database is locked'); raise SystemExit(3)",
    ]
    local = PrefectLocalServer(state_dir=tmp_path, command=crash)

    with pytest.raises(LocalServerError, match="exited with code 3") as err:
        local.start(_free_port())

    assert "database is locked" in str(err.value)
    assert not local.state_path.exists()


def test_server_that_never_answers_times_out_and_is_cleaned_up(tmp_path):
    local = PrefectLocalServer(
        state_dir=tmp_path, command=_fake(delay=30), startup_timeout=1, stop_timeout=3
    )
    port = _free_port()

    with pytest.raises(LocalServerError, match="did not answer"):
        local.start(port)

    with socket.socket() as probe:
        assert probe.connect_ex(("127.0.0.1", port)) != 0
    assert not local.state_path.exists()


def test_stale_state_for_a_dead_process_is_discarded(tmp_path):
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    state = tmp_path / "prefect-server.json"
    state.write_text(
        json.dumps(
            {
                "pid": dead.pid,
                "port": 1,
                "api_url": "http://127.0.0.1:1/api",
                "started_at": "2026-01-01T00:00:00+00:00",
                "log_path": str(tmp_path / "prefect-server.log"),
            }
        )
    )

    assert PrefectLocalServer(state_dir=tmp_path).status() is None
    assert not state.exists()
