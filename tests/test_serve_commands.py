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
from pirlo.infrastructure.adapters.cli.serve_commands import serve_main

_ENSURE_POOL = "pirlo.infrastructure.adapters.cli.serve_commands.ensure_work_pool"


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
        self, running: LocalServerStatus | None = None, fail: str = ""
    ) -> None:
        self.running = running
        self.fail = fail
        self.started_with: int | None = None

    def start(self, preferred_port: int) -> LocalServerStatus:
        if self.fail:
            raise LocalServerError(self.fail)
        self.started_with = preferred_port
        self.running = self.running or _status(preferred_port)
        return self.running

    def status(self) -> LocalServerStatus | None:
        return self.running

    def stop(self) -> bool:
        was_running, self.running = self.running is not None, None
        return was_running


def test_serve_starts_the_server_and_its_work_pool(capsys):
    server = StubServer()

    with patch(_ENSURE_POOL, return_value=True) as ensure_pool:
        assert serve_main([], server=server) == 0

    assert server.started_with == 4200
    ensure_pool.assert_called_once_with("http://127.0.0.1:4200/api")
    out = capsys.readouterr().out
    assert "Prefect server started." in out
    assert "Prefect UI:  http://127.0.0.1:4200" in out
    assert "pirlo-pool (created" in out
    assert "ssh -L 4200:127.0.0.1:4200 " in out


def test_serve_reuses_a_running_server(capsys):
    server = StubServer(running=_status(4201))

    with patch(_ENSURE_POOL, return_value=False):
        assert serve_main([], server=server) == 0

    assert server.started_with is None
    out = capsys.readouterr().out
    assert "Prefect server is running." in out
    assert "http://127.0.0.1:4201" in out


def test_serve_reports_a_failed_start(capsys):
    server = StubServer(fail="Prefect server exited with code 3")

    with patch(_ENSURE_POOL) as ensure_pool:
        assert serve_main([], server=server) == 1

    ensure_pool.assert_not_called()
    assert "exited with code 3" in capsys.readouterr().err


@pytest.mark.parametrize(("running", "code"), [(_status(), 0), (None, 1)])
def test_serve_status(capsys, running, code):
    assert serve_main(["--status"], server=StubServer(running=running)) == code

    out = capsys.readouterr().out
    if running:
        assert "PID:         4321" in out
    else:
        assert "No Prefect server" in out


def test_serve_stop(capsys):
    server = StubServer(running=_status())

    assert serve_main(["--stop"], server=server) == 0
    assert serve_main(["--stop"], server=server) == 0

    out = capsys.readouterr().out
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
