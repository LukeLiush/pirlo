from typing import Any

from rich.console import Console

from pirlo.core.ports.play import Play
from pirlo.core.ports.play_ui import PlayUI
from pirlo.infrastructure.adapters.cli.terminal_play_ui import TerminalPlayUI


class MockPlayUI(PlayUI):
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

    def summary_card(
        self,
        run_id: str,
        playbook_name: str,
        status: str,
        duration: float,
        result_data: Any,
        dashboard_url: str | None = None,
        log_file_path: Any | None = None,
        parameter_file_path: Any | None = None,
    ) -> None:
        self.calls.append(f"summary_card:{run_id}:{status}")


class CustomPlay(Play[None]):
    async def execute(self) -> None:
        pass


def test_pitch_ui_delegation():
    mock_ui = MockPlayUI()
    play = CustomPlay(ui=mock_ui)

    play.ui.header("Test Header", subtitle="Sub")
    play.ui.goal("Goal scored!")
    play.ui.red_card("Error!")
    play.ui.yellow_card("Warning!")
    play.ui.commentary("Match commentary log")
    play.ui.lineup("Lineup", ["Col"], [["Val"]])

    assert "header:Test Header:Sub" in mock_ui.calls
    assert "goal:Goal scored!" in mock_ui.calls
    assert "red_card:Error!" in mock_ui.calls
    assert "yellow_card:Warning!" in mock_ui.calls
    assert "commentary:Match commentary log" in mock_ui.calls
    assert "lineup:Lineup" in mock_ui.calls


def test_terminal_play_ui_console():
    console = Console(record=True)
    ui = TerminalPlayUI(console=console)
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


def test_terminal_play_ui_run_id_prefix():
    console = Console(record=True)
    ui = TerminalPlayUI(
        play_name="demo_download_report#58f51a",
        run_id="49a3e670",
        console=console,
    )
    ui.commentary("Downloading report...")
    ui.goal("Download finished", detail="/tmp/reports/monthly_2026_08.pdf")
    ui.header("Step Header")
    ui.red_card("Step Error")
    ui.yellow_card("Step Warning")

    output = console.export_text()
    assert "[49a3e670/demo_download_report#58f51a]" in output
    assert "GOAL! Download finished" in output
    assert "/tmp/reports/monthly_2026_08.pdf" in output


def test_terminal_play_ui_discovers_run_id_from_context():
    from pirlo.core.logging_context import workflow_logging_context

    console = Console(record=True)
    with workflow_logging_context("49a3e670"):
        ui = TerminalPlayUI(
            play_name="demo_download_report#58f51a",
            console=console,
        )
        ui.goal("Download finished")

    output = console.export_text()
    assert "[49a3e670/demo_download_report#58f51a]" in output


def test_summary_card_local_mode(tmp_path):
    log_file = tmp_path / "run.log"
    param_file = tmp_path / "params.json"
    log_file.write_text("sample log", encoding="utf-8")
    param_file.write_text("{}", encoding="utf-8")

    console = Console(record=True)
    ui = TerminalPlayUI(console=console)
    ui.summary_card(
        run_id="8efd6618",
        playbook_name="demo_report_dag",
        status="SUCCESS",
        duration=3.14,
        result_data={"alert": True},
        dashboard_url=None,
        log_file_path=log_file,
        parameter_file_path=param_file,
    )
    output = console.export_text()
    assert "Execution Summary" in output
    assert "Run ID:     8efd6618" in output
    assert "Playbook:   demo_report_dag" in output
    assert "SUCCESS (completed in 3.14s)" in output
    assert "Log File:" in output
    assert "Params:" in output
    assert "pirlo run show 8efd6618" in output


def test_summary_card_remote_dashboard_mode(tmp_path):
    console = Console(record=True)
    ui = TerminalPlayUI(console=console)
    ui.summary_card(
        run_id="8efd6618",
        playbook_name="demo_report_dag",
        status="SUCCESS",
        duration=4.50,
        result_data="Done",
        dashboard_url="http://prefect.server:4200/flow-runs?name=8efd6618",
    )
    output = console.export_text()
    assert "Execution Summary" in output
    assert "Run ID:     8efd6618" in output
    assert "Dashboard:  http://prefect.server:4200/flow-runs?name=8efd6618" in output
    assert "pirlo run show" not in output


def test_summary_card_deployed_suppresses_cli_hint(tmp_path, monkeypatch):
    monkeypatch.setenv("PIRLO_DEPLOYED", "1")
    log_file = tmp_path / "run.log"
    param_file = tmp_path / "params.json"
    log_file.write_text("sample log", encoding="utf-8")
    param_file.write_text("{}", encoding="utf-8")

    console = Console(record=True)
    ui = TerminalPlayUI(console=console)
    ui.summary_card(
        run_id="8efd6618",
        playbook_name="demo_report_dag",
        status="SUCCESS",
        duration=2.00,
        result_data="Done",
        dashboard_url=None,
        log_file_path=log_file,
        parameter_file_path=param_file,
    )
    output = console.export_text()
    assert "Execution Summary" in output
    assert "pirlo run show" not in output
