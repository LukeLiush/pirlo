from pathlib import Path
from unittest.mock import patch

from pirlo.playbooks.connect.adapters.ssh_key_helper import (
    PRIVATE_KEY_PERMISSIONS,
    PUBLIC_KEY_PERMISSIONS,
    ensure_local_ssh_key,
)


def test_ensure_local_ssh_key_returns_existing_key(tmp_path: Path):
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir()
    existing_pub_key = ssh_dir / "id_rsa.pub"
    existing_pub_key.write_text("ssh-rsa AAAAB3NzaC1yc2E... user@host")

    with patch("pathlib.Path.expanduser", return_value=ssh_dir):
        pub_key = ensure_local_ssh_key()

    assert pub_key == existing_pub_key
    assert pub_key.exists()


def test_ensure_local_ssh_key_generates_new_ed25519_key_pair(tmp_path: Path):
    ssh_dir = tmp_path / ".ssh"

    with patch("pathlib.Path.expanduser", return_value=ssh_dir):
        pub_key = ensure_local_ssh_key()

    assert pub_key == ssh_dir / "id_ed25519.pub"
    assert pub_key.exists()
    assert (ssh_dir / "id_ed25519").exists()

    # Verify key content format
    assert pub_key.read_text().startswith("ssh-ed25519 ")

    # Verify file permissions
    assert (ssh_dir / "id_ed25519").stat().st_mode & 0o777 == PRIVATE_KEY_PERMISSIONS
    assert pub_key.stat().st_mode & 0o777 == PUBLIC_KEY_PERMISSIONS


def test_ensure_local_ssh_key_returns_none_on_cryptography_failure(tmp_path: Path):
    ssh_dir = tmp_path / ".ssh"

    with (
        patch("pathlib.Path.expanduser", return_value=ssh_dir),
        patch(
            "cryptography.hazmat.primitives.asymmetric.ed25519.Ed25519PrivateKey.generate",
            side_effect=RuntimeError("Cryptography engine error"),
        ),
    ):
        pub_key = ensure_local_ssh_key()

    assert pub_key is None
