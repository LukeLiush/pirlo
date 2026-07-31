import sqlite3
from datetime import datetime
from typing import Any

from pirlo.core.models.run import Run, RunStatus
from pirlo.core.ports.run_history import RunHistoryRepository


class SqliteRunHistoryRepository(RunHistoryRepository):
    def __init__(self, conn: sqlite3.Connection):
        """Accepts an injected Connection object. Can be in-memory or file-backed."""
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        with self.conn:
            # Check if task_id column exists to handle schema upgrade
            cursor = self.conn.execute("PRAGMA table_info(run_history)")
            columns = [row["name"] for row in cursor.fetchall()]
            if columns and "task_id" not in columns:
                self.conn.execute("DROP TABLE run_history")
                columns = []

            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS run_history (
                    run_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    playbook TEXT NOT NULL,
                    status TEXT NOT NULL,
                    parameter_file_location TEXT NOT NULL,
                    log_file_location TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT
                )
            """)

            if columns:
                if "started_at" not in columns:
                    self.conn.execute(
                        "ALTER TABLE run_history ADD COLUMN started_at TEXT"
                    )
                if "finished_at" not in columns:
                    self.conn.execute(
                        "ALTER TABLE run_history ADD COLUMN finished_at TEXT"
                    )

    def save(self, run: Run) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO run_history (
                    run_id, task_id, playbook, status, parameter_file_location, log_file_location, created_at, updated_at, started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    task_id=excluded.task_id,
                    status=excluded.status,
                    parameter_file_location=excluded.parameter_file_location,
                    log_file_location=excluded.log_file_location,
                    updated_at=excluded.updated_at,
                    started_at=excluded.started_at,
                    finished_at=excluded.finished_at
            """,
                (
                    run.run_id,
                    run.task_id,
                    run.playbook,
                    run.status.value,
                    run.parameter_file_location,
                    run.log_file_location,
                    run.created_at.isoformat(),
                    run.updated_at.isoformat(),
                    run.started_at.isoformat() if run.started_at else None,
                    run.finished_at.isoformat() if run.finished_at else None,
                ),
            )

    def get_by_id(self, run_id: str) -> Run | None:
        row = self.conn.execute(
            "SELECT * FROM run_history WHERE run_id = ?", (run_id,)
        ).fetchone()
        if not row:
            return None
        return Run(
            run_id=row["run_id"],
            task_id=row["task_id"],
            playbook=row["playbook"],
            status=RunStatus(row["status"]),
            parameter_file_location=row["parameter_file_location"],
            log_file_location=row["log_file_location"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            started_at=datetime.fromisoformat(row["started_at"])
            if row["started_at"]
            else None,
            finished_at=datetime.fromisoformat(row["finished_at"])
            if row["finished_at"]
            else None,
        )

    def list_runs(
        self, playbook: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[Run]:
        query = "SELECT * FROM run_history"
        params: list[Any] = []
        if playbook:
            query += " WHERE playbook = ?"
            params.append(playbook)
        query += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = self.conn.execute(query, params).fetchall()
        return [
            Run(
                run_id=row["run_id"],
                task_id=row["task_id"],
                playbook=row["playbook"],
                status=RunStatus(row["status"]),
                parameter_file_location=row["parameter_file_location"],
                log_file_location=row["log_file_location"],
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
                started_at=datetime.fromisoformat(row["started_at"])
                if row["started_at"]
                else None,
                finished_at=datetime.fromisoformat(row["finished_at"])
                if row["finished_at"]
                else None,
            )
            for row in rows
        ]

    def count_runs(self, playbook: str | None = None) -> int:
        query = "SELECT COUNT(*) FROM run_history"
        params = []
        if playbook:
            query += " WHERE playbook = ?"
            params.append(playbook)

        return self.conn.execute(query, params).fetchone()[0]
