import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# File permission modes (Octal notation)
SSH_DIR_PERMISSIONS = 0o700  # rwx------ (Owner read/write/execute only)
PRIVATE_KEY_PERMISSIONS = 0o600  # rw------- (Owner read/write only)
PUBLIC_KEY_PERMISSIONS = 0o644  # rw-r--r-- (Owner read/write, Others read)


def ensure_local_ssh_key() -> Path | None:
    """Finds an existing local SSH public key or generates a new ed25519 key pair using cryptography.

    Returns:
        Path to the public key file if available or successfully generated, or None if unavailable.
    """
    ssh_dir = Path("~/.ssh").expanduser()
    for key_name in ("id_ed25519.pub", "id_rsa.pub", "id_ecdsa.pub"):
        candidate = ssh_dir / key_name
        if candidate.exists():
            return candidate

    # No existing key found; attempt to generate one using cryptography library
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ed25519

        ssh_dir.mkdir(parents=True, mode=SSH_DIR_PERMISSIONS, exist_ok=True)
        private_key_path = ssh_dir / "id_ed25519"
        public_key_path = ssh_dir / "id_ed25519.pub"

        private_key = ed25519.Ed25519PrivateKey.generate()
        private_key_pem_bytes = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.OpenSSH,
            encryption_algorithm=serialization.NoEncryption(),
        )
        private_key_path.write_bytes(private_key_pem_bytes)
        private_key_path.chmod(PRIVATE_KEY_PERMISSIONS)

        public_key_openssh_bytes = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.OpenSSH,
            format=serialization.PublicFormat.OpenSSH,
        )
        public_key_path.write_bytes(public_key_openssh_bytes)
        public_key_path.chmod(PUBLIC_KEY_PERMISSIONS)

        logger.info("[pirlo connect] Generated new ed25519 SSH key pair at %s", private_key_path)
        return public_key_path
    except Exception as e:
        logger.warning(
            "[pirlo connect] Could not auto-generate SSH key via cryptography library: %s", e
        )
        return None
