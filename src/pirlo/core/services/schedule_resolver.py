import contextlib
import datetime
import os
from abc import ABC

from pirlo.core.models.parameters import Parameter

PRESET_SCHEDULES: dict[str, str] = {
    "hourly": "0 * * * *",
    "daily": "0 9 * * *",
    "weekly": "0 9 * * 1",
    "monthly": "0 9 1 * *",
}


def get_schedule_help_text() -> str:
    """Generate CLI help description dynamically from PRESET_SCHEDULES."""
    presets_str = ", ".join(f"'{k}'" for k in PRESET_SCHEDULES)
    tz_name = detect_local_timezone()
    return (
        f"Schedule preset ({presets_str}) or raw cron string (e.g. '0 9 * * *') "
        f"[local timezone: {tz_name}, requires: Prefect Server & Work Pool, default: None (Immediate)]"
    )


def detect_local_timezone() -> str:
    """Auto-detect system local IANA timezone name with UTC fallback."""
    if os.environ.get("TZ"):
        return os.environ["TZ"]
    with contextlib.suppress(Exception):
        import tzlocal

        return str(tzlocal.get_localzone_name())
    with contextlib.suppress(Exception):
        link = os.readlink("/etc/localtime")
        if "zoneinfo/" in link:
            return link.split("zoneinfo/")[-1]
    with contextlib.suppress(Exception):
        tz = datetime.datetime.now().astimezone().tzinfo
        if tz:
            if hasattr(tz, "key") and tz.key:
                return str(tz.key)
            name = tz.tzname(datetime.datetime.now(datetime.UTC))
            if name:
                return name
    return "UTC"


class ScheduleParameterResolver(ABC):
    def resolve(self, schedule: Parameter | None = None) -> str | None: ...
