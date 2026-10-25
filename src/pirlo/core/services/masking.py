# src/pirlo/core/services/masking.py
from __future__ import annotations

import dataclasses
import logging
from typing import Annotated, Any, get_args, get_origin, get_type_hints

from pirlo.core.models.parameters import Parameter

logger = logging.getLogger(__name__)

SENSITIVE_KEY_PATTERNS: tuple[str, ...] = (
    "password",
    "secret",
    "token",
    "api_key",
    "credential",
    "auth",
    "private_key",
)


def sensitive_parameter_names(play_cls: type[Any]) -> frozenset[str]:
    """Names of a play's execute() parameters declared with Parameter(sensitive=True)."""
    execute = getattr(play_cls, "execute", None)
    if execute is None:
        return frozenset()
    try:
        hints = get_type_hints(execute, include_extras=True)
    except (NameError, TypeError) as exc:
        logger.warning(
            "Cannot read %s.execute annotations; its sensitive=True parameters "
            "will not be masked: %s",
            play_cls.__name__,
            exc,
        )
        return frozenset()
    return frozenset(
        name
        for name, hint in hints.items()
        if get_origin(hint) is Annotated
        and any(
            isinstance(meta, Parameter) and meta.sensitive
            for meta in get_args(hint)[1:]
        )
    )


def is_sensitive_key(key: str) -> bool:
    """Checks if a parameter name matches common sensitive keyword patterns."""
    lower = key.lower()
    return any(pattern in lower for pattern in SENSITIVE_KEY_PATTERNS)


def _mask_value(
    v: Any,
    sensitive_keys: set[str] | None,
    mask_value: str,
) -> Any:
    """Mask a single value, recursing into dicts, dataclasses, and sequences."""
    if isinstance(v, dict):
        return mask_sensitive_data(v, sensitive_keys, mask_value)
    if dataclasses.is_dataclass(v) and not isinstance(v, type):
        return mask_sensitive_data(dataclasses.asdict(v), sensitive_keys, mask_value)
    if isinstance(v, (list, tuple)):
        return [_mask_value(item, sensitive_keys, mask_value) for item in v]
    return v


def mask_sensitive_data(
    data: dict[str, Any],
    sensitive_keys: set[str] | None = None,
    mask_value: str = "***",
) -> dict[str, Any]:
    """Recursively redacts sensitive values in a dictionary."""
    masked: dict[str, Any] = {}
    extra_keys = sensitive_keys or set()
    for k, v in data.items():
        if k in extra_keys or is_sensitive_key(k):
            masked[k] = mask_value
        else:
            masked[k] = _mask_value(v, sensitive_keys, mask_value)
    return masked
