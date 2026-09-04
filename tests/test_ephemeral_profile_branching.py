from pathlib import Path

from pirlo.infrastructure.services.profile_manager import ProfileManager


def test_create_ephemeral_worker_profile(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(ProfileManager, "get_workspace_dir", lambda: tmp_path)

    master_profile = tmp_path / "profiles" / "default"
    master_profile.mkdir(parents=True, exist_ok=True)

    metadata_file = master_profile / "metadata.json"
    metadata_file.write_text('{"name": "default"}', encoding="utf-8")

    cookies_file = master_profile / "Cookies"
    cookies_file.write_text("dummy_cookie_data", encoding="utf-8")

    worker_dir, cleanup = ProfileManager.create_ephemeral_worker_profile("default")

    assert worker_dir.exists()
    assert "default_worker_" in worker_dir.name
    assert (worker_dir / "metadata.json").exists()
    assert (worker_dir / "Cookies").read_text(encoding="utf-8") == "dummy_cookie_data"

    cleanup()
    assert not worker_dir.exists()
