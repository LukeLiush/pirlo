from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock, patch

import pytest

from pirlo.core.decorators import play
from pirlo.core.models.blueprint import PlayOutput
from pirlo.core.ports.play import Play


class GreetingOutput(PlayOutput):
    message: str


@play(name="server_target_play", description="Play for server target CLI tests")
class ServerTargetPlay(Play[GreetingOutput]):
    async def execute(self) -> GreetingOutput:
        return GreetingOutput(message="hi")


@pytest.mark.anyio
async def test_cli_run_links_to_the_configured_prefect_server(monkeypatch, tmp_path):
    from pirlo.infrastructure.adapters.cli.cli_play_runner import CliPlayRunner

    monkeypatch.setenv("PIRLO_SERVER", "auto")
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("PIRLO_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["pirlo", "server_target_play"])
    monkeypatch.setattr(
        "pirlo.infrastructure.adapters.orchestrator.prefect_settings."
        "discover_prefect_server_url",
        lambda: "http://h:4200/api",
    )

    with (
        patch(
            "pirlo.infrastructure.adapters.orchestrator.prefect_runner."
            "PrefectRunner._run_immediate_once",
            new_callable=AsyncMock,
            return_value=GreetingOutput(message="hi"),
        ) as run_here,
        patch(
            "pirlo.infrastructure.adapters.cli.terminal_play_ui."
            "TerminalPlayUI.summary_card"
        ) as summary_card,
    ):
        result = CliPlayRunner.run(ServerTargetPlay)
        if asyncio.iscoroutine(result):
            result = await result

    run_here.assert_awaited_once()
    card = summary_card.call_args.kwargs
    assert card["status"] == "SUCCESS"
    assert card["dashboard_url"] == (f"http://h:4200/flow-runs?name={card['run_id']}")
