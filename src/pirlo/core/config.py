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


def is_server_disabled() -> bool:
    """True when PIRLO_SERVER=off or a CI run forces temporary Prefect servers."""
    if os.environ.get("PIRLO_SERVER", "auto").strip().lower() == "off":
        return True
    return os.environ.get("CI", "").strip().lower() not in ("", "0", "false")


DEFAULT_PREFECT_PORT: int = 4200
DEFAULT_WORK_POOL: str = "pirlo-pool"

DEFAULT_LOG_LEVEL: str = "INFO"


def get_log_level() -> int:
    """Resolves Pirlo log level from PIRLO_LOG_LEVEL env var or defaults to INFO."""
    import logging

    level_str = os.environ.get("PIRLO_LOG_LEVEL", DEFAULT_LOG_LEVEL).upper()
    return getattr(logging, level_str, logging.INFO)
