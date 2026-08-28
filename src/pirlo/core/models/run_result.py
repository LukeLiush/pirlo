from dataclasses import dataclass, field
from typing import Any

from pirlo.core.models.run import RunStatus


@dataclass
class RunResult[T]:
    """Structured domain result returned by Pitch.play() and on_play()."""

    run_id: str
    status: RunStatus = RunStatus.COMPLETED
    data: T | None = None
    error: str | None = None
    duration_seconds: float = 0.0
    metrics: dict[str, Any] = field(default_factory=dict)
