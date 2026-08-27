import json
import logging
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from collections.abc import Sequence
from pathlib import Path

from pirlo.core.models.link import LlmLink

logger = logging.getLogger(__name__)

PREFERRED_DECOMPOSER_MODELS = ("qwen2.5:3b", "qwen2.5:1.5b")
DEFAULT_OLLAMA_PORT = 11434


class OllamaEndpointDetector:
    """SRP: Responsible ONLY for discovering environment binaries, detecting ports, and pinging host endpoints."""

    def find_env_ollama_binary(self) -> Path | None:
        """Resolves the ollama executable strictly from the library's active environment bin/ directory."""
        env_bin_dir = Path(sys.executable).parent
        env_ollama_bin = env_bin_dir / "ollama"

        if env_ollama_bin.exists() and os.access(env_ollama_bin, os.X_OK):
            return env_ollama_bin

        prefix_ollama_bin = Path(sys.prefix) / "bin" / "ollama"
        if prefix_ollama_bin.exists() and os.access(prefix_ollama_bin, os.X_OK):
            return prefix_ollama_bin

        logger.debug(
            f"Ollama binary not found in environment bin directories: '{env_bin_dir}' or '{sys.prefix}/bin'"
        )
        return None

    def is_reachable(self, base_url: str, timeout: float = 2.0) -> bool:
        """Test if Ollama server responds at base_url."""
        try:
            url = f"{base_url.rstrip('/')}/"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status == 200
        except Exception as e:
            logger.debug(
                f"Endpoint '{base_url}' health check failed: {e}",
                exc_info=True,
            )
            return False

    def detect_base_url(self) -> str:
        """4-Tier process & socket auto-detection for Ollama endpoint with diagnostic logging."""
        # Tier 1: Check OLLAMA_HOST env var
        env_host = os.environ.get("OLLAMA_HOST")
        if env_host:
            url = self._normalize_url(env_host)
            logger.debug(f"Tier 1: Checking OLLAMA_HOST endpoint '{url}'...")
            if self.is_reachable(url):
                logger.info(f"Ollama detected via OLLAMA_HOST: {url}")
                return url

        # Tier 2: Check standard localhost:11434 and 127.0.0.1:11434
        logger.debug("Tier 2: Checking standard localhost/127.0.0.1 ports...")
        for std_url in (
            f"http://localhost:{DEFAULT_OLLAMA_PORT}",
            f"http://127.0.0.1:{DEFAULT_OLLAMA_PORT}",
        ):
            if self.is_reachable(std_url):
                logger.info(f"Ollama detected on standard port: {std_url}")
                return std_url

        # Tier 3: Process inspection via psutil
        logger.debug(
            "Tier 3: Inspecting system processes for active Ollama listening ports..."
        )
        try:
            import psutil

            for proc in psutil.process_iter(["name", "cmdline"]):
                try:
                    pname = (proc.info.get("name") or "").lower()
                    cmdline = " ".join(proc.info.get("cmdline") or []).lower()
                    if "ollama" in pname or "ollama" in cmdline:
                        for conn in proc.connections(kind="tcp"):
                            if conn.status == psutil.CONN_LISTEN:
                                port_url = f"http://localhost:{conn.laddr.port}"
                                if self.is_reachable(port_url):
                                    logger.info(
                                        f"Ollama process detected listening on port {conn.laddr.port}: {port_url}"
                                    )
                                    return port_url
                except (
                    psutil.NoSuchProcess,
                    psutil.AccessDenied,
                    psutil.ZombieProcess,
                ) as proc_err:
                    logger.debug(
                        f"Process inspection skipped pid {getattr(proc, 'pid', 'unknown')}: {proc_err}",
                        exc_info=True,
                    )
                    continue
        except ImportError:
            logger.debug(
                "`psutil` package is not installed; skipping Tier 3 process inspection."
            )
        except Exception as e:
            logger.warning(
                f"Unexpected error during Tier 3 process inspection: {e}",
                exc_info=True,
            )

        # Tier 4: Auto-launch background `ollama serve` process using environment binary
        logger.debug(
            "Tier 4: Checking environment binary for background auto-launch..."
        )
        env_ollama_bin = self.find_env_ollama_binary()
        if env_ollama_bin:
            logger.info(
                f"Ollama server not running. Launching environment daemon: '{env_ollama_bin} serve'..."
            )
            try:
                subprocess.Popen(
                    [str(env_ollama_bin), "serve"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                for _ in range(10):
                    time.sleep(0.5)
                    auto_url = f"http://localhost:{DEFAULT_OLLAMA_PORT}"
                    if self.is_reachable(auto_url):
                        logger.info(
                            f"Successfully auto-started environment Ollama server at {auto_url}"
                        )
                        return auto_url
            except Exception as e:
                logger.warning(
                    f"Failed to auto-start environment `ollama serve`: {e}",
                    exc_info=True,
                )
        else:
            logger.debug("No environment Ollama binary found for Tier 4 auto-launch.")

        raise RuntimeError(
            "Could not connect to Ollama server. Please ensure Ollama is installed in the environment and running."
        )

    def _normalize_url(self, host_str: str) -> str:
        host_str = host_str.strip()
        if not host_str.startswith(("http://", "https://")):
            if host_str.startswith(":"):
                host_str = f"localhost{host_str}"
            host_str = f"http://{host_str}"
        parsed = urllib.parse.urlparse(host_str)
        scheme = parsed.scheme or "http"
        netloc = parsed.netloc or f"localhost:{DEFAULT_OLLAMA_PORT}"
        return f"{scheme}://{netloc}"


class OllamaClient:
    """SRP: Responsible ONLY for communication with Ollama REST API endpoints."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def fetch_installed_tags(self) -> list[str]:
        """Queries GET /api/tags and returns installed model tag names."""
        url = f"{self.base_url}/api/tags"
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                return [m["name"] for m in data.get("models", [])]
        except Exception as e:
            logger.warning(
                f"Failed to query Ollama tags at {url}: {e}",
                exc_info=True,
            )
            return []

    def execute_pull(self, model_name: str) -> None:
        """Sends POST /api/pull to download target model."""
        url = f"{self.base_url}/api/pull"
        payload = json.dumps({"name": model_name, "stream": False}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        print(f"⏳ Downloading '{model_name}' into Ollama server...")
        with urllib.request.urlopen(req, timeout=600) as resp:
            if resp.status == 200:
                print(f"✅ Downloaded '{model_name}' successfully.")
            else:
                raise RuntimeError(f"Ollama pull returned HTTP {resp.status}")


class OllamaModelCatalog:
    """SRP: Responsible ONLY for searching and matching model tags against preference policies."""

    def __init__(
        self, preferred_candidates: Sequence[str] = PREFERRED_DECOMPOSER_MODELS
    ) -> None:
        self.preferred_candidates = preferred_candidates

    def find_matching_model(self, installed_tags: list[str]) -> str | None:
        """Finds the highest priority installed model matching candidate list."""
        for candidate in self.preferred_candidates:
            for installed in installed_tags:
                if (
                    installed == candidate
                    or installed.split(":")[0] == candidate.split(":")[0]
                ):
                    return installed
        return None


class OllamaModelProvisioner:
    """SRP: Responsible ONLY for ensuring a requested model exists on the server."""

    def __init__(self, client: OllamaClient) -> None:
        self.client = client

    def ensure_model_available(self, model_name: str) -> None:
        """Checks if model exists; triggers pull if missing."""
        installed = self.client.fetch_installed_tags()
        if model_name not in installed:
            self.client.execute_pull(model_name)


class LocalDecomposerModelProvider:
    """Domain Provider: Orchestrates single-responsibility components to supply a valid LlmLink."""

    def __init__(
        self,
        detector: OllamaEndpointDetector | None = None,
        preferred_candidates: Sequence[str] = PREFERRED_DECOMPOSER_MODELS,
        default_pull_model: str = "qwen2.5:3b",
    ) -> None:
        self.detector = detector or OllamaEndpointDetector()
        self.catalog = OllamaModelCatalog(preferred_candidates)
        self.default_pull_model = default_pull_model

    def provide_link(self) -> LlmLink:
        """Discovers server, matches/provisions model, and constructs OpenAI-compatible LlmLink."""
        try:
            base_url = self.detector.detect_base_url()
            client = OllamaClient(base_url)

            installed_tags = client.fetch_installed_tags()
            selected_model = self.catalog.find_matching_model(installed_tags)

            if not selected_model:
                provisioner = OllamaModelProvisioner(client)
                provisioner.ensure_model_available(self.default_pull_model)
                selected_model = self.default_pull_model

            endpoint = f"{base_url.rstrip('/')}/v1"
            return LlmLink(
                name="local-ollama-auto",
                provider="openai",
                model=selected_model,
                api_key="ollama",
                base_url=endpoint,
            )
        except Exception as e:
            logger.warning(
                f"Could not auto-detect or provision local Ollama model: {e}",
                exc_info=True,
            )
            return LlmLink(
                name="local-ollama-fallback",
                provider="openai",
                model=self.default_pull_model,
                api_key="ollama",
                base_url=f"http://localhost:{DEFAULT_OLLAMA_PORT}/v1",
            )
