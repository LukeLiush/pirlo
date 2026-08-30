import pytest
from rich.console import Console

from pirlo.core.ports.pitch import Pitch
from pirlo.core.ports.pitch_ui import PitchUI
from pirlo.infrastructure.adapters.cli.terminal_pitch_ui import TerminalPitchUI


class MockPitchUI(PitchUI):
    def __init__(self) -> None:
        self.calls: list[str] = []

    def header(self, title: str, subtitle: str | None = None) -> None:
        self.calls.append(f"header:{title}:{subtitle}")

    def status(self, message: str):
        self.calls.append(f"status:{message}")

        class DummyCtx:
            def __enter__(self):
                pass

            def __exit__(self, *args):
                pass

        return DummyCtx()

    def lineup(self, title: str, columns: list[str], rows: list[list[str]]) -> None:
        self.calls.append(f"lineup:{title}")

    async def var_check(self, message: str) -> None:
        self.calls.append(f"var_check:{message}")

    async def prompt_password(self, prompt_message: str) -> str:
        self.calls.append(f"prompt_password:{prompt_message}")
        return "secret123"

    def goal(self, message: str, detail: str | None = None) -> None:
        self.calls.append(f"goal:{message}")

    def red_card(self, message: str, detail: str | None = None) -> None:
        self.calls.append(f"red_card:{message}")

    def yellow_card(self, message: str, detail: str | None = None) -> None:
        self.calls.append(f"yellow_card:{message}")

    def commentary(self, message: str, detail: str | None = None) -> None:
        self.calls.append(f"commentary:{message}")


class CustomPitch(Pitch):
    async def play(self, *args, **kwargs):
        pass


def test_pitch_ui_delegation():
    mock_ui = MockPitchUI()
    pitch = CustomPitch(ui=mock_ui)

    pitch.ui.header("Test Header", subtitle="Sub")
    pitch.ui.goal("Goal scored!")
    pitch.ui.red_card("Error!")
    pitch.ui.yellow_card("Warning!")
    pitch.ui.commentary("Match commentary log")
    pitch.ui.lineup("Lineup", ["Col"], [["Val"]])

    assert "header:Test Header:Sub" in mock_ui.calls
    assert "goal:Goal scored!" in mock_ui.calls
    assert "red_card:Error!" in mock_ui.calls
    assert "yellow_card:Warning!" in mock_ui.calls
    assert "commentary:Match commentary log" in mock_ui.calls
    assert "lineup:Lineup" in mock_ui.calls


def test_pitch_uninitialized_error_guards():
    pitch = CustomPitch()
    with pytest.raises(
        RuntimeError, match="Pitch orchestrator has not been initialized"
    ):
        _ = pitch.orchestrator

    with pytest.raises(
        RuntimeError, match="Pitch prepared_run accessed before preparation"
    ):
        import asyncio

        asyncio.run(pitch.prepared_run())


def test_terminal_pitch_ui_console():
    console = Console(record=True)
    ui = TerminalPitchUI(console=console)
    ui.header("Terminal Banner", subtitle="Rich Output")
    ui.goal("Scored!")
    ui.red_card("Failed!")
    ui.yellow_card("Warning!")
    ui.commentary("Match update in progress", detail="Sub detail")

    output = console.export_text()
    assert "Terminal Banner" in output
    assert "Scored!" in output
    assert "Failed!" in output
    assert "Warning!" in output
    assert "Match update in progress" in output
