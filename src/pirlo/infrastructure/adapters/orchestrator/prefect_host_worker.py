from __future__ import annotations

import logging
import os
import socket
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx

from pirlo.core.config import (
    DEFAULT_WORK_POOL,
    DEFAULT_WORKER_LIMIT,
    get_workspace_path,
)
from pirlo.core.ports.worker_fleet import WorkerFleet, WorkerFleetError, WorkerInfo
from pirlo.infrastructure.services.detached_process import (
    DetachedProcess,
    is_alive,
    terminate_group,
)

logger = logging.getLogger(__name__)

# The worker's flow-run bootstrap calls `python3`; it must resolve to pirlo's Python.
_PIRLO_BIN = Path(sys.executable).parent


def _prefect_worker_command(pool: str, name: str, limit: int) -> list[str]:
    return [
        str(_PIRLO_BIN / "prefect"),
        "worker",
        "start",
        "--pool",
        pool,
        "--type",
        "process",
        "--name",
        name,
        "--limit",
        str(limit),
    ]


def _worker_is_online(api_url: str, pool: str, name: str) -> bool:
    from prefect.client.orchestration import get_client
    from prefect.client.schemas.objects import WorkerStatus
    from prefect.exceptions import ObjectNotFound
    from prefect.settings import (
        PREFECT_API_URL,
        PREFECT_CLIENT_MAX_RETRIES,
        temporary_settings,
    )

    with temporary_settings({PREFECT_API_URL: api_url, PREFECT_CLIENT_MAX_RETRIES: 0}):
        try:
            with get_client(
                sync_client=True, httpx_settings={"timeout": 2.0}
            ) as client:
                workers = client.read_workers_for_work_pool(pool)
        except (httpx.HTTPError, ObjectNotFound):
            return False
    return any(w.name == name and w.status == WorkerStatus.ONLINE for w in workers)


class PrefectHostWorker(WorkerFleet):
    """One `prefect worker` process on this host, polling the pirlo work pool."""

    def __init__(
        self,
        state_dir: Path | None = None,
        pool: str = DEFAULT_WORK_POOL,
        name: str | None = None,
        limit: int = DEFAULT_WORKER_LIMIT,
        command: Callable[[str, str, int], list[str]] = _prefect_worker_command,
        is_online: Callable[[str, str, str], bool] = _worker_is_online,
        startup_timeout: float = 30.0,
        stop_timeout: float = 10.0,
    ) -> None:
        state_dir = state_dir or get_workspace_path() / "serve"
        self._process = DetachedProcess(
            state_dir / "prefect-worker.json", state_dir / "prefect-worker.log"
        )
        self._pool = pool
        self._name = name or socket.gethostname()
        self._limit = limit
        self._command = command
        self._is_online = is_online
        self._startup_timeout = startup_timeout
        self._stop_timeout = stop_timeout

    @property
    def state_path(self) -> Path:
        return self._process.state_path

    def start(self, api_url: str) -> list[WorkerInfo]:
        running = self.status()
        if running:
            return running

        env = dict(os.environ)
        # pirlo quiets Prefect's console for its own CLI; the worker log should not be.
        env.pop("PREFECT_LOGGING_HANDLERS_CONSOLE_LEVEL", None)
        env["PREFECT_API_URL"] = api_url
        env["PATH"] = os.pathsep.join([str(_PIRLO_BIN), env.get("PATH", "")])
        process = self._process.spawn(
            self._command(self._pool, self._name, self._limit), env
        )

        deadline = time.monotonic() + self._startup_timeout
        while not self._is_online(api_url, self._pool, self._name):
            if process.poll() is not None:
                raise WorkerFleetError(
                    f"Prefect worker exited with code {process.returncode} before "
                    f"coming online.\n{self._process.log_tail()}"
                )
            if time.monotonic() > deadline:
                terminate_group(process.pid, self._stop_timeout)
                raise WorkerFleetError(
                    f"Prefect worker {self._name} did not come online on "
                    f"{self._pool} within {self._startup_timeout:.0f}s.\n"
                    f"{self._process.log_tail()}"
                )
            time.sleep(0.5)

        info = WorkerInfo(
            name=self._name,
            pid=process.pid,
            pool=self._pool,
            limit=self._limit,
            started_at=datetime.now(UTC).isoformat(timespec="seconds"),
            log_path=self._process.log_path,
        )
        self._process.write(
            {
                "name": info.name,
                "pid": info.pid,
                "pool": info.pool,
                "limit": info.limit,
                "started_at": info.started_at,
                "log_path": str(info.log_path),
            }
        )
        return [info]

    def status(self) -> list[WorkerInfo]:
        info = self._read()
        if info is None:
            return []
        if not is_alive(info.pid):
            self._process.forget()
            return []
        return [info]

    def stop(self) -> int:
        info = self._read()
        if info is None:
            return 0
        if is_alive(info.pid):
            terminate_group(info.pid, self._stop_timeout)
        self._process.forget()
        return 1

    def _read(self) -> WorkerInfo | None:
        data = self._process.read()
        if data is None:
            return None
        try:
            return WorkerInfo(
                name=str(data["name"]),
                pid=int(data["pid"]),
                pool=str(data["pool"]),
                limit=int(data["limit"]),
                started_at=str(data["started_at"]),
                log_path=Path(data["log_path"]),
            )
        except (ValueError, KeyError, TypeError) as exc:
            logger.warning("Ignoring unreadable %s: %s", self.state_path, exc)
            return None
