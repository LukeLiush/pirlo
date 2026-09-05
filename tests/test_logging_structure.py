import asyncio
import logging
import os
import tempfile
from pathlib import Path

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
    capture_run_logs,
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
    assert all(tag == f"[shared_run/subtask#1001 (pid {pid})]" for tag in results["task1"])
    assert all(tag == f"[shared_run/subtask#1002 (pid {pid})]" for tag in results["task2"])


def test_pirlo_log_formatter_and_filter():
    logger = logging.getLogger("test_pirlo_logger")
    logger.setLevel(logging.INFO)

    log_filter = PirloLogFilter()
    formatter = PirloLogFormatter(
        "%(asctime)s %(prefix)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    with workflow_logging_context("3a4f8c9b"):
        with play_logging_context("autopass_execute_subtask#1235"):
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


def test_capture_run_logs_integration():
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        with workflow_logging_context("3a4f8c9b"):
            with capture_run_logs(run_dir):
                logger = logging.getLogger("pirlo.test")
                logger.info("Workflow starting (run-id 3a4f8c9b):")

                with play_logging_context("autopass_decompose#1234"):
                    logger.info("Task is starting.")
                    logger.info("Decomposed into 3 subtasks")
                    logger.info("Task finished successfully.")

                with play_logging_context("autopass_execute_subtask#1235"):
                    logger.info("Task is starting.")
                    logger.info("Querying gemini")
                    print("Raw stdout print from worker")

                logger.info("Done!")

        log_file = run_dir / "run.log"
        assert log_file.exists()
        log_content = log_file.read_text(encoding="utf-8")
        lines = log_content.strip().splitlines()

        pid = os.getpid()
        assert any("Workflow starting (run-id 3a4f8c9b):" in line for line in lines)
        assert any(f"[3a4f8c9b/autopass_decompose#1234 (pid {pid})] Task is starting." in line for line in lines)
        assert any(f"[3a4f8c9b/autopass_decompose#1234 (pid {pid})] Decomposed into 3 subtasks" in line for line in lines)
        assert any(f"[3a4f8c9b/autopass_execute_subtask#1235 (pid {pid})] Querying gemini" in line for line in lines)
        assert any(f"[3a4f8c9b/autopass_execute_subtask#1235 (pid {pid})] Raw stdout print from worker" in line for line in lines)
        assert any(f"[3a4f8c9b (pid {pid})] Done!" in line for line in lines)
