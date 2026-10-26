from __future__ import annotations

import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

from pirlo.core.ports.process_supervisor import ProcessSpec
from pirlo.infrastructure.adapters.process.honcho_supervisor import HonchoSupervisor


def _python(name: str, code: str) -> ProcessSpec:
    return ProcessSpec(
        name=name, command=[sys.executable, "-c", code], env=dict(os.environ)
    )


def _wait_until(predicate, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return False


def _is_gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


def test_one_process_exiting_stops_the_rest_and_sets_the_exit_code(capsys):
    started = time.monotonic()

    code = HonchoSupervisor().run(
        [
            _python(
                "quick", "import sys; print('quick done', flush=True); sys.exit(3)"
            ),
            _python("slow", "import time; time.sleep(60)"),
        ]
    )

    assert code == 3
    assert time.monotonic() - started < 15
    assert "quick done" in capsys.readouterr().out


def test_each_process_gets_exactly_its_own_environment(capsys):
    env = {"PATH": os.environ["PATH"], "PIRLO_PROBE": "worker-only"}
    spec = ProcessSpec(
        name="probe",
        command=[
            sys.executable,
            "-c",
            "import os; print(os.environ.get('PIRLO_PROBE'), 'HOME' in os.environ)",
        ],
        env=env,
    )

    assert HonchoSupervisor().run([spec]) == 0
    assert "worker-only False" in capsys.readouterr().out


def test_hang_up_stops_the_children(tmp_path: Path):
    pid_file = tmp_path / "child.pid"
    script = tmp_path / "supervise.py"
    script.write_text(
        textwrap.dedent(
            f"""
            import os, sys
            from pirlo.core.ports.process_supervisor import ProcessSpec
            from pirlo.infrastructure.adapters.process.honcho_supervisor import (
                HonchoSupervisor,
            )

            child = (
                "import os, time; "
                "open({str(pid_file)!r}, 'w').write(str(os.getpid())); "
                "time.sleep(60)"
            )
            if __name__ == "__main__":
                spec = ProcessSpec("sleeper", [sys.executable, "-c", child], dict(os.environ))
                sys.exit(HonchoSupervisor().run([spec]))
            """
        )
    )
    supervisor = subprocess.Popen(
        [sys.executable, str(script)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        assert _wait_until(lambda: pid_file.exists() and pid_file.read_text())
        child_pid = int(pid_file.read_text())

        supervisor.send_signal(signal.SIGHUP)

        supervisor.wait(timeout=15)
        assert _wait_until(lambda: _is_gone(child_pid))
    finally:
        if supervisor.poll() is None:
            supervisor.kill()
