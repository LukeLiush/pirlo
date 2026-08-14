from datetime import UTC, datetime

from pydantic import BaseModel, Field


class SubtaskSpec(BaseModel):
    """Specification for an atomic, single-source subtask."""

    subtask_id: str
    target_site: str
    target_url: str
    task_prompt: str = Field(
        ...,
        description=(
            "Self-contained prompt including starting URL, query action, and target data to extract."
        ),
    )
    extraction_targets: list[str] = Field(default_factory=list)


class DecomposerPlan(BaseModel):
    """Aggregated plan aggregate root stored in Plan Cache."""

    plan_id: str = ""
    original_prompt: str = ""
    subtasks: list[SubtaskSpec]
    aggregation_prompt: str = Field(
        ...,
        description=(
            "Instructions for the Aggregator on how to synthesize the subtask results."
        ),
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
