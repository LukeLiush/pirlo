# src/pirlo/infrastructure/services/code_bundler.py
from __future__ import annotations

import base64
import io
import os
import tarfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Literal

MAX_IN_MEMORY_SIZE_BYTES: int = 500 * 1024  # 500 KB (Prefect parameter limit is 512 KB)

DEFAULT_EXCLUDES: set[str] = {
    ".git",
    ".venv",
    ".venv*",
    "__pycache__",
    "*.pyc",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "build",
    "dist",
    "*.egg-info",
    ".DS_Store",
    # Heavy non-code data/model formats:
    "*.safetensors",
    "*.bin",
    "*.pt",
    "*.pth",
    "*.onnx",
    "*.parquet",
    "*.h5",
    "*.tar",
    "*.zip",
    "*.gz",
}


def create_tarball_bytes(root_dir: Path | None = None) -> bytes:
    """Packages Python files and project assets into an in-memory tarball (.tar.gz)."""
    target_dir: Path = root_dir or Path.cwd()
    buf: io.BytesIO = io.BytesIO()

    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for root, dirs, files in os.walk(target_dir):
            # Prune excluded directories in-place using clean variable names
            dirs[:] = [
                dir_name
                for dir_name in dirs
                if not any(
                    Path(dir_name).match(pat) or dir_name == pat
                    for pat in DEFAULT_EXCLUDES
                )
            ]
            for file_name in files:
                if any(
                    Path(file_name).match(pat) or file_name == pat
                    for pat in DEFAULT_EXCLUDES
                ):
                    continue
                file_path: Path = Path(root) / file_name
                rel_path: Path = file_path.relative_to(target_dir)
                tar.add(file_path, arcname=str(rel_path))

    return buf.getvalue()


class CodeStorageBackend(ABC):
    """Abstract port for code snapshot storage."""

    @abstractmethod
    async def upload(self, tar_bytes: bytes, snapshot_name: str) -> str:
        """Uploads/serializes tarball bytes, returning a reference identifier."""
        ...

    @abstractmethod
    async def extract(self, code_ref: str, dest_dir: Path) -> Path:
        """Downloads and extracts the code directly to disk into dest_dir with O(1) memory."""
        ...


class InMemoryCodeStorage(CodeStorageBackend):
    """Encodes tarball into base64 for transmission directly inside HTTP payload."""

    async def upload(self, tar_bytes: bytes, snapshot_name: str) -> str:
        byte_len: int = len(tar_bytes)
        if byte_len > MAX_IN_MEMORY_SIZE_BYTES:
            size_mb: float = byte_len / (1024 * 1024)
            limit_mb: float = MAX_IN_MEMORY_SIZE_BYTES / (1024 * 1024)
            raise ValueError(
                f"Code snapshot ({size_mb:.1f} MB) exceeds in-memory limit ({limit_mb:.0f} MB).\n"
                "Recommendations:\n"
                "  1. Ensure large dataset/model files are not in the project directory.\n"
                "  2. Use S3 code storage backend for large bundles: --code-storage s3"
            )
        return base64.b64encode(tar_bytes).decode("utf-8")

    async def extract(self, code_ref: str, dest_dir: Path) -> Path:
        raw_bytes: bytes = base64.b64decode(code_ref.encode("utf-8"))
        buf: io.BytesIO = io.BytesIO(raw_bytes)
        dest_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=buf, mode="r:gz") as tar:
            tar.extractall(path=dest_dir, filter="data")
        return dest_dir


class PrefectArtifactCodeStorage(CodeStorageBackend):
    """Stores tarball as a Prefect Artifact via Prefect API."""

    async def upload(self, tar_bytes: bytes, snapshot_name: str) -> str:
        from uuid import uuid4

        from prefect.client.orchestration import get_client
        from prefect.client.schemas.actions import ArtifactCreate

        b64_content: str = base64.b64encode(tar_bytes).decode("utf-8")
        clean_name: str = "".join(
            c if c.isalnum() else "-" for c in snapshot_name.lower()
        )[:40]
        key: str = f"pirlo-code-{clean_name}-{uuid4().hex[:8]}"
        async with get_client() as client:
            artifact: Any = await client.create_artifact(
                artifact=ArtifactCreate(
                    key=key,
                    data=b64_content,
                    description="Pirlo code bundle snapshot",
                )
            )
            return str(artifact.id)

    async def extract(self, code_ref: str, dest_dir: Path) -> Path:
        from uuid import UUID

        from prefect.client.orchestration import get_client
        from prefect.client.schemas.filters import (
            ArtifactFilter,
            ArtifactFilterId,
            ArtifactFilterKey,
        )

        dest_dir.mkdir(parents=True, exist_ok=True)
        try:
            art_uuid: UUID = UUID(code_ref)
            art_filter: ArtifactFilter = ArtifactFilter(
                id=ArtifactFilterId(any_=[art_uuid])
            )
        except ValueError:
            art_filter = ArtifactFilter(key=ArtifactFilterKey(any_=[code_ref]))

        async with get_client() as client:
            artifacts: Any = await client.read_artifacts(artifact_filter=art_filter)
            raw_bytes: bytes = base64.b64decode(str(artifacts[0].data).encode("utf-8"))
            buf: io.BytesIO = io.BytesIO(raw_bytes)
            with tarfile.open(fileobj=buf, mode="r:gz") as tar:
                tar.extractall(path=dest_dir, filter="data")
        return dest_dir


class S3CodeStorage(CodeStorageBackend):
    """Uploads and streams tarball directly from/to S3 with O(1) memory usage."""

    def __init__(
        self, bucket: str | None = None, prefix: str = "pirlo-snapshots"
    ) -> None:
        self.bucket: str = bucket or os.environ.get("PIRLO_CODE_STORAGE_S3_BUCKET", "")
        self.prefix: str = prefix

    async def upload(self, tar_bytes: bytes, snapshot_name: str) -> str:
        if not self.bucket:
            raise ValueError(
                "S3 bucket must be configured via PIRLO_CODE_STORAGE_S3_BUCKET "
                "environment variable or link config."
            )
        import anyio
        import boto3

        s3: Any = boto3.client("s3")
        key: str = f"{self.prefix}/{snapshot_name}.tar.gz"
        await anyio.to_thread.run_sync(
            lambda: s3.put_object(Bucket=self.bucket, Key=key, Body=tar_bytes)
        )
        return f"s3://{self.bucket}/{key}"

    async def extract(self, code_ref: str, dest_dir: Path) -> Path:
        from urllib.parse import urlparse

        import anyio
        import boto3

        parsed: Any = urlparse(code_ref)
        bucket: str = parsed.netloc
        key: str = parsed.path.lstrip("/")

        dest_dir.mkdir(parents=True, exist_ok=True)
        archive_path: Path = dest_dir / "bundle.tar.gz"

        # Stream download directly to file on disk (O(1) memory)
        s3: Any = boto3.client("s3")
        await anyio.to_thread.run_sync(
            lambda: s3.download_file(bucket, key, str(archive_path))
        )

        # Unpack archive into dest_dir
        with tarfile.open(archive_path, mode="r:gz") as tar:
            tar.extractall(path=dest_dir, filter="data")

        archive_path.unlink(missing_ok=True)
        return dest_dir


def get_code_storage_backend(
    storage_type: Literal["in_memory", "prefect_artifact", "s3"] = "in_memory",
    **kwargs: Any,
) -> CodeStorageBackend:
    if storage_type == "prefect_artifact":
        return PrefectArtifactCodeStorage()
    if storage_type == "s3":
        return S3CodeStorage(bucket=kwargs.get("s3_bucket"))
    return InMemoryCodeStorage()


def build_worker_bootstrap_command() -> str:
    """Builds a portable bash command for remote worker to extract code and launch flow engine."""
    py_code: str = (
        "import asyncio, base64, io, os, sys, tarfile\n"
        "from uuid import UUID\n"
        "from prefect.client.orchestration import get_client\n"
        "from prefect.client.schemas.filters import ArtifactFilter, ArtifactFilterId\n\n"
        "async def _boot():\n"
        "    flow_run_id_str = os.environ.get('PREFECT__FLOW_RUN_ID')\n"
        "    if not flow_run_id_str:\n"
        "        return\n"
        "    async with get_client() as client:\n"
        "        flow_run = await client.read_flow_run(UUID(flow_run_id_str))\n"
        "        params = flow_run.parameters or {}\n"
        "        code_ref = params.get('code_ref')\n"
        "        storage_type = params.get('storage_type', 'prefect_artifact')\n"
        "        if not code_ref:\n"
        "            return\n"
        "        if storage_type == 'in_memory':\n"
        "            raw_bytes = base64.b64decode(code_ref.encode('utf-8'))\n"
        "        elif storage_type == 'prefect_artifact':\n"
        "            try:\n"
        "                art_uuid = UUID(code_ref)\n"
        "                art_filter = ArtifactFilter(id=ArtifactFilterId(any_=[art_uuid]))\n"
        "            except ValueError:\n"
        "                from prefect.client.schemas.filters import ArtifactFilterKey\n"
        "                art_filter = ArtifactFilter(key=ArtifactFilterKey(any_=[code_ref]))\n"
        "            arts = await client.read_artifacts(artifact_filter=art_filter)\n"
        "            if not arts:\n"
        "                raise RuntimeError(f'Code artifact {code_ref} not found on Prefect server')\n"
        "            raw_bytes = base64.b64decode(str(arts[0].data).encode('utf-8'))\n"
        "        elif storage_type == 's3':\n"
        "            import boto3\n"
        "            clean_s3 = code_ref.replace('s3://', '')\n"
        "            bucket, key = clean_s3.split('/', 1)\n"
        "            s3 = boto3.client('s3')\n"
        "            resp = s3.get_object(Bucket=bucket, Key=key)\n"
        "            raw_bytes = resp['Body'].read()\n"
        "        else:\n"
        "            raise ValueError(f'Unknown storage type: {storage_type}')\n\n"
        "        buf = io.BytesIO(raw_bytes)\n        with tarfile.open(fileobj=buf, mode='r:gz') as tar:\n            tar.extractall('.', filter='data')\n\n        if os.path.exists('pyproject.toml'):\n            import subprocess\n            try:\n                subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-deps', '-e', '.'], check=False, capture_output=True)\n            except Exception:\n                pass\n\ntry:\n    asyncio.run(_boot())\nexcept Exception as e:\n    import traceback\n    traceback.print_exc()\n    sys.exit(1)\n"
    )
    b64_script: str = base64.b64encode(py_code.encode("utf-8")).decode("ascii")
    return (
        f'bash -c \'python3 -c "import sys,base64;exec(base64.b64decode(sys.argv[1]))" {b64_script} '
        f'&& export PYTHONPATH="$(pwd):$(pwd)/src:$PYTHONPATH" && python3 -m prefect.engine\''
    )
