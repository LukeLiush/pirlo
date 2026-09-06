import os

# Disable third-party telemetry (e.g. browser-use PostHog telemetry) by default
os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")
# Silence Prefect's default console handler so Pirlo's terminal presentation remains clean
os.environ.setdefault("PREFECT_LOGGING_HANDLERS_CONSOLE_LEVEL", "ERROR")

__version__ = "0.1.0"
