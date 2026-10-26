"""Starts a Prefect worker once its server answers.

`pirlo serve` starts the server and this gate together; the gate holds the
worker back until the server is healthy, makes sure the work pool exists,
then replaces itself with `prefect worker start`:

    python -m pirlo.infrastructure.adapters.orchestrator.prefect_worker_gate \\
        --api-url http://127.0.0.1:4200/api --name desk
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path

import httpx

from pirlo.core.config import DEFAULT_WORK_POOL, DEFAULT_WORKER_LIMIT
from pirlo.infrastructure.adapters.orchestrator.prefect_health import (
    is_prefect_healthy,
)
from pirlo.infrastructure.adapters.orchestrator.prefect_work_pool import (
    count_late_runs,
    ensure_work_pool,
)


def worker_command(pool: str, name: str, limit: int) -> list[str]:
    return [
        str(Path(sys.executable).with_name("prefect")),
        "worker",
        "start",
        "--pool",
        pool,
        "--type",
        "process",
        "--name",
        name,
        "--limit",
        str(limit),
    ]


def _prepare_pool(api_url: str, pool: str) -> None:
    try:
        created = ensure_work_pool(api_url, pool)
        print(f"Work pool {pool} {'created' if created else 'ready'}.")
        late = count_late_runs(api_url, pool)
    except httpx.HTTPError as exc:
        print(f"Warning: couldn't check work pool {pool}: {exc}", file=sys.stderr)
        return
    if late:
        print(
            f"{late} late run{'s are' if late != 1 else ' is'} waiting on {pool}; "
            "the worker will start on them."
        )


def run_gate(
    api_url: str,
    pool: str,
    name: str,
    limit: int,
    *,
    is_healthy: Callable[[str], bool] = is_prefect_healthy,
    prepare_pool: Callable[[str, str], None] = _prepare_pool,
    exec_worker: Callable[[list[str]], None] = lambda cmd: os.execv(cmd[0], cmd),
    timeout: float = 60.0,
    poll: float = 0.25,
) -> int:
    """Waits for the server, prepares the pool and execs the worker.

    Returns 1 if the server never answers; on success it does not return.
    """
    deadline = time.monotonic() + timeout
    while not is_healthy(api_url):
        if time.monotonic() > deadline:
            print(
                f"Prefect server at {api_url} did not answer within {timeout:.0f}s; "
                "not starting the worker.",
                file=sys.stderr,
            )
            return 1
        time.sleep(poll)

    prepare_pool(api_url, pool)
    # exec replaces this process; anything still buffered would be lost.
    sys.stdout.flush()
    sys.stderr.flush()
    exec_worker(worker_command(pool, name, limit))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--pool", default=DEFAULT_WORK_POOL)
    parser.add_argument("--limit", type=int, default=DEFAULT_WORKER_LIMIT)
    args = parser.parse_args(argv)
    return run_gate(args.api_url, args.pool, args.name, args.limit)


if __name__ == "__main__":
    sys.exit(main())
