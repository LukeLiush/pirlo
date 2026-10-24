# src/pirlo/infrastructure/adapters/shell/local_runner.py
from __future__ import annotations

import asyncio
import codecs
import contextlib
import os
import signal
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from pirlo.core.config import get_workspace_path
from pirlo.core.models.command import Command, CommandResult
from pirlo.core.ports.command_runner import CommandRunner
from pirlo.core.utils.ansi import strip_ansi
from pirlo.core.utils.line_splitter import LineSplitter

_READ_CHUNK_BYTES = 4096


class LocalCommandRunner(CommandRunner):
    """Runs commands as local subprocesses, streaming output line by line as it arrives.

    Each command runs in its own process group so timeouts and cancellation
    terminate the whole tree, not just the direct child.
    """

    def __init__(
        self,
        log_dir: Path | None = None,
        tail_lines: int = 200,
        max_line_len: int = 8192,
        kill_grace_s: float = 5.0,
    ) -> None:
        self._log_dir: Path | None = log_dir
        self._tail_lines: int = tail_lines
        self._max_line_len: int = max_line_len
        self._kill_grace_s: float = kill_grace_s

    async def run(
        self, command: Command, on_line: Callable[[str], None]
    ) -> CommandResult:
        log_dir = self._log_dir or get_workspace_path() / "shell-logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{uuid4().hex}.log"
        tail: deque[str] = deque(maxlen=self._tail_lines)
        # Unbuffered Python children flush per line into the pipe; command.env wins
        env = {**os.environ, "PYTHONUNBUFFERED": "1", **command.env}

        start = time.perf_counter()
        proc = await asyncio.create_subprocess_exec(
            *command.argv,
            cwd=command.cwd,
            env=env,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
        timed_out = False
        finished = False
        with log_path.open("wb") as log_file:
            try:
                await asyncio.wait_for(
                    self._pump(proc, log_file, tail, on_line), command.timeout_s
                )
                finished = True
            except TimeoutError:
                timed_out = True
            finally:
                # Covers timeout, cancellation, and on_line errors alike; the leader may
                # have exited while descendants still hold the pipe, so kill the group
                if not finished:
                    await self._kill_group(proc)

        return CommandResult(
            command=command,
            exit_code=proc.returncode if proc.returncode is not None else -1,
            duration_s=time.perf_counter() - start,
            output_tail="\n".join(tail),
            log_path=log_path,
            timed_out=timed_out,
        )

    async def _pump(
        self,
        proc: asyncio.subprocess.Process,
        log_file: BinaryIO,
        tail: deque[str],
        on_line: Callable[[str], None],
    ) -> None:
        assert proc.stdout is not None
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        splitter = LineSplitter(max_len=self._max_line_len)

        def emit(lines: list[str]) -> None:
            for line in lines:
                clean = strip_ansi(line)
                tail.append(clean)
                on_line(clean)

        while chunk := await proc.stdout.read(_READ_CHUNK_BYTES):
            log_file.write(chunk)
            log_file.flush()
            emit(splitter.feed(decoder.decode(chunk)))
        emit(splitter.flush(decoder.decode(b"", final=True)))
        await proc.wait()

    async def _kill_group(self, proc: asyncio.subprocess.Process) -> None:
        """Sends SIGTERM to the command's process group, then SIGKILL after the grace period."""
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(proc.wait(), self._kill_grace_s)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)
            await proc.wait()
