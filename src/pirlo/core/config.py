import os
from pathlib import Path


def get_workspace_path() -> Path:
    """
    Centralized single source of truth for Pirlo workspace directory.
    Resolves PIRLO_WORKSPACE environment variable or defaults to ~/.pirlo-pitch.
    """
    env_path = os.environ.get("PIRLO_WORKSPACE", "~/.pirlo-pitch")
    path = Path(env_path).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


DEFAULT_PREFECT_PORT: int = 4200
DEFAULT_OLLAMA_PORT: int = 11434
DEFAULT_OLLAMA_MODEL: str = "qwen2.5:3b"
DEFAULT_WORK_POOL: str = "pirlo-pool"


SERVE_MANIFEST_FILENAME: str = "serve.json"
ACTIVE_SESSION_FILENAME: str = "session.json"
