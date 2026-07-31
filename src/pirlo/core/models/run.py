from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class RunStatus(str, Enum):
    NOT_STARTED = "not_started"
    STARTED = "started"
    COMPLETED = "completed"


class RunCreateDTO(BaseModel):
    playbook: str
    parameters: dict[str, Any]


class Run(BaseModel):
    run_id: str
    task_id: str
    playbook: str
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
