from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict


class RunStatus(str, Enum):
    NOT_STARTED = "not_started"
    STARTED = "started"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class RunType(str, Enum):
    REPLAY = "replay"
    LLM = "llm"


class RunCreateDTO(BaseModel):
    playbook: str
    parameters: dict[str, Any]


class PlayRunDetail(BaseModel):
    play_run_id: str  # Prefect task run UUID
    play_name: str  # Play name, e.g. "add_to_cart"
    play_id: str  # Canonical identity, e.g. "add_to_cart#v1.0:d4e5f6"
    status: RunStatus
    duration: float | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None


class Run(BaseModel):
    run_id: str  # 8-char hex run ID (e.g. "e4f1a23c")
    playbook: str  # Playbook name (e.g. "ecommerce_buyer")
    status: RunStatus
    run_name: str | None = None  # Optional deterministic identity
    run_type: RunType = RunType.LLM
    duration: float | None = None  # Duration in seconds
    parameters: dict[str, Any] = {}  # Domain parameters
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    error_message: str | None = None
    dashboard_url: str | None = None
    play_runs: list[PlayRunDetail] = []

    def get_run_dir(self, workspace: Path) -> Path:
        return workspace / self.playbook / "runs" / self.run_id

    def get_play_log_path(self, workspace: Path, play_id: str) -> Path:
        import re

        safe_name: str = re.sub(r"[#:/\\?%*|\"<>]", "_", play_id) + ".log"
        return self.get_run_dir(workspace) / "logs" / safe_name


class PreparedRun(BaseModel):
    model_config = ConfigDict(frozen=True)
    playbook_name: str
    run_name: str
    run_id: str
    workspace: Path
    parameters: dict[str, Any]

    @property
    def run_dir(self) -> Path:
        return self.workspace / self.playbook_name / "runs" / self.run_id


class LogCursor(BaseModel):
    """Metadata bookmark for incremental Prefect log synchronization."""

    last_timestamp_utc: datetime
    last_timestamp_local: str
    lines_count: int = 0
    last_log_id: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_file(cls, path: Path) -> LogCursor | None:
        """Reads and parses a .cursor file, supporting both JSON and legacy plain ISO format."""
        import contextlib
        import json

        from pydantic import ValidationError

        if not path.exists():
            return None
        content: str = path.read_text(encoding="utf-8").strip()
        if not content:
            return None
        with contextlib.suppress(
            json.JSONDecodeError, ValidationError, ValueError, TypeError
        ):
            data: Any = json.loads(content)
            if isinstance(data, dict) and "last_timestamp_utc" in data:
                return cls.model_validate(data)

        # Fallback to legacy raw ISO timestamp string
        try:
            dt: datetime = datetime.fromisoformat(content)
            local_str: str = (
                dt.astimezone().strftime("%Y-%m-%d %H:%M:%S%z")
                if dt.tzinfo is not None
                else dt.strftime("%Y-%m-%d %H:%M:%S%z")
            )
            return cls(
                last_timestamp_utc=dt,
                last_timestamp_local=local_str,
                lines_count=0,
            )
        except (ValueError, TypeError):
            return None

    def save_to_file(self, path: Path) -> None:
        """Persists cursor metadata formatted as human-readable JSON."""
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")
