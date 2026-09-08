# tests/test_run_commands_cli.py
import io
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from pirlo.core.models.run import PlayRunDetail, Run, RunStatus
from pirlo.infrastructure.adapters.cli.run_commands import (
    format_status_markup,
    run_list,
    run_log,
    run_main,
    run_show,
)


class TestRunCommandsCLI(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir: tempfile.TemporaryDirectory[str] = tempfile.TemporaryDirectory()
        self.workspace: Path = Path(self.temp_dir.name)
        self.patcher: Any = patch(
            "pirlo.infrastructure.adapters.cli.run_commands.get_workspace_path",
            return_value=self.workspace,
        )
        self.patcher.start()

    def tearDown(self) -> None:
        self.patcher.stop()
        self.temp_dir.cleanup()

    def test_format_status_markup(self) -> None:
        self.assertIn("COMPLETED", format_status_markup(RunStatus.COMPLETED))
        self.assertIn("FAILED", format_status_markup(RunStatus.FAILED))
        self.assertIn("RUNNING", format_status_markup(RunStatus.RUNNING))

    @patch("pirlo.infrastructure.adapters.cli.run_commands.get_repository")
    def test_run_list_output(self, mock_get_repo: MagicMock) -> None:
        mock_repo: MagicMock = MagicMock()
        mock_get_repo.return_value = (mock_repo, self.workspace)

        run_item: Run = Run(
            run_id="e4f1a23c",
            playbook="ecommerce_buyer",
            status=RunStatus.COMPLETED,
            duration=6.4,
            parameters={"keyword": "espresso", "max": 5},
            started_at=datetime(2026, 9, 8, 15, 30, 0, tzinfo=UTC),
        )
        mock_repo.list_runs = AsyncMock(return_value=[run_item])

        with patch("sys.stdout", new=io.StringIO()) as fake_out:
            run_list(limit=5)
            output: str = fake_out.getvalue()

        self.assertIn("e4f1a23c", output)
        self.assertIn("ecommerce_buyer", output)
        self.assertIn("6.4s", output)
        self.assertIn("keyword=espresso", output)

    @patch("pirlo.infrastructure.adapters.cli.run_commands.get_repository")
    def test_run_show_minimal_play_layout(self, mock_get_repo: MagicMock) -> None:
        mock_repo: MagicMock = MagicMock()
        mock_get_repo.return_value = (mock_repo, self.workspace)

        p1: PlayRunDetail = PlayRunDetail(
            play_run_id="uuid-1",
            play_name="login",
            play_id="login#v1.0:1a2b3c",
            status=RunStatus.COMPLETED,
            duration=1.2,
        )
        p2: PlayRunDetail = PlayRunDetail(
            play_run_id="uuid-2",
            play_name="add_to_cart",
            play_id="add_to_cart#v1.0:d4e5f6",
            status=RunStatus.FAILED,
            duration=3.8,
            error_message="Item out of stock",
        )
        run_item: Run = Run(
            run_id="e4f1a23c",
            playbook="ecommerce_buyer",
            status=RunStatus.FAILED,
            duration=5.0,
            parameters={"keyword": "espresso machine", "max_results": 5},
            started_at=datetime(2026, 9, 8, 15, 30, 0, tzinfo=UTC),
            finished_at=datetime(2026, 9, 8, 15, 30, 5, tzinfo=UTC),
            error_message="Play 'add_to_cart#v1.0:d4e5f6' failed: Item out of stock",
            play_runs=[p1, p2],
        )
        mock_repo.get_by_id = AsyncMock(return_value=run_item)

        with patch("sys.stdout", new=io.StringIO()) as fake_out:
            run_show("e4f1a23c")
            output: str = fake_out.getvalue()

        self.assertIn("Run Inspection: e4f1a23c", output)
        self.assertIn("ecommerce_buyer", output)
        self.assertIn("keyword", output)
        self.assertIn("espresso machine", output)
        # Verify minimal play format: ✓ and ✗ present
        self.assertIn("login#v1.0:1a2b3c", output)
        self.assertIn("1.2s", output)
        self.assertIn("add_to_cart#v1.0:d4e5f6", output)
        self.assertIn("3.8s", output)
        # Verify log hint suggests the failed play
        self.assertIn("pirlo run log e4f1a23c/add_to_cart#v1.0:d4e5f6", output)

    @patch("pirlo.infrastructure.adapters.cli.run_commands.PrefectRunRepository")
    def test_run_log_slash_syntax_forwarding(self, mock_repo_cls: MagicMock) -> None:
        mock_repo: MagicMock = MagicMock()
        mock_repo_cls.return_value = mock_repo

        async def _fake_stream(*args: object, **kwargs: object):
            yield "15:30:14 [INFO] Play START"
            yield "15:30:18 [ERROR] Play FAILED"

        mock_repo.stream_play_logs = _fake_stream

        with patch("sys.stdout", new=io.StringIO()) as fake_out:
            run_log("e4f1a23c", play_id="add_to_cart#v1.0:d4e5f6", tail_lines=20)
            output: str = fake_out.getvalue()

        self.assertIn("15:30:14 [INFO] Play START", output)
        self.assertIn("15:30:18 [ERROR] Play FAILED", output)

    @patch("pirlo.infrastructure.adapters.cli.run_commands.run_log")
    def test_run_main_log_subcommand_parsing(self, mock_run_log: MagicMock) -> None:
        with patch(
            "sys.argv",
            ["pirlo", "run", "log", "e4f1a23c/step1#v1.0:abc", "-n", "30", "-f"],
        ):
            run_main()

        mock_run_log.assert_called_once_with(
            "e4f1a23c",
            play_id="step1#v1.0:abc",
            tail_lines=30,
            follow=True,
        )
