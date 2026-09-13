# src/pirlo/infrastructure/services/log_formatter.py
from __future__ import annotations

import contextlib
import re
from datetime import datetime
from typing import Any, Final

from pirlo.core.ports.log_envelope import LogEnvelope, LogMetadata, UnpackedLog


class JsonLogEnvelope(LogEnvelope):
    """JSON-based micro-envelope implementation of LogEnvelope using Pydantic."""

    META_REGEX: Final[re.Pattern[str]] = re.compile(
        r"^\[meta:(\{.*?\})\]\s*(.*)$", re.DOTALL
    )

    def pack(
        self,
        message: str,
        metadata: LogMetadata | None = None,
    ) -> str:
        if metadata is None:
            return message
        json_str: str = metadata.model_dump_json(exclude_none=True)
        if json_str == "{}":
            return message
        return f"[meta:{json_str}] {message}"

    def unpack(self, raw_message: str) -> UnpackedLog:
        match: re.Match[str] | None = self.META_REGEX.match(raw_message)
        if match:
            with contextlib.suppress(Exception):
                meta: LogMetadata = LogMetadata.model_validate_json(match.group(1))
                clean_msg: str = match.group(2)
                return UnpackedLog(clean_message=clean_msg, metadata=meta)
        return UnpackedLog(clean_message=raw_message, metadata=LogMetadata())


class LogPrefixStrategy:
    """Configurable strategy for formatting prefix tags from LogMetadata."""

    def build_prefix(self, meta: LogMetadata) -> str:
        parts: list[str] = []

        # 1. Target identifier
        if meta.run_id and meta.play_id:
            parts.append(f"{meta.run_id}/{meta.play_id}")
        elif meta.run_id:
            parts.append(str(meta.run_id))
        elif meta.play_id:
            parts.append(str(meta.play_id))
        elif meta.play_name:
            v_str: str = f"#v{meta.play_version}" if meta.play_version else ""
            parts.append(f"{meta.play_name}{v_str}")

        # 2. Worker PID
        if meta.pid is not None:
            parts.append(f"(pid {meta.pid})")

        # 3. Custom tags from extra fields
        extra_dict: dict[str, Any] = getattr(meta, "__pydantic_extra__", None) or {}
        for k, v in extra_dict.items():
            if v is not None:
                parts.append(f"{k}={v}")

        if not parts:
            return ""
        return f"[{' '.join(parts)}]"


class PlayLogFormatter:
    """Central formatter used by both live console output and API log readers."""

    TIMESTAMP_FORMAT: Final[str] = "%Y-%m-%d %H:%M:%S%z"

    def __init__(
        self,
        envelope: LogEnvelope | None = None,
        prefix_strategy: LogPrefixStrategy | None = None,
    ) -> None:
        self.envelope: LogEnvelope = envelope or JsonLogEnvelope()
        self.prefix_strategy: LogPrefixStrategy = prefix_strategy or LogPrefixStrategy()

    def format_line(
        self,
        raw_message: str,
        timestamp: datetime | None = None,
        level_name: str = "INFO",
        explicit_metadata: LogMetadata | None = None,
    ) -> str:
        unpacked: UnpackedLog = self.envelope.unpack(raw_message)
        clean_msg: str = unpacked.clean_message
        meta: LogMetadata = unpacked.metadata

        if explicit_metadata:
            merged_dict: dict[str, Any] = {
                **meta.model_dump(exclude_none=True),
                **explicit_metadata.model_dump(exclude_none=True),
            }
            meta = LogMetadata.model_validate(merged_dict)

        ts_str: str = ""
        if timestamp is not None:
            ts_str = (
                timestamp.astimezone().strftime(self.TIMESTAMP_FORMAT)
                if timestamp.tzinfo is not None
                else timestamp.strftime(self.TIMESTAMP_FORMAT)
            )

        prefix_tag: str = self.prefix_strategy.build_prefix(meta)
        header: str = f"{ts_str} [{level_name}] {prefix_tag}".strip()
        return f"{header} {clean_msg}".rstrip()
