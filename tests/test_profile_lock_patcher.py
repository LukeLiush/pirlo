from pathlib import Path

from pirlo.playbooks.autopass.adapters.profile_lock_patcher import (
    ChromiumProfileLockPatcher,
)


def test_chromium_profile_lock_patcher_clears_stale_locks(tmp_path: Path):
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir(parents=True, exist_ok=True)

    lock_file = profile_dir / "SingletonLock"
    cookie_file = profile_dir / "SingletonCookie"
    socket_file = profile_dir / "SingletonSocket"

    lock_file.write_text("fake_lock")
    cookie_file.write_text("fake_cookie")
    socket_file.write_text("fake_socket")

    assert lock_file.exists()
    assert cookie_file.exists()
    assert socket_file.exists()

    ChromiumProfileLockPatcher.patch(profile_dir)

    assert not lock_file.exists()
    assert not cookie_file.exists()
    assert not socket_file.exists()


def test_chromium_profile_lock_patcher_nonexistent_directory(tmp_path: Path):
    nonexistent = tmp_path / "does_not_exist"
    ChromiumProfileLockPatcher.patch(nonexistent)
