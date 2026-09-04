# src/pirlo/infrastructure/adapters/orchestrator/prefect_compiler.py
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, cast

from prefect import flow
from prefect.futures import PrefectFuture

from pirlo.core.models.blueprint import (
    BlueprintError,
    BlueprintNode,
    PlaybookBlueprint,
    PlaybookOutput,
    SymbolicProxy,
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

        @flow(name=blueprint.name)
        async def prefect_master_flow(
            **workflow_kwargs: object,
        ) -> PlaybookOutput | None:
            futures: dict[str, PrefectFuture[PlaybookOutput]] = {}

            blueprint_node: BlueprintNode
            for blueprint_node in blueprint.nodes:
                resolved_kwargs: dict[str, object] = dict(blueprint_node.static_kwargs)
                param_name: str
                param_binding: Any
                for param_name, param_binding in blueprint_node.param_bindings.items():
                    parent_future: PrefectFuture[PlaybookOutput] = futures[
                        param_binding.source_node_id
                    ]
                    parent_result: PlaybookOutput = await parent_future.result()  # type: ignore[misc]
                    resolved_kwargs[param_name] = getattr(
                        parent_result, param_binding.source_field, None
                    )

                playbook_cls: type[Playbook[PlaybookOutput]] = (
                    cls._resolve_playbook_class(blueprint_node.playbook_name)
                )

                @flow(name=f"Subflow: {blueprint_node.playbook_name}")
                async def subflow_runner(
                    _cls: type[Playbook[PlaybookOutput]] = playbook_cls,
                    **kwargs: object,
                ) -> PlaybookOutput:
                    instance: Playbook[PlaybookOutput] = _cls()
                    playbook_result: (
                        PlaybookOutput | RunResult[PlaybookOutput] | SymbolicProxy
                    ) = await instance.play(**kwargs)  # type: ignore[arg-type]
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
                            await mapped_parent_future.result()  # type: ignore[misc]
                        )
                        mapped_kwargs[param_name] = getattr(
                            mapped_parent_result, param_binding.source_field, []
                        )

                    from prefect import unmapped

                    unmapped_kwargs = {
                        k: unmapped(v) for k, v in resolved_kwargs.items()
                    }
                    mapped_future: Any = await subflow_runner.map(  # type: ignore[attr-defined]
                        wait_for=parent_futures,
                        **mapped_kwargs,
                        **unmapped_kwargs,
                    )
                    futures[blueprint_node.node_id] = mapped_future
                else:
                    prefect_future: PrefectFuture[
                        PlaybookOutput
                    ] = await subflow_runner.submit(  # type: ignore[attr-defined]
                        wait_for=parent_futures, **resolved_kwargs
                    )
                    futures[blueprint_node.node_id] = prefect_future

            if blueprint.output_node_id and blueprint.output_node_id in futures:
                final_prefect_future: PrefectFuture[PlaybookOutput] = futures[
                    blueprint.output_node_id
                ]
                return await final_prefect_future.result()  # type: ignore[misc]
            return None

        return prefect_master_flow

    @classmethod
    def _resolve_playbook_class(
        cls, playbook_name: str
    ) -> type[Playbook[PlaybookOutput]]:
        from pirlo.infrastructure.services.playbook_scanner import PlaybookScanner

        class_object: type[object] = PlaybookScanner().get_playbook_class(playbook_name)
        return cast(type[Playbook[PlaybookOutput]], class_object)
