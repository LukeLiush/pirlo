from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

PageT = TypeVar("PageT")


@dataclass(frozen=True)
class ExecutionContext(Generic[PageT]):  # noqa: UP046
    """Encapsulates runtime environment, parameters, and page references for workflow execution."""

    page: PageT | None = None
    cache_key: str | None = None
    run_id: str | None = None
    play_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


DEFAULT_CONTEXT: ExecutionContext[Any] = ExecutionContext()
