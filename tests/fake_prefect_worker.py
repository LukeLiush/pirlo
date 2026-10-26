"""A stand-in for `prefect worker start`: logs its environment, then idles.

Usage: python fake_prefect_worker.py POOL NAME LIMIT
"""

import os
import sys
import time

if __name__ == "__main__":
    pool, name, limit = sys.argv[1:4]
    print(f"worker {name} on {pool} limit={limit}", flush=True)
    print(f"PID={os.getpid()}", flush=True)
    print(f"PREFECT_API_URL={os.environ.get('PREFECT_API_URL')}", flush=True)
    print(f"PATH_FIRST={os.environ['PATH'].split(os.pathsep)[0]}", flush=True)
    print(
        f"CONSOLE_LEVEL={os.environ.get('PREFECT_LOGGING_HANDLERS_CONSOLE_LEVEL')}",
        flush=True,
    )
    while True:
        time.sleep(1)
