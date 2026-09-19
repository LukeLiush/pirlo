import contextlib
import importlib
import inspect
import pkgutil
from pathlib import Path
from typing import Any, ClassVar, get_args

from pirlo.core.models.orchestrator import OrchestratorLink
from pirlo.core.ports.orchestrator_plugin import OrchestratorPlugin


class OrchestratorRegistry:
    """Registry managing workflow engine plugins with automated discovery."""

    base_package: ClassVar[str] = "pirlo.infrastructure.adapters.orchestrator"
    search_dir: ClassVar[Path | None] = None
    _plugins: ClassVar[dict[str, OrchestratorPlugin[Any]]] = {}
    _orchestrator_link_classes: ClassVar[dict[str, type[OrchestratorLink]]] = {}
    _initialized: ClassVar[bool] = False

    @classmethod
    def _discover_plugins(cls) -> None:
        """Fully automated discovery: scans local subpackages."""
        if cls._initialized:
            return
        cls._initialized = True

        # 1. Auto-scan local subdirectories using configurable base_package and search_dir
        current_dir = cls.search_dir or Path(__file__).parent
        for module_info in pkgutil.iter_modules([str(current_dir)]):
            if module_info.ispkg:
                with contextlib.suppress(ImportError, AttributeError):
                    module = importlib.import_module(
                        f"{cls.base_package}.{module_info.name}.plugin"
                    )
                    for _, obj in inspect.getmembers(module, inspect.isclass):
                        if (
                            issubclass(obj, OrchestratorPlugin)
                            and obj is not OrchestratorPlugin
                        ):
                            engine = getattr(obj, "engine_name", module_info.name)

                            # Extract link class from generic base OrchestratorPlugin[TLink]
                            for base in getattr(obj, "__orig_bases__", ()):
                                args = get_args(base)
                                if (
                                    args
                                    and isinstance(args[0], type)
                                    and issubclass(args[0], OrchestratorLink)
                                ):
                                    link_cls = args[0]
                                    link_cls.model_fields["engine"].default = engine
                                    cls._orchestrator_link_classes[engine] = link_cls
                                    break

                            cls._plugins[engine] = obj()

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
    def get_orchestrator_link_cls(cls, engine_name: str) -> type[OrchestratorLink]:
        """Retrieves the OrchestratorLink class associated with the engine."""
        cls._discover_plugins()
        normalized = engine_name.lower().strip()
        if normalized not in cls._orchestrator_link_classes:
            raise ValueError(
                f"Unknown orchestrator engine '{engine_name}'. "
                f"Discovered engines: {list(cls._orchestrator_link_classes.keys())}"
            )
        return cls._orchestrator_link_classes[normalized]

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
        cls._orchestrator_link_classes.clear()
        cls._initialized = False
