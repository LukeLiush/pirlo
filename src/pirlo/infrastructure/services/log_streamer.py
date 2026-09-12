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
        from pirlo.core.logging_context import (
            get_current_play_id,
            get_current_run_id,
        )

        asctime: str = self.formatTime(record, "%H:%M:%S")
        levelname: str = record.levelname
        flow_run_name: str | None = (
            getattr(record, "flow_run_name", None) or get_current_run_id()
        )
        task_run_name: str | None = (
            getattr(record, "task_run_name", None) or get_current_play_id()
        )

        if not flow_run_name or not task_run_name:
            with contextlib.suppress(Exception):
                from prefect.context import FlowRunContext, TaskRunContext

                if not task_run_name:
                    task_ctx = TaskRunContext.get()
                    if task_ctx and task_ctx.task_run and task_ctx.task_run.name:
                        task_run_name = task_ctx.task_run.name

                if not flow_run_name:
                    flow_ctx = FlowRunContext.get()
                    if flow_ctx and flow_ctx.flow_run and flow_ctx.flow_run.name:
                        flow_run_name = flow_ctx.flow_run.name
                    else:
                        task_ctx = TaskRunContext.get()
                        if task_ctx:
                            flow_run = getattr(task_ctx, "flow_run", None)
                            if flow_run and flow_run.name:
                                flow_run_name = flow_run.name

        import os

        pid: int = os.getpid()

        if flow_run_name and task_run_name:
            prefix: str = f"[{flow_run_name}/{task_run_name} (pid {pid})]"
        elif flow_run_name:
            prefix = f"[{flow_run_name} (pid {pid})]"
        elif task_run_name:
            prefix = f"[{task_run_name} (pid {pid})]"
        else:
            prefix = ""

        msg: str = record.getMessage()
        clean_msg: str = msg
        clean_msg = re.sub(r"^\d{2}:\d{2}:\d{2}\s+", "", clean_msg)
        clean_msg = re.sub(r"^\[[\w\-#.:/]+(?:\s+\(pid\s+\d+\))?\]\s+", "", clean_msg)

        header: str = (
            f"{asctime} [{levelname}] {prefix}".rstrip()
            if prefix
            else f"{asctime} [{levelname}]"
        )
        lines: list[str] = clean_msg.splitlines()
        if not lines:
            formatted: str = header
        elif len(lines) == 1:
            formatted = f"{header} {lines[0]}"
        else:
            formatted = "\n".join(
                f"{header} {line}" if line else header for line in lines
            )

        if record.exc_info and not record.exc_text:
            record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            if not formatted.endswith("\n"):
                formatted += "\n"
            formatted += record.exc_text
        if record.stack_info:
            if not formatted.endswith("\n"):
                formatted += "\n"
            formatted += self.formatStack(record.stack_info)

        return formatted


def setup_pirlo_logging(show_logs: bool = False) -> None:
    """Configures centralized Pirlo logging with consistent [run_id/play_id] formatting.

    Neutralizes third-party loggers (such as browser-use) that hijack the root
    logger, configures Prefect logging, and ensures all console output respects
    show_logs and PirloConsoleFormatter.
    """
    import os

    from pirlo.core.config import get_log_level

    # 1. Neutralize browser_use logging hijack if present
    with contextlib.suppress(Exception):
        import browser_use.logging_config as bu_logging

        bu_logging.setup_logging = lambda *args, **kwargs: logging.getLogger(
            "browser_use"
        )

    # 2. Reset third-party loggers that disable propagation
    for rogue_name in (
        "browser_use",
        "bubus",
        "cdp_use",
        "websockets.client",
        "cdp_use.client",
    ):
        l: logging.Logger = logging.getLogger(rogue_name)
        l.handlers.clear()
        l.propagate = True

    # 3. Configure Prefect environment settings
    log_level_int: int = get_log_level()
    log_level_name: str = logging.getLevelName(log_level_int)

    os.environ["PREFECT_LOGGING_LEVEL"] = log_level_name
    if show_logs:
        os.environ["PREFECT_LOGGING_HANDLERS_CONSOLE_LEVEL"] = log_level_name
    else:
        os.environ["PREFECT_LOGGING_HANDLERS_CONSOLE_LEVEL"] = "ERROR"
        os.environ["PREFECT_LOGGING_TO_API_WHEN_MISSING_FLOW"] = "ignore"

    # 4. Clear root handlers and initialize Prefect logging
    root_logger: logging.Logger = logging.getLogger()
    root_logger.handlers.clear()

    with contextlib.suppress(Exception):
        from prefect.logging.configuration import setup_logging

        setup_logging(incremental=False)

    # 5. Set up formatter and stream on all root handlers
    root_logger.setLevel(log_level_int)
    console_level: int = log_level_int if show_logs else logging.ERROR

    formatter: PirloConsoleFormatter = PirloConsoleFormatter()
    if not root_logger.handlers and show_logs:
        stream_handler: logging.StreamHandler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        stream_handler.setLevel(console_level)
        root_logger.addHandler(stream_handler)
    else:
        for handler in root_logger.handlers:
            handler.setFormatter(formatter)
            handler.setLevel(console_level)
            if hasattr(handler, "stream"):
                handler.stream = sys.stdout
            if hasattr(handler, "console"):
                handler.console.file = sys.stdout

    # 6. Ensure core & extra loggers propagate to root at log_level_int
    for logger_name in ("prefect", "pirlo", "browser_use"):
        core_l: logging.Logger = logging.getLogger(logger_name)
        core_l.setLevel(log_level_int)
        core_l.propagate = True


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
