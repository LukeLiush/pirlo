# tests/test_prefect_run_repository.py
import tempfile
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from pirlo.core.models.run import PlayRunDetail, Run, RunStatus
from pirlo.infrastructure.adapters.orchestrator.prefect_run_repository import (
    PrefectRunRepository,
    _extract_run_id,
    _map_prefect_state,
)


class TestPrefectRunRepository(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir: tempfile.TemporaryDirectory[str] = tempfile.TemporaryDirectory()
        self.workspace: Path = Path(self.temp_dir.name)
        self.patcher: Any = patch(
            "pirlo.infrastructure.adapters.orchestrator.prefect_run_repository.get_workspace_path",
            return_value=self.workspace,
        )
        self.patcher.start()
        self.repo: PrefectRunRepository = PrefectRunRepository()

    async def asyncTearDown(self) -> None:
        self.patcher.stop()
        self.temp_dir.cleanup()

    def test_state_mapping(self) -> None:
        self.assertEqual(_map_prefect_state("Completed"), RunStatus.COMPLETED)
        self.assertEqual(_map_prefect_state("Failed"), RunStatus.FAILED)
        self.assertEqual(_map_prefect_state("Crashed"), RunStatus.FAILED)
        self.assertEqual(_map_prefect_state("Running"), RunStatus.RUNNING)
        self.assertEqual(_map_prefect_state("Cancelled"), RunStatus.CANCELLED)
        self.assertEqual(_map_prefect_state("Skipped"), RunStatus.SKIPPED)
        self.assertEqual(_map_prefect_state("Pending"), RunStatus.STARTED)
        self.assertEqual(_map_prefect_state(None), RunStatus.NOT_STARTED)

    def test_extract_run_id(self) -> None:
        fr_with_tags: MagicMock = MagicMock(tags=["env:prod", "pirlo_id:e4f1a23c"])
        fr_with_tags.name = "random-flow-name"
        self.assertEqual(_extract_run_id(fr_with_tags), "e4f1a23c")

        fr_no_tags: MagicMock = MagicMock(tags=[])
        fr_no_tags.name = "b89d20f1"
        self.assertEqual(_extract_run_id(fr_no_tags), "b89d20f1")

    @patch(
        "pirlo.infrastructure.adapters.orchestrator.prefect_run_repository.get_client"
    )
    async def test_list_runs(self, mock_get_client: MagicMock) -> None:
        mock_client: AsyncMock = AsyncMock()
        mock_get_client.return_value.__aenter__.return_value = mock_client

        flow_id: uuid.UUID = uuid.uuid4()
        now: datetime = datetime.now(UTC)
        mock_flow_run: MagicMock = MagicMock()
        mock_flow_run.id = uuid.uuid4()
        mock_flow_run.name = "e4f1a23c"
        mock_flow_run.tags = ["pirlo_id:e4f1a23c"]
        mock_flow_run.flow_id = flow_id
        mock_flow_run.state_name = "Completed"
        mock_flow_run.total_run_time = timedelta(seconds=6.4)
        mock_flow_run.parameters = {"keyword": "espresso"}
        mock_flow_run.start_time = now
        mock_flow_run.end_time = now + timedelta(seconds=6.4)

        mock_flow: MagicMock = MagicMock()
        mock_flow.name = "ecommerce_buyer"

        mock_client.read_flow_runs.return_value = [mock_flow_run]
        mock_client.read_flow.return_value = mock_flow

        runs: list[Run] = await self.repo.list_runs(limit=5)
        self.assertEqual(len(runs), 1)
        r: Run = runs[0]
        self.assertEqual(r.run_id, "e4f1a23c")
        self.assertEqual(r.playbook, "ecommerce_buyer")
        self.assertEqual(r.status, RunStatus.COMPLETED)
        self.assertAlmostEqual(r.duration or 0, 6.4)
        self.assertEqual(r.parameters, {"keyword": "espresso"})

    @patch(
        "pirlo.infrastructure.adapters.orchestrator.prefect_run_repository.get_client"
    )
    async def test_get_by_id_with_plays(self, mock_get_client: MagicMock) -> None:
        mock_client: AsyncMock = AsyncMock()
        mock_get_client.return_value.__aenter__.return_value = mock_client

        flow_id: uuid.UUID = uuid.uuid4()
        fr_id: uuid.UUID = uuid.uuid4()
        now: datetime = datetime.now(UTC)

        mock_flow_run: MagicMock = MagicMock()
        mock_flow_run.id = fr_id
        mock_flow_run.name = "e4f1a23c"
        mock_flow_run.tags = ["pirlo_id:e4f1a23c"]
        mock_flow_run.flow_id = flow_id
        mock_flow_run.state_name = "Failed"
        mock_flow_run.state.is_failed.return_value = True
        mock_flow_run.state.message = "Task failure in play 2"
        mock_flow_run.total_run_time = timedelta(seconds=8.0)
        mock_flow_run.parameters = {"query": "beans"}
        mock_flow_run.start_time = now
        mock_flow_run.end_time = now + timedelta(seconds=8.0)

        mock_flow: MagicMock = MagicMock()
        mock_flow.name = "ecommerce_buyer"

        mock_client.read_flow_runs.return_value = [mock_flow_run]
        mock_client.read_flow.return_value = mock_flow

        # Mock two task runs (one completed, one failed)
        tr1: MagicMock = MagicMock()
        tr1.id = uuid.uuid4()
        tr1.name = "login#v1.0:1a2b3c"
        tr1.state_name = "Completed"
        tr1.state.is_failed.return_value = False
        tr1.total_run_time = timedelta(seconds=1.2)
        tr1.start_time = now
        tr1.end_time = now + timedelta(seconds=1.2)

        tr2: MagicMock = MagicMock()
        tr2.id = uuid.uuid4()
        tr2.name = "checkout#v1.0:4d5e6f"
        tr2.state_name = "Failed"
        tr2.state.is_failed.return_value = True
        tr2.state.message = "Out of stock"
        tr2.total_run_time = timedelta(seconds=2.5)
        tr2.start_time = now + timedelta(seconds=1.3)
        tr2.end_time = now + timedelta(seconds=3.8)

        mock_client.read_task_runs.return_value = [tr1, tr2]

        run: Run | None = await self.repo.get_by_id("e4f1a23c")
        self.assertIsNotNone(run)
        assert run is not None
        self.assertEqual(run.run_id, "e4f1a23c")
        self.assertEqual(run.status, RunStatus.FAILED)
        self.assertEqual(run.error_message, "Task failure in play 2")
        self.assertEqual(len(run.play_runs), 2)

        self.assertEqual(run.play_runs[0].play_id, "login#v1.0:1a2b3c")
        self.assertEqual(run.play_runs[0].play_name, "login")
        self.assertEqual(run.play_runs[0].status, RunStatus.COMPLETED)
        self.assertAlmostEqual(run.play_runs[0].duration or 0, 1.2)

        self.assertEqual(run.play_runs[1].play_id, "checkout#v1.0:4d5e6f")
        self.assertEqual(run.play_runs[1].play_name, "checkout")
        self.assertEqual(run.play_runs[1].status, RunStatus.FAILED)
        self.assertEqual(run.play_runs[1].error_message, "Out of stock")

    @patch(
        "pirlo.infrastructure.adapters.orchestrator.prefect_run_repository.get_client"
    )
    async def test_stream_play_logs_local_cache_hit(
        self, mock_get_client: MagicMock
    ) -> None:
        # Pre-seed local cache file
        playbook: str = "demo_pb"
        run_id: str = "a1b2c3d4"
        play_id: str = "step1#v1.0:998877"

        play_detail: PlayRunDetail = PlayRunDetail(
            play_run_id=str(uuid.uuid4()),
            play_name="step1",
            play_id=play_id,
            status=RunStatus.COMPLETED,
        )
        run_obj: Run = Run(
            run_id=run_id,
            playbook=playbook,
            status=RunStatus.COMPLETED,
            play_runs=[play_detail],
        )

        with patch.object(self.repo, "get_by_id", return_value=run_obj):
            log_file: Path = run_obj.get_play_log_path(self.workspace, play_id)
            log_file.parent.mkdir(parents=True, exist_ok=True)
            log_file.write_text("Line 1 from cache\nLine 2 from cache\n")

            lines: list[str] = [
                line
                async for line in self.repo.stream_play_logs(
                    run_id, play_id=play_id, tail_lines=10, follow=False
                )
            ]

            self.assertEqual(lines, ["Line 1 from cache", "Line 2 from cache"])
            # Prefect client should NOT even be called for completed cached play!
            mock_get_client.assert_not_called()

    @patch(
        "pirlo.infrastructure.adapters.orchestrator.prefect_run_repository.get_client"
    )
    async def test_stream_play_logs_fetch_and_cache(
        self, mock_get_client: MagicMock
    ) -> None:
        mock_client: AsyncMock = AsyncMock()
        mock_get_client.return_value.__aenter__.return_value = mock_client

        playbook: str = "demo_pb"
        run_id: str = "a1b2c3d4"
        play_id: str = "step1#v1.0:998877"
        task_uuid: uuid.UUID = uuid.uuid4()
        fr_uuid: uuid.UUID = uuid.uuid4()

        play_detail: PlayRunDetail = PlayRunDetail(
            play_run_id=str(task_uuid),
            play_name="step1",
            play_id=play_id,
            status=RunStatus.RUNNING,
        )
        run_obj: Run = Run(
            run_id=run_id,
            playbook=playbook,
            status=RunStatus.RUNNING,
            play_runs=[play_detail],
        )

        now: datetime = datetime(2026, 9, 8, 12, 0, 0, tzinfo=UTC)
        mock_log: MagicMock = MagicMock()
        mock_log.id = uuid.uuid4()
        mock_log.level = 20  # INFO
        mock_log.message = "Hello from prefect"
        mock_log.timestamp = now

        mock_flow_run: MagicMock = MagicMock(id=fr_uuid)
        mock_client.read_flow_runs.return_value = [mock_flow_run]
        mock_client.read_logs.return_value = [mock_log]

        with patch.object(self.repo, "get_by_id", return_value=run_obj):
            lines: list[str] = [
                line
                async for line in self.repo.stream_play_logs(
                    run_id, play_id=play_id, tail_lines=50, follow=False
                )
            ]

            self.assertEqual(len(lines), 1)
            self.assertIn(
                "12:00:00 [INFO] [a1b2c3d4/step1#v1.0:998877] Hello from prefect",
                lines[0],
            )

            # Verify local log file was saved
            log_file: Path = run_obj.get_play_log_path(self.workspace, play_id)
            self.assertTrue(log_file.exists())
            self.assertIn(
                "12:00:00 [INFO] [a1b2c3d4/step1#v1.0:998877] Hello from prefect",
                log_file.read_text(),
            )

            # Verify cursor was saved
            cursor_file: Path = log_file.with_suffix(".cursor")
            self.assertTrue(cursor_file.exists())
            self.assertEqual(cursor_file.read_text(), now.isoformat())
