import json
import logging
from typing import Any

from pirlo.core.models.serve_manifest import ServeManifest
from pirlo.playbooks.connect.adapters.ssh_key_helper import ensure_local_ssh_key
from pirlo.playbooks.connect.ports.remote_manifest_prober import RemoteManifestProber

logger = logging.getLogger(__name__)


class ParamikoManifestProber(RemoteManifestProber):
    """Pure-Python Paramiko implementation of RemoteManifestProber (100% Cross-Platform)."""

    def install_ssh_key_if_needed(self, ssh_client: Any) -> bool:
        """Appends local SSH public key to remote ~/.ssh/authorized_keys idempotently.

        Returns:
            bool: True if key installation succeeded, False otherwise.
        """
        public_key_path = ensure_local_ssh_key()
        if not public_key_path or not public_key_path.exists():
            logger.warning(
                "[pirlo connect] No local SSH public key found or generated in ~/.ssh."
            )
            return False

        key_content = public_key_path.read_text().strip()
        if not key_content:
            logger.warning(
                "[pirlo connect] Local SSH public key file %s is empty.", public_key_path
            )
            return False

        clean_key = key_content.splitlines()[0].strip()
        cmd = (
            f"mkdir -p ~/.ssh && chmod 700 ~/.ssh && "
            f'grep -q -F "{clean_key}" ~/.ssh/authorized_keys 2>/dev/null || '
            f'echo "{clean_key}" >> ~/.ssh/authorized_keys && '
            f"chmod 600 ~/.ssh/authorized_keys"
        )
        _stdin, stdout, stderr = ssh_client.exec_command(cmd)
        exit_code = stdout.channel.recv_exit_status()
        if exit_code != 0:
            err_msg = stderr.read().decode("utf-8").strip()
            raise RuntimeError(
                f"Failed to append SSH key to remote authorized_keys (exit code {exit_code}): {err_msg}"
            )
        return True

    def fetch_manifest(
        self,
        remote_host: str,
        ssh_user: str = "ubuntu",
        ssh_port: int = 22,
        ssh_password: str | None = None,
    ) -> ServeManifest:
        cmd_str = f'ssh {ssh_user}@{remote_host} "cat ~/.pirlo-pitch/serve/serve.json"'
        print(f"[pirlo connect] Probing remote manifest via Paramiko SSH: {cmd_str}")

        try:
            import paramiko

            ssh_client = paramiko.SSHClient()
            ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh_client.connect(
                remote_host,
                port=ssh_port,
                username=ssh_user,
                password=ssh_password,
                timeout=5.0,
            )
            _stdin, stdout, _stderr = ssh_client.exec_command(
                "cat ~/.pirlo-pitch/serve/serve.json"
            )
            output_data = stdout.read().decode("utf-8").strip()

            if ssh_password:
                try:
                    self.install_ssh_key_if_needed(ssh_client)
                except Exception as e:
                    logger.exception(
                        "[pirlo connect] Exception encountered while copying SSH public key to remote host: %s",
                        e,
                    )

            ssh_client.close()

            if output_data:
                data: dict = json.loads(output_data)
                return ServeManifest(**data)
        except Exception as e:  # noqa: BLE001
            print(f"[pirlo connect] [WARN] Paramiko SSH manifest probe failed: {e}")

        print(
            f"[pirlo connect] [WARN] Remote serve manifest unreadable from {remote_host}."
        )
        print(
            f"💡 Manual Verification Hint:\n   Verify pirlo serve is active by running:\n     {cmd_str}\n"
        )
        return ServeManifest()

