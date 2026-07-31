import io
import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

from pirlo.core.models.run import Run, RunCreateDTO, RunStatus
from pirlo.core.services.run_id_generator import generate_run_id, generate_task_id
from pirlo.infrastructure.adapters.cli.tee import main as tee_main
from pirlo.infrastructure.adapters.db.sqlite_run_history_repository import (
    SqliteRunHistoryRepository,
)
from pirlo.infrastructure.adapters.gui.controller import ConsoleController
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

        # MVC Controller
        self.controller = ConsoleController(
            workspace=self.test_dir,
            run_repository=self.repository,
            parameter_storage=self.parameter_storage,
        )

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

    def test_controller_kickoff_run_flow(self):
        params = {"profile": "default", "verbose": True}
        dto = RunCreateDTO(playbook="dummy", parameters=params)

        # Kickoff
        run = self.controller.kickoff_run(dto)

        self.assertEqual(run.playbook, "dummy")
        self.assertEqual(run.status, RunStatus.NOT_STARTED)
        self.assertIsNotNone(run.task_id)

        # Verify run was saved to database
        db_run = self.repository.get_by_id(run.run_id)
        self.assertIsNotNone(db_run)
        self.assertEqual(db_run.task_id, run.task_id)

        # Verify parameter file was written by ParameterStorage under task_id (stable path)
        param_abs_path = run.get_parameter_location(self.test_dir)
        self.assertTrue(param_abs_path.exists())
        with open(param_abs_path, "r", encoding="utf-8") as f:
            written_params = json.load(f)
        self.assertEqual(written_params, params)

    def test_tee_redirection_cross_platform(self):
        log_file = self.test_dir / "logs" / "tee_test.log"
        test_data = b"Hello, this is a stdout pipe test line!\nAnd another line."

        # Mock sys.stdin.buffer and sys.stdout.buffer
        original_stdin = sys.stdin
        original_stdout = sys.stdout
        original_argv = sys.argv

        sys.stdin = MagicMock()
        sys.stdin.buffer = io.BytesIO(test_data)

        sys.stdout = MagicMock()
        mock_stdout_buffer = io.BytesIO()
        sys.stdout.buffer = mock_stdout_buffer

        sys.argv = ["tee.py", str(log_file)]

        try:
            tee_main()
        finally:
            sys.stdin = original_stdin
            sys.stdout = original_stdout
            sys.argv = original_argv

        # Verify written file content
        self.assertTrue(log_file.exists())
        with open(log_file, "rb") as f:
            written_data = f.read()
        self.assertEqual(written_data, test_data)

        # Verify printed console content
        self.assertEqual(mock_stdout_buffer.getvalue(), test_data)


if __name__ == "__main__":
    unittest.main()
