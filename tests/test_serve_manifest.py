from pathlib import Path

from pirlo.core.models.serve_manifest import ActiveSession, ServeManifest


def test_serve_manifest_serialization(tmp_path: Path):
    manifest_file = tmp_path / "serve.json"
    manifest = ServeManifest(
        default_prefect_port=4200,
        default_ollama_port=11434,
        default_model="qwen3.2",
        models=["qwen3.2", "deepseek-r1:8b"],
    )
    manifest.save(manifest_file)
    assert manifest_file.exists()

    loaded = ServeManifest.load(manifest_file)
    assert loaded.default_prefect_port == 4200
    assert loaded.default_ollama_port == 11434
    assert loaded.default_model == "qwen3.2"
    assert loaded.models == ["qwen3.2", "deepseek-r1:8b"]


def test_active_session_properties_and_host_matching(tmp_path: Path):
    session_file = tmp_path / "session.json"
    session = ActiveSession(
        remote_host="user@gpu-server.local",
        local_prefect_port=4201,
        local_ollama_port=11435,
        remote_prefect_port=4200,
        remote_ollama_port=11434,
        cli_pid=12345,
    )

    assert session.prefect_api_url == "http://127.0.0.1:4201/api"
    assert session.ollama_base_url == "http://127.0.0.1:11435"

    assert session.is_same_host("user@gpu-server.local")
    assert session.is_same_host("USER@GPU-SERVER.LOCAL")
    assert not session.is_same_host("other-host")

    session.save(session_file)
    assert session_file.exists()
