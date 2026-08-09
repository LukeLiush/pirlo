import pytest

from pirlo.core.services.schedule_resolver import ScheduleResolver


def test_resolve_none_returns_none():
    assert ScheduleResolver.resolve(None) is None
    assert ScheduleResolver.resolve("") is None


@pytest.mark.parametrize(
    ("preset", "expected_cron"),
    [
        ("hourly", "0 * * * *"),
        ("daily", "0 9 * * *"),
        ("weekly", "0 9 * * 1"),
        ("monthly", "0 9 1 * *"),
        ("HOURLY", "0 * * * *"),
        ("Daily", "0 9 * * *"),
    ],
)
def test_resolve_presets(preset: str, expected_cron: str):
    assert ScheduleResolver.resolve(preset) == expected_cron


@pytest.mark.parametrize(
    "cron_str",
    [
        "0 9 * * *",
        "*/15 * * * *",
        "0 12 * * 1-5",
        "0 0 1 1 *",
    ],
)
def test_resolve_raw_cron_expressions(cron_str: str):
    assert ScheduleResolver.resolve(cron_str) == cron_str


def test_resolve_invalid_format_raises_error():
    with pytest.raises(ValueError, match="Invalid schedule format 'invalid_preset'"):
        ScheduleResolver.resolve("invalid_preset")

    with pytest.raises(ValueError, match=r"Invalid schedule format '0 9 \*'"):
        ScheduleResolver.resolve("0 9 *")
