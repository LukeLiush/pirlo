# src/pirlo/core/services/idempotency.py
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from pydantic_core import to_jsonable_python


@dataclass(frozen=True)
class PlayIdentity:
    """Immutable content-addressed identity for a Play execution instance."""

    play_name: str
    digest: str
    version: str = "1.0"

    @property
    def full_id(self) -> str:
        """Full 64-hex idempotency key, e.g. 'demo_download_report-v1.0-e4f5a6b7c8...'"""
        return f"{self.play_name}-v{self.version}-{self.digest}"

    @property
    def short_id(self) -> str:
        """Compact badge ID for terminal telemetry, e.g. 'demo_download_report#v1.0:e4f5a6'"""
        return f"{self.play_name}#v{self.version}:{self.digest[:6]}"

    def __str__(self) -> str:
        return self.short_id


def compute_play_identity(
    play_name: str,
    kwargs: dict[str, Any],
    version: str = "1.0",
) -> PlayIdentity:
    """Computes a deterministic, content-addressed PlayIdentity from inputs and version."""
    jsonable = to_jsonable_python(kwargs, fallback=lambda _: None)
    canonical_json = json.dumps(
        jsonable,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    raw_payload = f"{play_name}:v{version}:{canonical_json}"
    digest = hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()
    return PlayIdentity(play_name=play_name, digest=digest, version=version)
