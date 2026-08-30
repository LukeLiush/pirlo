import json

from pirlo.core.models.serve_manifest import ServeManifest
from pirlo.playbooks.connect.ports.remote_manifest_prober import RemoteManifestProber


class ParamikoManifestProber(RemoteManifestProber):
    """Pure-Python Paramiko implementation of RemoteManifestProber (100% Cross-Platform)."""

    def fetch_manifest(
        self, remote_host: str, ssh_user: str = "ubuntu", ssh_port: int = 22
    ) -> ServeManifest:
        cmd_str = f'ssh {ssh_user}@{remote_host} "cat ~/.pirlo-pitch/serve/serve.json"'
        print(f"[pirlo connect] Probing remote manifest via Paramiko SSH: {cmd_str}")

        try:
            import paramiko

            ssh_client = paramiko.SSHClient()
            ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh_client.connect(
                remote_host, port=ssh_port, username=ssh_user, timeout=5.0
            )
            _stdin, stdout, _stderr = ssh_client.exec_command(
                "cat ~/.pirlo-pitch/serve/serve.json"
            )
            output_data = stdout.read().decode("utf-8").strip()
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
