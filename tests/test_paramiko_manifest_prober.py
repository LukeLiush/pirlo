import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pirlo.playbooks.connect.adapters.paramiko_manifest_prober import (
    ParamikoManifestProber,
)


def test_install_ssh_key_if_needed_no_key(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    prober = ParamikoManifestProber()
    mock_ssh = MagicMock()

    with (
        patch(
            "pirlo.playbooks.connect.adapters.paramiko_manifest_prober.ensure_local_ssh_key",
            return_value=None,
        ),
        caplog.at_level(logging.WARNING),
    ):
        result = prober.install_ssh_key_if_needed(mock_ssh)

    assert result is False
    assert "No local SSH public key found" in caplog.text
    mock_ssh.exec_command.assert_not_called()


def test_install_ssh_key_if_needed_success(tmp_path: Path):
    prober = ParamikoManifestProber()
    mock_ssh = MagicMock()

    pub_key = tmp_path / "id_ed25519.pub"
    pub_key.write_text("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestKey user@host")

    mock_stdout = MagicMock()
    mock_stdout.channel.recv_exit_status.return_value = 0
    mock_ssh.exec_command.return_value = (None, mock_stdout, MagicMock())

    with patch(
        "pirlo.playbooks.connect.adapters.paramiko_manifest_prober.ensure_local_ssh_key",
        return_value=pub_key,
    ):
        result = prober.install_ssh_key_if_needed(mock_ssh)

    assert result is True
    mock_ssh.exec_command.assert_called_once()


def test_install_ssh_key_if_needed_command_error(tmp_path: Path):
    prober = ParamikoManifestProber()
    mock_ssh = MagicMock()

    pub_key = tmp_path / "id_ed25519.pub"
    pub_key.write_text("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestKey user@host")

    mock_stdout = MagicMock()
    mock_stdout.channel.recv_exit_status.return_value = 1
    mock_stderr = MagicMock()
    mock_stderr.read.return_value = b"Permission denied"
    mock_ssh.exec_command.return_value = (None, mock_stdout, mock_stderr)

    with (
        patch(
            "pirlo.playbooks.connect.adapters.paramiko_manifest_prober.ensure_local_ssh_key",
            return_value=pub_key,
        ),
        pytest.raises(RuntimeError, match="Failed to append SSH key"),
    ):
        prober.install_ssh_key_if_needed(mock_ssh)


def test_fetch_manifest_logs_key_install_exception(caplog: pytest.LogCaptureFixture):
    prober = ParamikoManifestProber()

    with patch("paramiko.SSHClient") as mock_ssh_cls:
        mock_client = MagicMock()
        mock_ssh_cls.return_value = mock_client
        mock_stdout = MagicMock()
        mock_stdout.read.return_value = b'{"default_prefect_port": 4200}'
        mock_client.exec_command.return_value = (None, mock_stdout, MagicMock())

        with (
            patch.object(
                prober,
                "install_ssh_key_if_needed",
                side_effect=RuntimeError("SSH key failure"),
            ),
            caplog.at_level(logging.ERROR),
        ):
            manifest = prober.fetch_manifest(
                "remote-host", ssh_password="secret_password"
            )

    assert manifest.default_prefect_port == 4200
    assert "Exception encountered while copying SSH public key" in caplog.text
