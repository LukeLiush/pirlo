# tests/test_shell.py
from __future__ import annotations

import logging
from pathlib import Path

import pytest
from command_runner_stub import StubCommandRunner

from pirlo.core.services.shell import CommandFailed, Shell

pytestmark = pytest.mark.anyio

LOGGER_NAME = "test.shell"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def shell_logs(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    return caplog


def _messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == LOGGER_NAME]


async def test_success_logs_invocation_then_streamed_output(shell_logs):
    stub = StubCommandRunner().respond("echo", "hi there", output="hi there\n")
    result = await Shell(stub, logging.getLogger(LOGGER_NAME)).run("echo", "hi there")

    assert result.exit_code == 0
    assert _messages(shell_logs) == ["$ echo 'hi there'", "hi there", "exit 0 in 0.0s"]


async def test_unexpected_exit_raises_with_result_attached():
    stub = StubCommandRunner().respond("brazil-build", exit_code=2)
    shell = Shell(stub, logging.getLogger(LOGGER_NAME))

    with pytest.raises(CommandFailed, match="`brazil-build` exited 2") as exc_info:
        await shell.run("brazil-build")
    assert exc_info.value.result.exit_code == 2


async def test_ok_codes_accept_an_expected_failure():
    stub = StubCommandRunner().respond("repro-bug", exit_code=1)
    result = await Shell(stub, logging.getLogger(LOGGER_NAME)).run(
        "repro-bug", ok_codes={1}
    )
    assert result.exit_code == 1


async def test_timeout_fails_even_when_exit_code_is_ok():
    stub = StubCommandRunner().respond("slow", exit_code=0, timed_out=True)
    shell = Shell(stub, logging.getLogger(LOGGER_NAME))

    with pytest.raises(CommandFailed, match="timed out"):
        await shell.run("slow", timeout_s=1.0)


async def test_builds_command_from_arguments(tmp_path: Path):
    stub = StubCommandRunner().respond("cat", str(tmp_path / "f.txt"))
    await Shell(stub, logging.getLogger(LOGGER_NAME)).run(
        "cat", tmp_path / "f.txt", cwd=tmp_path, env={"A": "1"}, timeout_s=5.0
    )

    command = stub.calls[0]
    assert command.argv == ("cat", str(tmp_path / "f.txt"))
    assert command.cwd == tmp_path
    assert dict(command.env) == {"A": "1"}
    assert command.timeout_s == 5.0


async def test_output_with_percent_signs_is_logged_verbatim(shell_logs):
    stub = StubCommandRunner().respond("progress", output="50% done %s %d\n")
    await Shell(stub, logging.getLogger(LOGGER_NAME)).run("progress")

    assert "50% done %s %d" in _messages(shell_logs)


async def test_stub_rejects_unknown_commands():
    shell = Shell(StubCommandRunner(), logging.getLogger(LOGGER_NAME))
    with pytest.raises(LookupError, match="no response"):
        await shell.run("typo")
