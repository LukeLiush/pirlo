from __future__ import annotations

import sys
from pathlib import Path

from pirlo.infrastructure.adapters.orchestrator.prefect_worker_gate import (
    run_gate,
    worker_command,
)

API_URL = "http://127.0.0.1:4200/api"


def _healthy_after(calls: int):
    seen: list[str] = []

    def is_healthy(api_url: str) -> bool:
        seen.append(api_url)
        return len(seen) >= calls

    return is_healthy, seen


def test_waits_for_the_server_then_prepares_the_pool_and_execs_the_worker():
    is_healthy, seen = _healthy_after(3)
    steps: list[object] = []

    run_gate(
        API_URL,
        "pirlo-pool",
        "desk",
        4,
        is_healthy=is_healthy,
        prepare_pool=lambda url, pool: steps.append(("pool", url, pool)),
        exec_worker=lambda cmd: steps.append(("exec", cmd)),
        poll=0,
    )

    assert seen == [API_URL] * 3
    assert steps == [
        ("pool", API_URL, "pirlo-pool"),
        ("exec", worker_command("pirlo-pool", "desk", 4)),
    ]


def test_gives_up_without_starting_the_worker_when_the_server_never_answers(capsys):
    steps: list[object] = []

    code = run_gate(
        API_URL,
        "pirlo-pool",
        "desk",
        4,
        is_healthy=lambda url: False,
        prepare_pool=lambda url, pool: steps.append("pool"),
        exec_worker=lambda cmd: steps.append("exec"),
        timeout=0,
        poll=0,
    )

    assert code == 1
    assert steps == []
    assert "did not answer" in capsys.readouterr().err


def test_worker_command_uses_pirlos_prefect():
    command = worker_command("pirlo-pool", "desk", 4)

    assert command[0] == str(Path(sys.executable).with_name("prefect"))
    assert command[1:] == [
        "worker",
        "start",
        "--pool",
        "pirlo-pool",
        "--type",
        "process",
        "--name",
        "desk",
        "--limit",
        "4",
    ]
