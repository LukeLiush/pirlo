from __future__ import annotations

import socket
import sys
from pathlib import Path

from pirlo.infrastructure.adapters.orchestrator import prefect_worker_gate
from pirlo.infrastructure.adapters.orchestrator.prefect_serve import (
    free_loopback_port,
    server_process,
    worker_process,
)

PIRLO_BIN = str(Path(sys.executable).parent)


def test_busy_preferred_port_falls_back_to_another():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        taken = busy.getsockname()[1]

        port = free_loopback_port(taken)

    assert port != taken
    assert port > 0


def test_server_listens_on_loopback_without_a_client_url(monkeypatch):
    monkeypatch.setenv("PREFECT_API_URL", "http://elsewhere:4200/api")

    spec = server_process(4321)

    assert spec.command == [
        f"{PIRLO_BIN}/prefect",
        "server",
        "start",
        "--host",
        "127.0.0.1",
        "--port",
        "4321",
    ]
    assert "PREFECT_API_URL" not in spec.env
    assert spec.env["PYTHONUNBUFFERED"] == "1"


def test_worker_gate_gets_the_server_url_pirlos_python_and_a_loud_console(
    monkeypatch,
):
    monkeypatch.setenv("PREFECT_LOGGING_HANDLERS_CONSOLE_LEVEL", "ERROR")
    api_url = "http://127.0.0.1:4321/api"

    spec = worker_process(api_url, "desk")

    assert spec.command == [
        sys.executable,
        "-m",
        prefect_worker_gate.__name__,
        "--api-url",
        api_url,
        "--name",
        "desk",
    ]
    assert spec.env["PREFECT_API_URL"] == api_url
    assert spec.env["PATH"].split(":")[0] == PIRLO_BIN
    assert "PREFECT_LOGGING_HANDLERS_CONSOLE_LEVEL" not in spec.env
