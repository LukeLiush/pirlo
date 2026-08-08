import logging
import re
import sys
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from rich.text import Text

# Match both standard ANSI escape codes and orphan color code fragments (e.g. [34m, [35m, [0m)
ANSI_BRACKET_REGEX = re.compile(r"(\x1b)?\[[0-9;?]*[a-zA-Z]")


class StdioTee:
    """Tees stdout/stderr output: sends raw ANSI to terminal, delegates ANSI parsing to Rich for log_file."""

    def __init__(self, original_stream, log_file, get_prefix_fn=None):
        self.original_stream = original_stream
        self.log_file = log_file
        self.get_prefix_fn = get_prefix_fn
        self._at_line_start = True
        self._last_logged_status: str | None = None

    def write(self, data):
        self.original_stream.write(data)
        if not data:
            return

        # Delegate ANSI escape code parsing to Rich + strip orphan bracket color codes (e.g. [34m, [0m)
        plain_text = Text.from_ansi(data).plain.replace("\r", "")
        clean_data = ANSI_BRACKET_REGEX.sub("", plain_text)
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

    def flush(self):
        self.original_stream.flush()
        if self.log_file:
            self.log_file.flush()

    def isatty(self) -> bool:
        return getattr(self.original_stream, "isatty", lambda: False)()

    def fileno(self) -> int:
        return self.original_stream.fileno()


@contextmanager
def capture_run_logs(run_dir: Path, get_prefix_fn=None):
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
        formatter = logging.Formatter(
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
