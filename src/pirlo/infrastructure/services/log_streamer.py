import logging
import re
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
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


class StdioTee:
    """Tees stdout/stderr output: sends raw ANSI to terminal, writes formatted text to log_file."""

    def __init__(
        self,
        original_stream: Any,
        log_file: Any,
        get_prefix_fn: Callable[[], str] | None = None,
    ) -> None:
        self.original_stream: Any = original_stream
        self.log_file: Any = log_file
        self.get_prefix_fn: Callable[[], str] | None = get_prefix_fn
        self._buffer: str = ""
        self._at_line_start: bool = True
        self._last_logged_status: str | None = None

    def _process_line(self, raw_data: str) -> None:
        plain_text = Text.from_ansi(raw_data).plain.replace("\r", "")
        clean_data = ftfy.fix_text(plain_text)
        lines = clean_data.splitlines()

        for raw_line in lines:
            line_content = re.sub(r"^[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏]\s*", "", raw_line).strip()
            if not line_content:
                continue

            if line_content == self._last_logged_status:
                continue
            self._last_logged_status = line_content

            prefix = ""
            if self.get_prefix_fn:
                try:
                    prefix = self.get_prefix_fn() or ""
                except Exception:  # noqa: BLE001
                    prefix = ""
            if not prefix:
                prefix, _ = resolve_log_prefix()

            now = datetime.now(UTC).astimezone()
            now_str = (
                now.strftime("%Y-%m-%d %H:%M:%S") + f".{now.microsecond // 1000:03d}"
            )
            formatted_prefix = f"{prefix} " if prefix else ""
            if self.log_file:
                self.log_file.write(f"{now_str} {formatted_prefix}{line_content}\n")
                self.log_file.flush()

    def write(self, data: str) -> int:
        written = self.original_stream.write(data)
        if not data:
            return written if isinstance(written, int) else 0

        self._buffer += data
        if "\n" not in self._buffer:
            return written if isinstance(written, int) else len(data)

        lines = self._buffer.split("\n")
        self._buffer = lines.pop()

        for line in lines:
            self._process_line(line)
        return written if isinstance(written, int) else len(data)

    def flush(self) -> None:
        self.original_stream.flush()
        if self._buffer:
            self._process_line(self._buffer)
            self._buffer = ""
        if self.log_file:
            self.log_file.flush()

    def isatty(self) -> bool:
        return getattr(self.original_stream, "isatty", lambda: False)()

    def fileno(self) -> int:
        return self.original_stream.fileno()


@contextmanager
def capture_run_logs(
    run_dir: Path,
    get_prefix_fn: Callable[[], str] | None = None,
    console_stream: bool = False,
    console_level: int = logging.INFO,
    file_level: int = logging.INFO,
    log_level: int | None = None,
) -> Iterator[Path]:
    """Context manager capturing all stdout/stderr and logging module calls into run_dir/run.log.

    - file_handler always captures at file_level into run.log.
    - console_handler is attached only if console_stream is True (-l / --log passed).
    """
    effective_file_level = log_level if log_level is not None else file_level
    effective_console_level = log_level if log_level is not None else console_level

    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "run.log"

    root_logger = logging.getLogger()
    orig_level = root_logger.level
    min_required_level = min(
        effective_file_level,
        effective_console_level if console_stream else effective_file_level,
    )
    if orig_level > min_required_level or orig_level == logging.NOTSET:
        root_logger.setLevel(min_required_level)

    formatter = PirloLogFormatter(
        "%(asctime)s %(prefix)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    with open(log_path, "a", encoding="utf-8") as log_file:
        old_stdout = sys.stdout
        old_stderr = sys.stderr

        # 1. Tee raw print() / self.ui calls to terminal + run.log
        tee_stdout = StdioTee(old_stdout, log_file, get_prefix_fn=get_prefix_fn)
        tee_stderr = StdioTee(old_stderr, log_file, get_prefix_fn=get_prefix_fn)

        sys.stdout = tee_stdout
        sys.stderr = tee_stderr

        # 2. File handler always writes all logs to run.log
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(effective_file_level)
        file_handler.setFormatter(formatter)
        file_handler.addFilter(PirloLogFilter())
        root_logger.addHandler(file_handler)

        # 3. Console handler attached ONLY when -l / --log is requested
        console_handler: logging.StreamHandler[Any] | None = None
        if console_stream:
            console_handler = logging.StreamHandler(old_stdout)
            console_handler.setLevel(effective_console_level)
            console_handler.setFormatter(formatter)
            console_handler.addFilter(PirloLogFilter())
            root_logger.addHandler(console_handler)

        try:
            yield log_path
        finally:
            root_logger.removeHandler(file_handler)
            file_handler.close()
            if console_handler is not None:
                root_logger.removeHandler(console_handler)
                console_handler.close()
            root_logger.setLevel(orig_level)
            sys.stdout = old_stdout
            sys.stderr = old_stderr
