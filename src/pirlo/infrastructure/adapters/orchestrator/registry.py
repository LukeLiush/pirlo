import contextlib
import importlib
import importlib.metadata
import inspect
import pkgutil
from pathlib import Path
from typing import Any, ClassVar

from pirlo.core.ports.orchestrator_plugin import OrchestratorPlugin


class OrchestratorRegistry:
    """Registry managing workflow engine plugins with automated discovery."""

    base_package: ClassVar[str] = "pirlo.infrastructure.adapters.orchestrator"
    search_dir: ClassVar[Path | None] = None
    _plugins: ClassVar[dict[str, OrchestratorPlugin[Any]]] = {}
    _initialized: ClassVar[bool] = False

    @classmethod
    def _discover_plugins(cls) -> None:
        """Fully automated discovery: scans local subpackages and entry points."""
        if cls._initialized:
            return
        cls._initialized = True

        # 1. Auto-scan local subdirectories using configurable base_package and search_dir
        current_dir = cls.search_dir or Path(__file__).parent
        for module_info in pkgutil.iter_modules([str(current_dir)]):
            if module_info.ispkg:
                try:
                    module = importlib.import_module(
                        f"{cls.base_package}.{module_info.name}.plugin"
                    )
                    for _, obj in inspect.getmembers(module, inspect.isclass):
                        if (
                            issubclass(obj, OrchestratorPlugin)
                            and obj is not OrchestratorPlugin
                        ):
                            cls.register(obj())
                except (ImportError, AttributeError):
                    pass

        # 2. Auto-load 3rd-party plugins registered via entry_points
        with contextlib.suppress(Exception):
            for ep in importlib.metadata.entry_points(group="pirlo.orchestrators"):
                plugin_cls = ep.load()
                cls.register(plugin_cls())

    @classmethod
    def register(cls, plugin: OrchestratorPlugin[Any]) -> None:
        """Registers a plugin instance."""
        cls._plugins[plugin.engine_name.lower()] = plugin

    @classmethod
    def get(cls, engine_name: str) -> OrchestratorPlugin[Any]:
        """Retrieves a registered plugin by engine name."""
        cls._discover_plugins()
        normalized = engine_name.lower().strip()
        if normalized not in cls._plugins:
            raise ValueError(
                f"Unknown orchestrator engine '{engine_name}'. "
                f"Discovered engines: {list(cls._plugins.keys())}"
            )
        return cls._plugins[normalized]

    @classmethod
    def is_registered(cls, engine_name: str) -> bool:
        """Checks whether an engine identifier is registered."""
        cls._discover_plugins()
        return engine_name.lower().strip() in cls._plugins

    @classmethod
    def list_engines(cls) -> list[str]:
        """Returns all registered engine identifiers."""
        cls._discover_plugins()
        return list(cls._plugins.keys())

    @classmethod
    def reset(cls) -> None:
        """Resets the registry state (useful in test suites)."""
        cls._plugins.clear()
        cls._initialized = False
