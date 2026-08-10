import importlib.metadata
import os
import tomllib
from pathlib import Path
from typing import Any, ClassVar

from pirlo.core.ports.orchestrator import TaskOrchestrator
from pirlo.infrastructure.adapters.orchestrator.prefect_orchestrator import (
    SmartPrefectTaskOrchestrator,
)


class OrchestratorFactory:
    """Dynamic Factory for Orchestrator Adapters."""

    _registry: ClassVar[dict[str, type[TaskOrchestrator]]] = {
        "prefect": SmartPrefectTaskOrchestrator,
    }

    @classmethod
    def list_orchestrators(cls) -> dict[str, type[TaskOrchestrator]]:
        """Returns dict of all registered orchestrator adapter classes."""
        cls._discover_plugins()
        return dict(cls._registry)

    @classmethod
    def register(cls, name: str, orchestrator_cls: type[TaskOrchestrator]) -> None:
        """Allows external plugins to register orchestrators dynamically."""
        cls._registry[name.lower()] = orchestrator_cls

    @classmethod
    def resolve_config_path(cls, custom_path: Path | None = None) -> Path | None:
        """Resolves pirlo.toml path from custom path, PIRLO_CONFIG env var, CWD, or workspace root."""
        if custom_path and custom_path.exists():
            return custom_path

        env_cfg = os.environ.get("PIRLO_CONFIG")
        if env_cfg and Path(env_cfg).exists():
            return Path(env_cfg)

        cwd_cfg = Path.cwd() / "pirlo.toml"
        if cwd_cfg.exists():
            return cwd_cfg

        from pirlo.core.config import get_workspace_path

        ws_cfg = get_workspace_path() / "pirlo.toml"
        if ws_cfg.exists():
            return ws_cfg

        return None

    @classmethod
    def create(
        cls,
        name: str = "prefect",
        config_path: Path | None = None,
        **overrides: Any,
    ) -> TaskOrchestrator:
        """
        Creates and returns an instance of the requested orchestrator adapter.
        Merges parameters with precedence:
          CLI Overrides > Environment Variables > pirlo.toml > Defaults
        """
        cls._discover_plugins()

        target_name = name.lower()
        orchestrator_cls = cls._registry.get(target_name)
        if not orchestrator_cls:
            available = list(cls._registry.keys())
            raise ValueError(
                f"Unknown orchestrator backend '{name}'. Available: {available}"
            )

        toml_opts: dict[str, Any] = {}
        resolved_path = cls.resolve_config_path(config_path)
        if resolved_path:
            try:
                with open(resolved_path, "rb") as f:
                    raw_cfg = tomllib.load(f)
                    toml_opts = (
                        raw_cfg.get("pirlo", {})
                        .get("orchestrator", {})
                        .get(target_name, {})
                    )
            except Exception as e:  # noqa: BLE001
                print(f"⚠️ Warning: Failed to parse {resolved_path}: {e}")

        # Check for provider specific environment variables if applicable
        if (
            target_name == "prefect"
            and "server_url" not in toml_opts
            and os.environ.get("PREFECT_API_URL")
        ):
            toml_opts["server_url"] = os.environ.get("PREFECT_API_URL")

        active_overrides = {k: v for k, v in overrides.items() if v is not None}
        final_kwargs = {**toml_opts, **active_overrides}

        return orchestrator_cls(**final_kwargs)

    @classmethod
    def _discover_plugins(cls) -> None:
        """Scans installed Python package entry points for external orchestrator plugins."""
        with_entry_points = hasattr(importlib.metadata, "entry_points")
        if not with_entry_points:
            return

        try:
            entry_points = importlib.metadata.entry_points()
            plugins = (
                entry_points.select(group="pirlo.orchestrators")
                if hasattr(entry_points, "select")
                else entry_points.get("pirlo.orchestrators", [])  # type: ignore[union-attr,attr-defined]
            )

            for ep in plugins:
                if ep.name not in cls._registry:
                    try:
                        plugin_cls = ep.load()
                        cls.register(ep.name, plugin_cls)
                    except Exception as e:  # noqa: BLE001
                        print(
                            f"⚠️ Warning: Failed to load orchestrator plugin '{ep.name}': {e}"
                        )
        except Exception as e:  # noqa: BLE001
            print(f"⚠️ Warning: Plugin discovery failed: {e}")
