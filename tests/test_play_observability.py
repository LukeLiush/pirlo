# tests/test_play_observability.py
from __future__ import annotations

import asyncio
import logging
from typing import Annotated

import pytest

from pirlo.core.decorators import play
from pirlo.core.logging_context import (
    generate_short_run_id,
    workflow_logging_context,
)
from pirlo.core.models.blueprint import PlayBlueprint, PlayOutput
from pirlo.core.models.parameters import Parameter
from pirlo.core.ports.play import Play
from pirlo.core.services.blueprint_extractor import BlueprintExtractor
from pirlo.core.services.masking import is_sensitive_key, mask_sensitive_data
from pirlo.infrastructure.adapters.orchestrator.prefect_compiler import (
    PrefectCompiler,
)
from pirlo.infrastructure.services.log_streamer import capture_play_stdio


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


def test_mask_sensitive_data_with_dataclass():
    from pirlo.core.models.link import LlmLink

    link = LlmLink(
        name="test",
        provider="gemini",
        model="gemini-2.5-flash",
        api_key="AIzaFAKE_test_key_not_real_1234567890",
    )
    raw = {"playmaker": link, "use_vision": False}
    masked = mask_sensitive_data(raw)

    assert masked["use_vision"] is False
    # The dataclass should be converted to a dict with api_key masked
    assert isinstance(masked["playmaker"], dict)
    assert masked["playmaker"]["api_key"] == "***"
    assert "AIzaFAKE_test_key_not_real_1234567890" not in str(masked)


def test_mask_sensitive_data_with_nested_list():
    from pirlo.core.models.link import LlmLink

    links = [
        LlmLink(name="a", provider="gemini", model="m1", api_key="secret_key_1"),
        LlmLink(name="b", provider="openai", model="m2", api_key="secret_key_2"),
    ]
    raw = {"models": links, "count": 2}
    masked = mask_sensitive_data(raw)

    assert masked["count"] == 2
    assert len(masked["models"]) == 2
    for item in masked["models"]:
        assert isinstance(item, dict)
        assert item["api_key"] == "***"
    assert "secret_key_1" not in str(masked)
    assert "secret_key_2" not in str(masked)


def test_llmlink_repr_masks_api_key():
    from pirlo.core.models.link import LlmLink

    link = LlmLink(
        name="test",
        provider="gemini",
        model="gemini-2.5-flash",
        api_key="AIzaFAKE_test_key_not_real_1234567890",
    )
    r = repr(link)
    assert "AIzaFAKE_test_key_not_real_1234567890" not in r
    assert "AIza" in r  # first 4 chars visible
    assert "7890" in r  # last 4 chars visible


def test_llmlink_to_safe_dict_masks_api_key():
    from pirlo.core.models.link import LlmLink

    link = LlmLink(
        name="test",
        provider="gemini",
        model="gemini-2.5-flash",
        api_key="AIzaFAKE_test_key_not_real_1234567890",
    )
    safe = link.to_safe_dict()
    raw = link.to_dict()

    # to_safe_dict masks the key
    assert safe["api_key"] != "AIzaFAKE_test_key_not_real_1234567890"
    assert "****" in safe["api_key"]

    # to_dict still returns the real key (needed for persistence)
    assert raw["api_key"] == "AIzaFAKE_test_key_not_real_1234567890"


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
        self.ui.commentary(f"Commentary for user {user}")
        self.ui.goal(f"Goal for user {user}")
        return SampleOutput(message=f"Hello, {user}!")


def test_play_logger_property():
    instance = SampleObservabilityPlay()
    assert isinstance(instance.logger, logging.Logger)
    assert instance.logger.name == "pirlo.play.obs_sample_play"


@pytest.mark.anyio
async def test_prefect_compiler_lifecycle_logging():
    blueprint: PlayBlueprint = BlueprintExtractor.extract_from_play(
        SampleObservabilityPlay,
        user_kwargs={"user": "admin", "password": "confidential_password"},
    )
    from pirlo.infrastructure.adapters.orchestrator.prefect_run_repository import (
        PrefectRunRepository,
    )
    from pirlo.infrastructure.adapters.orchestrator.prefect_runner import (
        PrefectRunner,
    )

    compiler = PrefectCompiler()
    runner = PrefectRunner(compiler=compiler, mode="ephemeral")

    run_id = generate_short_run_id()
    with workflow_logging_context(run_id):
        result = await runner.run(blueprint)

    assert isinstance(result, SampleOutput)
    assert result.message == "Hello, admin!"

    repo = PrefectRunRepository()
    run_record = await repo.get_by_id(run_id)
    assert run_record is not None
    assert len(run_record.play_runs) > 0

    play_run = run_record.play_runs[0]
    full_log_text = ""
    for _ in range(30):
        logs = [
            line
            async for line in repo.stream_play_logs(
                run_id, play_id=play_run.play_id, tail_lines=200
            )
        ]
        full_log_text = "\n".join(logs)
        if "Play START" in full_log_text:
            break
        await asyncio.sleep(0.1)

    # Verify Play START with masked password
    assert "Play START | inputs=" in full_log_text
    assert "'password': '***'" in full_log_text
    assert "confidential_password" not in full_log_text

    # Verify custom self.logger message forwarded to Prefect
    assert "Executing sample play with user admin" in full_log_text

    # Verify self.ui.commentary and self.ui.goal teed to Prefect
    assert "Commentary for user admin" in full_log_text
    assert "Goal for user admin" in full_log_text

    # Verify Play SUCCESS with duration
    assert "Play SUCCESS | duration=" in full_log_text
    assert "SampleOutput(message='Hello, admin!')" in full_log_text

    # Verify every line has the standardized [run_id/play_id] prefix
    assert len(logs) > 0
    expected_prefix = f"[{run_id}/{play_run.play_id}]"
    for line in logs:
        assert expected_prefix in line, f"Line missing prefix {expected_prefix}: {line}"


def test_get_log_level_resolution(monkeypatch: pytest.MonkeyPatch):
    from pirlo.core.config import get_log_level

    monkeypatch.delenv("PIRLO_LOG_LEVEL", raising=False)
    assert get_log_level() == logging.INFO

    monkeypatch.setenv("PIRLO_LOG_LEVEL", "DEBUG")
    assert get_log_level() == logging.DEBUG

    monkeypatch.setenv("PIRLO_LOG_LEVEL", "error")
    assert get_log_level() == logging.ERROR


def test_capture_play_stdio_captures_output():
    captured: list[str] = []
    with capture_play_stdio(on_line=captured.append):
        print("Hello from task!")
        print("Another task output line")

    assert "Hello from task!" in captured
    assert "Another task output line" in captured


@pytest.mark.anyio
async def test_cli_play_runner_log_flag_controls_prefect_console_level(
    monkeypatch: pytest.MonkeyPatch,
):
    import os
    import sys
    from unittest.mock import AsyncMock, MagicMock, patch

    from pirlo.infrastructure.adapters.cli.cli_play_runner import CliPlayRunner

    monkeypatch.setattr(sys, "argv", ["pirlo", "obs_sample_play", "-l"])
    with patch(
        "pirlo.infrastructure.adapters.cli.cli_play_runner.PlayRunnerFactory.get_runner"
    ) as mock_factory:
        mock_runner = MagicMock()
        mock_runner.run = AsyncMock(return_value=SampleOutput(message="hi"))
        mock_runner.get_dashboard_url.return_value = None
        mock_factory.return_value = mock_runner

        res = CliPlayRunner.run(SampleObservabilityPlay)
        if asyncio.iscoroutine(res):
            await res
        assert os.environ.get("PREFECT_LOGGING_HANDLERS_CONSOLE_LEVEL") == "INFO"
        assert os.environ.get("PREFECT_LOGGING_LEVEL") == "INFO"

    monkeypatch.setattr(sys, "argv", ["pirlo", "obs_sample_play"])
    with patch(
        "pirlo.infrastructure.adapters.cli.cli_play_runner.PlayRunnerFactory.get_runner"
    ) as mock_factory:
        mock_runner = MagicMock()
        mock_runner.run = AsyncMock(return_value=SampleOutput(message="hi"))
        mock_runner.get_dashboard_url.return_value = None
        mock_factory.return_value = mock_runner

        res = CliPlayRunner.run(SampleObservabilityPlay)
        if asyncio.iscoroutine(res):
            await res
        assert os.environ.get("PREFECT_LOGGING_HANDLERS_CONSOLE_LEVEL") == "ERROR"


@play(name="obs_failing_play", description="Failing play for testing")
class FailingObservabilityPlay(Play[SampleOutput]):
    async def execute(self) -> SampleOutput:
        raise ValueError("Simulated computation failure")


@pytest.mark.anyio
async def test_prefect_compiler_failure_lifecycle_logging():
    from pirlo.infrastructure.adapters.orchestrator.prefect_run_repository import (
        PrefectRunRepository,
    )
    from pirlo.infrastructure.adapters.orchestrator.prefect_runner import (
        PrefectRunner,
    )

    blueprint: PlayBlueprint = BlueprintExtractor.extract_from_play(
        FailingObservabilityPlay
    )
    compiler = PrefectCompiler()
    runner = PrefectRunner(compiler=compiler, mode="ephemeral")

    run_id = generate_short_run_id()
    with pytest.raises(ValueError), workflow_logging_context(run_id):
        await runner.run(blueprint)

    repo = PrefectRunRepository()
    run_record = await repo.get_by_id(run_id)
    assert run_record is not None
    assert len(run_record.play_runs) > 0

    play_run = run_record.play_runs[0]
    full_log_text = ""
    for _ in range(30):
        logs = [
            line
            async for line in repo.stream_play_logs(
                run_id, play_id=play_run.play_id, tail_lines=200
            )
        ]
        full_log_text = "\n".join(logs)
        if "Play START" in full_log_text:
            break
        await asyncio.sleep(0.1)

    # Verify Play START and Play FAILED with duration and exception
    assert "Play START | inputs=" in full_log_text
    assert "Play FAILED | duration=" in full_log_text
    assert "ValueError" in full_log_text


def test_identity_factory_generates_8_char_run_id():
    from pirlo.infrastructure.services.run_id_generator import IdentityFactory

    factory = IdentityFactory("test_play", {"foo": "bar"})
    run_id = factory.generate_run_id()
    assert len(run_id) == 8
    assert int(run_id, 16) >= 0


@pytest.mark.anyio
async def test_run_id_consistency_across_disk_and_logs():
    from pirlo.core.logging_context import workflow_logging_context
    from pirlo.infrastructure.adapters.orchestrator.prefect_run_repository import (
        PrefectRunRepository,
    )
    from pirlo.infrastructure.adapters.orchestrator.prefect_runner import PrefectRunner
    from pirlo.infrastructure.services.run_id_generator import IdentityFactory

    factory = IdentityFactory("sample", {"user": "alice"})
    run_id = factory.generate_run_id()
    assert len(run_id) == 8

    compiler = PrefectCompiler()
    runner = PrefectRunner(compiler=compiler, mode="ephemeral")
    blueprint = BlueprintExtractor.extract_from_play(
        SampleObservabilityPlay,
        user_kwargs={"user": "alice"},
    )

    with workflow_logging_context(run_id):
        await runner.run(blueprint)

    repo = PrefectRunRepository()
    run_record = await repo.get_by_id(run_id)
    assert run_record is not None
    assert run_record.run_id == run_id
