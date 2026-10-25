# tests/test_cli_upstream_parameters.py
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_upstream_flag_reaches_the_upstream_play(tmp_path: Path):
    """Runs the real `pirlo` CLI in a separate process, as a user would."""
    result = subprocess.run(
        [sys.executable, "-m", "pirlo", "demo_report_dag", "--quarter", "Q1-2027"],
        env={
            **os.environ,
            "PIRLO_WORKSPACE": str(tmp_path / "ws"),
            "PREFECT_HOME": str(tmp_path / "prefect"),
            "PREFECT_LOCAL_STORAGE_PATH": str(tmp_path / "store"),
            "COLUMNS": "200",  # wide terminal so the output isn't wrapped
        },
        capture_output=True,
        check=False,  # asserted below, with output shown on failure
        text=True,
        timeout=180,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    # --quarter is declared on demo_fetch_budget_target, an upstream play
    assert "Budget target loaded for Q1-2027" in result.stdout, result.stdout
