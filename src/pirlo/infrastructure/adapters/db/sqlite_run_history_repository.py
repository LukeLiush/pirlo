import sqlite3
from datetime import datetime
from typing import Any

from pirlo.core.models.run import Run, RunStatus, RunType
from pirlo.core.repository.run_history_repository import RunHistoryRepository


class SqliteRunHistoryRepository(RunHistoryRepository):
    def __init__(self, conn: sqlite3.Connection) -> None:
        """Accepts an injected Connection object. Can be in-memory or file-backed."""
        self.conn: sqlite3.Connection = conn
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        with self.conn:
            # Enable foreign key support
            self.conn.execute("PRAGMA foreign_keys = ON")

            # Check if run_name column exists to handle schema upgrade
            cursor = self.conn.execute("PRAGMA table_info(run_history)")
            columns = [row["name"] for row in cursor.fetchall()]
            if columns and "run_name" not in columns:
                self.conn.execute("DROP TABLE run_history")
                columns = []

            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS run_history (
                    run_id TEXT PRIMARY KEY,
                    run_name TEXT NOT NULL,
                    playbook TEXT NOT NULL,
                    run_type TEXT NOT NULL DEFAULT 'llm',
                    status TEXT NOT NULL,
                    parameter_file_location TEXT NOT NULL,
                    log_file_location TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT
                )
            """)

            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS run_step_history (
                    run_id TEXT NOT NULL,
                    step_number INTEGER NOT NULL,
                    action_type TEXT NOT NULL,
                    goal TEXT,
                    status TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    PRIMARY KEY (run_id, step_number),
                    FOREIGN KEY (run_id) REFERENCES run_history (run_id) ON DELETE CASCADE
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
                if "run_type" not in columns:
                    self.conn.execute(
                        "ALTER TABLE run_history ADD COLUMN run_type TEXT NOT NULL DEFAULT 'llm'"
                    )

    def save(self, run: Run) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO run_history (
                    run_id, run_name, playbook, run_type, status, parameter_file_location, log_file_location, created_at, updated_at, started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    run_name=excluded.run_name,
                    run_type=excluded.run_type,
                    status=excluded.status,
                    parameter_file_location=excluded.parameter_file_location,
                    log_file_location=excluded.log_file_location,
                    updated_at=excluded.updated_at,
                    started_at=excluded.started_at,
                    finished_at=excluded.finished_at
            """,
                (
                    run.run_id,
                    run.run_name,
                    run.playbook,
                    run.run_type.value,
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
            run_name=row["run_name"],
            playbook=row["playbook"],
            run_type=RunType(row["run_type"]),
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
        self,
        playbook: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Run]:
        query = "SELECT * FROM run_history"
        conditions = []
        params: list[Any] = []
        if playbook:
            conditions.append("playbook = ?")
            params.append(playbook)
        if status:
            conditions.append("status = ?")
            params.append(status.lower() if isinstance(status, str) else status)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY created_at DESC, updated_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = self.conn.execute(query, params).fetchall()
        return [
            Run(
                run_id=row["run_id"],
                run_name=row["run_name"],
                playbook=row["playbook"],
                run_type=RunType(row["run_type"]),
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

    def save_step(
        self,
        run_id: str,
        step_number: int,
        action_type: str,
        status: str,
        goal: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO run_step_history (
                    run_id, step_number, action_type, goal, status, started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, step_number) DO UPDATE SET
                    action_type=excluded.action_type,
                    goal=excluded.goal,
                    status=excluded.status,
                    started_at=excluded.started_at,
                    finished_at=excluded.finished_at
            """,
                (
                    run_id,
                    step_number,
                    action_type,
                    goal,
                    status,
                    started_at.isoformat() if started_at else None,
                    finished_at.isoformat() if finished_at else None,
                ),
            )

    def get_steps(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM run_step_history WHERE run_id = ? ORDER BY step_number ASC",
            (run_id,),
        ).fetchall()
        return [
            {
                "run_id": row["run_id"],
                "step_number": row["step_number"],
                "action_type": row["action_type"],
                "goal": row["goal"],
                "status": row["status"],
                "started_at": datetime.fromisoformat(row["started_at"])
                if row["started_at"]
                else None,
                "finished_at": datetime.fromisoformat(row["finished_at"])
                if row["finished_at"]
                else None,
            }
            for row in rows
        ]
