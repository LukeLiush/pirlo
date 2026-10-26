from __future__ import annotations

import os
import shlex
import signal
from types import FrameType

from honcho.manager import Manager

from pirlo.core.ports.process_supervisor import ProcessSpec, ProcessSupervisor


class HonchoSupervisor(ProcessSupervisor):
    """Runs processes with honcho: one prefixed output stream, stopped together.

    honcho stops everything on SIGINT and SIGTERM, but not on SIGHUP. Its
    children run in their own sessions, so a closed terminal would leave them
    running; this treats SIGHUP as a stop too.
    """

    def run(self, processes: list[ProcessSpec]) -> int:
        manager = Manager()
        for spec in processes:
            manager.add_process(spec.name, shlex.join(spec.command), env=spec.env)

        def _hang_up(signum: int, frame: FrameType | None) -> None:
            # The terminal is gone; writing to it would fail and abandon the children.
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, 1)
            os.dup2(devnull, 2)
            os.close(devnull)
            manager.terminate()

        handled = (signal.SIGHUP, signal.SIGINT, signal.SIGTERM)
        previous = {sig: signal.getsignal(sig) for sig in handled}
        signal.signal(signal.SIGHUP, _hang_up)
        try:
            manager.loop()
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
        return int(manager.returncode or 0)
