import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from pirlo.core.models.run import LogCursor
from pirlo.infrastructure.services.play_log_cache import PlayLogCache


class TestPlayLogCache(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir: tempfile.TemporaryDirectory[str] = tempfile.TemporaryDirectory()
        self.workspace: Path = Path(self.temp_dir.name)
        self.cache: PlayLogCache = PlayLogCache(workspace=self.workspace)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_append_and_read_cached_lines(self) -> None:
        playbook = "ecommerce"
        run_id = "run123"
        play_id = "login#v1.0:abc"
        ts = datetime(2026, 9, 12, 17, 0, 0, tzinfo=UTC)

        self.cache.append(playbook, run_id, play_id, "Line 1", ts, log_id="id-1")
        self.cache.append(playbook, run_id, play_id, "Line 2", ts, log_id="id-2")
        self.cache.append(playbook, run_id, play_id, "Line 3", ts, log_id="id-3")

        lines = self.cache.read_cached_lines(playbook, run_id, play_id, tail_lines=2)
        self.assertEqual(lines, ["Line 2", "Line 3"])

        cursor = self.cache.get_cursor(playbook, run_id, play_id)
        self.assertIsNotNone(cursor)
        self.assertEqual(cursor.lines_count, 3)
        self.assertEqual(cursor.last_log_id, "id-3")
        self.assertEqual(cursor.last_timestamp_utc, ts)

    def test_log_cursor_json_and_legacy_fallback(self) -> None:
        cursor_file = self.workspace / "test.cursor"
        cursor_file.parent.mkdir(parents=True, exist_ok=True)

        # 1. Structured JSON parsing
        cursor_data = {
            "last_timestamp_utc": "2026-09-13T00:11:21.071416+00:00",
            "last_timestamp_local": "2026-09-12 17:11:21-0700",
            "lines_count": 5,
            "last_log_id": "test-uuid",
            "updated_at": "2026-09-12 17:11:21-0700",
        }
        cursor_file.write_text(json.dumps(cursor_data), encoding="utf-8")
        parsed = LogCursor.from_file(cursor_file)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.lines_count, 5)
        self.assertEqual(parsed.last_log_id, "test-uuid")

        # 2. Legacy raw ISO string parsing fallback
        cursor_file.write_text("2026-09-13T00:11:21.071416+00:00", encoding="utf-8")
        legacy_parsed = LogCursor.from_file(cursor_file)
        self.assertIsNotNone(legacy_parsed)
        self.assertEqual(
            legacy_parsed.last_timestamp_utc,
            datetime(2026, 9, 13, 0, 11, 21, 71416, tzinfo=UTC),
        )
        self.assertEqual(legacy_parsed.lines_count, 0)
