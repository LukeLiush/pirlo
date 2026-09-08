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
