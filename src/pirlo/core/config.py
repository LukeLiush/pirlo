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
