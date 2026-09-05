from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T", bound=type[Any])


def play(name: str, description: str | None = None) -> Callable[[T], T]:
    """Class decorator to register a playbook command name and description."""

    def decorator(cls: T) -> T:
        cls.play_name = name
        doc_desc = cls.__doc__.strip().split("\n")[0] if cls.__doc__ else None
        cls.play_description = description or doc_desc or ""
        return cls

    return decorator
