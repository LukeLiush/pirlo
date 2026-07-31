from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pirlo.core.models.run import Run, RunCreateDTO, RunStatus
from pirlo.core.ports.parameter_storage import ParameterStorage
from pirlo.core.ports.run_history import RunHistoryRepository
from pirlo.core.services.run_id_generator import generate_run_id, generate_task_id


class ConsoleController:
    def __init__(
        self,
        workspace: Path,
        run_repository: RunHistoryRepository,
        parameter_storage: ParameterStorage,
    ):
        self.workspace = workspace
        self.run_repository = run_repository
        self.parameter_storage = parameter_storage

    def kickoff_run(self, dto: RunCreateDTO) -> Run:
        """Orchestrates saving the parameters and creating the run record."""
        task_id = generate_task_id(dto.playbook, dto.parameters)
        run_id = generate_run_id(task_id)

        # Save parameter file under task_id (reusable by reruns)
        param_loc = f"{dto.playbook}/logs/{task_id}_params.json"
        log_loc = f"{dto.playbook}/logs/{run_id}.log"
        now = datetime.now(UTC)

        # 1. Save parameters using the abstract storage adapter
        self.parameter_storage.save_parameters(param_loc, dto.parameters)

        # 2. Record run in database as 'not_started'
        run = Run(
            run_id=run_id,
            task_id=task_id,
            playbook=dto.playbook,
            status=RunStatus.NOT_STARTED,
            parameter_file_location=param_loc,
            log_file_location=log_loc,
            created_at=now,
            updated_at=now,
        )
        self.run_repository.save(run)
        return run

    def get_runs_history(
        self, playbook: str, page: int, per_page: int
    ) -> tuple[list[Run], int]:
        offset = page * per_page
        runs = self.run_repository.list_runs(
            playbook=playbook, limit=per_page, offset=offset
        )
        total_count = self.run_repository.count_runs(playbook=playbook)
        total_pages = max(1, (total_count + per_page - 1) // per_page)
        return runs, total_pages

    def read_run_logs(self, run: Run) -> list[str]:
        log_path = run.get_log_location(self.workspace)
        if not log_path.exists():
            return ["[ERROR] Log file not found."]
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                return f.readlines()
        except Exception as e:  # noqa: BLE001
            return [f"[ERROR] Failed to read log file: {e}"]

    def read_run_parameters(self, run: Run) -> dict[str, Any]:
        return self.parameter_storage.load_parameters(run.parameter_file_location)
