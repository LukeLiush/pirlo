from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T", bound=type[Any])


def play(
    name: str,
    version: str = "1.0",
    description: str | None = None,
    retries: int = 0,
    retry_delay: int = 0,
    timeout: int | None = None,
) -> Callable[[T], T]:
    """Class decorator to register a playbook command name, version, description, and task resilience settings."""

    def decorator(cls: T) -> T:
        cls.play_name = name
        cls.play_version = version
        doc_desc = cls.__doc__.strip().split("\n")[0] if cls.__doc__ else None
        cls.play_description = description or doc_desc or ""
        cls.play_retries = retries
        cls.play_retry_delay = retry_delay
        cls.play_timeout = timeout
        return cls

    return decorator
