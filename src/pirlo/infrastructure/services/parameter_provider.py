from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pirlo.core.ports.play import Play
from pirlo.infrastructure.adapters.cli.argument_parser_builder import (
    ArgumentParserBuilder,
)

TargetSignatureSource = type[Play] | Callable[..., Any]


def discover_parameters(
    target_cls_or_fn: TargetSignatureSource,
) -> list[dict[str, Any]]:
    """Collect parameter metadata for a play, including those bubbled up from its upstream plays.

    Uses the same list the CLI parser is built from, so every flag shown in
    --help is also resolved for the run.
    """
    return ArgumentParserBuilder(target_cls_or_fn).parameters
