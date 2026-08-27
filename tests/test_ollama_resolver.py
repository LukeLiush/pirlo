from unittest.mock import MagicMock, patch

from pirlo.infrastructure.services.ollama_resolver import (
    LocalDecomposerModelProvider,
    OllamaClient,
    OllamaEndpointDetector,
    OllamaModelCatalog,
    OllamaModelProvisioner,
)


def test_ollama_endpoint_detector_normalize_url():
    detector = OllamaEndpointDetector()
    assert detector._normalize_url("127.0.0.1:11434") == "http://127.0.0.1:11434"
    assert detector._normalize_url(":11435") == "http://localhost:11435"
    assert detector._normalize_url("http://localhost:11434") == "http://localhost:11434"


def test_ollama_endpoint_detector_env_binary():
    detector = OllamaEndpointDetector()
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("os.access", return_value=True),
    ):
        bin_path = detector.find_env_ollama_binary()
        assert bin_path is not None


def test_ollama_endpoint_detector_env_var():
    detector = OllamaEndpointDetector()
    with (
        patch.dict("os.environ", {"OLLAMA_HOST": "127.0.0.1:11435"}),
        patch.object(detector, "is_reachable", return_value=True) as mock_reachable,
    ):
        url = detector.detect_base_url()
        assert url == "http://127.0.0.1:11435"
        mock_reachable.assert_called_with("http://127.0.0.1:11435")


def test_ollama_model_catalog_find_matching():
    catalog = OllamaModelCatalog(preferred_candidates=("qwen2.5:3b", "qwen2.5:1.5b"))

    # Matches exact or base tag
    matched = catalog.find_matching_model(["qwen2.5:1.5b", "llama3:latest"])
    assert matched == "qwen2.5:1.5b"

    # Returns None if no candidate present
    no_match = catalog.find_matching_model(["mistral:latest"])
    assert no_match is None


def test_ollama_model_provisioner_pulls_if_missing():
    mock_client = MagicMock(spec=OllamaClient)
    mock_client.fetch_installed_tags.return_value = ["llama3:latest"]

    provisioner = OllamaModelProvisioner(mock_client)
    provisioner.ensure_model_available("qwen2.5:3b")

    mock_client.execute_pull.assert_called_once_with("qwen2.5:3b")


def test_local_decomposer_model_provider():
    mock_detector = MagicMock(spec=OllamaEndpointDetector)
    mock_detector.detect_base_url.return_value = "http://localhost:11434"

    provider = LocalDecomposerModelProvider(detector=mock_detector)
    with patch.object(
        OllamaClient, "fetch_installed_tags", return_value=["qwen2.5:3b"]
    ):
        link = provider.provide_link()
        assert link.provider == "openai"
        assert link.model == "qwen2.5:3b"
        assert link.base_url == "http://localhost:11434/v1"
