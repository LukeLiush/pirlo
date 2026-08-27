from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T", bound=type[Any])


def playbook(name: str, description: str | None = None) -> Callable[[T], T]:
    """Class decorator to register a playbook command name and description."""

    def decorator(cls: T) -> T:
        cls.playbook_name = name
        doc_desc = cls.__doc__.strip().split("\n")[0] if cls.__doc__ else None
        cls.playbook_description = description or doc_desc or ""
        return cls

    return decorator


def orchestrator(name: str, description: str | None = None) -> Callable[[T], T]:
    """Class decorator to register a TaskOrchestrator engine backend."""

    def decorator(cls: T) -> T:
        cls.orchestrator_name = name
        doc_desc = cls.__doc__.strip().split("\n")[0] if cls.__doc__ else None
        cls.orchestrator_description = description or doc_desc or ""
        return cls

    return decorator
