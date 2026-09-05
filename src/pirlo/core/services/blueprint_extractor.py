# src/pirlo/core/services/blueprint_extractor.py
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
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
from pirlo.core.ports.playbook import MappedParameter

if TYPE_CHECKING:
    from pirlo.core.ports.play import Play
    from pirlo.core.ports.playbook import Playbook, PlayerNode


class BlueprintExtractorStrategy(ABC):
    """Abstract Strategy for extracting a PlaybookBlueprint IR."""

    @abstractmethod
    def extract(self, target: Any, **kwargs: Any) -> PlaybookBlueprint:
        """Extract a PlaybookBlueprint from the target definition."""
        raise NotImplementedError


class PullBasedPlayExtractorStrategy(BlueprintExtractorStrategy):
    """Extracts a PlaybookBlueprint by recursively resolving requires() descriptors from a target Play."""

    def extract(
        self,
        target: type[Play[Any]] | Play[Any],
        user_kwargs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> PlaybookBlueprint:

        target_cls: type[Play[Any]] = (
            target if isinstance(target, type) else target.__class__
        )
        blueprint = PlaybookBlueprint(
            name=target_cls.__name__,
            entry_playbook=target_cls.__name__,
        )
        visited_nodes: dict[type[Play[Any]], str] = {}
        all_user_kwargs: dict[str, Any] = user_kwargs or {}

        def _resolve(play_cls: type[Play[Any]], step_kwargs: dict[str, Any]) -> str:
            if play_cls in visited_nodes:
                return visited_nodes[play_cls]

            node_id = f"play_{len(blueprint.nodes) + 1}_{play_cls.__name__}"
            depends_on: list[str] = []
            param_bindings: dict[str, ParamBinding] = {}
            mapped_bindings: dict[str, ParamBinding] = {}
            is_mapped: bool = False

            # 1. Resolve upstream requirements first (depth-first traversal)
            for field_name, req_desc in play_cls.get_upstream_requirements().items():
                upstream_id = _resolve(req_desc.play_cls, req_desc.kwargs)
                if upstream_id not in depends_on:
                    depends_on.append(upstream_id)
                # Injects entire upstream output into downstream field
                param_bindings[field_name] = ParamBinding(
                    source_node_id=upstream_id,
                    source_field="",
                )

            # 2. Check for parameters bubbled from user_kwargs that belong to this play
            import inspect

            fn = getattr(play_cls, "execute", getattr(play_cls, "play", None))
            node_user_kwargs: dict[str, Any] = {}
            if fn:
                sig = inspect.signature(fn)
                for p_name, p_val in all_user_kwargs.items():
                    if p_name in sig.parameters:
                        node_user_kwargs[p_name] = p_val

            effective_step_kwargs = {**node_user_kwargs, **step_kwargs}

            # 3. Process node kwargs & dynamic mapping
            static_kwargs: dict[str, ParameterValue] = {}
            mapped_static_kwargs: list[str] = []
            for param_name, parameter_value in effective_step_kwargs.items():
                if isinstance(parameter_value, MappedParameter):
                    is_mapped = True
                    target_val = parameter_value.target
                    if isinstance(target_val, ProxyRef):
                        mapped_bindings[param_name] = ParamBinding(
                            source_node_id=target_val.node_id,
                            source_field=target_val.field,
                        )
                        if target_val.node_id not in depends_on:
                            depends_on.append(target_val.node_id)
                    else:
                        static_kwargs[param_name] = target_val
                        mapped_static_kwargs.append(param_name)
                elif isinstance(parameter_value, ProxyRef):
                    param_bindings[param_name] = ParamBinding(
                        source_node_id=parameter_value.node_id,
                        source_field=parameter_value.field,
                    )
                    if parameter_value.node_id not in depends_on:
                        depends_on.append(parameter_value.node_id)
                else:
                    static_kwargs[param_name] = parameter_value

            node = BlueprintNode(
                node_id=node_id,
                playbook_name=play_cls.__name__,
                static_kwargs=static_kwargs,
                param_bindings=param_bindings,
                mapped_bindings=mapped_bindings,
                mapped_static_kwargs=mapped_static_kwargs,
                is_mapped=is_mapped
                or len(mapped_bindings) > 0
                or len(mapped_static_kwargs) > 0,
                depends_on=depends_on,
            )
            blueprint.nodes.append(node)
            visited_nodes[play_cls] = node_id
            return node_id

        terminal_id = _resolve(target_cls, {})
        blueprint.output_node_id = terminal_id
        return blueprint


class TracingPlaybookExtractorStrategy(BlueprintExtractorStrategy):
    """Extracts a PlaybookBlueprint by dry-run tracing forward Playbook.play() calls."""

    async def extract_async(
        self, playbook: Playbook[Any] | type[Playbook[Any]]
    ) -> PlaybookBlueprint:
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

    def extract(self, target: Any, **kwargs: Any) -> PlaybookBlueprint:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.extract_async(target))
        else:
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(
                    lambda: asyncio.run(self.extract_async(target))
                ).result()


class BlueprintExtractor:
    """Facade for blueprint extraction dispatching to appropriate strategies."""

    @classmethod
    def extract_from_play(
        cls,
        play_cls: type[Play[Any]] | Play[Any],
        user_kwargs: dict[str, Any] | None = None,
    ) -> PlaybookBlueprint:
        """Extracts a PlaybookBlueprint from a Play class using pull-based requires() resolution."""
        strategy = PullBasedPlayExtractorStrategy()
        return strategy.extract(play_cls, user_kwargs=user_kwargs)

    @classmethod
    async def extract_async(
        cls, playbook: Playbook[Any] | type[Playbook[Any]]
    ) -> PlaybookBlueprint:
        """Asynchronously traces a Playbook instance or class in dry-run mode."""
        strategy = TracingPlaybookExtractorStrategy()
        return await strategy.extract_async(playbook)

    @classmethod
    def extract(
        cls, playbook: Playbook[Any] | type[Playbook[Any]]
    ) -> PlaybookBlueprint:
        """Traces the playbook in dry-run mode to generate the PlaybookBlueprint."""
        from pirlo.core.ports.play import Play

        if isinstance(playbook, type) and issubclass(playbook, Play):
            return cls.extract_from_play(playbook)
        if isinstance(playbook, Play):
            return cls.extract_from_play(playbook)

        strategy = TracingPlaybookExtractorStrategy()
        return strategy.extract(playbook)

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
