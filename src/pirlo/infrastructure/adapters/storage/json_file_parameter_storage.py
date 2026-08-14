import json
from pathlib import Path
from typing import Any

class JsonFileParameterStorage:
    def __init__(self, workspace: Path):
        self.workspace = Path(workspace)

    def save_parameters(self, location: str, parameters: dict[str, Any]) -> None:
        abs_path = self.workspace / location
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            json.dump(parameters, f, indent=4)

    def load_parameters(self, location: str) -> dict[str, Any]:
        abs_path = self.workspace / location
        if not abs_path.exists():
            return {}
        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
                return {}
        except Exception:  # noqa: BLE001
            return {}
