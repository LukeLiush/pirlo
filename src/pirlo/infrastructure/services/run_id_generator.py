import json
import uuid
from datetime import UTC, datetime
from typing import Any

FUN_WORDS = [
    "panenka",
    "golazo",
    "rabona",
    "tiki-taka",
    "regista",
    "trequartista",
    "scudetto",
    "nutmeg",
    "clean-sheet",
    "hat-trick",
    "box-to-box",
    "counter-attack",
]


class IdentityFactory:
    def __init__(self, name: str, parameters: dict[str, Any]) -> None:
        self._fun_words: list[str] = FUN_WORDS
        self.name: str = name
        self.parameters: dict[str, Any] = parameters

    def generate_run_name(self) -> str:
        """Generates a stable, deterministic Run Name based ONLY on playbook and domain parameters."""
        payload = {
            "playbook": self.name,
            "parameters": self.parameters,
        }
        serialized = json.dumps(payload, sort_keys=True, default=str)
        deterministic_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, serialized)

        word = self._fun_words[int(deterministic_uuid) % len(self._fun_words)]
        short_id = str(deterministic_uuid)[:8]

        return f"{word}-{short_id}"

    def generate_run_id(self) -> str:
        """Generates a unique execution Run ID for a run by appending a UTC timestamp with microsecond resolution."""
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
        return f"{self.generate_run_name()}-{timestamp}"
