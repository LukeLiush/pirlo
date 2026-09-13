# tests/test_log_envelope.py
from __future__ import annotations

from datetime import UTC, datetime

from pirlo.core.ports.log_envelope import LogMetadata, UnpackedLog
from pirlo.infrastructure.services.log_formatter import (
    JsonLogEnvelope,
    LogPrefixStrategy,
    PlayLogFormatter,
)


def test_json_log_envelope_pack_and_unpack() -> None:
    envelope: JsonLogEnvelope = JsonLogEnvelope()

    # With Pydantic LogMetadata
    meta_in: LogMetadata = LogMetadata(pid=12345, play_name="demo")
    packed: str = envelope.pack("Test message", meta_in)
    assert packed == '[meta:{"pid":12345,"play_name":"demo"}] Test message'

    unpacked: UnpackedLog = envelope.unpack(packed)
    assert unpacked.clean_message == "Test message"
    assert unpacked.metadata.pid == 12345
    assert unpacked.metadata.play_name == "demo"

    # Tuple unpacking support
    clean_msg: str
    meta_out: LogMetadata
    clean_msg, meta_out = envelope.unpack(packed)
    assert clean_msg == "Test message"
    assert meta_out.pid == 12345

    # Without metadata
    assert envelope.pack("Simple message") == "Simple message"
    unpacked_empty: UnpackedLog = envelope.unpack("Simple message")
    assert unpacked_empty.clean_message == "Simple message"
    assert unpacked_empty.metadata.pid is None


def test_log_prefix_strategy() -> None:
    strategy: LogPrefixStrategy = LogPrefixStrategy()

    meta1: LogMetadata = LogMetadata(
        run_id="a1b2c3d4",
        play_id="select#v1.0:998877",
        pid=1234,
    )
    assert strategy.build_prefix(meta1) == "[a1b2c3d4/select#v1.0:998877 (pid 1234)]"

    meta2: LogMetadata = LogMetadata(
        play_name="report",
        play_version="2.0",
        pid=5678,
    )
    assert strategy.build_prefix(meta2) == "[report#v2.0 (pid 5678)]"


def test_play_log_formatter() -> None:
    formatter: PlayLogFormatter = PlayLogFormatter()
    dt: datetime = datetime(2026, 9, 12, 18, 44, 34, tzinfo=UTC)

    # 1. Enveloped message with explicit metadata
    raw: str = '[meta:{"pid":54321}] Processing batch 001/100...'
    line: str = formatter.format_line(
        raw_message=raw,
        timestamp=dt,
        level_name="INFO",
        explicit_metadata=LogMetadata(
            run_id="cca663ee", play_id="demo_select#v1.0:d88b62"
        ),
    )
    expected_ts: str = dt.astimezone().strftime("%Y-%m-%d %H:%M:%S%z")
    assert (
        line
        == f"{expected_ts} [INFO] [cca663ee/demo_select#v1.0:d88b62 (pid 54321)] Processing batch 001/100..."
    )

    # 2. Plain engine message without PID
    raw_engine: str = "Finished in state Completed()"
    engine_line: str = formatter.format_line(
        raw_message=raw_engine,
        timestamp=dt,
        level_name="INFO",
        explicit_metadata=LogMetadata(
            run_id="cca663ee", play_id="demo_select#v1.0:d88b62"
        ),
    )
    assert (
        engine_line
        == f"{expected_ts} [INFO] [cca663ee/demo_select#v1.0:d88b62] Finished in state Completed()"
    )
