import shutil
import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from pirlo.core.models.run import Run, RunStatus
from pirlo.core.services.run_id_generator import generate_run_id, generate_task_id
from pirlo.infrastructure.adapters.db.sqlite_run_history_repository import (
    SqliteRunHistoryRepository,
)
from pirlo.infrastructure.adapters.storage.json_file_parameter_storage import (
    JsonFileParameterStorage,
)


class TestRunHistoryAndMVC(unittest.TestCase):
    def setUp(self):
        # Create temp dir for workspace simulation
        self.test_dir = Path(tempfile.mkdtemp())

        # In-memory database connection for repository testing
        self.conn = sqlite3.connect(":memory:")
        self.repository = SqliteRunHistoryRepository(self.conn)

        # Parameter storage using temp dir workspace
        self.parameter_storage = JsonFileParameterStorage(self.test_dir)

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.test_dir)

    def test_run_id_generation_is_seeded_and_unique(self):
        playbook = "dummy"
        params = {"foo": "bar", "count": 10}

        # Task IDs are identical because inputs are identical
        task_id1 = generate_task_id(playbook, params)
        task_id2 = generate_task_id(playbook, params)
        self.assertEqual(task_id1, task_id2)

        # Sequential runs generate unique execution run IDs
        run_id1 = generate_run_id(task_id1)
        run_id2 = generate_run_id(task_id2)

        self.assertNotEqual(run_id1, run_id2)
        self.assertTrue(run_id1.startswith(task_id1))

    def test_sqlite_repository_save_and_retrieve(self):
        run = Run(
            run_id="test-run-12345678",
            task_id="test-task-abcdefgh",
            playbook="login",
            status=RunStatus.NOT_STARTED,
            parameter_file_location="login/logs/test-run-12345678_params.json",
            log_file_location="login/logs/test-run-12345678.log",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        # Save to DB
        self.repository.save(run)

        # Retrieve by ID
        fetched = self.repository.get_by_id(run.run_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.run_id, run.run_id)
        self.assertEqual(fetched.task_id, run.task_id)
        self.assertEqual(fetched.playbook, run.playbook)
        self.assertEqual(fetched.status, RunStatus.NOT_STARTED)
        self.assertIsNone(fetched.started_at)
        self.assertIsNone(fetched.finished_at)

        # Verify update (e.g. to STARTED)
        fetched.status = RunStatus.STARTED
        started_time = datetime.now(UTC)
        fetched.started_at = started_time
        fetched.updated_at = started_time
        self.repository.save(fetched)

        updated = self.repository.get_by_id(run.run_id)
        self.assertEqual(updated.status, RunStatus.STARTED)
        self.assertIsNotNone(updated.started_at)
        self.assertEqual(updated.started_at, started_time)
        self.assertIsNone(updated.finished_at)

        # Verify update to COMPLETED
        updated.status = RunStatus.COMPLETED
        finished_time = datetime.now(UTC)
        updated.finished_at = finished_time
        updated.updated_at = finished_time
        self.repository.save(updated)

        completed = self.repository.get_by_id(run.run_id)
        self.assertEqual(completed.status, RunStatus.COMPLETED)
        self.assertEqual(completed.started_at, started_time)
        self.assertEqual(completed.finished_at, finished_time)

    def test_sqlite_repository_pagination_and_counting(self):
        # Insert 12 runs
        for i in range(12):
            run = Run(
                run_id=f"run-{i}-abcdefgh",
                task_id="test-task-xyz",
                playbook="login" if i % 2 == 0 else "dummy",
                status=RunStatus.COMPLETED,
                parameter_file_location=f"dummy/logs/run-{i}_params.json",
                log_file_location=f"dummy/logs/run-{i}.log",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            self.repository.save(run)

        # Count all
        self.assertEqual(self.repository.count_runs(), 12)
        # Count filtered by playbook
        self.assertEqual(self.repository.count_runs("login"), 6)
        self.assertEqual(self.repository.count_runs("dummy"), 6)

        # Paginate (limit=5, offset=0)
        page1 = self.repository.list_runs(playbook=None, limit=5, offset=0)
        self.assertEqual(len(page1), 5)

        # Paginate offset
        page2 = self.repository.list_runs(playbook=None, limit=5, offset=10)
        self.assertEqual(len(page2), 2)

    def test_list_runs_with_status_filter(self):
        # Insert completed and failed runs
        for i in range(3):
            run = Run(
                run_id=f"completed-{i}",
                task_id="task-1",
                playbook="autopass",
                status=RunStatus.COMPLETED,
                parameter_file_location=f"p_{i}.json",
                log_file_location=f"l_{i}.log",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            self.repository.save(run)

        failed_run = Run(
            run_id="failed-1",
            task_id="task-2",
            playbook="autopass",
            status=RunStatus.FAILED,
            parameter_file_location="p_failed.json",
            log_file_location="l_failed.log",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.repository.save(failed_run)

        # Query only failed runs
        failed_list = self.repository.list_runs(status="failed")
        self.assertEqual(len(failed_list), 1)
        self.assertEqual(failed_list[0].run_id, "failed-1")

        # Query completed runs
        completed_list = self.repository.list_runs(status="completed")
        self.assertEqual(len(completed_list), 3)

    def test_json_file_parameter_storage(self):
        params = {"url": "https://example.com", "headless": True}
        loc = "login/logs/test_run_params.json"

        # Save parameters
        self.parameter_storage.save_parameters(loc, params)

        # Check file exists in simulated workspace
        abs_path = self.test_dir / loc
        self.assertTrue(abs_path.exists())

        # Load parameters
        loaded = self.parameter_storage.load_parameters(loc)
        self.assertEqual(loaded, params)

    def test_sqlite_repository_run_type_and_step_executions(self):
        from pirlo.core.models.run import RunType

        # 1. Create a run with REPLAY type
        run = Run(
            run_id="replay-run-123",
            task_id="replay-task-123",
            playbook="login",
            run_type=RunType.REPLAY,
            status=RunStatus.NOT_STARTED,
            parameter_file_location="login/logs/replay-run-123_params.json",
            log_file_location="login/logs/replay-run-123.log",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.repository.save(run)

        # Verify run_type is preserved in DB retrieval
        fetched = self.repository.get_by_id(run.run_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.run_type, RunType.REPLAY)

        # 2. Save step execution history
        started_time = datetime.now(UTC)
        finished_time = datetime.now(UTC)

        # Step 1
        self.repository.save_step(
            run_id=run.run_id,
            step_number=1,
            action_type="navigate",
            status="completed",
            goal="Open target page",
            started_at=started_time,
            finished_at=finished_time,
        )
        # Step 2
        self.repository.save_step(
            run_id=run.run_id,
            step_number=2,
            action_type="click",
            status="running",
            goal="Click login button",
            started_at=started_time,
        )

        # 3. Retrieve and assert step executions
        steps = self.repository.get_steps(run.run_id)
        self.assertEqual(len(steps), 2)

        # Assert Step 1 properties
        step1 = steps[0]
        self.assertEqual(step1["step_number"], 1)
        self.assertEqual(step1["action_type"], "navigate")
        self.assertEqual(step1["status"], "completed")
        self.assertEqual(step1["goal"], "Open target page")
        self.assertEqual(step1["started_at"], started_time)
        self.assertEqual(step1["finished_at"], finished_time)

        # Assert Step 2 properties
        step2 = steps[1]
        self.assertEqual(step2["step_number"], 2)
        self.assertEqual(step2["action_type"], "click")
        self.assertEqual(step2["status"], "running")
        self.assertEqual(step2["goal"], "Click login button")
        self.assertEqual(step2["started_at"], started_time)
        self.assertIsNone(step2["finished_at"])

    def test_playwright_adapter_step_callback(self):
        from unittest.mock import AsyncMock

        from pirlo.core.models.actions import (
            ClickAction,
            ElementContext,
            NavigateAction,
        )
        from pirlo.core.models.workflow import Workflow
        from pirlo.infrastructure.adapters.browser.playwright_adapter import (
            PlaywrightAdapter,
        )

        # 1. Create a dummy workflow with actions
        actions = [
            NavigateAction(url="https://www.google.com"),
            ClickAction(
                element_context=ElementContext(
                    xpath="//button", tag_name="button", text="click me"
                )
            ),
        ]
        workflow = Workflow(
            workflow_id="dummy-flow", description="test description", actions=actions
        )

        # 2. Mock Playwright page and adapter
        mock_page = AsyncMock()
        mock_page.url = "https://www.google.com"
        mock_page.locator = MagicMock()

        # We need mock_page.locator(...).first to return a mock locator
        mock_locator = AsyncMock()
        mock_locator.scroll_into_view_if_needed = AsyncMock()
        mock_locator.evaluate = AsyncMock(
            side_effect=lambda js: "BUTTON" if "tagName" in js else {}
        )
        mock_locator.inner_text = AsyncMock(return_value="click me")
        mock_page.locator.return_value.first = mock_locator

        adapter = PlaywrightAdapter(mock_page)

        # Mock execute_action to prevent real browser actions
        adapter.execute_action = AsyncMock()

        # 3. Define callback to verify incremental invocations
        called_steps = []

        async def on_step_update(step_num: int, action):
            called_steps.append((step_num, action.status.value))

        # 4. Execute
        import asyncio

        original_sleep = asyncio.sleep
        asyncio.sleep = AsyncMock()  # Mock sleep to speed up test execution
        try:
            asyncio.run(
                adapter.execute_workflow(workflow, on_step_update=on_step_update)
            )
        finally:
            asyncio.sleep = original_sleep

        # 5. Verify the callback was called in sequence:
        # Step 1: not_started, Step 2: not_started (initial reset)
        # Step 1: running
        # Step 1: completed
        # Step 2: running
        # Step 2: completed
        self.assertIn((1, "not_started"), called_steps)
        self.assertIn((2, "not_started"), called_steps)
        self.assertIn((1, "running"), called_steps)
        self.assertIn((1, "completed"), called_steps)
        self.assertIn((2, "running"), called_steps)
        self.assertIn((2, "completed"), called_steps)

    def test_workflow_runner_cache_key_and_step_history(self):
        import asyncio

        from pirlo.core.models.actions import DoneAction, NavigateAction
        from pirlo.core.models.workflow import Workflow
        from pirlo.infrastructure.repository import JsonFileWorkflowRepository
        from pirlo.infrastructure.services.self_healing_workflow import (
            SelfHealingRunner,
        )

        cache_dir = Path(tempfile.mkdtemp())
        try:
            repo = JsonFileWorkflowRepository(directory=cache_dir)
            mock_replay = MagicMock()
            mock_replay.run = MagicMock(
                side_effect=lambda task_prompt, cache_key, run_id: asyncio.sleep(
                    0, result="replay result"
                )
            )
            mock_fallback = MagicMock()

            # Pre-save workflow cache using cache_key (run_name)
            run_name = "regista-12345678"
            run_id = "regista-12345678-20260811_123456_000000"
            workflow = Workflow(
                workflow_id=run_name,
                description="test task",
                actions=[
                    NavigateAction(url="https://google.com"),
                    DoneAction(text="done"),
                ],
            )
            repo.save(workflow)

            runner = SelfHealingRunner(
                replay_runner=mock_replay,
                fallback_runner=mock_fallback,
                repository=repo,
            )

            result = asyncio.run(
                runner.run(task_prompt="test prompt", cache_key=run_name, run_id=run_id)
            )
            self.assertEqual(result, "replay result")
            self.assertTrue(repo.exists(run_name))
        finally:
            shutil.rmtree(cache_dir)

    def test_run_show_displays_workflow_location(self):
        import io
        from contextlib import redirect_stdout

        from pirlo.infrastructure.adapters.cli.run_commands import run_show

        run_id = "test-show-run-1"
        run = Run(
            run_id=run_id,
            task_id="task-show-1",
            playbook="autopass",
            status=RunStatus.COMPLETED,
            parameter_file_location="autopass/runs/params.json",
            log_file_location="autopass/runs/test.log",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.repository.save(run)

        # Create target workflow json and an unrelated workflow json in runs dir
        runs_dir = self.test_dir / "autopass" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        target_wf = runs_dir / "task-show-1_workflow.json"
        target_wf.write_text('{"workflow_id": "task-show-1", "actions": []}')

        other_wf = runs_dir / "unrelated_task_workflow.json"
        other_wf.write_text('{"workflow_id": "unrelated_task", "actions": []}')

        with patch(
            "pirlo.infrastructure.adapters.cli.run_commands.get_repository"
        ) as mock_get_repo:
            mock_get_repo.return_value = (self.repository, self.test_dir)
            f = io.StringIO()
            with redirect_stdout(f):
                run_show(run_id)
            output = f.getvalue()

        self.assertIn("Artifacts & Recorded Logs", output)
        self.assertIn("task-show-1_workflow.json", output)
        self.assertNotIn("unrelated_task_workflow.json", output)
        self.assertNotIn("Workflow Snapshot Location:", output)

    def test_playwright_replay_runner_snapshots_workflow_to_run_dir(self):
        import asyncio

        from pirlo.core.models.actions import DoneAction, NavigateAction
        from pirlo.core.models.browser_config import BrowserConfig
        from pirlo.core.models.workflow import Workflow
        from pirlo.infrastructure.repository import JsonFileWorkflowRepository
        from pirlo.infrastructure.services.playwright_workflow import (
            PlaywrightReplayRunner,
        )

        cache_dir = Path(tempfile.mkdtemp())
        try:
            repo = JsonFileWorkflowRepository(directory=cache_dir)
            cache_key = "test_cache_key"
            run_id = "test_cache_key-20260811_123456_000000"
            wf = Workflow(
                workflow_id=cache_key,
                description="test task",
                actions=[
                    NavigateAction(url="https://example.com"),
                    DoneAction(text="done"),
                ],
            )
            repo.save(wf)

            runner = PlaywrightReplayRunner(
                repository=repo,
                llm=None,
                browser_config=BrowserConfig(cdp_url=None),
            )

            with patch(
                "pirlo.infrastructure.services.playwright_workflow.async_playwright"
            ) as mock_pw:
                mock_p = MagicMock()
                mock_browser = AsyncMock()
                mock_context = AsyncMock()
                mock_page = AsyncMock()
                mock_browser.new_context.return_value = mock_context
                mock_context.new_page.return_value = mock_page
                mock_p.chromium.launch = AsyncMock(return_value=mock_browser)
                mock_pw.return_value.__aenter__.return_value = mock_p

                with patch(
                    "pirlo.infrastructure.adapters.browser.playwright_adapter.PlaywrightAdapter.execute_workflow",
                    new_callable=AsyncMock,
                ):
                    asyncio.run(
                        runner.run(
                            task_prompt="test", cache_key=cache_key, run_id=run_id
                        )
                    )

            snapshot_file = cache_dir / run_id / f"{cache_key}_workflow.json"
            self.assertTrue(snapshot_file.exists())
        finally:
            shutil.rmtree(cache_dir)


if __name__ == "__main__":
    unittest.main()
