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


def generate_task_id(playbook: str, parameters: dict[str, Any]) -> str:
    """Generates a stable, deterministic Task ID based ONLY on playbook and parameters."""
    payload = {
        "playbook": playbook,
        "parameters": parameters,
    }
    serialized = json.dumps(payload, sort_keys=True)
    deterministic_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, serialized)

    word = FUN_WORDS[int(deterministic_uuid) % len(FUN_WORDS)]
    short_id = str(deterministic_uuid)[:8]

    return f"{word}-{short_id}"


def generate_run_id(task_id: str) -> str:
    """Generates a unique execution Run ID for a task by appending a UTC timestamp with microsecond resolution."""
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
    return f"{task_id}-{timestamp}"
