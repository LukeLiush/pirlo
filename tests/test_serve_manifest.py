from pathlib import Path

from pirlo.core.models.serve_manifest import ServeManifest


def test_serve_manifest_serialization(tmp_path: Path):
    manifest_file = tmp_path / "serve.json"
    manifest = ServeManifest(
        default_prefect_port=4200,
        default_ollama_port=11434,
        default_model="qwen2.5",
        models=["qwen2.5", "deepseek-r1:8b"],
    )
    manifest.save(manifest_file)
    assert manifest_file.exists()

    loaded = ServeManifest.load(manifest_file)
    assert loaded.default_prefect_port == 4200
    assert loaded.default_ollama_port == 11434
    assert loaded.default_model == "qwen2.5"
    assert loaded.models == ["qwen2.5", "deepseek-r1:8b"]
