# src/pirlo/infrastructure/adapters/orchestrator/prefect_compiler.py
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, cast

from prefect import flow, task
from prefect.futures import PrefectFuture

from pirlo.core.models.blueprint import (
    BlueprintError,
    BlueprintNode,
    PlaybookBlueprint,
    PlaybookOutput,
)
from pirlo.core.models.run_result import RunResult
from pirlo.core.ports.compiler import BlueprintCompiler
from pirlo.core.ports.play import Play
from pirlo.infrastructure.adapters.cli.terminal_play_ui import TerminalPlayUI

logger = logging.getLogger(__name__)


class PrefectCompiler(
    BlueprintCompiler[Callable[..., Awaitable[PlaybookOutput | None]]]
):
    """Compiles a PlaybookBlueprint into executable Prefect 3 Flows & Tasks."""

    @classmethod
    def compile(
        cls, blueprint: PlaybookBlueprint
    ) -> Callable[..., Awaitable[PlaybookOutput | None]]:
        """Dynamically constructs a master Prefect Flow from the PlaybookBlueprint."""
        if not blueprint.nodes:
            raise BlueprintError(f"Cannot compile empty blueprint '{blueprint.name}'.")

        @flow(name=blueprint.name, validate_parameters=False)
        async def prefect_master_flow(
            **workflow_kwargs: object,
        ) -> PlaybookOutput | None:
            futures: dict[str, PrefectFuture[PlaybookOutput]] = {}

            async def _resolve_future_result(fut: Any) -> Any:
                import inspect

                if isinstance(fut, list):
                    return [await _resolve_future_result(f) for f in fut]
                res = fut.result()
                if inspect.isawaitable(res):
                    return await res
                return res

            blueprint_node: BlueprintNode
            for blueprint_node in blueprint.nodes:
                resolved_kwargs: dict[str, object] = dict(blueprint_node.static_kwargs)
                param_name: str
                param_binding: Any
                for param_name, param_binding in blueprint_node.param_bindings.items():
                    parent_future: PrefectFuture[PlaybookOutput] = futures[
                        param_binding.source_node_id
                    ]
                    parent_result: PlaybookOutput = await _resolve_future_result(
                        parent_future
                    )
                    resolved_kwargs[param_name] = (
                        getattr(parent_result, param_binding.source_field)
                        if param_binding.source_field
                        else parent_result
                    )

                playbook_cls: type[Any] = cls._resolve_playbook_class(
                    blueprint_node.playbook_name
                )

                @task(
                    name=f"Task: {blueprint_node.playbook_name}",
                )
                async def subflow_runner(
                    target_cls: type[Any] = playbook_cls,
                    **kwargs: object,
                ) -> PlaybookOutput:
                    try:
                        instance: Any = target_cls(ui=TerminalPlayUI())
                    except TypeError:
                        instance = target_cls()

                    exec_kwargs = dict(kwargs)
                    import inspect

                    sig = inspect.signature(instance.execute)
                    has_var_keyword = any(
                        p.kind == inspect.Parameter.VAR_KEYWORD
                        for p in sig.parameters.values()
                    )

                    # Injects resolved upstream requirements into instance.__dict__
                    if hasattr(target_cls, "get_upstream_requirements"):
                        reqs = target_cls.get_upstream_requirements()
                        for field_name in reqs:
                            if field_name in kwargs:
                                setattr(instance, field_name, kwargs[field_name])
                                if field_name not in sig.parameters:
                                    exec_kwargs.pop(field_name, None)

                    # Filter exec_kwargs to only accepted parameters if no **kwargs
                    if not has_var_keyword:
                        exec_kwargs = {
                            k: v for k, v in exec_kwargs.items() if k in sig.parameters
                        }

                    # Executes execute() for Play
                    playbook_result: Any = await instance.execute(**exec_kwargs)

                    return (
                        playbook_result.data
                        if isinstance(playbook_result, RunResult)
                        and playbook_result.data
                        else cast(PlaybookOutput, playbook_result)
                    )

                parent_futures: list[PrefectFuture[PlaybookOutput]] = [
                    futures[parent_id] for parent_id in blueprint_node.depends_on
                ]

                if blueprint_node.is_mapped:
                    mapped_kwargs: dict[str, object] = {}
                    for (
                        param_name,
                        param_binding,
                    ) in blueprint_node.mapped_bindings.items():
                        mapped_parent_future: PrefectFuture[PlaybookOutput] = futures[
                            param_binding.source_node_id
                        ]
                        mapped_parent_result: PlaybookOutput = (
                            await _resolve_future_result(mapped_parent_future)
                        )
                        mapped_kwargs[param_name] = (
                            getattr(mapped_parent_result, param_binding.source_field)
                            if param_binding.source_field
                            else mapped_parent_result
                        )

                    from prefect import unmapped

                    unmapped_kwargs = {}
                    for k, v in resolved_kwargs.items():
                        if k in getattr(blueprint_node, "mapped_static_kwargs", []):
                            mapped_kwargs[k] = v
                        else:
                            unmapped_kwargs[k] = unmapped(v)

                    mapped_future: Any = subflow_runner.map(  # type: ignore[call-overload]
                        wait_for=parent_futures,
                        **mapped_kwargs,
                        **unmapped_kwargs,
                    )
                    futures[blueprint_node.node_id] = mapped_future
                else:
                    prefect_future: PrefectFuture[PlaybookOutput] = (
                        subflow_runner.submit(  # type: ignore[call-overload]
                            wait_for=parent_futures, **resolved_kwargs
                        )
                    )
                    futures[blueprint_node.node_id] = prefect_future

            if blueprint.output_node_id and blueprint.output_node_id in futures:
                final_prefect_future: PrefectFuture[PlaybookOutput] = futures[
                    blueprint.output_node_id
                ]
                return await _resolve_future_result(final_prefect_future)
            return None

        return prefect_master_flow

    @classmethod
    async def run_ephemeral(cls, blueprint: PlaybookBlueprint) -> PlaybookOutput | None:
        """Executes the PlaybookBlueprint in local ephemeral mode."""
        from prefect.settings import (
            PREFECT_API_URL,
            PREFECT_SERVER_ALLOW_EPHEMERAL_MODE,
            temporary_settings,
        )

        from pirlo.infrastructure.adapters.orchestrator.prefect_discovery import (
            discover_prefect_server_url,
        )

        active_api_url: str | None = discover_prefect_server_url()
        override_settings = (
            {PREFECT_API_URL: active_api_url}
            if active_api_url
            else {PREFECT_API_URL: None, PREFECT_SERVER_ALLOW_EPHEMERAL_MODE: True}
        )

        with temporary_settings(override_settings):
            master_flow = cls.compile(blueprint)
            return await master_flow()

    @classmethod
    def _resolve_playbook_class(cls, playbook_name: str) -> type[Any]:
        import contextlib
        import sys

        # 1. Search sys.modules for loaded Playbook or Play subclasses
        for module in list(sys.modules.values()):
            if not module:
                continue
            with contextlib.suppress(AttributeError, TypeError):
                module_dict = getattr(module, "__dict__", {})
                for obj in module_dict.values():
                    if (
                        isinstance(obj, type)
                        and issubclass(obj, Play)
                        and obj.__name__ == playbook_name
                    ):
                        return cast(type[Any], obj)

        # 2. Fallback to PlayScanner disk scanner
        from pirlo.infrastructure.services.play_scanner import PlayScanner

        class_object: type[object] = PlayScanner().get_play_class(playbook_name)
        return cast(type[Any], class_object)
