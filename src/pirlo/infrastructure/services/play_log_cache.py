# src/pirlo/infrastructure/services/play_log_cache.py
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from pirlo.core.config import get_workspace_path
from pirlo.core.models.run import LogCursor


class PlayLogCache:
    """Manages local file caching and LogCursor metadata for play log streams."""

    def __init__(self, workspace: Path | None = None) -> None:
        self._workspace: Path = workspace or get_workspace_path()

    def get_log_path(self, playbook: str, run_id: str, play_id: str) -> Path:
        safe_name: str = re.sub(r"[#:/\\?%*|\"<>]", "_", play_id) + ".log"
        return self._workspace / playbook / "runs" / run_id / "logs" / safe_name

    def get_cursor_path(self, playbook: str, run_id: str, play_id: str) -> Path:
        return self.get_log_path(playbook, run_id, play_id).with_suffix(".cursor")

    def is_cached(self, playbook: str, run_id: str, play_id: str) -> bool:
        return self.get_log_path(playbook, run_id, play_id).exists()

    def get_cursor(self, playbook: str, run_id: str, play_id: str) -> LogCursor | None:
        cursor_path: Path = self.get_cursor_path(playbook, run_id, play_id)
        return LogCursor.from_file(cursor_path)

    def read_cached_lines(
        self, playbook: str, run_id: str, play_id: str, tail_lines: int = 50
    ) -> list[str]:
        log_path: Path = self.get_log_path(playbook, run_id, play_id)
        if not log_path.exists():
            return []
        with open(log_path, "r", encoding="utf-8") as f:
            lines: list[str] = [line.rstrip() for line in f]
        return lines[-tail_lines:]

    def append(
        self,
        playbook: str,
        run_id: str,
        play_id: str,
        line: str,
        ts: datetime,
        log_id: Any | None = None,
    ) -> None:
        log_path: Path = self.get_log_path(playbook, run_id, play_id)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

        cursor_path: Path = self.get_cursor_path(playbook, run_id, play_id)
        current_cursor: LogCursor | None = LogCursor.from_file(cursor_path)
        current_lines_count: int = (
            (current_cursor.lines_count if current_cursor else 0) + 1
        )

        local_ts_str: str = (
            ts.astimezone().strftime("%Y-%m-%d %H:%M:%S%z")
            if ts.tzinfo is not None
            else ts.strftime("%Y-%m-%d %H:%M:%S%z")
        )
        new_cursor = LogCursor(
            last_timestamp_utc=ts,
            last_timestamp_local=local_ts_str,
            lines_count=current_lines_count,
            last_log_id=str(log_id) if log_id is not None else None,
            updated_at=datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S%z"),
        )
        new_cursor.save_to_file(cursor_path)
