import contextlib
import json
from pathlib import Path
from typing import Any

from pirlo.core.models.orchestrator import OrchestratorLink
from pirlo.core.ports.orchestrator_repository import OrchestratorRepository


class JsonOrchestratorRepository(OrchestratorRepository):
    """JSON file-based storage adapter for OrchestratorLink instances."""

    def __init__(self, filepath: Path) -> None:
        self.filepath: Path = Path(filepath)

    def _load_data(self) -> dict[str, Any]:
        if not self.filepath.exists():
            return {}
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:  # noqa: BLE001
            return {}

    def _save_data(self, data: dict[str, Any]) -> None:
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        temp_file = self.filepath.with_suffix(".tmp")
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        temp_file.replace(self.filepath)

    def save(self, link: OrchestratorLink) -> None:
        data = self._load_data()
        data[link.name] = link.to_dict()
        self._save_data(data)

    def get_by_name(self, name: str) -> OrchestratorLink | None:
        data = self._load_data()
        if name in data and isinstance(data[name], dict):
            return OrchestratorLink.from_dict(name, data[name])
        return None

    def delete(self, name: str) -> bool:
        data = self._load_data()
        if name in data:
            del data[name]
            self._save_data(data)
            return True
        return False

    def list_all(self) -> list[OrchestratorLink]:
        data = self._load_data()
        links: list[OrchestratorLink] = []
        for name, details in data.items():
            if isinstance(details, dict):
                with contextlib.suppress(Exception):
                    links.append(OrchestratorLink.from_dict(name, details))
        return links
