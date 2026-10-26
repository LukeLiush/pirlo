import json
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
    host: str = "127.0.0.1"
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
