from pathlib import Path

from pirlo.infrastructure.services.playbook_scanner import (
    PlaybookScanner,
)


def test_scan_existing_playbooks_dir():
    pkg_playbooks_dir = (
        Path(__file__).resolve().parents[1] / "src" / "pirlo" / "playbooks"
    )
    specs = PlaybookScanner.scan_directory(pkg_playbooks_dir)

    assert "login" in specs
    assert "dummy" in specs or "demo_dummy" in specs
    assert "autopass" in specs

    login_spec = specs["login"]
    assert login_spec.class_name == "LoginSession"
    assert "Launch a browser" in login_spec.description
    assert login_spec.module_path == "pirlo.playbooks.login"

    dummy_key = "demo_dummy" if "demo_dummy" in specs else "dummy"
    dummy_spec = specs[dummy_key]
    assert dummy_spec.class_name == "DummyPlay"
    assert "Dummy test session" in dummy_spec.description

    autopass_spec = specs["autopass"]
    assert autopass_spec.class_name == "AutopassPlay"
    assert "self-healing" in autopass_spec.description


def test_scan_file_missing_name_warning(tmp_path: Path, capsys):
    bad_file = tmp_path / "bad_playbook.py"
    bad_file.write_text(
        "from pirlo.core.decorators import playbook\n\n"
        "@playbook(description='Missing name')\n"
        "class BadSession:\n"
        "    pass\n"
    )

    spec = PlaybookScanner.scan_file(bad_file, root_dir=tmp_path)
    assert spec is None

    stderr = capsys.readouterr().err
    assert "missing the required 'name' argument" in stderr


def test_scan_file_extra_kwargs(tmp_path: Path):
    custom_file = tmp_path / "custom.py"
    custom_file.write_text(
        "from pirlo.core.decorators import playbook\n\n"
        "@playbook(name='custom', description='Custom task', timeout=30, is_experimental=True)\n"
        "class CustomSession:\n"
        "    pass\n"
    )

    spec = PlaybookScanner.scan_file(custom_file, root_dir=tmp_path)
    assert spec is not None
    assert spec.name == "custom"
    assert spec.description == "Custom task"
    assert spec.extra_kwargs.get("timeout") == 30
    assert spec.extra_kwargs.get("is_experimental") is True


def test_should_skip_file():
    assert PlaybookScanner._should_skip_file(Path("__init__.py")) is True
    assert PlaybookScanner._should_skip_file(Path("_private.py")) is True
    assert PlaybookScanner._should_skip_file(Path("tests/test_playbook.py")) is True
    assert (
        PlaybookScanner._should_skip_file(Path("src/pirlo/playbooks/login.py")) is False
    )
