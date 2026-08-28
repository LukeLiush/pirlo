import json
from pathlib import Path

from pirlo.core.models.plan import DecomposerPlan
from pirlo.core.repository.plan_repository import PlanRepository


class JsonFilePlanRepository(PlanRepository):
    """Concrete adapter persisting Decomposer Plans to JSON files in a target directory."""

    directory: Path

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _get_path(self, plan_id: str) -> Path:
        return self.directory / f"{plan_id}_plan.json"

    def exists(self, plan_id: str) -> bool:
        path = self._get_path(plan_id)
        return path.exists() and path.stat().st_size > 0

    def load(self, plan_id: str) -> DecomposerPlan:
        path = self._get_path(plan_id)
        if not self.exists(plan_id):
            raise FileNotFoundError(f"Plan cache file not found or empty at: {path}")
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return DecomposerPlan.model_validate(data)
        except Exception as e:
            path.unlink(missing_ok=True)
            raise FileNotFoundError(f"Plan cache file corrupted at {path}: {e}") from e

    def save(self, plan: DecomposerPlan) -> None:
        path = self._get_path(plan.plan_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(plan.model_dump_json(indent=2))
