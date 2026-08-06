from pathlib import Path

from pirlo.core.config import get_workspace_path


def test_get_workspace_path_default(monkeypatch, tmp_path):
    monkeypatch.delenv("PIRLO_WORKSPACE", raising=False)
    # Mock expanduser to use tmp_path
    monkeypatch.setattr(Path, "expanduser", lambda self: tmp_path / ".pirlo-pitch")
    workspace = get_workspace_path()
    assert workspace.exists()
    assert workspace == tmp_path / ".pirlo-pitch"


def test_get_workspace_path_custom_env(monkeypatch, tmp_path):
    custom_dir = tmp_path / "custom_pirlo_workspace"
    monkeypatch.setenv("PIRLO_WORKSPACE", str(custom_dir))
    workspace = get_workspace_path()
    assert workspace.exists()
    assert workspace == custom_dir
