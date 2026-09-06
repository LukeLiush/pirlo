import json
import uuid
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


from pirlo.core.logging_context import generate_short_run_id


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
        """Generates an 8-character hex UUID for unique execution identity."""
        return generate_short_run_id(8)
