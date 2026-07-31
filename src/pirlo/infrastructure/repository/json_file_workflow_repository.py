import json
from pathlib import Path

from pirlo.core.models.workflow import Workflow
from pirlo.core.repository import WorkflowRepository


class JsonFileWorkflowRepository(WorkflowRepository):
    """Concrete adapter persisting workflows to JSON files in a target directory."""

    directory: Path

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _get_path(self, workflow_id: str) -> Path:
        return self.directory / f"{workflow_id}_workflow.json"

    def exists(self, workflow_id: str) -> bool:
        return self._get_path(workflow_id).exists()

    def load(self, workflow_id: str) -> Workflow:
        path = self._get_path(workflow_id)
        if not path.exists():
            raise FileNotFoundError(f"Workflow cache file not found at: {path}")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Workflow.model_validate(data)

    def save(self, workflow: Workflow) -> None:
        path = self._get_path(workflow.workflow_id)
        with open(path, "w", encoding="utf-8") as f:
            f.write(workflow.model_dump_json(indent=2))
