from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict


class RunStatus(str, Enum):
    NOT_STARTED = "not_started"
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"


class RunType(str, Enum):
    REPLAY = "replay"
    LLM = "llm"


class RunCreateDTO(BaseModel):
    playbook: str
    parameters: dict[str, Any]


class Run(BaseModel):
    run_id: str
    run_name: str
    playbook: str
    run_type: RunType = RunType.LLM
    status: RunStatus
    parameter_file_location: str  # Workspace-relative location
    log_file_location: str  # Workspace-relative location
    created_at: datetime
    updated_at: datetime  # Becomes finished_time when status = completed
    started_at: datetime | None = None
    finished_at: datetime | None = None

    def get_log_location(self, workspace: Path) -> Path:
        """Resolves the absolute log file location path."""
        return workspace / self.log_file_location

    def get_parameter_location(self, workspace: Path) -> Path:
        """Resolves the absolute parameter file location path."""
        return workspace / self.parameter_file_location


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

    @property
    def parameter_file_path(self) -> Path:
        return self.run_dir / "params.json"

    @property
    def log_file_path(self) -> Path:
        return self.run_dir / "run.log"
