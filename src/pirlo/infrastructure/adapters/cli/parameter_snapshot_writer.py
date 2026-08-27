"""Snapshot resolved parameter values to disk."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from pirlo.infrastructure.services.parameter_provider import ParameterProvider


class ParameterSnapshotWriter:
    """Writes a resolved-parameter snapshot to disk (best effort)."""

    def __init__(self, parameter_provider: ParameterProvider) -> None:
        self._parameter_provider = parameter_provider

    def write(self, instance: Any, to: Path) -> None:
        params = self._parameter_provider.provide(type(instance))
        try:
            to.parent.mkdir(parents=True, exist_ok=True)
            with open(to, "w", encoding="utf-8") as f:
                json.dump(params, f, indent=4, default=str)
        except OSError as e:
            print(
                f"Warning: Failed to save per-run parameter snapshot to {to}: {e}",
                file=sys.stderr,
            )
