# tests/test_local_command_runner.py
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

import pytest

from pirlo.core.models.command import Command
from pirlo.core.utils.line_splitter import CONTINUATION_MARK
from pirlo.infrastructure.adapters.shell.local_runner import LocalCommandRunner

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def runner(tmp_path: Path) -> LocalCommandRunner:
    return LocalCommandRunner(log_dir=tmp_path / "logs", kill_grace_s=1.0)


async def _wait_until_dead(pid: int, timeout_s: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        await asyncio.sleep(0.05)
    return False


async def test_returns_nonzero_exit_code(runner: LocalCommandRunner):
    r = await runner.run(Command(("sh", "-c", "exit 3")), on_line=lambda _: None)
    assert r.exit_code == 3
    assert r.timed_out is False


async def test_lines_stream_before_process_exits(runner: LocalCommandRunner):
    seen: list[tuple[str, float]] = []
    await runner.run(
        Command(("sh", "-c", "echo one; sleep 1; echo two")),
        on_line=lambda line: seen.append((line, time.monotonic())),
    )
    assert [line for line, _ in seen] == ["one", "two"]
    assert seen[1][1] - seen[0][1] > 0.8


async def test_python_child_streams_without_a_tty(runner: LocalCommandRunner):
    seen: list[tuple[str, float]] = []
    await runner.run(
        Command(
            (sys.executable, "-c", "import time; print(1); time.sleep(1); print(2)")
        ),
        on_line=lambda line: seen.append((line, time.monotonic())),
    )
    assert [line for line, _ in seen] == ["1", "2"]
    assert seen[1][1] - seen[0][1] > 0.8


async def test_applies_cwd_and_env(runner: LocalCommandRunner, tmp_path: Path):
    lines: list[str] = []
    await runner.run(
        Command(("sh", "-c", "pwd; echo $FOO"), cwd=tmp_path, env={"FOO": "bar"}),
        on_line=lines.append,
    )
    assert Path(lines[0]).resolve() == tmp_path.resolve()
    assert lines[1] == "bar"


async def test_arguments_are_passed_literally(runner: LocalCommandRunner):
    lines: list[str] = []
    await runner.run(
        Command(("printf", "%s\n", "a b; rm -rf x $(id)")), on_line=lines.append
    )
    assert lines == ["a b; rm -rf x $(id)"]


async def test_carriage_returns_surface_as_updates(runner: LocalCommandRunner):
    lines: list[str] = []
    await runner.run(Command(("printf", "a\rb\rc")), on_line=lines.append)
    assert lines == ["a", "b", "c"]


async def test_overlong_line_is_cut_not_fatal(tmp_path: Path):
    runner = LocalCommandRunner(log_dir=tmp_path, max_line_len=8192)
    lines: list[str] = []
    r = await runner.run(
        Command((sys.executable, "-c", "print('x' * 100_000)")), on_line=lines.append
    )
    assert r.exit_code == 0
    assert all(len(line) <= 8192 + len(CONTINUATION_MARK) for line in lines)
    assert sum(line.count("x") for line in lines) == 100_000


async def test_ansi_stripped_from_lines_but_kept_in_log(runner: LocalCommandRunner):
    lines: list[str] = []
    r = await runner.run(
        Command(("printf", "\033[31mred\033[0m\n")), on_line=lines.append
    )
    assert lines == ["red"]
    assert b"\x1b[31m" in r.log_path.read_bytes()


async def test_full_log_on_disk_and_tail_in_result(tmp_path: Path):
    runner = LocalCommandRunner(log_dir=tmp_path, tail_lines=2)
    r = await runner.run(
        Command(("sh", "-c", "for i in 1 2 3 4 5; do echo $i; done")),
        on_line=lambda _: None,
    )
    assert r.log_path.read_text() == "1\n2\n3\n4\n5\n"
    assert r.output_tail == "4\n5"


async def test_timeout_kills_the_whole_process_group(runner: LocalCommandRunner):
    lines: list[str] = []
    r = await runner.run(
        Command(("sh", "-c", "sleep 30 & echo $!; wait"), timeout_s=0.5),
        on_line=lines.append,
    )
    assert r.timed_out is True
    assert await _wait_until_dead(int(lines[0]))


async def test_cancellation_kills_the_whole_process_group(runner: LocalCommandRunner):
    lines: list[str] = []
    task = asyncio.create_task(
        runner.run(
            Command(("sh", "-c", "sleep 30 & echo $!; wait")), on_line=lines.append
        )
    )
    while not lines:
        await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await _wait_until_dead(int(lines[0]))


async def test_on_line_error_does_not_orphan_the_process(runner: LocalCommandRunner):
    pids: list[int] = []

    def explode(line: str) -> None:
        pids.append(int(line))
        raise RuntimeError("logging broke")

    with pytest.raises(RuntimeError, match="logging broke"):
        await runner.run(
            Command(("sh", "-c", "sleep 30 & echo $!; wait")), on_line=explode
        )
    assert await _wait_until_dead(pids[0])
