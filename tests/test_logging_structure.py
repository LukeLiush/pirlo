import asyncio
import logging
import os

import pytest

from pirlo.core.logging_context import (
    generate_short_run_id,
    get_current_play_id,
    get_current_run_id,
    play_logging_context,
    resolve_log_prefix,
    workflow_logging_context,
)
from pirlo.infrastructure.services.log_streamer import (
    PirloLogFilter,
    PirloLogFormatter,
    StdioTee,
    capture_play_stdio,
)


def test_short_run_id_generation():
    run_id1 = generate_short_run_id()
    run_id2 = generate_short_run_id()
    assert len(run_id1) == 8
    assert len(run_id2) == 8
    assert run_id1 != run_id2


def test_workflow_and_play_logging_context():
    assert get_current_run_id() is None
    assert get_current_play_id() is None

    with workflow_logging_context("test_run_123") as active_id:
        assert active_id == "test_run_123"
        assert get_current_run_id() == "test_run_123"
        prefix, pid = resolve_log_prefix()
        assert prefix == f"[test_run_123 (pid {os.getpid()})]"
        assert pid == os.getpid()

        with play_logging_context("demo_play#a1b2c3"):
            assert get_current_play_id() == "demo_play#a1b2c3"
            prefix, pid = resolve_log_prefix()
            assert prefix == f"[test_run_123/demo_play#a1b2c3 (pid {os.getpid()})]"

        assert get_current_play_id() is None
        prefix, _ = resolve_log_prefix()
        assert prefix == f"[test_run_123 (pid {os.getpid()})]"

    assert get_current_run_id() is None


@pytest.mark.anyio
async def test_async_concurrency_context_isolation():
    """Verifies that concurrent asyncio tasks running in parallel maintain isolated play contexts."""
    results: dict[str, list[str]] = {"task1": [], "task2": []}

    async def worker(task_name: str, play_id: str, delay: float):
        with play_logging_context(play_id, run_id="shared_run"):
            for _ in range(3):
                prefix, _ = resolve_log_prefix()
                results[task_name].append(prefix)
                await asyncio.sleep(delay)

    await asyncio.gather(
        worker("task1", "subtask#1001", 0.01),
        worker("task2", "subtask#1002", 0.015),
    )

    pid = os.getpid()
    assert all(
        tag == f"[shared_run/subtask#1001 (pid {pid})]" for tag in results["task1"]
    )
    assert all(
        tag == f"[shared_run/subtask#1002 (pid {pid})]" for tag in results["task2"]
    )


def test_pirlo_log_formatter_and_filter():
    logger = logging.getLogger("test_pirlo_logger")
    logger.setLevel(logging.INFO)

    log_filter = PirloLogFilter()
    formatter = PirloLogFormatter(
        "%(asctime)s %(prefix)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    with (
        workflow_logging_context("3a4f8c9b"),
        play_logging_context("autopass_execute_subtask#1235"),
    ):
        record = logger.makeRecord(
            name="test_pirlo_logger",
            level=logging.INFO,
            fn="test.py",
            lno=10,
            msg="Querying \x1b[32mgemini\x1b[0m",
            args=(),
            exc_info=None,
        )
        assert log_filter.filter(record)
        output = formatter.format(record)

        pid = os.getpid()
        assert f"[3a4f8c9b/autopass_execute_subtask#1235 (pid {pid})]" in output
        assert "Querying gemini" in output
        assert "\x1b[32m" not in output  # ANSI codes must be stripped


def test_stdio_tee_and_capture_play_stdio():
    import io

    fake_stream = io.StringIO()
    tee_lines: list[str] = []
    tee = StdioTee(fake_stream, on_line=tee_lines.append)
    tee.write("Hello from StdioTee\n")
    tee.flush()
    assert fake_stream.getvalue() == "Hello from StdioTee\n"
    assert tee_lines == ["Hello from StdioTee"]

    received_lines: list[str] = []

    def on_line(line: str) -> None:
        received_lines.append(line)
        # Test re-entrancy / recursion guard: printing inside on_line shouldn't recurse
        print("recursive print inside on_line")

    with capture_play_stdio(on_line=on_line):
        print("\x1b[32m[bold green]Goal achieved![/bold green]\x1b[0m")
        print("⠋ Loading something in background...")
        print("Standard line 1\nStandard line 2")

    # ANSI codes stripped
    assert any("Goal achieved!" in line for line in received_lines)
    assert not any("\x1b[32m" in line for line in received_lines)
    # Spinner stripped
    assert any("Loading something in background..." in line for line in received_lines)
    assert not any("⠋" in line for line in received_lines)
    # Multiline split
    assert "Standard line 1" in received_lines
    assert "Standard line 2" in received_lines


def test_pirlo_console_formatter():
    from pirlo.infrastructure.services.log_streamer import PirloConsoleFormatter

    formatter = PirloConsoleFormatter()
    logger = logging.getLogger("test_console_logger")

    # 1. Inside workflow and play context
    pid = os.getpid()
    with (
        workflow_logging_context("caedceb9"),
        play_logging_context("autopass#v1.0:869c68"),
    ):
        record = logger.makeRecord(
            name="test_console_logger",
            level=logging.INFO,
            fn="test.py",
            lno=10,
            msg="Play START | inputs={...}",
            args=(),
            exc_info=None,
        )
        line = formatter.format(record)
        assert (
            f"[INFO] [caedceb9/autopass#v1.0:869c68 (pid {pid})] Play START | inputs={{...}}"
            in line
        )

        # Multiline message formatting
        multiline_record = logger.makeRecord(
            name="test_console_logger",
            level=logging.INFO,
            fn="test.py",
            lno=11,
            msg="Header line\nDetail line 1\nDetail line 2",
            args=(),
            exc_info=None,
        )
        multiline_output = formatter.format(multiline_record)
        lines = multiline_output.splitlines()
        assert len(lines) == 3
        for l in lines:
            assert f"[INFO] [caedceb9/autopass#v1.0:869c68 (pid {pid})]" in l

    # 2. Inside workflow context only
    with workflow_logging_context("caedceb9"):
        record = logger.makeRecord(
            name="test_console_logger",
            level=logging.INFO,
            fn="test.py",
            lno=20,
            msg="Beginning flow run",
            args=(),
            exc_info=None,
        )
        line = formatter.format(record)
        assert f"[INFO] [caedceb9 (pid {pid})] Beginning flow run" in line

    record = logger.makeRecord(
        name="test_console_logger",
        level=logging.INFO,
        fn="test.py",
        lno=30,
        msg="Task completed",
        args=(),
        exc_info=None,
        extra={"flow_run_name": "run1234", "task_run_name": "task5678"},
    )
    line = formatter.format(record)
    assert f"[INFO] [run1234/task5678 (pid {pid})] Task completed" in line

    # 4. Strips embedded [(pid 9999)] tag without duplicating PID in output
    record_with_pid_tag = logger.makeRecord(
        name="test_console_logger",
        level=logging.INFO,
        fn="test.py",
        lno=35,
        msg="[(pid 9999)] Task completed with embedded tag",
        args=(),
        exc_info=None,
        extra={"flow_run_name": "run1234", "task_run_name": "task5678"},
    )
    line_with_pid_tag = formatter.format(record_with_pid_tag)
    assert (
        f"[INFO] [run1234/task5678 (pid {pid})] Task completed with embedded tag"
        in line_with_pid_tag
    )
    assert "[(pid 9999)]" not in line_with_pid_tag


def test_setup_pirlo_logging_neutralization():
    from pirlo.infrastructure.services.log_streamer import (
        PirloConsoleFormatter,
        setup_pirlo_logging,
    )

    root = logging.getLogger()
    # Simulate rogue handler added by a third-party library
    rogue_handler = logging.StreamHandler()
    root.addHandler(rogue_handler)

    bu_logger = logging.getLogger("browser_use")
    bu_logger.addHandler(logging.StreamHandler())
    bu_logger.propagate = False

    setup_pirlo_logging(show_logs=True)

    assert any(isinstance(h.formatter, PirloConsoleFormatter) for h in root.handlers)
    assert bu_logger.propagate is True
    assert len(bu_logger.handlers) == 0
