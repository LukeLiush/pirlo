# src/pirlo/core/ports/log_envelope.py
from __future__ import annotations

from typing import NamedTuple, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict


class LogMetadata(BaseModel):
    """Pydantic model for structured metadata embedded in log envelopes."""

    model_config = ConfigDict(extra="allow")

    pid: int | None = None
    run_id: str | None = None
    play_id: str | None = None
    play_name: str | None = None
    play_version: str | None = None


class UnpackedLog(NamedTuple):
    """Self-documenting result of unpacking a raw log payload into clean text and metadata."""

    clean_message: str
    metadata: LogMetadata


@runtime_checkable
class LogEnvelope(Protocol):
    """Protocol for packing and unpacking metadata within log message payloads."""

    def pack(
        self,
        message: str,
        metadata: LogMetadata | None = None,
    ) -> str:
        """Encodes LogMetadata into a log payload string."""
        ...

    def unpack(self, raw_message: str) -> UnpackedLog:
        """Decodes raw log payload into clean message and LogMetadata instance."""
        ...
