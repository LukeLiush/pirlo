"""The processes `pirlo serve` runs: a Prefect server on loopback and a worker gate."""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

from pirlo.core.ports.process_supervisor import ProcessSpec
from pirlo.infrastructure.adapters.orchestrator import prefect_worker_gate

LOOPBACK = "127.0.0.1"

# The worker's flow-run bootstrap calls `python3`; it must resolve to pirlo's Python.
_PIRLO_BIN = Path(sys.executable).parent


class NoFreePortError(Exception):
    """Raised when no port on 127.0.0.1 can be bound."""


def free_loopback_port(preferred_port: int) -> int:
    for port in (preferred_port, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((LOOPBACK, port))
            except OSError:
                continue
            return int(sock.getsockname()[1])
    raise NoFreePortError("No free port on 127.0.0.1.")


def server_process(port: int) -> ProcessSpec:
    env = dict(os.environ)
    # The server reads its own settings; a client URL in our env is irrelevant.
    env.pop("PREFECT_API_URL", None)
    env["PYTHONUNBUFFERED"] = "1"
    return ProcessSpec(
        name="server",
        command=[
            str(_PIRLO_BIN / "prefect"),
            "server",
            "start",
            "--host",
            LOOPBACK,
            "--port",
            str(port),
        ],
        env=env,
    )


def worker_process(api_url: str, name: str) -> ProcessSpec:
    env = dict(os.environ)
    # pirlo quiets Prefect's console for its own CLI; the worker's output should not be.
    env.pop("PREFECT_LOGGING_HANDLERS_CONSOLE_LEVEL", None)
    env["PREFECT_API_URL"] = api_url
    env["PATH"] = os.pathsep.join([str(_PIRLO_BIN), env.get("PATH", "")])
    env["PYTHONUNBUFFERED"] = "1"
    return ProcessSpec(
        name="worker",
        command=[
            sys.executable,
            "-m",
            prefect_worker_gate.__name__,
            "--api-url",
            api_url,
            "--name",
            name,
        ],
        env=env,
    )
