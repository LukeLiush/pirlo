from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class DetachedProcess:
    """A background process recorded in a JSON state file next to its log.

    The process gets its own session, so it outlives the pirlo command that
    started it and can be stopped as a group.
    """

    def __init__(self, state_path: Path, log_path: Path) -> None:
        self.state_path = state_path
        self.log_path = log_path

    def spawn(self, command: list[str], env: dict[str, str]) -> subprocess.Popen[bytes]:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_path, "ab") as log:
            return subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                env=env,
                start_new_session=True,
            )

    def read(self) -> dict[str, Any] | None:
        try:
            data = json.loads(self.state_path.read_text())
        except FileNotFoundError:
            return None
        except ValueError as exc:
            logger.warning("Ignoring unreadable %s: %s", self.state_path, exc)
            return None
        if not isinstance(data, dict):
            logger.warning("Ignoring unreadable %s: not an object", self.state_path)
            return None
        return data

    def write(self, data: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(data, indent=2))

    def forget(self) -> None:
        self.state_path.unlink(missing_ok=True)

    def log_tail(self, lines: int = 15) -> str:
        try:
            tail = self.log_path.read_text(errors="replace").splitlines()[-lines:]
        except FileNotFoundError:
            return f"(no log at {self.log_path})"
        return f"Last lines of {self.log_path}:\n" + "\n".join(tail)


def is_alive(pid: int) -> bool:
    try:
        # Reap it first if it is our own exited child, so it doesn't linger as a zombie.
        reaped_pid, _ = os.waitpid(pid, os.WNOHANG)
        if reaped_pid == pid:
            return False
    except ChildProcessError:
        pass
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def terminate_group(pid: int, timeout: float) -> None:
    """Sends SIGTERM to the process group, then SIGKILL if it outlives timeout."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pid, sig)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not is_alive(pid):
                return
            time.sleep(0.1)
        logger.warning("Process group %s ignored %s.", pid, sig.name)
