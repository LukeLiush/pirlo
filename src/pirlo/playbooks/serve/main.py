import os
import socket
from pathlib import Path
from typing import Annotated, Any

from pirlo.core.config import (
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_OLLAMA_PORT,
    DEFAULT_PREFECT_PORT,
    get_workspace_path,
)
from pirlo.core.decorators import playbook
from pirlo.core.models.parameters import Parameter
from pirlo.core.models.run import RunStatus
from pirlo.core.models.run_result import RunResult
from pirlo.core.models.serve_manifest import ServeManifest
from pirlo.core.ports.pitch import Pitch
from pirlo.infrastructure.adapters.docker.docker_compose_manager import (
    DockerComposeManager,
)


@playbook(
    name="serve",
    description="Starts Pirlo serve (Prefect dev server + Ollama multi-model) using Docker.",
)
class ServeSession(Pitch):
    """Serve playbook that launches Prefect dev server and Ollama via Docker Compose."""

    def _find_free_port(self, preferred_port: int) -> int:
        """Checks if preferred_port is occupied on server host; returns free port if busy."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("0.0.0.0", preferred_port)) != 0:
                return preferred_port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("0.0.0.0", 0))
            return s.getsockname()[1]

    async def play(
        self,
        stop: Annotated[
            bool,
            Parameter(help="Stop active pirlo serve containers", short="-s"),
        ] = False,
        down: Annotated[
            bool,
            Parameter(help="Alias for --stop", short="-d"),
        ] = False,
        purge: Annotated[
            bool,
            Parameter(help="Stop containers and delete persistent volumes", short="-p"),
        ] = False,
        purge_all: Annotated[
            bool,
            Parameter(help="Stop containers, delete volumes, and remove Docker images"),
        ] = False,
        prefect_port: Annotated[
            int, Parameter(help="Host port for Prefect dev server")
        ] = DEFAULT_PREFECT_PORT,
        ollama_port: Annotated[
            int, Parameter(help="Host port for Ollama LLM server")
        ] = DEFAULT_OLLAMA_PORT,
        models: Annotated[
            str, Parameter(help="Comma-separated list of Ollama models to serve")
        ] = DEFAULT_OLLAMA_MODEL,
        default_model: Annotated[
            str, Parameter(help="Default general-purpose Ollama model tag")
        ] = DEFAULT_OLLAMA_MODEL,
        *args: Any,
        **kwargs: Any,
    ) -> RunResult[Any]:
        compose_file = Path(__file__).parent / "docker-compose.yml"
        compose_manager = DockerComposeManager(compose_file=compose_file)
        run_id_val = (
            (await self.prepared_run()).run_id if self._prepared_run else "serve-run"
        )

        is_teardown = stop or down or purge or purge_all

        if is_teardown:
            self.ui.header(
                "Pirlo Serve Engine", subtitle="Cleaning Up Docker Serve Stack"
            )
            remove_vols = purge or purge_all
            remove_imgs = "all" if purge_all else None

            success, msg = compose_manager.down(
                remove_volumes=remove_vols, remove_images=remove_imgs
            )

            if success:
                tier_msg = (
                    "Containers, volumes, and images purged."
                    if purge_all
                    else "Containers and persistent volumes purged."
                    if purge
                    else "Containers stopped."
                )
                self.ui.goal(
                    "pirlo serve stack cleanup complete!",
                    detail=f"{tier_msg}\n{msg}",
                )
                return RunResult(
                    run_id=run_id_val,
                    status=RunStatus.COMPLETED,
                    data={"status": "stopped"},
                )
            self.ui.commentary(f"[ERROR] Failed to stop Docker Compose stack: {msg}")
            return RunResult(
                run_id=run_id_val,
                status=RunStatus.FAILED,
                error=msg,
            )

        self.ui.header(
            "Pirlo Serve Engine",
            subtitle="Launching Prefect Dev Server & Ollama Multi-Model Docker Stack",
        )

        resolved_prefect_port: int = self._find_free_port(prefect_port)
        resolved_ollama_port: int = self._find_free_port(ollama_port)

        model_list = [m.strip() for m in models.split(",") if m.strip()]
        if not model_list:
            model_list = [default_model]

        # Host Path Expansion (~/.pirlo-pitch/serve -> absolute host path)
        serve_dir: Path = get_workspace_path() / "serve"
        serve_dir.mkdir(parents=True, exist_ok=True)

        manifest = ServeManifest(
            default_prefect_port=resolved_prefect_port,
            default_ollama_port=resolved_ollama_port,
            default_model=default_model,
            models=model_list,
        )
        manifest.save(serve_dir / "serve.json")

        ready, ready_msg = compose_manager.is_docker_ready()
        if not ready:
            self.ui.commentary(f"[ERROR] Docker daemon is unreachable: {ready_msg}\n")
            self.ui.commentary(
                "💡 Action Required to Start Docker:\n"
                "   1. Ensure Docker Desktop (or docker.service on Linux) is running:\n"
                "      • macOS: Open 'Docker Desktop' app from Applications\n"
                "      • Linux: Run 'sudo systemctl start docker'\n"
                "   2. Verify user socket permissions:\n"
                "      • Linux: Run 'sudo usermod -aG docker $USER'\n"
            )
            return RunResult(
                run_id=run_id_val,
                status=RunStatus.FAILED,
                error=f"Docker daemon unreachable: {ready_msg}",
            )

        env_vars = os.environ.copy()
        env_vars["PREFECT_PORT"] = str(resolved_prefect_port)
        env_vars["OLLAMA_PORT"] = str(resolved_ollama_port)
        env_vars["OLLAMA_MODELS"] = ",".join(model_list)

        self.ui.commentary(
            f"[INFO] Invoking Docker Compose stack ({compose_file.name})..."
        )
        success, msg = compose_manager.up(env_vars=env_vars)

        if not success:
            self.ui.commentary(
                f"[ERROR] Failed to start Docker Compose stack.\nDetails: {msg}\n"
            )
            self.ui.commentary(
                "💡 Troubleshooting Steps:\n"
                f"   1. Check if ports {resolved_prefect_port} or {resolved_ollama_port} are in use:\n"
                "      • Try running with alternate ports: 'pirlo serve --prefect-port 4201 --ollama-port 11435'\n"
                "   2. Test running Docker Compose manually:\n"
                f"      • cd {compose_file.parent} && docker compose up\n"
            )
            return RunResult(
                run_id=run_id_val,
                status=RunStatus.FAILED,
                error=f"Docker Compose failed: {msg}",
            )

        import getpass

        current_user = getpass.getuser()
        hostname = socket.gethostname()

        self.ui.goal(
            "pirlo serve started successfully!",
            detail=(
                f"Prefect API: http://0.0.0.0:{resolved_prefect_port}/api\n"
                f"Ollama Base: http://0.0.0.0:{resolved_ollama_port}\n"
                f"Served Models: {', '.join(model_list)}\n"
                f"Manifest written to {serve_dir / 'serve.json'}\n\n"
                f"💡 How to Connect from Another Machine:\n"
                f"   Run 'pirlo connect {current_user}@{hostname}' (or <user>@<remote_ip>)\n\n"
                f"💡 To shut down or purge the serve stack at any time, run:\n"
                f"   • Stop containers:            pirlo serve --stop\n"
                f"   • Stop & delete volumes:      pirlo serve --purge\n"
                f"   • Stop, delete & purge images: pirlo serve --purge-all"
            ),
        )

        return RunResult(
            run_id=run_id_val,
            status=RunStatus.COMPLETED,
            data={
                "prefect_port": resolved_prefect_port,
                "ollama_port": resolved_ollama_port,
                "models": model_list,
                "manifest_path": str(serve_dir / "serve.json"),
            },
        )


if __name__ == "__main__":
    ServeSession.cli()
