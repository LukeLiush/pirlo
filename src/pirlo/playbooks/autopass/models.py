from dataclasses import dataclass, field


@dataclass
class AutopassRunOutput:
    """Strongly-typed payload data returned by AutopassSession."""

    task_prompt: str | None
    final_message: str
    actions_count: int = 0
    output_files: list[str] = field(default_factory=list)
