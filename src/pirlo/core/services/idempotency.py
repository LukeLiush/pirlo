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

    @property
    def full_id(self) -> str:
        """Full 64-hex idempotency key, e.g. 'demo_download_report-e4f5a6b7c8...'"""
        return f"{self.play_name}-{self.digest}"

    @property
    def short_id(self) -> str:
        """Compact badge ID for terminal telemetry, e.g. 'demo_download_report#e4f5a6'"""
        return f"{self.play_name}#{self.digest[:6]}"

    def __str__(self) -> str:
        return self.short_id


def compute_play_identity(
    play_name: str,
    kwargs: dict[str, Any],
) -> PlayIdentity:
    """Computes a deterministic, content-addressed PlayIdentity from inputs."""
    jsonable = to_jsonable_python(kwargs)
    canonical_json = json.dumps(
        jsonable,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    raw_payload = f"{play_name}:{canonical_json}"
    digest = hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()
    return PlayIdentity(play_name=play_name, digest=digest)
