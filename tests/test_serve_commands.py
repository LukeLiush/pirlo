from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from pirlo.core.ports.local_server import (
    LocalServer,
    LocalServerError,
    LocalServerStatus,
)
from pirlo.core.ports.worker_fleet import WorkerFleet, WorkerFleetError, WorkerInfo
from pirlo.infrastructure.adapters.cli.serve_commands import serve_main

_ENSURE_POOL = "pirlo.infrastructure.adapters.cli.serve_commands.ensure_work_pool"
_LATE_RUNS = "pirlo.infrastructure.adapters.cli.serve_commands.count_late_runs"


def _status(port: int = 4200) -> LocalServerStatus:
    return LocalServerStatus(
        pid=4321,
        port=port,
        api_url=f"http://127.0.0.1:{port}/api",
        started_at="2026-10-25T21:00:00+00:00",
        log_path=Path("/tmp/prefect-server.log"),
    )


class StubServer(LocalServer):
    def __init__(
        self,
        running: LocalServerStatus | None = None,
        fail: str = "",
        calls: list[str] | None = None,
    ) -> None:
        self.running = running
        self.fail = fail
        self.started_with: int | None = None
        self.calls = calls if calls is not None else []

    def start(self, preferred_port: int) -> LocalServerStatus:
        if self.fail:
            raise LocalServerError(self.fail)
        self.started_with = preferred_port
        self.running = self.running or _status(preferred_port)
        return self.running

    def status(self) -> LocalServerStatus | None:
        return self.running

    def stop(self) -> bool:
        self.calls.append("server.stop")
        was_running, self.running = self.running is not None, None
        return was_running


def _worker() -> WorkerInfo:
    return WorkerInfo(
        name="desk",
        pid=5123,
        pool="pirlo-pool",
        limit=10,
        started_at="2026-10-25T21:00:00+00:00",
        log_path=Path("/tmp/prefect-worker.log"),
    )


class StubFleet(WorkerFleet):
    def __init__(
        self,
        running: bool = False,
        fail: str = "",
        calls: list[str] | None = None,
    ) -> None:
        self.running = [_worker()] if running else []
        self.fail = fail
        self.started_against: str | None = None
        self.calls = calls if calls is not None else []

    def start(self, api_url: str) -> list[WorkerInfo]:
        if self.fail:
            raise WorkerFleetError(self.fail)
        self.started_against = api_url
        self.running = self.running or [_worker()]
        return self.running

    def status(self) -> list[WorkerInfo]:
        return self.running

    def stop(self) -> int:
        self.calls.append("fleet.stop")
        count, self.running = len(self.running), []
        return count


def test_serve_starts_the_server_its_work_pool_and_a_worker(capsys):
    server, fleet = StubServer(), StubFleet()

    with (
        patch(_ENSURE_POOL, return_value=True) as ensure_pool,
        patch(_LATE_RUNS, return_value=0),
    ):
        assert serve_main([], server=server, fleet=fleet) == 0

    assert server.started_with == 4200
    ensure_pool.assert_called_once_with("http://127.0.0.1:4200/api")
    assert fleet.started_against == "http://127.0.0.1:4200/api"
    out = capsys.readouterr().out
    assert "Prefect server started." in out
    assert "Prefect UI:  http://127.0.0.1:4200" in out
    assert "pirlo-pool (created)" in out
    assert "Worker:      desk on pirlo-pool, up to 10 runs at once (pid 5123)" in out
    assert "Note:" not in out
    assert "ssh -L 4200:127.0.0.1:4200 " in out


def test_serve_reuses_a_running_server_and_worker(capsys):
    server, fleet = StubServer(running=_status(4201)), StubFleet(running=True)

    with patch(_ENSURE_POOL) as ensure_pool, patch(_LATE_RUNS) as late_runs:
        assert serve_main([], server=server, fleet=fleet) == 0

    assert server.started_with is None
    ensure_pool.assert_not_called()
    late_runs.assert_not_called()
    out = capsys.readouterr().out
    assert "Prefect server is running." in out
    assert "http://127.0.0.1:4201" in out
    assert "Worker:      desk" in out


def test_serve_starts_a_missing_worker_next_to_a_running_server():
    server, fleet = StubServer(running=_status()), StubFleet()

    with patch(_ENSURE_POOL, return_value=False), patch(_LATE_RUNS, return_value=0):
        assert serve_main([], server=server, fleet=fleet) == 0

    assert server.started_with is None
    assert fleet.started_against == "http://127.0.0.1:4200/api"


def test_serve_warns_about_late_runs_before_starting_the_worker(capsys):
    with patch(_ENSURE_POOL, return_value=False), patch(_LATE_RUNS, return_value=3):
        assert serve_main([], server=StubServer(), fleet=StubFleet()) == 0

    assert "3 late runs are waiting on pirlo-pool" in capsys.readouterr().out


def test_serve_reports_a_failed_start(capsys):
    server, fleet = StubServer(fail="Prefect server exited with code 3"), StubFleet()

    with patch(_ENSURE_POOL) as ensure_pool:
        assert serve_main([], server=server, fleet=fleet) == 1

    ensure_pool.assert_not_called()
    assert fleet.started_against is None
    assert "exited with code 3" in capsys.readouterr().err


def test_failed_worker_leaves_the_server_running(capsys):
    server = StubServer()
    fleet = StubFleet(fail="Prefect worker exited with code 2")

    with patch(_ENSURE_POOL, return_value=True), patch(_LATE_RUNS, return_value=0):
        assert serve_main([], server=server, fleet=fleet) == 1

    assert server.running is not None
    captured = capsys.readouterr()
    assert "exited with code 2" in captured.err
    assert "The server is still running" in captured.out


@pytest.mark.parametrize(("running", "code"), [(_status(), 0), (None, 1)])
def test_serve_status(capsys, running, code):
    server = StubServer(running=running)
    fleet = StubFleet(running=running is not None)

    assert serve_main(["--status"], server=server, fleet=fleet) == code

    out = capsys.readouterr().out
    if running:
        assert "PID:         4321" in out
        assert "Worker:      desk on pirlo-pool" in out
    else:
        assert "No Prefect server" in out


def test_serve_stop_stops_the_worker_before_the_server(capsys):
    calls: list[str] = []
    server = StubServer(running=_status(), calls=calls)
    fleet = StubFleet(running=True, calls=calls)

    assert serve_main(["--stop"], server=server, fleet=fleet) == 0
    assert serve_main(["--stop"], server=server, fleet=fleet) == 0

    assert calls[:2] == ["fleet.stop", "server.stop"]
    out = capsys.readouterr().out
    assert "Stopped the Prefect worker." in out
    assert "Stopped the Prefect server." in out
    assert "No Prefect server started by pirlo serve is running." in out


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
