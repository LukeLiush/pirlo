from abc import ABC

from pirlo.core.models.parameters import Parameter

PRESET_SCHEDULES: dict[str, str] = {
    "hourly": "0 * * * *",
    "daily": "0 9 * * *",
    "weekly": "0 9 * * 1",
    "monthly": "0 9 1 * *",
}


class ScheduleParameterResolver(ABC):
    def resolve(self, schedule: Parameter | None = None) -> str | None: ...
