from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from pirlo.core.ports.process_supervisor import ProcessSpec, ProcessSupervisor
from pirlo.infrastructure.adapters.cli.serve_commands import serve_main
from pirlo.infrastructure.adapters.orchestrator import prefect_worker_gate
from pirlo.infrastructure.adapters.orchestrator.serve_beacon import (
    ServeBeacon,
    ServeRecord,
)

_HEALTH = "pirlo.infrastructure.adapters.cli.serve_commands.is_prefect_healthy"
_ONLINE = "pirlo.infrastructure.adapters.cli.serve_commands.is_worker_online"


class StubSupervisor(ProcessSupervisor):
    def __init__(self, beacon: ServeBeacon, code: int = 0) -> None:
        self.beacon = beacon
        self.code = code
        self.processes: list[ProcessSpec] | None = None
        self.record_while_running: ServeRecord | None = None

    def run(self, processes: list[ProcessSpec]) -> int:
        self.processes = processes
        self.record_while_running = self.beacon.read()
        return self.code


@pytest.fixture
def beacon(tmp_path: Path) -> ServeBeacon:
    return ServeBeacon(tmp_path / "serve.json")


def _record(pid: int, port: int = 4200) -> ServeRecord:
    return ServeRecord(
        pid=pid,
        port=port,
        api_url=f"http://127.0.0.1:{port}/api",
        worker="desk",
        started_at="2026-10-26T09:00:00+00:00",
    )


def _dead_pid() -> int:
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    return process.pid


def test_serve_runs_the_server_and_worker_gate_while_recording_itself(beacon, capsys):
    supervisor = StubSupervisor(beacon)

    assert serve_main([], supervisor=supervisor, beacon=beacon) == 0

    record = supervisor.record_while_running
    assert record is not None
    assert record.pid == os.getpid()
    server, worker = supervisor.processes
    assert server.name == "server"
    assert server.command[-5:] == [
        "start",
        "--host",
        "127.0.0.1",
        "--port",
        str(record.port),
    ]
    assert worker.name == "worker"
    assert worker.command[1:3] == ["-m", prefect_worker_gate.__name__]
    assert worker.command[-4:] == ["--api-url", record.api_url, "--name", record.worker]
    assert beacon.read() is None
    out = capsys.readouterr().out
    assert f"Prefect UI:  http://127.0.0.1:{record.port}" in out
    assert f"ssh -L {record.port}:127.0.0.1:{record.port} " in out
    assert "pirlo serve --stop" in out


def test_serve_returns_the_supervisors_exit_code(beacon):
    assert (
        serve_main([], supervisor=StubSupervisor(beacon, code=130), beacon=beacon)
        == 130
    )


def test_serve_forgets_itself_when_the_supervisor_is_interrupted(beacon):
    class Interrupted(StubSupervisor):
        def run(self, processes: list[ProcessSpec]) -> int:
            assert self.beacon.read() is not None
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        serve_main([], supervisor=Interrupted(beacon), beacon=beacon)

    assert beacon.read() is None


def test_serve_does_not_start_a_second_one(beacon, capsys):
    beacon.write(_record(os.getpid()))
    supervisor = StubSupervisor(beacon)

    assert serve_main([], supervisor=supervisor, beacon=beacon) == 0

    assert supervisor.processes is None
    assert "already running" in capsys.readouterr().out


def test_serve_replaces_a_record_left_by_a_dead_serve(beacon):
    beacon.write(_record(_dead_pid()))
    supervisor = StubSupervisor(beacon)

    assert serve_main([], supervisor=supervisor, beacon=beacon) == 0

    assert supervisor.record_while_running.pid == os.getpid()


def test_status_of_a_running_serve(beacon, capsys):
    beacon.write(_record(os.getpid()))

    with patch(_HEALTH, return_value=True), patch(_ONLINE, return_value=True) as online:
        assert serve_main(["--status"], beacon=beacon) == 0

    online.assert_called_once_with("http://127.0.0.1:4200/api", "pirlo-pool", "desk")
    out = capsys.readouterr().out
    assert "Prefect UI:  http://127.0.0.1:4200" in out
    assert f"pirlo serve: pid {os.getpid()}" in out
    assert "Server:      answering" in out
    assert "Worker:      desk on pirlo-pool, online" in out


def test_status_while_the_server_is_still_starting(beacon, capsys):
    beacon.write(_record(os.getpid()))

    with patch(_HEALTH, return_value=False), patch(_ONLINE) as online:
        assert serve_main(["--status"], beacon=beacon) == 0

    online.assert_not_called()
    out = capsys.readouterr().out
    assert "Server:      not answering yet" in out
    assert "not online yet" in out


@pytest.mark.parametrize("recorded", [False, True])
def test_status_when_not_running_forgets_a_stale_record(beacon, capsys, recorded):
    if recorded:
        beacon.write(_record(_dead_pid()))

    assert serve_main(["--status"], beacon=beacon) == 1

    assert not beacon.path.exists()
    assert "pirlo serve isn't running." in capsys.readouterr().out


def test_stop_sends_sigterm_to_pirlo_serve_and_waits_for_it(beacon, capsys):
    serve = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    # Reap it as soon as it exits, as its own parent shell would.
    threading.Thread(target=serve.wait, daemon=True).start()
    beacon.write(_record(serve.pid))

    try:
        with patch(_HEALTH, return_value=True):
            assert serve_main(["--stop"], beacon=beacon, stop_timeout=10) == 0
    finally:
        if serve.poll() is None:
            serve.kill()

    assert serve.wait(timeout=5) == -15
    assert "Stopped pirlo serve" in capsys.readouterr().out


def test_stop_leaves_a_pid_alone_when_no_server_answers(beacon, capsys):
    beacon.write(_record(os.getpid()))

    with patch(_HEALTH, return_value=False):
        assert serve_main(["--stop"], beacon=beacon) == 1

    assert beacon.read() is not None
    assert "not stopping it" in capsys.readouterr().err


def test_stop_when_nothing_runs(beacon, capsys):
    assert serve_main(["--stop"], beacon=beacon) == 0
    assert "pirlo serve isn't running." in capsys.readouterr().out


def test_entrypoint_routes_serve_to_the_built_in(monkeypatch):
    from pirlo.infrastructure.adapters.cli.entrypoint import main

    monkeypatch.setattr(sys, "argv", ["pirlo", "serve", "--status"])
    with (
        patch(
            "pirlo.infrastructure.adapters.cli.serve_commands.serve_main",
            return_value=0,
        ) as serve,
        pytest.raises(SystemExit) as exit_info,
    ):
        main()

    serve.assert_called_once_with()
    assert exit_info.value.code == 0
