# src/pirlo/core/services/blueprint_extractor.py
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from pirlo.core.models.blueprint import (
    BlueprintError,
    BlueprintNode,
    ParamBinding,
    ParameterValue,
    PlaybookBlueprint,
    PlaybookOutput,
    ProxyRef,
    SymbolicProxy,
)

if TYPE_CHECKING:
    from pirlo.core.ports.playbook import MappedParameter, Playbook, PlayerNode


class BlueprintExtractor:
    """Dedicated service for dry-run tracing a Playbook to generate a PlaybookBlueprint."""

    @classmethod
    async def extract_async(
        cls, playbook: Playbook[Any] | type[Playbook[Any]]
    ) -> PlaybookBlueprint:
        """Asynchronously traces a Playbook instance or class in dry-run mode to generate a PlaybookBlueprint."""
        from pirlo.core.ports.playbook import PlayerNode

        instance: Playbook[Any] = playbook() if isinstance(playbook, type) else playbook
        instance._is_tracing = True
        blueprint = PlaybookBlueprint(
            name=instance.__class__.__name__,
            entry_playbook=instance.__class__.__name__,
        )
        instance._tracing_blueprint = blueprint
        instance._drafted_players = []

        try:
            play_result: Any = await instance.play()
            if blueprint is not None:
                if isinstance(play_result, (PlayerNode, SymbolicProxy)):
                    blueprint.output_node_id = str(play_result.node_id)
                elif blueprint.output_node_id is None and instance._drafted_players:
                    blueprint.output_node_id = instance._drafted_players[-1].node_id
        except Exception as error:
            raise BlueprintError(
                f"Failed to trace blueprint for {instance.__class__.__name__}: {error}"
            ) from error
        finally:
            instance._is_tracing = False
            instance._tracing_blueprint = None

        return blueprint

    @classmethod
    def extract(
        cls, playbook: Playbook[Any] | type[Playbook[Any]]
    ) -> PlaybookBlueprint:
        """Traces the playbook in dry-run mode to generate the PlaybookBlueprint."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(cls.extract_async(playbook))
        else:
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(
                    lambda: asyncio.run(cls.extract_async(playbook))
                ).result()

    @classmethod
    def blueprint_from_players(
        cls,
        playbook: Playbook[Any],
        players: list[PlayerNode],
        target_node_id: str | None = None,
    ) -> PlaybookBlueprint:
        """Generates a PlaybookBlueprint directly from a list of drafted PlayerNodes."""
        blueprint = PlaybookBlueprint(
            name=playbook.__class__.__name__,
            entry_playbook=playbook.__class__.__name__,
            output_node_id=target_node_id or (players[-1].node_id if players else None),
        )

        for p in players:
            extra_deps = [dep.node_id for dep in p.depends_on_nodes]
            cls.record_traced_node(
                blueprint=blueprint,
                playbook_cls=p.playbook_cls,
                kwargs=p.kwargs,
                node_id=p.node_id,
                extra_deps=extra_deps,
                is_mapped=p.is_mapped,
            )

        return blueprint

    @classmethod
    def record_traced_node(
        cls,
        blueprint: PlaybookBlueprint,
        playbook_cls: type[Playbook[PlaybookOutput]],
        kwargs: dict[str, ParameterValue | ProxyRef | MappedParameter | SymbolicProxy],
        node_id: str | None = None,
        extra_deps: list[str] | None = None,
        is_mapped: bool = False,
    ) -> SymbolicProxy:
        """Records a single node into the given PlaybookBlueprint."""
        from pirlo.core.ports.playbook import MappedParameter

        step_index: int = len(blueprint.nodes) + 1
        effective_id: str = node_id or f"node_{step_index}_{playbook_cls.__name__}"

        static_kwargs: dict[str, ParameterValue] = {}
        param_bindings: dict[str, ParamBinding] = {}
        mapped_bindings: dict[str, ParamBinding] = {}
        depends_on: set[str] = set(extra_deps or [])

        for param_name, parameter_value in kwargs.items():
            if isinstance(parameter_value, MappedParameter):
                target = parameter_value.target
                if isinstance(target, ProxyRef):
                    mapped_bindings[param_name] = ParamBinding(
                        source_node_id=target.node_id,
                        source_field=target.field,
                    )
                    depends_on.add(target.node_id)
            elif isinstance(parameter_value, SymbolicProxy):
                proxy_node_id: str = getattr(
                    parameter_value, "_node_id", str(parameter_value.node_id)
                )
                param_bindings[param_name] = ParamBinding(
                    source_node_id=proxy_node_id,
                    source_field="",
                )
                depends_on.add(proxy_node_id)
            elif isinstance(parameter_value, ProxyRef):
                param_bindings[param_name] = ParamBinding(
                    source_node_id=parameter_value.node_id,
                    source_field=parameter_value.field,
                )
                depends_on.add(parameter_value.node_id)
            else:
                static_kwargs[param_name] = parameter_value

        node: BlueprintNode = BlueprintNode(
            node_id=effective_id,
            playbook_name=playbook_cls.__name__,
            static_kwargs=static_kwargs,
            param_bindings=param_bindings,
            mapped_bindings=mapped_bindings,
            is_mapped=is_mapped or len(mapped_bindings) > 0,
            depends_on=sorted(depends_on),
        )
        blueprint.nodes.append(node)
        blueprint.output_node_id = effective_id
        return SymbolicProxy(node_id=effective_id)
