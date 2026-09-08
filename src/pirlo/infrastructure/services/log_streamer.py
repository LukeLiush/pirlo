from __future__ import annotations

import contextlib
import logging
import re
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import ftfy
from rich.text import Text

from pirlo.core.logging_context import resolve_log_prefix

ANSI_PATTERN = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\b\[\d+m")


class PirloLogFilter(logging.Filter):
    """Enriches LogRecord with contextual prefix and process PID."""

    def filter(self, record: logging.LogRecord) -> bool:
        prefix, pid = resolve_log_prefix()
        msg_str = str(record.msg)
        if msg_str.startswith("Workflow starting"):
            record.prefix = ""
        else:
            record.prefix = prefix
        record.pid = pid
        return True


class PirloLogFormatter(logging.Formatter):
    """Logging Formatter producing millisecond precision timestamps:
    'YYYY-MM-DD HH:MM:SS.mmm [3a4f8c9b/subtask#1235 (pid 5678)] message'
    and stripping ANSI escape codes.
    """

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        ct = self.converter(record.created)
        t = time.strftime(datefmt or "%Y-%m-%d %H:%M:%S", ct)
        return f"{t}.{int(record.msecs):03d}"

    def format(self, record: logging.LogRecord) -> str:
        msg = super().format(record)
        clean_msg = ANSI_PATTERN.sub("", msg)
        return re.sub(r"  +", " ", clean_msg)


AnsiStrippingFormatter = PirloLogFormatter


import contextvars

_current_stdio_handler: contextvars.ContextVar[Callable[[str], None] | None] = (
    contextvars.ContextVar("_current_stdio_handler", default=None)
)
_current_stdio_passthrough: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "_current_stdio_passthrough", default=True
)
_current_stdio_buffer: contextvars.ContextVar[str] = contextvars.ContextVar(
    "_current_stdio_buffer", default=""
)
_current_stdio_in_callback: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "_current_stdio_in_callback", default=False
)
_current_stdio_last_status: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_current_stdio_last_status", default=None
)

_active_capture_count: int = 0
_original_global_stdout: Any = None


class PirloConsoleFormatter(logging.Formatter):
    """Formats console log records with consistent [run_id/play_id] prefix matching pirlo run log."""

    def format(self, record: logging.LogRecord) -> str:
        from pirlo.core.logging_context import get_current_run_id

        asctime: str = self.formatTime(record, "%H:%M:%S")
        levelname: str = record.levelname
        flow_run_name: str | None = (
            getattr(record, "flow_run_name", None) or get_current_run_id()
        )
        task_run_name: str | None = getattr(record, "task_run_name", None)

        if flow_run_name and task_run_name:
            prefix: str = f"[{flow_run_name}/{task_run_name}]"
        elif flow_run_name:
            prefix = f"[{flow_run_name}]"
        elif task_run_name:
            prefix = f"[{task_run_name}]"
        else:
            prefix = ""

        msg: str = record.getMessage()
        clean_msg: str = msg
        clean_msg = re.sub(r"^\d{2}:\d{2}:\d{2}\s+", "", clean_msg)
        clean_msg = re.sub(r"^\[[\w\-#.:/]+(?:\s+\(pid\s+\d+\))?\]\s+", "", clean_msg)

        if prefix:
            return f"{asctime} [{levelname}] {prefix} {clean_msg}"
        return f"{asctime} [{levelname}] {clean_msg}"


class StdioTee:
    """Tees stdout/stderr stream: forwards raw output to terminal while streaming clean lines to a callback."""

    def __init__(
        self,
        original_stream: Any,
        on_line: Callable[[str], None] | None = None,
    ) -> None:
        self.original_stream: Any = original_stream
        self.on_line: Callable[[str], None] | None = on_line
        self._buffer: str = ""
        self._in_callback: bool = False
        self._last_logged_status: str | None = None

    def _is_passthrough(self) -> bool:
        if self.on_line is not None:
            return True
        return _current_stdio_passthrough.get()

    def _get_buffer(self) -> str:
        if self.on_line is not None:
            return self._buffer
        return _current_stdio_buffer.get()

    def _set_buffer(self, val: str) -> None:
        if self.on_line is not None:
            self._buffer = val
        else:
            _current_stdio_buffer.set(val)

    def _is_in_callback(self) -> bool:
        if self.on_line is not None:
            return self._in_callback
        return _current_stdio_in_callback.get()

    def _set_in_callback(self, val: bool) -> None:
        if self.on_line is not None:
            self._in_callback = val
        else:
            _current_stdio_in_callback.set(val)

    def _get_last_status(self) -> str | None:
        if self.on_line is not None:
            return self._last_logged_status
        return _current_stdio_last_status.get()

    def _set_last_status(self, val: str | None) -> None:
        if self.on_line is not None:
            self._last_logged_status = val
        else:
            _current_stdio_last_status.set(val)

    def _process_line(self, raw_data: str) -> None:
        cb: Callable[[str], None] | None = self.on_line or _current_stdio_handler.get()
        if cb is None:
            return

        plain_text: str = Text.from_ansi(raw_data).plain.replace("\r", "")
        clean_data: str = ftfy.fix_text(plain_text)
        lines: list[str] = clean_data.splitlines()

        for raw_line in lines:
            line_content: str = re.sub(r"^[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏]\s*", "", raw_line).strip()
            if not line_content or line_content == self._get_last_status():
                continue
            self._set_last_status(line_content)

            clean_msg: str = line_content
            clean_msg = re.sub(r"^\d{2}:\d{2}:\d{2}\s+", "", clean_msg)
            clean_msg = re.sub(
                r"^\[[\w\-#.:/]+(?:\s+\(pid\s+\d+\))?\]\s+", "", clean_msg
            )

            if not self._is_in_callback():
                self._set_in_callback(True)
                try:
                    with contextlib.suppress(Exception):
                        cb(clean_msg)
                finally:
                    self._set_in_callback(False)

    def write(self, data: str) -> int:
        written: Any = 0
        if self._is_passthrough():
            written = self.original_stream.write(data)
        if not data or self._is_in_callback():
            return written if isinstance(written, int) else len(data)

        buf: str = self._get_buffer() + data
        if "\n" not in buf:
            self._set_buffer(buf)
            return written if isinstance(written, int) else len(data)

        lines: list[str] = buf.split("\n")
        self._set_buffer(lines.pop())

        for line in lines:
            self._process_line(line)
        return written if isinstance(written, int) else len(data)

    def flush(self) -> None:
        self.original_stream.flush()
        buf: str = self._get_buffer()
        if buf:
            self._process_line(buf)
            self._set_buffer("")

    def isatty(self) -> bool:
        return getattr(self.original_stream, "isatty", lambda: False)()

    def fileno(self) -> int:
        return self.original_stream.fileno()


@contextmanager
def capture_play_stdio(
    on_line: Callable[[str], None],
    passthrough: bool = True,
) -> Iterator[None]:
    """Context manager that tees sys.stdout to an on_line callback.

    Interactive terminal output is preserved untouched while clean lines
    (ANSI and progress spinners removed) are forwarded to on_line.
    Uses ContextVar so concurrent asyncio tasks never leak output across tasks.
    """
    global _active_capture_count, _original_global_stdout
    token_handler: contextvars.Token[Callable[[str], None] | None] = (
        _current_stdio_handler.set(on_line)
    )
    token_pt: contextvars.Token[bool] = _current_stdio_passthrough.set(passthrough)
    if _active_capture_count == 0:
        _original_global_stdout = sys.stdout
        sys.stdout = StdioTee(_original_global_stdout)
    _active_capture_count += 1
    try:
        yield
    finally:
        sys.stdout.flush()
        _current_stdio_handler.reset(token_handler)
        _current_stdio_passthrough.reset(token_pt)
        _active_capture_count -= 1
        if _active_capture_count == 0 and _original_global_stdout is not None:
            sys.stdout = _original_global_stdout
            _original_global_stdout = None
