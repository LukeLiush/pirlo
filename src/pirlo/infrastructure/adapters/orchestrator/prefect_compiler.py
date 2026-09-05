# src/pirlo/infrastructure/adapters/orchestrator/prefect_compiler.py
from __future__ import annotations

import logging
from typing import Any, cast

from prefect import flow, task
from prefect.futures import PrefectFuture

from pirlo.core.models.blueprint import (
    BlueprintError,
    BlueprintNode,
    PlayBlueprint,
    PlayOutput,
)
from pirlo.core.models.run_result import RunResult
from pirlo.core.ports.compiler import BlueprintCompiler
from pirlo.core.ports.play import Play
from pirlo.core.services.idempotency import compute_play_identity
from pirlo.infrastructure.adapters.cli.terminal_play_ui import TerminalPlayUI
from pirlo.infrastructure.adapters.orchestrator.prefect_model import (
    PrefectWorkflow,
)

logger = logging.getLogger(__name__)


class PrefectCompiler(BlueprintCompiler[PrefectWorkflow]):
    """Compiles a PlayBlueprint into an executable PrefectWorkflow model."""

    def __init__(self, validate_parameters: bool = False) -> None:
        self.validate_parameters: bool = validate_parameters

    def compile(
        self,
        blueprint: PlayBlueprint,
    ) -> PrefectWorkflow:
        """Dynamically constructs a master PrefectWorkflow from the PlayBlueprint."""
        if not blueprint.nodes:
            raise BlueprintError(f"Cannot compile empty blueprint '{blueprint.name}'.")

        @flow(name=blueprint.name, validate_parameters=self.validate_parameters)
        async def prefect_master_flow(
            **workflow_kwargs: object,
        ) -> PlayOutput | None:
            futures: dict[str, PrefectFuture[PlayOutput]] = {}

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
                    parent_future: PrefectFuture[PlayOutput] = futures[
                        param_binding.source_node_id
                    ]
                    parent_result: PlayOutput = await _resolve_future_result(
                        parent_future
                    )
                    resolved_kwargs[param_name] = (
                        getattr(parent_result, param_binding.source_field)
                        if param_binding.source_field
                        else parent_result
                    )

                play_cls: type[Any] = self._resolve_play_class(
                    blueprint_node.playbook_name
                )
                play_name: str = getattr(
                    play_cls, "play_name", blueprint_node.playbook_name
                )

                @task(
                    name=f"Task: {play_name}",
                )
                async def subflow_runner(
                    target_cls: type[Any] = play_cls,
                    node_name: str = blueprint_node.playbook_name,
                    **kwargs: object,
                ) -> PlayOutput:
                    active_play_name = getattr(target_cls, "play_name", node_name)
                    identity = compute_play_identity(active_play_name, kwargs)
                    try:
                        instance: Any = target_cls(
                            ui=TerminalPlayUI(play_name=identity.short_id),
                            play_id=identity.full_id,
                        )
                    except TypeError:
                        try:
                            instance = target_cls(
                                ui=TerminalPlayUI(play_name=identity.short_id)
                            )
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
                    play_result: Any = await instance.execute(**exec_kwargs)

                    return (
                        play_result.data
                        if isinstance(play_result, RunResult) and play_result.data
                        else cast(PlayOutput, play_result)
                    )

                parent_futures: list[PrefectFuture[PlayOutput]] = [
                    futures[parent_id] for parent_id in blueprint_node.depends_on
                ]

                if blueprint_node.is_mapped:
                    mapped_kwargs: dict[str, object] = {}
                    for (
                        param_name,
                        param_binding,
                    ) in blueprint_node.mapped_bindings.items():
                        mapped_parent_future: PrefectFuture[PlayOutput] = futures[
                            param_binding.source_node_id
                        ]
                        mapped_parent_result: PlayOutput = await _resolve_future_result(
                            mapped_parent_future
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
                    prefect_future: PrefectFuture[PlayOutput] = subflow_runner.submit(  # type: ignore[call-overload]
                        wait_for=parent_futures, **resolved_kwargs
                    )
                    futures[blueprint_node.node_id] = prefect_future

            if blueprint.output_node_id and blueprint.output_node_id in futures:
                final_prefect_future: PrefectFuture[PlayOutput] = futures[
                    blueprint.output_node_id
                ]
                return await _resolve_future_result(final_prefect_future)
            return None

        return PrefectWorkflow(
            name=blueprint.name,
            flow=prefect_master_flow,
            blueprint=blueprint,
        )

    def _resolve_play_class(self, play_name: str) -> type[Any]:
        import contextlib
        import sys

        # 1. Search sys.modules for loaded Play subclasses
        for module in list(sys.modules.values()):
            if not module:
                continue
            with contextlib.suppress(AttributeError, TypeError):
                module_dict = getattr(module, "__dict__", {})
                for obj in module_dict.values():
                    if (
                        isinstance(obj, type)
                        and issubclass(obj, Play)
                        and obj.__name__ == play_name
                    ):
                        return cast(type[Any], obj)

        # 2. Fallback to PlayScanner disk scanner
        from pirlo.infrastructure.services.play_scanner import PlayScanner

        class_object: type[object] = PlayScanner().get_play_class(play_name)
        return cast(type[Any], class_object)
