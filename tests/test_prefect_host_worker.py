from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from pirlo.core.ports.worker_fleet import WorkerFleetError
from pirlo.infrastructure.adapters.orchestrator.prefect_host_worker import (
    PrefectHostWorker,
)
from pirlo.infrastructure.services.detached_process import is_alive

FAKE_WORKER = Path(__file__).with_name("fake_prefect_worker.py")
API_URL = "http://127.0.0.1:4200/api"


def _fake(pool: str, name: str, limit: int) -> list[str]:
    return [sys.executable, str(FAKE_WORKER), pool, name, str(limit)]


def _online_after(calls: int):
    seen: list[tuple[str, str, str]] = []

    def is_online(api_url: str, pool: str, name: str) -> bool:
        seen.append((api_url, pool, name))
        return len(seen) >= calls

    return is_online, seen


@pytest.fixture
def worker(tmp_path: Path) -> Iterator[PrefectHostWorker]:
    is_online, _ = _online_after(2)
    host = PrefectHostWorker(
        state_dir=tmp_path,
        name="desk",
        limit=3,
        command=_fake,
        is_online=is_online,
        stop_timeout=3,
    )
    yield host
    host.stop()


def test_start_records_an_online_worker_with_pirlos_python_first(worker):
    [info] = worker.start(API_URL)

    assert (info.name, info.pool, info.limit) == ("desk", "pirlo-pool", 3)
    assert is_alive(info.pid)
    assert json.loads(worker.state_path.read_text())["pid"] == info.pid
    log = info.log_path.read_text()
    assert f"PREFECT_API_URL={API_URL}" in log
    assert f"PATH_FIRST={Path(sys.executable).parent}" in log


def test_second_start_reuses_the_running_worker(worker):
    [first] = worker.start(API_URL)

    assert worker.start(API_URL) == [first]


def test_stop_ends_the_worker_and_forgets_it(worker):
    [info] = worker.start(API_URL)

    assert worker.stop() == 1

    assert not is_alive(info.pid)
    assert worker.status() == []
    assert not worker.state_path.exists()
    assert worker.stop() == 0


def test_worker_that_exits_early_reports_its_log(tmp_path):
    crash = lambda pool, name, limit: [
        sys.executable,
        "-c",
        "print('work pool type mismatch'); raise SystemExit(2)",
    ]
    host = PrefectHostWorker(
        state_dir=tmp_path, command=crash, is_online=lambda *_: False
    )

    with pytest.raises(WorkerFleetError, match="exited with code 2") as err:
        host.start(API_URL)

    assert "work pool type mismatch" in str(err.value)
    assert not host.state_path.exists()


def test_worker_that_never_comes_online_times_out_and_is_ended(tmp_path):
    is_online, seen = _online_after(10**9)
    host = PrefectHostWorker(
        state_dir=tmp_path,
        name="desk",
        command=_fake,
        is_online=is_online,
        startup_timeout=1,
        stop_timeout=3,
    )

    with pytest.raises(WorkerFleetError, match="did not come online"):
        host.start(API_URL)

    assert seen[0] == (API_URL, "pirlo-pool", "desk")
    assert host.status() == []
    log = (tmp_path / "prefect-worker.log").read_text()
    pid = int(next(line for line in log.splitlines() if line.startswith("PID="))[4:])
    assert not is_alive(pid)


def test_stale_state_for_a_dead_worker_is_discarded(tmp_path):
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    state = tmp_path / "prefect-worker.json"
    state.write_text(
        json.dumps(
            {
                "name": "desk",
                "pid": dead.pid,
                "pool": "pirlo-pool",
                "limit": 10,
                "started_at": "2026-01-01T00:00:00+00:00",
                "log_path": str(tmp_path / "prefect-worker.log"),
            }
        )
    )

    assert PrefectHostWorker(state_dir=tmp_path).status() == []
    assert not state.exists()
