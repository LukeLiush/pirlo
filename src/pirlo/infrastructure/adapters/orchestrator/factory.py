"""Dynamic factory for orchestrator adapters."""

from __future__ import annotations

import importlib.metadata
import os
import tomllib
from pathlib import Path
from typing import Any, ClassVar, cast

from pirlo.infrastructure.adapters.cli.parameter_sources import (
    EnvironmentSource,
    OverrideSource,
    ParameterSource,
    TomlSource,
    ValueConverter,
)
from pirlo.infrastructure.services.parameter_resolution import ParameterResolver

from pirlo.core.models.parameters import Parameterizable
from pirlo.core.ports.orchestrator import TaskOrchestrator
from pirlo.infrastructure.adapters.cli.parameter_binder import ParameterBinder
from pirlo.infrastructure.adapters.orchestrator.prefect_orchestrator import (
    SmartPrefectTaskOrchestrator,
)
from pirlo.infrastructure.services.parameter_provider import ParameterProvider


class OrchestratorFactory:
    """Registry-backed factory that constructs orchestrator adapters and
    resolves their parameters with precedence:

        Defaults < pirlo.toml < Environment < CLI overrides.
    """

    _registry: ClassVar[dict[str, type[TaskOrchestrator]]] = {
        "prefect": SmartPrefectTaskOrchestrator,
    }

    # --- registry ---------------------------------------------------------

    @classmethod
    def list_orchestrators(cls) -> dict[str, type[TaskOrchestrator]]:
        """Return all registered orchestrator adapter classes."""
        cls._discover_plugins()
        return dict(cls._registry)

    @classmethod
    def register(cls, name: str, orchestrator_cls: type[TaskOrchestrator]) -> None:
        """Register an orchestrator adapter (used by external plugins)."""
        cls._registry[name.lower()] = orchestrator_cls

    # --- creation ---------------------------------------------------------

    @classmethod
    def create_from_invocation(
        cls,
        name: str,
        playbook_name: str,
        orchestrator_flags: list[str],
        config_path: Path | None = None,
    ) -> TaskOrchestrator:
        """Validate, parse CLI options for, and construct an orchestrator.

        Single entry point for the CLI/preparer flow: it owns registry
        lookup and validation so callers don't reach into the registry.

        Raises:
            ValueError: if ``name`` is not a registered orchestrator.
        """
        orchestrator_cls = cls._require_orchestrator(name)
        options = orchestrator_cls.parse_cli_options(
            playbook_name=playbook_name,
            orchestrator_flags=orchestrator_flags,
        )
        return cls.create(name=name, config_path=config_path, **options)

    @classmethod
    def create(
        cls,
        name: str = "prefect",
        config_path: Path | None = None,
        **overrides: Any,
    ) -> TaskOrchestrator:
        """Construct an orchestrator with its parameters resolved across
        sources (Defaults < toml < env < overrides).

        Raises:
            ValueError: if ``name`` is not a registered orchestrator.
        """
        orchestrator_cls: type[TaskOrchestrator] = cls._require_orchestrator(name)

        toml_opts: dict[str, Any] = cls.resolve_toml_config(name.lower(), config_path)
        resolver: ParameterResolver = cls._build_resolver(toml_opts, overrides)

        provider = ParameterProvider(resolver)
        binder = ParameterBinder(provider)

        orchestrator: Parameterizable = binder.bind(orchestrator_cls())

        return cast(TaskOrchestrator, orchestrator)

    @classmethod
    def _require_orchestrator(cls, name: str) -> type[TaskOrchestrator]:
        """Look up an orchestrator class, raising if the name is unknown."""
        cls._discover_plugins()
        orchestrator_cls = cls._registry.get(name.lower())
        if not orchestrator_cls:
            available = ", ".join(sorted(cls._registry))
            raise ValueError(
                f"Unknown orchestrator backend '{name}'. Available: {available}"
            )
        return orchestrator_cls

    @staticmethod
    def _build_resolver(
        toml_opts: dict[str, Any],
        overrides: dict[str, Any],
    ) -> ParameterResolver:
        """Assemble the precedence source stack for orchestrator params.

        Ordered lowest -> highest: toml, env, overrides. Defaults are seeded
        by the resolver from each Parameter. No link repository: orchestrators
        declare no LinkParameters.
        """
        converter = ValueConverter()
        sources: list[ParameterSource] = [
            TomlSource(toml_opts, converter),
            EnvironmentSource(converter),
            OverrideSource(overrides, converter),
        ]
        return ParameterResolver(sources)  # link_repository defaults to None

    # --- config resolution ------------------------------------------------

    @classmethod
    def resolve_config_path(cls, custom_path: Path | None = None) -> Path | None:
        """Resolve pirlo.toml from custom path, PIRLO_CONFIG, CWD, or workspace."""
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
        return ws_cfg if ws_cfg.exists() else None

    @classmethod
    def resolve_toml_config(
        cls, orchestrator_name: str, config_path: Path | None = None
    ) -> dict[str, Any]:
        """Load the ``[pirlo.orchestrator.<name>]`` table, or {} if absent."""
        resolved_path = cls.resolve_config_path(config_path)
        if not resolved_path:
            return {}
        try:
            with open(resolved_path, "rb") as f:
                raw_cfg = tomllib.load(f)
        except (OSError, tomllib.TOMLDecodeError) as e:
            print(f"⚠️ Warning: Failed to parse {resolved_path}: {e}")
            return {}
        return (
            raw_cfg.get("pirlo", {}).get("orchestrator", {}).get(orchestrator_name, {})
        )

    # --- plugin discovery -------------------------------------------------

    @classmethod
    def _discover_plugins(cls) -> None:
        """Scan installed package entry points for external orchestrator plugins."""
        try:
            entry_points = importlib.metadata.entry_points()
            plugins = (
                entry_points.select(group="pirlo.orchestrators")
                if hasattr(entry_points, "select")
                else entry_points.get("pirlo.orchestrators", [])  # type: ignore[union-attr,attr-defined]
            )
        except Exception as e:  # noqa: BLE001
            print(f"⚠️ Warning: Plugin discovery failed: {e}")
            return

        for ep in plugins:
            if ep.name in cls._registry:
                continue
            try:
                cls.register(ep.name, ep.load())
            except Exception as e:  # noqa: BLE001
                print(f"⚠️ Warning: Failed to load orchestrator plugin '{ep.name}': {e}")
