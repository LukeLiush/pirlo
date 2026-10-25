# tests/test_run_preparer.py
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pirlo.core.models.play_invocation import PlayInvocation
from pirlo.core.models.run import PreparedRun
from pirlo.infrastructure.adapters.cli.argument_parser_builder import (
    ArgumentParserBuilder,
)
from pirlo.infrastructure.services.parameter_resolution import ParameterResolver
from pirlo.infrastructure.services.run_preparer import RunPreparer
from pirlo.playbooks.demo.report_dag import SendAlertPlay


def _prepare(play_cls: Any, argv: list[str], workspace: Path) -> PreparedRun:
    invocation = PlayInvocation.from_raw(argv)
    builder = ArgumentParserBuilder(play_cls)
    parser = builder.build_parser(play_cls.play_name)
    resolver = ParameterResolver.create(
        playbook_parser=parser,
        playbook_invocation=invocation,
        pirlo_workspace=workspace,
        toml_config={},
    )
    return RunPreparer(builder.parameters, workspace, resolver).prepare(
        play_cls.play_name, invocation
    )


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("PIRLO_WORKSPACE", str(tmp_path))
    return tmp_path


def test_upstream_cli_flag_reaches_the_prepared_parameters(workspace: Path):
    prepared = _prepare(
        SendAlertPlay, ["--quarter", "Q1-2027", "--channel", "#ops"], workspace
    )

    assert prepared.parameters["quarter"] == "Q1-2027"  # declared on an upstream play
    assert prepared.parameters["channel"] == "#ops"  # declared on the target play


def test_upstream_parameter_defaults_are_resolved_when_omitted(workspace: Path):
    prepared = _prepare(SendAlertPlay, [], workspace)

    assert prepared.parameters["quarter"] == "Q3-2026"
    assert prepared.parameters["channel"] == "#finance"
