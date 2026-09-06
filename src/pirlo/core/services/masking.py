# src/pirlo/core/services/masking.py
from __future__ import annotations

from typing import Any

SENSITIVE_KEY_PATTERNS: tuple[str, ...] = (
    "password",
    "secret",
    "token",
    "api_key",
    "credential",
    "auth",
    "private_key",
)


def is_sensitive_key(key: str) -> bool:
    """Checks if a parameter name matches common sensitive keyword patterns."""
    lower = key.lower()
    return any(pattern in lower for pattern in SENSITIVE_KEY_PATTERNS)


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
        elif isinstance(v, dict):
            masked[k] = mask_sensitive_data(v, sensitive_keys, mask_value)
        else:
            masked[k] = v
    return masked
