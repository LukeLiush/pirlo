# tests/test_code_bundler.py
from __future__ import annotations

import base64
import io
import tarfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pirlo.infrastructure.services.code_bundler import (
    InMemoryCodeStorage,
    PrefectArtifactCodeStorage,
    S3CodeStorage,
    create_tarball_bytes,
    get_code_storage_backend,
)


def test_create_tarball_bytes_and_excludes(tmp_path: Path):
    # Setup test file tree
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "app.py").write_text("print('hello')")
    (src_dir / "heavy_model.safetensors").write_text("binary-data")
    (src_dir / "data.parquet").write_text("parquet-data")

    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main")

    venv_dir = tmp_path / ".venv"
    venv_dir.mkdir()
    (venv_dir / "bin").mkdir()
    (venv_dir / "bin" / "python").write_text("mock")

    tar_bytes = create_tarball_bytes(root_dir=tmp_path)
    assert len(tar_bytes) > 0

    # Inspect tarball contents
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:gz") as tar:
        names = tar.getnames()
        assert "src/app.py" in names
        assert not any(".git" in n for n in names)
        assert not any(".venv" in n for n in names)
        assert not any(n.endswith(".safetensors") for n in names)
        assert not any(n.endswith(".parquet") for n in names)


@pytest.mark.anyio
async def test_in_memory_code_storage_roundtrip(tmp_path: Path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "main.py").write_text("x = 42\n")

    tar_bytes = create_tarball_bytes(root_dir=tmp_path)
    storage = InMemoryCodeStorage()

    code_ref = await storage.upload(tar_bytes, "test_snapshot")
    assert isinstance(code_ref, str)

    dest_dir = tmp_path / "extracted"
    extracted_path = await storage.extract(code_ref, dest_dir)
    assert extracted_path == dest_dir
    assert (dest_dir / "src" / "main.py").read_text() == "x = 42\n"


@pytest.mark.anyio
async def test_in_memory_code_storage_size_limit():
    storage = InMemoryCodeStorage()
    # 26 MB of bytes should trip the guardrail
    fake_heavy_bytes = b"0" * (26 * 1024 * 1024)
    with pytest.raises(ValueError, match="exceeds in-memory limit"):
        await storage.upload(fake_heavy_bytes, "heavy")


@pytest.mark.anyio
async def test_prefect_artifact_code_storage(tmp_path: Path):
    src_file = tmp_path / "play.py"
    src_file.write_text("print('play')")
    tar_bytes = create_tarball_bytes(root_dir=tmp_path)

    storage = PrefectArtifactCodeStorage()
    artifact_uuid: str = "artifact-uuid-123"
    created_artifact = MagicMock()
    created_artifact.id = artifact_uuid

    mock_artifact = MagicMock()
    mock_artifact.data = base64.b64encode(tar_bytes).decode("utf-8")

    mock_client = AsyncMock()
    mock_client.create_artifact = AsyncMock(return_value=created_artifact)
    mock_client.read_artifacts = AsyncMock(return_value=[mock_artifact])

    mock_client_ctx = MagicMock()
    mock_client_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_ctx.__aexit__ = AsyncMock(return_value=None)

    with patch("prefect.client.orchestration.get_client", return_value=mock_client_ctx):
        code_ref = await storage.upload(tar_bytes, "test_artifact")
        assert code_ref == "artifact-uuid-123"

        dest_dir = tmp_path / "extracted_artifact"
        res_dir = await storage.extract(code_ref, dest_dir)
        assert (res_dir / "play.py").read_text() == "print('play')"


@pytest.mark.anyio
async def test_s3_code_storage(tmp_path: Path):
    src_file = tmp_path / "pipeline.py"
    src_file.write_text("def run(): pass")
    tar_bytes = create_tarball_bytes(root_dir=tmp_path)

    storage = S3CodeStorage(bucket="my-bucket", prefix="snapshots")
    mock_s3 = MagicMock()

    def mock_download(bucket, key, local_dest):
        Path(local_dest).write_bytes(tar_bytes)

    mock_s3.download_file = MagicMock(side_effect=mock_download)

    with patch("boto3.client", return_value=mock_s3):
        code_ref = await storage.upload(tar_bytes, "my_flow")
        assert code_ref == "s3://my-bucket/snapshots/my_flow.tar.gz"

        dest_dir = tmp_path / "extracted_s3"
        res_dir = await storage.extract(code_ref, dest_dir)
        assert (res_dir / "pipeline.py").read_text() == "def run(): pass"


def test_get_code_storage_backend_factory():
    assert isinstance(get_code_storage_backend("in_memory"), InMemoryCodeStorage)
    assert isinstance(
        get_code_storage_backend("prefect_artifact"), PrefectArtifactCodeStorage
    )
    assert isinstance(
        get_code_storage_backend("s3", s3_bucket="test-bkt"), S3CodeStorage
    )
