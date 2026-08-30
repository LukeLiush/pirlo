import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class ChromiumProfileLockPatcher:
    """Safely patches orphaned Chromium profile singleton locks before browser launch."""

    LOCK_FILES: tuple[str, ...] = (
        "SingletonLock",
        "SingletonCookie",
        "SingletonSocket",
    )

    @classmethod
    def patch(cls, profile_path: Path) -> None:
        """Clears stale Chromium singleton lock files/symlinks from the profile directory."""
        if not profile_path.exists():
            return

        for lock_filename in cls.LOCK_FILES:
            lock_path = profile_path / lock_filename
            if lock_path.exists() or lock_path.is_symlink():
                try:
                    lock_path.unlink()
                    logger.debug("Cleared stale Chromium lock file: %s", lock_path)
                except Exception as e:  # noqa: BLE001
                    logger.warning(
                        "Could not clear Chromium lock file %s: %s", lock_path, e
                    )
