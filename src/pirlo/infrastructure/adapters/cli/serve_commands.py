from __future__ import annotations

import argparse
import getpass
import socket
import sys

import httpx

from pirlo.core.config import DEFAULT_PREFECT_PORT, DEFAULT_WORK_POOL
from pirlo.core.ports.local_server import (
    LocalServer,
    LocalServerError,
    LocalServerStatus,
)
from pirlo.core.ports.worker_fleet import WorkerFleet, WorkerFleetError, WorkerInfo
from pirlo.infrastructure.adapters.orchestrator.prefect_host_worker import (
    PrefectHostWorker,
)
from pirlo.infrastructure.adapters.orchestrator.prefect_local_server import (
    PrefectLocalServer,
)
from pirlo.infrastructure.adapters.orchestrator.prefect_work_pool import (
    count_late_runs,
    ensure_work_pool,
)


def _ui_url(status: LocalServerStatus) -> str:
    return status.api_url.removesuffix("/api")


def _print_server(status: LocalServerStatus) -> None:
    print(f"Prefect UI:  {_ui_url(status)}")
    print(f"PID:         {status.pid} (since {status.started_at})")
    print(f"Log:         {status.log_path}")


def _print_workers(workers: list[WorkerInfo]) -> None:
    if not workers:
        print("Worker:      none running")
    for worker in workers:
        print(
            f"Worker:      {worker.name} on {worker.pool}, up to {worker.limit} runs "
            f"at once (pid {worker.pid})"
        )


def _prepare_pool(api_url: str) -> None:
    try:
        created = ensure_work_pool(api_url)
        print(f"Work pool:   {DEFAULT_WORK_POOL} ({'created' if created else 'ready'})")
        late = count_late_runs(api_url)
    except httpx.HTTPError as exc:
        print(
            f"Warning: couldn't check work pool {DEFAULT_WORK_POOL}: {exc}",
            file=sys.stderr,
        )
        return
    if late:
        print(
            f"Note:        {late} late run{'s are' if late != 1 else ' is'} waiting on "
            f"{DEFAULT_WORK_POOL}; the worker will start on them."
        )


def serve_main(
    argv: list[str] | None = None,
    server: LocalServer | None = None,
    fleet: WorkerFleet | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        prog="pirlo serve",
        description=(
            "Start a Prefect server on 127.0.0.1 that pirlo runs report to, and a "
            "worker on this host that runs scheduled routines. Both keep running "
            "until 'pirlo serve --stop'."
        ),
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "-s",
        "--status",
        action="store_true",
        help="Show whether the server and worker are running",
    )
    action.add_argument(
        "--stop",
        action="store_true",
        help="Stop the worker and server pirlo serve started",
    )
    args = parser.parse_args(sys.argv[2:] if argv is None else argv)

    local: LocalServer = server or PrefectLocalServer()
    workers: WorkerFleet = fleet or PrefectHostWorker()

    if args.stop:
        stopped_workers = workers.stop()
        stopped_server = local.stop()
        if stopped_workers:
            print("Stopped the Prefect worker.")
        if stopped_server:
            print("Stopped the Prefect server.")
        if not (stopped_workers or stopped_server):
            print("No Prefect server started by pirlo serve is running.")
        return 0

    if args.status:
        running = local.status()
        if running is None:
            print("No Prefect server started by pirlo serve is running.")
            return 1
        _print_server(running)
        _print_workers(workers.status())
        return 0

    already = local.status()
    if already is None:
        print("Starting a Prefect server on 127.0.0.1...")
    try:
        status = already or local.start(DEFAULT_PREFECT_PORT)
    except LocalServerError as exc:
        print(f"Couldn't start the Prefect server: {exc}", file=sys.stderr)
        return 1

    print("Prefect server is running." if already else "Prefect server started.")
    _print_server(status)
    if not workers.status():
        _prepare_pool(status.api_url)
    try:
        running_workers = workers.start(status.api_url)
    except WorkerFleetError as exc:
        print(f"Couldn't start the Prefect worker: {exc}", file=sys.stderr)
        print("The server is still running; stop it with: pirlo serve --stop")
        return 1
    _print_workers(running_workers)

    print()
    print("Runs now report here: pirlo <play>; routines run on the worker.")
    print("From another machine, tunnel over SSH:")
    print(
        f"  ssh -L {status.port}:127.0.0.1:{status.port} "
        f"{getpass.getuser()}@{socket.gethostname()}"
    )
    print("Stop both with: pirlo serve --stop")
    return 0
