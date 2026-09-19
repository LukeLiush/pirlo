from collections.abc import Callable
from typing import Any, TypeVar, get_args

from pirlo.core.models.orchestrator import OrchestratorLink

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


PluginT = TypeVar("PluginT")


def orchestrator(
    name: str,
    description: str | None = None,
) -> Callable[[type[PluginT]], type[PluginT]]:
    """Decorator marking an OrchestratorPlugin with engine metadata."""

    def decorator(cls: type[PluginT]) -> type[PluginT]:
        engine_str = name.lower().strip()
        cls.engine_name = engine_str  # type: ignore[attr-defined]
        if description:
            cls.__doc__ = description

        # If generic OrchestratorPlugin[TLink], set the link's default engine
        for base in getattr(cls, "__orig_bases__", ()):
            args = get_args(base)
            if (
                args
                and isinstance(args[0], type)
                and issubclass(args[0], OrchestratorLink)
            ):
                args[0].model_fields["engine"].default = engine_str
                args[0].model_rebuild(force=True)
                break

        return cls

    return decorator
