import sys
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path


class StdioTee:
    """Tees stdout/stderr output to both original stream and a log file with task prefixes."""

    def __init__(self, original_stream, log_file, get_prefix_fn=None):
        self.original_stream = original_stream
        self.log_file = log_file
        self.get_prefix_fn = get_prefix_fn
        self._at_line_start = True

    def write(self, data):
        self.original_stream.write(data)
        if not data:
            return

        prefix = ""
        if self.get_prefix_fn:
            try:
                prefix = self.get_prefix_fn() or ""
            except Exception:  # noqa: BLE001
                prefix = ""

        lines = data.splitlines(keepends=True)
        for line in lines:
            if self._at_line_start and line.strip():
                now_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
                formatted_prefix = (
                    f"[{now_str}] {prefix} " if prefix else f"[{now_str}] "
                )
                self.log_file.write(formatted_prefix + line)
            else:
                self.log_file.write(line)
            self._at_line_start = line.endswith("\n")

        self.log_file.flush()

    def flush(self):
        self.original_stream.flush()
        self.log_file.flush()


@contextmanager
def capture_run_logs(run_dir: Path, get_prefix_fn=None):
    """Context manager capturing all stdout/stderr into run_dir/run.log."""
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "run.log"
    with open(log_path, "a", encoding="utf-8") as log_file:
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = StdioTee(old_stdout, log_file, get_prefix_fn=get_prefix_fn)
        sys.stderr = StdioTee(old_stderr, log_file, get_prefix_fn=get_prefix_fn)
        try:
            yield log_path
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
