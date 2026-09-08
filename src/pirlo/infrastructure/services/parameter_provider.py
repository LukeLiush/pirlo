from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pirlo.core.ports.play import Play
from pirlo.infrastructure.adapters.cli.argument_parser_builder import (
    extract_signature_parameters,
)

TargetSignatureSource = type[Play] | Callable[..., Any]


def discover_parameters(
    target_cls_or_fn: TargetSignatureSource,
) -> list[dict[str, Any]]:
    """Collect parameter metadata dicts declared on a play signature."""
    if hasattr(target_cls_or_fn, "execute"):
        return extract_signature_parameters(target_cls_or_fn.execute)
    return extract_signature_parameters(target_cls_or_fn)
