from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from pirlo.core.ports.orchestrator import TaskOrchestrator

T = TypeVar("T", bound=type[Any])
O = TypeVar("O", bound=type["TaskOrchestrator"])


def play(name: str, description: str | None = None) -> Callable[[T], T]:
    """Class decorator to register a playbook command name and description."""

    def decorator(cls: T) -> T:
        cls.play_name = name
        doc_desc = cls.__doc__.strip().split("\n")[0] if cls.__doc__ else None
        cls.play_description = description or doc_desc or ""
        return cls

    return decorator


def orchestrator(
    name: str,
    description: str | None = None,
    **extra_info: Any,
) -> Callable[[O], O]:
    """Class decorator to register a TaskOrchestrator engine backend."""

    def decorator(cls: O) -> O:
        from pirlo.core.ports.orchestrator import OrchestratorInfo

        doc_desc = cls.__doc__.strip().split("\n")[0] if cls.__doc__ else None
        cls.info = OrchestratorInfo(
            name=name,
            description=description or doc_desc or "",
            extra=extra_info,
        )
        return cls

    return decorator
