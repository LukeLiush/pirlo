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
from pirlo.core.ports.playbook import Playbook

logger = logging.getLogger(__name__)


class PrefectCompiler:
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

                playbook_cls: type[Playbook[PlaybookOutput]] = (
                    cls._resolve_playbook_class(blueprint_node.playbook_name)
                )

                @task(
                    name=f"Task: {blueprint_node.playbook_name}",
                )
                async def subflow_runner(
                    target_cls: type[Playbook[Any]] = playbook_cls,
                    **kwargs: object,
                ) -> PlaybookOutput:
                    instance: Playbook[PlaybookOutput] = target_cls()
                    playbook_result: Any = await instance.play(**kwargs)
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

                    unmapped_kwargs = {
                        k: unmapped(v) for k, v in resolved_kwargs.items()
                    }
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
    def _resolve_playbook_class(
        cls, playbook_name: str
    ) -> type[Playbook[PlaybookOutput]]:
        import contextlib
        import sys

        from pirlo.core.ports.playbook import Playbook
        from pirlo.infrastructure.services.playbook_scanner import PlaybookScanner

        # 1. Search sys.modules for loaded Playbook subclasses
        for module in list(sys.modules.values()):
            if not module:
                continue
            with contextlib.suppress(AttributeError, TypeError):
                module_dict = getattr(module, "__dict__", {})
                for obj in module_dict.values():
                    if (
                        isinstance(obj, type)
                        and issubclass(obj, Playbook)
                        and obj.__name__ == playbook_name
                    ):
                        return cast(type[Playbook[PlaybookOutput]], obj)

        # 2. Fallback to PlaybookScanner disk scanner
        class_object: type[object] = PlaybookScanner().get_playbook_class(playbook_name)
        return cast(type[Playbook[PlaybookOutput]], class_object)
