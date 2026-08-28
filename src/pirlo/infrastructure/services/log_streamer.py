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


class StdioTee:
    """Tees stdout/stderr output: sends raw ANSI to terminal, uses line-buffering and Rich for log_file."""

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

            now_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
            formatted_prefix = f"[{now_str}] {prefix} " if prefix else f"[{now_str}] "
            if self.log_file:
                self.log_file.write(formatted_prefix + line_content + "\n")
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


ANSI_PATTERN = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\b\[\d+m")


class AnsiStrippingFormatter(logging.Formatter):
    """Logging Formatter that strips raw ANSI escape codes from log records before saving to file."""

    def format(self, record: logging.LogRecord) -> str:
        formatted_message = super().format(record)
        return ANSI_PATTERN.sub("", formatted_message)


@contextmanager
def capture_run_logs(
    run_dir: Path, get_prefix_fn: Callable[[], str] | None = None
) -> Iterator[Path]:
    """Context manager capturing all stdout/stderr and logging module calls into run_dir/run.log without duplicating terminal output."""
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "run.log"

    with open(log_path, "a", encoding="utf-8") as log_file:
        old_stdout = sys.stdout
        old_stderr = sys.stderr

        # 1. Tee raw print() calls to terminal + run.log
        tee_stdout = StdioTee(old_stdout, log_file, get_prefix_fn=get_prefix_fn)
        tee_stderr = StdioTee(old_stderr, log_file, get_prefix_fn=get_prefix_fn)

        sys.stdout = tee_stdout
        sys.stderr = tee_stderr

        # 2. Attach FileHandler directly to root_logger
        # (All child loggers including prefect propagate up to root_logger)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        formatter = AnsiStrippingFormatter(
            "[%(asctime)s UTC] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )
        formatter.converter = time.gmtime
        file_handler.setFormatter(formatter)

        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        root_logger.addHandler(file_handler)

        try:
            yield log_path
        finally:
            root_logger.removeHandler(file_handler)
            file_handler.close()
            sys.stdout = old_stdout
            sys.stderr = old_stderr
