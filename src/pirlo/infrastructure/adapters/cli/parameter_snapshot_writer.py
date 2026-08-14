"""Discover, resolve, and apply playbook parameter values.

Responsibilities are split across small, single-purpose collaborators:

* :func:`discover_parameters`      -- find ``Parameter`` attributes on a class.
* :class:`ArgumentParserBuilder`   -- build the argparse parser.
* :class:`ParameterResolver`       -- resolve values across sources + domain.
* :class:`ParameterProvider`       -- discover + resolve for a playbook class.
* :class:`ParameterBinder`         -- apply resolved values onto an instance.
* :class:`ParameterSnapshotWriter` -- snapshot resolved values to disk.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pirlo.core.models.parameters import Parameterizable
from pirlo.infrastructure.services.parameter_provider import ParameterProvider


class ParameterSnapshotWriter:
    """Writes a resolved-parameter snapshot to disk (best effort)."""

    def __init__(self, parameter_provider: ParameterProvider) -> None:
        self._parameter_provider = parameter_provider

    def write(self, instance: Parameterizable, to: Path) -> None:
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
