import json
import os
import socket
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pirlo.core.config import (
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_OLLAMA_PORT,
    DEFAULT_PREFECT_PORT,
)


@dataclass
class ServeManifest:
    """Server runtime metadata written by pirlo serve."""

    default_prefect_port: int = DEFAULT_PREFECT_PORT
    default_ollama_port: int = DEFAULT_OLLAMA_PORT
    default_model: str = DEFAULT_OLLAMA_MODEL
    models: list[str] = field(default_factory=lambda: [DEFAULT_OLLAMA_MODEL])
    host: str = "0.0.0.0"
    started_at: str = ""
    status: str = "running"

    def save(self, filepath: Path) -> None:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls, filepath: Path) -> "ServeManifest":
        if not filepath.exists():
            return cls()
        data: dict = json.loads(filepath.read_text())
        return cls(**data)


@dataclass
class ActiveSession:
    """Client connection state written by pirlo connect."""

    remote_host: str
    local_prefect_port: int
    local_ollama_port: int
    remote_prefect_port: int
    remote_ollama_port: int
    cli_pid: int | None = None

    def is_same_host(self, target_host: str) -> bool:
        """Encapsulates host string comparison logic."""
        return self.remote_host.strip().lower() == target_host.strip().lower()

    def is_alive(self) -> bool:
        """2-Tier validation: Checks local OS PID existence & local socket ping."""
        if self.cli_pid is not None:
            try:
                os.kill(self.cli_pid, 0)
            except OSError:
                return False

        try:
            with socket.create_connection(
                ("127.0.0.1", self.local_prefect_port), timeout=0.1
            ):
                return True
        except (OSError, TimeoutError):
            return False

    @property
    def prefect_api_url(self) -> str:
        return f"http://127.0.0.1:{self.local_prefect_port}/api"

    @property
    def ollama_base_url(self) -> str:
        return f"http://127.0.0.1:{self.local_ollama_port}"

    def save(self, filepath: Path) -> None:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load_active(cls, filepath: Path) -> "ActiveSession | None":
        if not filepath.exists():
            return None
        try:
            data: dict = json.loads(filepath.read_text())
            session = cls(**data)
            if not session.is_alive():
                return None
            return session
        except Exception:  # noqa: BLE001
            return None
