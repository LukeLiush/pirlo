import json
from pathlib import Path
from typing import Optional

from pirlo.core.models.link import LlmLink, deserialize_link
from pirlo.core.ports.link_repository import LinkRepository


class JsonLinkRepository(LinkRepository):
    def __init__(self, filepath: Path):
        self.filepath = Path(filepath)

    def _load_data(self) -> dict:
        if not self.filepath.exists():
            return {}
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_data(self, data: dict) -> None:
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)

    def save(self, link: LlmLink) -> None:
        data = self._load_data()
        data[link.name] = link.to_dict()
        self._save_data(data)

    def get_by_name(self, name: str) -> Optional[LlmLink]:
        data = self._load_data()
        if name in data:
            return deserialize_link(name, data[name])
        return None

    def delete(self, name: str) -> bool:
        data = self._load_data()
        if name in data:
            del data[name]
            self._save_data(data)
            return True
        return False

    def list_all(self) -> list[LlmLink]:
        data = self._load_data()
        return [
            deserialize_link(name, details)
            for name, details in data.items()
            if isinstance(details, dict)
        ]
