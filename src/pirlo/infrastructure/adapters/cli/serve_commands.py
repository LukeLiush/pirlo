from __future__ import annotations

import argparse
import getpass
import os
import signal
import socket
import sys
import time
from datetime import UTC, datetime

from pirlo.core.config import (
    DEFAULT_PREFECT_PORT,
    DEFAULT_WORK_POOL,
    DEFAULT_WORKER_LIMIT,
)
from pirlo.core.ports.process_supervisor import ProcessSupervisor
from pirlo.infrastructure.adapters.orchestrator.prefect_health import (
    is_prefect_healthy,
)
from pirlo.infrastructure.adapters.orchestrator.prefect_serve import (
    NoFreePortError,
    free_loopback_port,
    server_process,
    worker_process,
)
from pirlo.infrastructure.adapters.orchestrator.prefect_work_pool import (
    is_worker_online,
)
from pirlo.infrastructure.adapters.orchestrator.serve_beacon import (
    ServeBeacon,
    ServeRecord,
    is_alive,
)
from pirlo.infrastructure.adapters.process.honcho_supervisor import HonchoSupervisor

NOT_RUNNING = "pirlo serve isn't running."


def _ui_url(record: ServeRecord) -> str:
    return record.api_url.removesuffix("/api")


def _serve(beacon: ServeBeacon, supervisor: ProcessSupervisor) -> int:
    existing = beacon.read()
    if existing and is_alive(existing.pid):
        print(
            f"pirlo serve is already running (pid {existing.pid}) at "
            f"{_ui_url(existing)}; see it with 'pirlo serve --status'."
        )
        return 0

    try:
        port = free_loopback_port(DEFAULT_PREFECT_PORT)
    except NoFreePortError as exc:
        print(f"Couldn't start the Prefect server: {exc}", file=sys.stderr)
        return 1
    record = ServeRecord(
        pid=os.getpid(),
        port=port,
        api_url=f"http://127.0.0.1:{port}/api",
        worker=socket.gethostname(),
        started_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )

    print(f"Prefect UI:  {_ui_url(record)}")
    print(
        f"Worker:      {record.worker} on {DEFAULT_WORK_POOL}, up to "
        f"{DEFAULT_WORKER_LIMIT} runs at once"
    )
    print("Runs now report here: pirlo <play>; routines run on the worker.")
    print("From another machine, tunnel over SSH:")
    print(
        f"  ssh -L {port}:127.0.0.1:{port} {getpass.getuser()}@{socket.gethostname()}"
    )
    print("Stop with Ctrl-C, or 'pirlo serve --stop' from another terminal.")
    print(flush=True)

    beacon.write(record)
    try:
        return supervisor.run(
            [server_process(port), worker_process(record.api_url, record.worker)]
        )
    finally:
        beacon.forget()


def _status(beacon: ServeBeacon) -> int:
    record = beacon.read()
    if record is None or not is_alive(record.pid):
        beacon.forget()
        print(NOT_RUNNING)
        return 1
    healthy = is_prefect_healthy(record.api_url)
    online = healthy and is_worker_online(
        record.api_url, DEFAULT_WORK_POOL, record.worker
    )
    print(f"Prefect UI:  {_ui_url(record)}")
    print(f"pirlo serve: pid {record.pid} (since {record.started_at})")
    print(f"Server:      {'answering' if healthy else 'not answering yet'}")
    print(
        f"Worker:      {record.worker} on {DEFAULT_WORK_POOL}, "
        f"{'online' if online else 'not online yet'}"
    )
    return 0


def _stop(beacon: ServeBeacon, timeout: float) -> int:
    record = beacon.read()
    if record is None or not is_alive(record.pid):
        beacon.forget()
        print(NOT_RUNNING)
        return 0
    # A PID alone could belong to another process by now; the server answering
    # on the recorded port is the evidence that it is still pirlo serve.
    if not is_prefect_healthy(record.api_url):
        print(
            f"No Prefect server answers at {record.api_url}, so pid {record.pid} may "
            "not be pirlo serve; not stopping it. If pirlo serve is still starting, "
            "try again in a moment.",
            file=sys.stderr,
        )
        return 1

    os.kill(record.pid, signal.SIGTERM)
    deadline = time.monotonic() + timeout
    while is_alive(record.pid):
        if time.monotonic() > deadline:
            print(
                f"pirlo serve (pid {record.pid}) is still running after "
                f"{timeout:.0f}s.",
                file=sys.stderr,
            )
            return 1
        time.sleep(0.2)
    print("Stopped pirlo serve: the Prefect server and worker.")
    return 0


def serve_main(
    argv: list[str] | None = None,
    supervisor: ProcessSupervisor | None = None,
    beacon: ServeBeacon | None = None,
    stop_timeout: float = 30.0,
) -> int:
    parser = argparse.ArgumentParser(
        prog="pirlo serve",
        description=(
            "Run a Prefect server on 127.0.0.1 that pirlo runs report to, and a "
            "worker on this host that runs scheduled routines, in this terminal. "
            "Ctrl-C stops both."
        ),
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "-s",
        "--status",
        action="store_true",
        help="Show whether pirlo serve, its server and its worker are running",
    )
    action.add_argument(
        "--stop",
        action="store_true",
        help="Stop a pirlo serve running in another terminal",
    )
    args = parser.parse_args(sys.argv[2:] if argv is None else argv)

    record_file = beacon or ServeBeacon()
    if args.stop:
        return _stop(record_file, stop_timeout)
    if args.status:
        return _status(record_file)

    return _serve(record_file, supervisor or HonchoSupervisor())
