import os

# Disable third-party telemetry (e.g. browser-use PostHog telemetry) by default
os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")

__version__ = "0.1.0"
