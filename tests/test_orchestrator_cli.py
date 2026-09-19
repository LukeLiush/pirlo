from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from pirlo.infrastructure.adapters.cli.orchestrator_commands import (
    orchestrator_main,
)


def test_orchestrator_cli_crud(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PIRLO_WORKSPACE", str(tmp_path))

    # 1. List initially empty
    with patch.object(sys, "argv", ["pirlo", "orchestrator", "list"]):
        orchestrator_main()
    captured = capsys.readouterr().out
    assert "No orchestrator links registered" in captured

    # 2. Create prod link
    with patch.object(
        sys,
        "argv",
        [
            "pirlo",
            "orchestrator",
            "create",
            "prod",
            "--engine",
            "prefect",
            "--server",
            "http://prefect.prod:4200/api",
            "--work-pool",
            "prod-pool",
        ],
    ):
        orchestrator_main()
    captured = capsys.readouterr().out
    assert "created successfully" in captured

    # 3. List contains prod
    with patch.object(sys, "argv", ["pirlo", "orchestrator", "list"]):
        orchestrator_main()
    captured = capsys.readouterr().out
    assert "prod" in captured
    assert "prefect" in captured
    assert "http://prefect.prod:4200/api" in captured
    assert "work_pool=prod-pool" in captured

    # 4. Show prod
    with patch.object(sys, "argv", ["pirlo", "orchestrator", "show", "prod"]):
        orchestrator_main()
    captured = capsys.readouterr().out
    assert "Orchestrator Link: prod" in captured
    assert "prefect" in captured

    # 5. Delete prod
    with patch.object(sys, "argv", ["pirlo", "orchestrator", "delete", "prod"]):
        orchestrator_main()
    captured = capsys.readouterr().out
    assert "deleted successfully" in captured

    # 6. Verify deleted
    with patch.object(sys, "argv", ["pirlo", "orchestrator", "list"]):
        orchestrator_main()
    captured = capsys.readouterr().out
    assert "No orchestrator links registered" in captured


def test_orchestrator_cli_verify_and_engines(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PIRLO_WORKSPACE", str(tmp_path))

    # 1. Create link with --verify (ephemeral)
    with patch.object(
        sys,
        "argv",
        [
            "pirlo",
            "orchestrator",
            "create",
            "local-test",
            "--engine",
            "prefect",
            "--server",
            "ephemeral",
            "--verify",
        ],
    ):
        orchestrator_main()
    captured = capsys.readouterr().out
    assert "Verifying connection to 'local-test'" in captured
    assert "Local ephemeral Prefect engine is ready" in captured
    assert "created successfully" in captured

    # 2. Verify command on existing link
    with patch.object(sys, "argv", ["pirlo", "orchestrator", "verify", "local-test"]):
        orchestrator_main()
    captured = capsys.readouterr().out
    assert "Verifying orchestrator link 'local-test'" in captured
    assert "Local ephemeral Prefect engine is ready" in captured

    # 3. Engines list command
    with patch.object(sys, "argv", ["pirlo", "orchestrator", "engines"]):
        orchestrator_main()
    captured = capsys.readouterr().out
    assert "Registered Orchestrator Engines" in captured
    assert "prefect" in captured

    # 4. Engines schema command (inspect prefect)
    with patch.object(sys, "argv", ["pirlo", "orchestrator", "engines", "prefect"]):
        orchestrator_main()
    captured = capsys.readouterr().out
    assert "Engine: prefect" in captured
    assert "--server-url" in captured
    assert "--work-pool" in captured
