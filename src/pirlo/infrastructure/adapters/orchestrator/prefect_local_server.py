from __future__ import annotations

import logging
import os
import socket
import sys
import time
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from pirlo.core.config import get_workspace_path
from pirlo.core.ports.local_server import (
    LocalServer,
    LocalServerError,
    LocalServerStatus,
)
from pirlo.infrastructure.adapters.orchestrator.prefect_health import (
    is_prefect_healthy,
)
from pirlo.infrastructure.services.detached_process import (
    DetachedProcess,
    is_alive,
    terminate_group,
)

logger = logging.getLogger(__name__)

LOOPBACK = "127.0.0.1"


def _prefect_server_command(port: int) -> list[str]:
    prefect_bin = Path(sys.executable).with_name("prefect")
    return [
        str(prefect_bin),
        "server",
        "start",
        "--host",
        LOOPBACK,
        "--port",
        str(port),
    ]


class PrefectLocalServer(LocalServer):
    """Runs `prefect server start` on loopback as a detached host process.

    The PID, port and URL are recorded in a state file so later pirlo commands
    can find the server, and `stop()` can end it.
    """

    def __init__(
        self,
        state_dir: Path | None = None,
        command: Callable[[int], list[str]] = _prefect_server_command,
        startup_timeout: float = 20.0,
        stop_timeout: float = 10.0,
    ) -> None:
        state_dir = state_dir or get_workspace_path() / "serve"
        self._process = DetachedProcess(
            state_dir / "prefect-server.json", state_dir / "prefect-server.log"
        )
        self._command = command
        self._startup_timeout = startup_timeout
        self._stop_timeout = stop_timeout

    @property
    def state_path(self) -> Path:
        return self._process.state_path

    @property
    def log_path(self) -> Path:
        return self._process.log_path

    def start(self, preferred_port: int) -> LocalServerStatus:
        running = self.status()
        if running:
            return running
        recorded = self._read_state()
        if recorded and is_alive(recorded.pid):
            raise LocalServerError(
                f"A Prefect server (pid {recorded.pid}) is running but not answering "
                f"at {recorded.api_url}; stop it with 'pirlo serve --stop'."
            )

        port = _free_loopback_port(preferred_port)
        api_url = f"http://{LOOPBACK}:{port}/api"
        # The server reads its own settings; a client URL in our env is irrelevant.
        env = {k: v for k, v in os.environ.items() if k != "PREFECT_API_URL"}
        process = self._process.spawn(self._command(port), env)

        deadline = time.monotonic() + self._startup_timeout
        while not is_prefect_healthy(api_url):
            if process.poll() is not None:
                raise LocalServerError(
                    f"Prefect server exited with code {process.returncode} before "
                    f"answering.\n{self._process.log_tail()}"
                )
            if time.monotonic() > deadline:
                terminate_group(process.pid, self._stop_timeout)
                raise LocalServerError(
                    f"Prefect server did not answer at {api_url} within "
                    f"{self._startup_timeout:.0f}s.\n{self._process.log_tail()}"
                )
            time.sleep(0.25)

        status = LocalServerStatus(
            pid=process.pid,
            port=port,
            api_url=api_url,
            started_at=datetime.now(UTC).isoformat(timespec="seconds"),
            log_path=self.log_path,
        )
        self._write_state(status)
        return status

    def status(self) -> LocalServerStatus | None:
        recorded = self._read_state()
        if recorded is None:
            return None
        if not is_alive(recorded.pid):
            self._process.forget()
            return None
        return recorded if is_prefect_healthy(recorded.api_url) else None

    def stop(self) -> bool:
        recorded = self._read_state()
        if recorded is None:
            return False
        if is_alive(recorded.pid):
            terminate_group(recorded.pid, self._stop_timeout)
        self._process.forget()
        return True

    def _read_state(self) -> LocalServerStatus | None:
        data = self._process.read()
        if data is None:
            return None
        try:
            return LocalServerStatus(
                pid=int(data["pid"]),
                port=int(data["port"]),
                api_url=str(data["api_url"]),
                started_at=str(data["started_at"]),
                log_path=Path(data["log_path"]),
            )
        except (ValueError, KeyError, TypeError) as exc:
            logger.warning("Ignoring unreadable %s: %s", self.state_path, exc)
            return None

    def _write_state(self, status: LocalServerStatus) -> None:
        data = asdict(status)
        data["log_path"] = str(status.log_path)
        self._process.write(data)


def _free_loopback_port(preferred_port: int) -> int:
    for port in (preferred_port, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((LOOPBACK, port))
            except OSError:
                continue
            return int(sock.getsockname()[1])
    raise LocalServerError("No free port on 127.0.0.1.")
