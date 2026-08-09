PRESET_SCHEDULES: dict[str, str] = {
    "hourly": "0 * * * *",
    "daily": "0 9 * * *",
    "weekly": "0 9 * * 1",
    "monthly": "0 9 1 * *",
}


class ScheduleResolver:
    """Resolves human-readable schedule presets or raw cron expressions to standard 5-part cron syntax."""

    @classmethod
    def resolve(cls, schedule: str | None = None) -> str | None:
        if not schedule:
            return None

        clean_val = schedule.strip().lower()

        # 1. Match preset keywords
        if clean_val in PRESET_SCHEDULES:
            return PRESET_SCHEDULES[clean_val]

        # 2. Validate standard 5-part cron syntax (e.g., "0 9 * * *" or "*/15 * * * *")
        parts = schedule.strip().split()
        if len(parts) == 5:
            return schedule.strip()

        raise ValueError(
            f"Invalid schedule format '{schedule}'. Expected preset ('hourly', 'daily', 'weekly', 'monthly') "
            f"or standard 5-field cron expression (e.g. '0 9 * * *' or '*/15 * * * *')."
        )
