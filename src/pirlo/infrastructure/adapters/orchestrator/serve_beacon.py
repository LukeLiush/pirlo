from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from pirlo.core.config import get_workspace_path
from pirlo.infrastructure.adapters.orchestrator.prefect_health import (
    is_prefect_healthy,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ServeRecord:
    """What a running `pirlo serve` tells other pirlo commands about itself."""

    pid: int  # the pirlo serve process; stopping it stops the server and worker
    port: int
    api_url: str
    worker: str
    started_at: str


def is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class ServeBeacon:
    """The record `pirlo serve` keeps in the workspace while it runs.

    honcho owns the processes; this file only lets runs, `--status` and
    `--stop` find the server. A leftover file is harmless: readers check that
    the process is alive and the server answers.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or get_workspace_path() / "serve" / "serve.json"

    def write(self, record: ServeRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(asdict(record), indent=2))

    def read(self) -> ServeRecord | None:
        try:
            data = json.loads(self.path.read_text())
            return ServeRecord(
                pid=int(data["pid"]),
                port=int(data["port"]),
                api_url=str(data["api_url"]),
                worker=str(data["worker"]),
                started_at=str(data["started_at"]),
            )
        except FileNotFoundError:
            return None
        except (ValueError, KeyError, TypeError) as exc:
            logger.warning("Ignoring unreadable %s: %s", self.path, exc)
            return None

    def forget(self) -> None:
        self.path.unlink(missing_ok=True)

    def running(self) -> ServeRecord | None:
        """The record, if its pirlo serve is alive and its server answers."""
        record = self.read()
        if record and is_alive(record.pid) and is_prefect_healthy(record.api_url):
            return record
        return None
