# tests/test_play_observability.py
from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Annotated

import pytest

from pirlo.core.decorators import play
from pirlo.core.models.blueprint import PlayBlueprint, PlayOutput
from pirlo.core.models.parameters import Parameter
from pirlo.core.ports.play import Play
from pirlo.core.services.blueprint_extractor import BlueprintExtractor
from pirlo.core.services.masking import is_sensitive_key, mask_sensitive_data
from pirlo.infrastructure.adapters.orchestrator.prefect_compiler import (
    PrefectCompiler,
)
from pirlo.infrastructure.services.log_streamer import capture_run_logs


def test_sensitive_key_detection():
    assert is_sensitive_key("password") is True
    assert is_sensitive_key("DB_PASSWORD") is True
    assert is_sensitive_key("api_key") is True
    assert is_sensitive_key("bearer_token") is True
    assert is_sensitive_key("client_secret") is True
    assert is_sensitive_key("username") is False
    assert is_sensitive_key("report_date") is False


def test_mask_sensitive_data():
    raw = {
        "username": "alice",
        "password": "super-secret-123",
        "nested": {
            "api_token": "tok_xyz789",
            "host": "localhost",
        },
        "custom_secret": "hidden_value",
    }
    masked = mask_sensitive_data(raw, sensitive_keys={"custom_secret"})

    assert masked["username"] == "alice"
    assert masked["password"] == "***"
    assert masked["nested"]["host"] == "localhost"
    assert masked["nested"]["api_token"] == "***"
    assert masked["custom_secret"] == "***"


def test_parameter_sensitive_flag():
    param = Parameter(help="Access token", sensitive=True)
    assert param.sensitive is True

    default_param = Parameter(help="Standard parameter")
    assert default_param.sensitive is False


class SampleOutput(PlayOutput):
    message: str


@play(name="obs_sample_play", description="Observability testing play")
class SampleObservabilityPlay(Play[SampleOutput]):
    async def execute(
        self,
        user: str = "tester",
        password: Annotated[str, Parameter(sensitive=True)] = "secret_pass",
    ) -> SampleOutput:
        self.logger.info("Executing sample play with user %s", user)
        return SampleOutput(message=f"Hello, {user}!")


def test_play_logger_property():
    instance = SampleObservabilityPlay()
    assert isinstance(instance.logger, logging.Logger)
    assert instance.logger.name == "pirlo.play.obs_sample_play"


@pytest.mark.anyio
async def test_prefect_compiler_lifecycle_logging(tmp_path: Path):
    blueprint: PlayBlueprint = BlueprintExtractor.extract_from_play(
        SampleObservabilityPlay,
        user_kwargs={"user": "admin", "password": "confidential_password"},
    )
    from pirlo.infrastructure.adapters.orchestrator.prefect_runner import (
        PrefectRunner,
    )

    compiler = PrefectCompiler()
    runner = PrefectRunner(compiler=compiler, mode="ephemeral")

    run_dir = tmp_path / "runs" / "test_run"
    with capture_run_logs(run_dir):
        result = await runner.run(blueprint)

    assert isinstance(result, SampleOutput)
    assert result.message == "Hello, admin!"

    log_path = run_dir / "run.log"
    assert log_path.exists()
    content = log_path.read_text(encoding="utf-8")

    # Verify Play START with masked password
    assert "Play START | inputs=" in content
    assert "'password': '***'" in content
    assert "confidential_password" not in content

    # Verify custom self.logger message
    assert "Executing sample play with user admin" in content

    # Verify Play SUCCESS with duration
    assert "Play SUCCESS | duration=" in content
    assert "SampleOutput(message='Hello, admin!')" in content


def test_get_log_level_resolution(monkeypatch: pytest.MonkeyPatch):
    from pirlo.core.config import get_log_level

    monkeypatch.delenv("PIRLO_LOG_LEVEL", raising=False)
    assert get_log_level() == logging.INFO

    monkeypatch.setenv("PIRLO_LOG_LEVEL", "DEBUG")
    assert get_log_level() == logging.DEBUG

    monkeypatch.setenv("PIRLO_LOG_LEVEL", "error")
    assert get_log_level() == logging.ERROR


def test_capture_run_logs_quiet_by_default(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    run_dir = tmp_path / "quiet_test"
    with capture_run_logs(run_dir, console_stream=False):
        logger = logging.getLogger("pirlo.test")
        logger.info("Hidden from console but captured to file")

    captured = capsys.readouterr()
    # Ensure nothing was streamed to console stdout
    assert "Hidden from console but captured to file" not in captured.out
    # Ensure file contains the record
    assert (run_dir / "run.log").exists()
    assert "Hidden from console but captured to file" in (run_dir / "run.log").read_text(encoding="utf-8")


def test_capture_run_logs_console_streaming(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    run_dir = tmp_path / "console_test"
    with capture_run_logs(run_dir, console_stream=True):
        logger = logging.getLogger("pirlo.test")
        logger.info("Structured console log event")

    captured = capsys.readouterr()
    assert "Structured console log event" in captured.out
    assert (run_dir / "run.log").exists()
    assert "Structured console log event" in (run_dir / "run.log").read_text(encoding="utf-8")


@play(name="obs_failing_play", description="Failing play for testing")
class FailingObservabilityPlay(Play[SampleOutput]):
    async def execute(self) -> SampleOutput:
        raise ValueError("Simulated computation failure")


@pytest.mark.anyio
async def test_prefect_compiler_failure_lifecycle_logging(tmp_path: Path):
    from pirlo.infrastructure.adapters.orchestrator.prefect_runner import (
        PrefectRunner,
    )

    blueprint: PlayBlueprint = BlueprintExtractor.extract_from_play(
        FailingObservabilityPlay
    )
    compiler = PrefectCompiler()
    runner = PrefectRunner(compiler=compiler, mode="ephemeral")

    run_dir = tmp_path / "runs" / "test_fail_run"
    with pytest.raises(Exception):
        with capture_run_logs(run_dir):
            await runner.run(blueprint)

    log_path = run_dir / "run.log"
    assert log_path.exists()
    content = log_path.read_text(encoding="utf-8")

    # Verify Play START and Play FAILED with duration and exception
    assert "Play START | inputs=" in content
    assert "Play FAILED | duration=" in content
    assert "ValueError: Simulated computation failure" in content
