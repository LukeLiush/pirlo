# src/pirlo/core/ports/pitch.py
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Generator
from typing import Any, Generic, TypeVar, cast

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
from pirlo.core.models.run import PreparedRun
from pirlo.core.models.run_result import RunResult
from pirlo.core.ports.playbook_ui import PlaybookUI
from pirlo.infrastructure.adapters.cli.terminal_playbook_ui import TerminalPlaybookUI

T = TypeVar("T", bound=PlaybookOutput)


class MappedParameter:
    """Wrapper marking a parameter for dynamic subtask fan-out mapping."""

    def __init__(self, target: ProxyRef | list[Any]) -> None:
        self.target: ProxyRef | list[Any] = target


def each(target: ProxyRef | list[Any]) -> MappedParameter:
    """Marks a parameter for dynamic subtask fan-out mapping across items."""
    return MappedParameter(target)


class PlayerNode:
    """Represents a player (task node) drafted onto the Pitch for DAG composition with '.after()' or '>>'."""

    def __init__(
        self,
        node_id: str,
        playbook_cls: type[Playbook[PlaybookOutput]],
        kwargs: dict[str, ParameterValue | ProxyRef | MappedParameter | SymbolicProxy],
        is_mapped: bool = False,
        playbook: Playbook[Any] | None = None,
    ) -> None:
        self.node_id: str = node_id
        self.playbook_cls: type[Playbook[PlaybookOutput]] = playbook_cls
        self.kwargs: dict[
            str, ParameterValue | ProxyRef | MappedParameter | SymbolicProxy
        ] = kwargs
        self.is_mapped: bool = is_mapped
        self.depends_on_nodes: list[PlayerNode] = []
        self._proxy: SymbolicProxy = SymbolicProxy(node_id=node_id)
        self._playbook: Playbook[Any] | None = playbook

    def __await__(self) -> Generator[Any, None, Any]:
        if self._playbook is None:
            raise BlueprintError("PlayerNode is not bound to a Playbook instance.")
        return self._playbook._execute_player_node(self).__await__()

    @property
    def ball(self) -> SymbolicProxy:
        """Access output payload fields of this player (e.g. player_1.ball.auth_token)."""
        return self._proxy

    def __getattr__(self, name: str) -> ProxyRef:
        """Direct property proxying (e.g. player_1.auth_token)."""
        return getattr(self._proxy, name)

    def after(self, *upstream_nodes: PlayerNode | list[PlayerNode]) -> PlayerNode:
        """Fluent method declaring that this player node runs AFTER the specified upstream player nodes."""
        node_argument: PlayerNode | list[PlayerNode]
        for node_argument in upstream_nodes:
            nodes_list: list[PlayerNode] = (
                node_argument if isinstance(node_argument, list) else [node_argument]
            )
            upstream_node: PlayerNode
            for upstream_node in nodes_list:
                if upstream_node not in self.depends_on_nodes:
                    self.depends_on_nodes.append(upstream_node)
        return self

    def __rshift__(
        self, other: PlayerNode | list[PlayerNode]
    ) -> PlayerNode | list[PlayerNode]:
        """Operator '>>' syntax sugar forwarding to .after(self)."""
        target_player_nodes: list[PlayerNode] = (
            other if isinstance(other, list) else [other]
        )
        target_node: PlayerNode
        for target_node in target_player_nodes:
            target_node.after(self)
        return other

    def __rrshift__(self, other: PlayerNode | list[PlayerNode]) -> PlayerNode:
        """Reversed Operator '>>' for list-to-single (e.g. [A, B] >> C)."""
        self.after(other)
        return self


class PlayerGroup:
    """Group of PlayerNode instances for batch operators like players(p1, p2) >> p3."""

    def __init__(self, nodes: list[PlayerNode]) -> None:
        self.nodes: list[PlayerNode] = nodes

    def __rshift__(
        self, other: PlayerNode | list[PlayerNode]
    ) -> PlayerNode | list[PlayerNode]:
        player_node: PlayerNode
        for player_node in self.nodes:
            player_node >> other
        return other


def players(*nodes: PlayerNode) -> PlayerGroup:
    """Helper function to group multiple PlayerNodes for batch dependency wiring: players(p1, p2) >> p3."""
    return PlayerGroup(nodes=list(nodes))


class Playbook(ABC, Generic[T]):  # noqa: UP046
    """Pure Abstract Port representing presentation canvas & lifecycle contract."""

    def __init__(
        self,
        prepared_run: PreparedRun | None = None,
        orchestrator: Any | None = None,
        ui: PlaybookUI | None = None,
    ) -> None:
        self._prepared_run: PreparedRun | None = prepared_run
        self._orchestrator: Any | None = orchestrator
        self._ui: PlaybookUI = ui if ui is not None else TerminalPlaybookUI()
        self._is_tracing: bool = False
        self._tracing_blueprint: PlaybookBlueprint | None = None
        self._drafted_players: list[PlayerNode] = []

    @property
    def ui(self) -> PlaybookUI:
        return self._ui

    @property
    def orchestrator(self) -> Any:
        if self._orchestrator is None:
            raise RuntimeError(
                "Playbook orchestrator has not been initialized. "
                "Ensure Playbook is instantiated with an orchestrator engine."
            )
        return self._orchestrator

    async def prepared_run(self) -> PreparedRun:
        """Returns the PreparedRun context (run_id, run_dir, parameters) for the active playbook run."""
        if self._prepared_run is None:
            raise RuntimeError(
                "Playbook prepared_run accessed before preparation. "
                "Ensure RunPreparer has prepared the run before accessing."
            )
        return self._prepared_run

    @abstractmethod
    async def play(self, *args: Any, **kwargs: Any) -> Any:
        """Core playbook execution logic implemented by subclasses."""

    async def _execute_player_node(self, player_node: PlayerNode) -> Any:
        if self._is_tracing:
            if self._tracing_blueprint is not None:
                self._tracing_blueprint.output_node_id = player_node.node_id
            return SymbolicProxy(node_id=player_node.node_id)
        return await self._practice_run(
            self._drafted_players, target_node_id=player_node.node_id
        )

    async def run_play(self, *args: Any, **kwargs: Any) -> T:
        """Executes play() and auto-evaluates the DAG if a PlayerNode, SymbolicProxy, or None is returned."""
        play_result: Any = await self.play(*args, **kwargs)

        target_node_id: str | None = None
        if isinstance(play_result, (PlayerNode, SymbolicProxy)):
            target_node_id = str(play_result.node_id)
        elif play_result is None and self._drafted_players:
            target_node_id = self._drafted_players[-1].node_id
        elif play_result is not None:
            return cast(T, play_result)

        return await self._practice_run(
            self._drafted_players, target_node_id=target_node_id
        )

    def player(
        self,
        playbook_cls: type[Playbook[PlaybookOutput]],
        **kwargs: ParameterValue | ProxyRef | MappedParameter | SymbolicProxy,
    ) -> PlayerNode:
        """Drafts a player node onto the Pitch for DAG composition with '.after()' or '>>'."""
        step_index: int = len(self._drafted_players) + 1
        node_id: str = f"player_{step_index}_{playbook_cls.__name__}"
        is_mapped = any(isinstance(v, MappedParameter) for v in kwargs.values())
        player_node: PlayerNode = PlayerNode(
            node_id=node_id,
            playbook_cls=playbook_cls,
            kwargs=kwargs,
            is_mapped=is_mapped,
            playbook=self,
        )
        self._drafted_players.append(player_node)

        if self._is_tracing:
            extra_dependencies: list[str] = [
                dependency_node.node_id
                for dependency_node in player_node.depends_on_nodes
            ]
            self._record_traced_node(
                playbook_cls,
                kwargs,
                node_id=node_id,
                extra_deps=extra_dependencies,
                is_mapped=is_mapped,
            )

        return player_node

    def players(
        self,
        playbook_cls: type[Playbook[PlaybookOutput]],
        params: ProxyRef | list[Any] | None = None,
        **kwargs: ParameterValue | ProxyRef | MappedParameter | SymbolicProxy,
    ) -> PlayerNode:
        """Convenience helper drafting a dynamic fan-out player node for mapped execution across items."""
        if params is not None:
            kwargs["params"] = MappedParameter(params)
        elif not any(isinstance(v, MappedParameter) for v in kwargs.values()):
            # Wrap any ProxyRef in kwargs as MappedParameter if explicitly called via self.players(...)
            first_proxy_key = next(
                (k for k, v in kwargs.items() if isinstance(v, ProxyRef)), None
            )
            if first_proxy_key:
                kwargs[first_proxy_key] = MappedParameter(
                    cast(ProxyRef, kwargs[first_proxy_key])
                )
        return self.player(playbook_cls, **kwargs)

    async def kickoff(self) -> Any:
        """Kicks off execution of the drafted DAG player nodes."""
        if not self._drafted_players:
            raise BlueprintError("kickoff() called without drafting any player nodes.")
        return await self._drafted_players[-1]

    def extract_blueprint(self) -> PlaybookBlueprint:
        """Traces the playbook in dry-run mode to generate the PlaybookBlueprint."""
        self._is_tracing = True
        self._tracing_blueprint = PlaybookBlueprint(
            name=self.__class__.__name__, entry_playbook=self.__class__.__name__
        )
        self._drafted_players = []

        try:
            play_result: Any = asyncio.run(self.play())
            if self._tracing_blueprint is not None:
                if isinstance(play_result, (PlayerNode, SymbolicProxy)):
                    self._tracing_blueprint.output_node_id = str(play_result.node_id)
                elif (
                    self._tracing_blueprint.output_node_id is None
                    and self._drafted_players
                ):
                    self._tracing_blueprint.output_node_id = self._drafted_players[
                        -1
                    ].node_id
        except Exception as error:
            raise BlueprintError(
                f"Failed to trace blueprint for {self.__class__.__name__}: {error}"
            ) from error
        finally:
            self._is_tracing = False

        blueprint: PlaybookBlueprint | None = self._tracing_blueprint
        self._tracing_blueprint = None
        if blueprint is None:
            raise BlueprintError("Tracing completed but blueprint was not generated.")
        return blueprint

    def _record_traced_node(
        self,
        playbook_cls: type[Playbook[PlaybookOutput]],
        kwargs: dict[str, ParameterValue | ProxyRef | MappedParameter | SymbolicProxy],
        node_id: str | None = None,
        extra_deps: list[str] | None = None,
        is_mapped: bool = False,
    ) -> SymbolicProxy:
        if self._tracing_blueprint is None:
            raise BlueprintError("_record_traced_node called without active blueprint.")

        step_index: int = len(self._tracing_blueprint.nodes) + 1
        effective_id: str = node_id or f"node_{step_index}_{playbook_cls.__name__}"

        static_kwargs: dict[str, ParameterValue] = {}
        param_bindings: dict[str, ParamBinding] = {}
        mapped_bindings: dict[str, ParamBinding] = {}
        depends_on: set[str] = set(extra_deps or [])

        param_name: str
        parameter_value: ParameterValue | ProxyRef | MappedParameter | SymbolicProxy
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
        self._tracing_blueprint.nodes.append(node)
        self._tracing_blueprint.output_node_id = effective_id
        return SymbolicProxy(node_id=effective_id)

    async def _practice_run(
        self,
        players_list: list[PlayerNode],
        target_node_id: str | None = None,
    ) -> T:
        """Executes player nodes sequentially in-process on the local Playbook during practice runs."""
        from graphlib import TopologicalSorter

        # Build dependency graph and topologically sort nodes before execution
        node_map: dict[str, PlayerNode] = {p.node_id: p for p in players_list}
        topological_sorter: TopologicalSorter = TopologicalSorter()
        for p in players_list:
            dep_ids: set[str] = {
                dep.node_id for dep in p.depends_on_nodes if dep.node_id in node_map
            }
            for v in p.kwargs.values():
                if isinstance(v, SymbolicProxy):
                    v_node_id: str = getattr(v, "_node_id", str(v.node_id))
                    if v_node_id in node_map:
                        dep_ids.add(v_node_id)
                elif isinstance(v, ProxyRef) and v.node_id in node_map:
                    dep_ids.add(v.node_id)
                elif (
                    isinstance(v, MappedParameter)
                    and isinstance(v.target, ProxyRef)
                    and v.target.node_id in node_map
                ):
                    dep_ids.add(v.target.node_id)
            topological_sorter.add(p.node_id, *dep_ids)

        ordered_node_ids = list(topological_sorter.static_order())
        ordered_players = [node_map[nid] for nid in ordered_node_ids if nid in node_map]

        results: dict[str, Any] = {}

        player_node: PlayerNode
        for player_node in ordered_players:
            # 1. Resolve parameters from parent outputs
            resolved_kwargs: dict[str, Any] = dict(player_node.kwargs)
            param_name: str
            parameter_value: Any
            for param_name, parameter_value in list(resolved_kwargs.items()):
                if isinstance(parameter_value, SymbolicProxy):
                    target_id: str = getattr(
                        parameter_value, "_node_id", str(parameter_value.node_id)
                    )
                    parent_output: Any = results.get(target_id)
                    if parent_output is not None:
                        resolved_kwargs[param_name] = parent_output
                elif isinstance(parameter_value, ProxyRef):
                    parent_output = results.get(parameter_value.node_id)
                    if parent_output is not None:
                        resolved_kwargs[param_name] = getattr(
                            parent_output, parameter_value.field, parent_output
                        )
                elif isinstance(parameter_value, list):
                    resolved_list: list[Any] = []
                    item: Any
                    for item in parameter_value:
                        if isinstance(item, ProxyRef):
                            parent_output = results.get(item.node_id)
                            if parent_output is not None:
                                resolved_list.append(
                                    getattr(parent_output, item.field, parent_output)
                                )
                        else:
                            resolved_list.append(item)
                    resolved_kwargs[param_name] = resolved_list

            # Fallback: if 'subtask_results' parameter is accepted by play() and unbound, collect outputs from depends_on_nodes
            import inspect

            play_params: dict[str, inspect.Parameter] = dict(
                inspect.signature(player_node.playbook_cls.play).parameters
            )
            if (
                "subtask_results" in play_params
                and (
                    "subtask_results" not in resolved_kwargs
                    or not resolved_kwargs["subtask_results"]
                )
                and player_node.depends_on_nodes
            ):
                dep_outputs: list[PlaybookOutput] = []
                for dep in player_node.depends_on_nodes:
                    dep_val = results.get(dep.node_id)
                    if isinstance(dep_val, list):
                        dep_outputs.extend(dep_val)
                    elif isinstance(dep_val, PlaybookOutput):
                        dep_outputs.append(dep_val)
                if dep_outputs:
                    resolved_kwargs["subtask_results"] = dep_outputs

            # 2. Handle dynamic fan-out mapped execution if is_mapped is True
            if player_node.is_mapped:
                mapped_param_names: list[str] = []
                mapped_param_lists: list[list[Any]] = []

                for k, v in list(resolved_kwargs.items()):
                    if isinstance(v, MappedParameter):
                        target_val = v.target
                        if isinstance(target_val, ProxyRef):
                            parent_out: PlaybookOutput | None = results.get(
                                target_val.node_id  # type: ignore[arg-type]
                            )
                            resolved_list = (
                                getattr(parent_out, target_val.field, [])
                                if parent_out
                                else []
                            )
                        elif isinstance(target_val, list):
                            resolved_list = target_val
                        else:
                            resolved_list = [target_val]

                        mapped_param_names.append(k)
                        mapped_param_lists.append(resolved_list)
                        resolved_kwargs.pop(k, None)

                mapped_results: list[PlaybookOutput] = []
                if mapped_param_lists:
                    zipped_tuples = zip(*mapped_param_lists)
                    for tuple_item in zipped_tuples:
                        instance = player_node.playbook_cls(
                            prepared_run=self._prepared_run, ui=self._ui
                        )
                        item_kwargs = dict(resolved_kwargs)
                        for param_n, val_item in zip(mapped_param_names, tuple_item):
                            item_kwargs[param_n] = val_item

                        sub_res = await instance.play(
                            **cast(dict[str, ParameterValue], item_kwargs)
                        )
                        res_data = (
                            sub_res.data if isinstance(sub_res, RunResult) else sub_res
                        )
                        if res_data is not None:
                            mapped_results.append(res_data)

                results[player_node.node_id] = mapped_results  # type: ignore[assignment]
                continue

            # 3. Instantiate and run standard single player playbook
            playbook_cls: type[Playbook[PlaybookOutput]] = player_node.playbook_cls
            single_instance: Playbook[PlaybookOutput] = playbook_cls(
                prepared_run=self._prepared_run, ui=self._ui
            )
            playbook_result: (
                PlaybookOutput | RunResult[PlaybookOutput]
            ) = await single_instance.play(
                **cast(dict[str, ParameterValue], resolved_kwargs)
            )

            # 4. Store result in practice run score table
            if (
                isinstance(playbook_result, RunResult)
                and playbook_result.data is not None
            ):
                results[player_node.node_id] = playbook_result.data
            elif isinstance(playbook_result, PlaybookOutput):
                results[player_node.node_id] = playbook_result

        # 4. Return final player output
        output_node_id: str = target_node_id or (
            self._tracing_blueprint.output_node_id
            if (self._tracing_blueprint and self._tracing_blueprint.output_node_id)
            else players_list[-1].node_id
        )
        raw_final_output: PlaybookOutput | None = results.get(output_node_id)
        if raw_final_output is None:
            raise BlueprintError(
                f"No execution result found for output node '{output_node_id}'."
            )

        final_output: T = cast(T, raw_final_output)
        return final_output

    # --- Runner Entrypoints (Lazy Infrastructure Delegation) ---

    @classmethod
    def cli(cls, playbook_name: str | None = None) -> RunResult[Any]:
        """Parse CLI parameters using POSIX '--' delimiter and play the playbook."""
        from pirlo.infrastructure.adapters.cli.cli_playbook_runner import (
            CliPlaybookRunner,
        )

        return CliPlaybookRunner.run(cls, playbook_name=playbook_name)
