# src/pirlo/core/ports/pitch.py
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
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
from pirlo.core.ports.pitch_ui import PitchUI
from pirlo.infrastructure.adapters.cli.terminal_pitch_ui import TerminalPitchUI

T = TypeVar("T", bound=PlaybookOutput)


class PlayerNode:
    """Represents a player (task node) drafted onto the Pitch for DAG composition with '.after()' or '>>'."""

    def __init__(
        self,
        node_id: str,
        playbook_cls: type[Pitch[PlaybookOutput]],
        kwargs: dict[str, ParameterValue | ProxyRef],
    ) -> None:
        self.node_id: str = node_id
        self.playbook_cls: type[Pitch[PlaybookOutput]] = playbook_cls
        self.kwargs: dict[str, ParameterValue | ProxyRef] = kwargs
        self.depends_on_nodes: list[PlayerNode] = []
        self._proxy: SymbolicProxy = SymbolicProxy(node_id=node_id)

    @property
    def ball(self) -> SymbolicProxy:
        """Access output payload fields of this player (e.g. player_1.ball.auth_token)."""
        return self._proxy

    def __getattr__(self, name: str) -> ProxyRef:
        """Direct property proxying (e.g. player_1.auth_token)."""
        return getattr(self._proxy, name)

    def after(
        self, *upstream_nodes: PlayerNode | list[PlayerNode]
    ) -> PlayerNode:
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
        target_player_nodes: list[PlayerNode] = other if isinstance(other, list) else [other]
        target_node: PlayerNode
        for target_node in target_player_nodes:
            target_node.after(self)
        return other

    def __rrshift__(
        self, other: PlayerNode | list[PlayerNode]
    ) -> PlayerNode:
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


class Pitch(ABC, Generic[T]):
    """Pure Abstract Port representing presentation canvas & lifecycle contract."""

    def __init__(
        self,
        prepared_run: PreparedRun | None = None,
        orchestrator: Any | None = None,
        ui: PitchUI | None = None,
    ) -> None:
        self._prepared_run: PreparedRun | None = prepared_run
        self._orchestrator: Any | None = orchestrator
        self._ui: PitchUI = ui if ui is not None else TerminalPitchUI()
        self._is_tracing: bool = False
        self._tracing_blueprint: PlaybookBlueprint | None = None
        self._drafted_players: list[PlayerNode] = []

    @property
    def ui(self) -> PitchUI:
        return self._ui

    @property
    def orchestrator(self) -> Any:
        if self._orchestrator is None:
            raise RuntimeError(
                "Pitch orchestrator has not been initialized. "
                "Ensure Pitch is instantiated with an orchestrator engine."
            )
        return self._orchestrator

    async def prepared_run(self) -> PreparedRun:
        """Returns the PreparedRun context (run_id, run_dir, parameters) for the active playbook run."""
        if self._prepared_run is None:
            raise RuntimeError(
                "Pitch prepared_run accessed before preparation. "
                "Ensure RunPreparer has prepared the run before accessing."
            )
        return self._prepared_run

    @abstractmethod
    async def play(self, *args: ParameterValue, **kwargs: ParameterValue) -> T | RunResult[T]:
        """Core playbook execution logic implemented by subclasses."""

    def player(
        self, playbook_cls: type[Pitch[PlaybookOutput]], **kwargs: ParameterValue | ProxyRef
    ) -> PlayerNode:
        """Drafts a player node onto the Pitch for DAG composition with '.after()' or '>>'."""
        step_index: int = len(self._drafted_players) + 1
        node_id: str = f"player_{step_index}_{playbook_cls.__name__}"
        player_node: PlayerNode = PlayerNode(
            node_id=node_id, playbook_cls=playbook_cls, kwargs=kwargs
        )
        self._drafted_players.append(player_node)
        return player_node

    async def kickoff(self, players_list: list[PlayerNode]) -> T | SymbolicProxy:
        """Kicks off execution of the drafted DAG player nodes.

        Returns strongly-typed output T in execution mode, or SymbolicProxy in tracing mode.
        """
        if not players_list:
            raise BlueprintError("kickoff() called with an empty player list.")

        if self._is_tracing:
            if self._tracing_blueprint is None:
                raise BlueprintError(
                    "Tracing mode is active but _tracing_blueprint is None."
                )

            player_node: PlayerNode
            for player_node in players_list:
                extra_dependencies: list[str] = [
                    dependency_node.node_id for dependency_node in player_node.depends_on_nodes
                ]
                self._record_traced_node(
                    player_node.playbook_cls,
                    player_node.kwargs,
                    node_id=player_node.node_id,
                    extra_deps=extra_dependencies,
                )
            last_player_node: PlayerNode = players_list[-1]
            return SymbolicProxy(node_id=last_player_node.node_id)

        # In Local CLI execution mode: run practice run locally in-process
        return await self._practice_run(players_list)

    def extract_blueprint(self) -> PlaybookBlueprint:
        """Traces the playbook in dry-run mode to generate the PlaybookBlueprint."""
        self._is_tracing = True
        self._tracing_blueprint = PlaybookBlueprint(
            name=self.__class__.__name__, entry_playbook=self.__class__.__name__
        )
        self._drafted_players = []

        try:
            asyncio.run(self.play())
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
        playbook_cls: type[Pitch[PlaybookOutput]],
        kwargs: dict[str, ParameterValue | ProxyRef],
        node_id: str | None = None,
        extra_deps: list[str] | None = None,
    ) -> SymbolicProxy:
        if self._tracing_blueprint is None:
            raise BlueprintError("_record_traced_node called without active blueprint.")

        step_index: int = len(self._tracing_blueprint.nodes) + 1
        effective_id: str = node_id or f"node_{step_index}_{playbook_cls.__name__}"

        static_kwargs: dict[str, ParameterValue] = {}
        param_bindings: dict[str, ParamBinding] = {}
        depends_on: set[str] = set(extra_deps or [])

        param_name: str
        parameter_value: ParameterValue | ProxyRef
        for param_name, parameter_value in kwargs.items():
            if isinstance(parameter_value, ProxyRef):
                param_bindings[param_name] = ParamBinding(
                    source_node_id=parameter_value.node_id, source_field=parameter_value.field
                )
                depends_on.add(parameter_value.node_id)
            else:
                static_kwargs[param_name] = parameter_value

        node: BlueprintNode = BlueprintNode(
            node_id=effective_id,
            playbook_name=playbook_cls.__name__,
            static_kwargs=static_kwargs,
            param_bindings=param_bindings,
            depends_on=sorted(list(depends_on)),
        )
        self._tracing_blueprint.nodes.append(node)
        self._tracing_blueprint.output_node_id = effective_id
        return SymbolicProxy(node_id=effective_id)

    async def _practice_run(
        self, players_list: list[PlayerNode]
    ) -> T:
        """Executes player nodes sequentially in-process on the local Pitch during CLI practice runs."""
        results: dict[str, PlaybookOutput] = {}

        player_node: PlayerNode
        for player_node in players_list:
            # 1. Resolve parameters from parent outputs
            resolved_kwargs: dict[str, Any] = dict(player_node.kwargs)
            param_name: str
            parameter_value: Any
            for param_name, parameter_value in list(resolved_kwargs.items()):
                if isinstance(parameter_value, ProxyRef):
                    parent_output: PlaybookOutput | None = results.get(parameter_value.node_id)
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
            if "subtask_results" in play_params:
                if ("subtask_results" not in resolved_kwargs or not resolved_kwargs["subtask_results"]) and player_node.depends_on_nodes:
                    dep_outputs: list[PlaybookOutput] = [
                        results[dep.node_id] for dep in player_node.depends_on_nodes if dep.node_id in results
                    ]
                    if dep_outputs:
                        resolved_kwargs["subtask_results"] = dep_outputs

            # 2. Instantiate and run player playbook with injected UI & PreparedRun dependencies
            playbook_cls: type[Pitch[PlaybookOutput]] = player_node.playbook_cls
            instance: Pitch[PlaybookOutput] = playbook_cls(
                prepared_run=self._prepared_run, ui=self._ui
            )
            playbook_result: PlaybookOutput | RunResult[PlaybookOutput] = await instance.play(
                **cast(dict[str, ParameterValue], resolved_kwargs)
            )

            # 3. Store result in practice run score table
            if isinstance(playbook_result, RunResult) and playbook_result.data is not None:
                results[player_node.node_id] = playbook_result.data
            elif isinstance(playbook_result, PlaybookOutput):
                results[player_node.node_id] = playbook_result

        # 4. Return final player output
        last_node_id: str = players_list[-1].node_id
        raw_final_output: PlaybookOutput | None = results.get(last_node_id)
        if raw_final_output is None:
            raise BlueprintError(
                f"No execution result found for last player node '{last_node_id}'."
            )

        final_output: T = cast(T, raw_final_output)
        return final_output

    # --- Runner Entrypoints (Lazy Infrastructure Delegation) ---

    @classmethod
    def cli(cls, playbook_name: str | None = None) -> RunResult[Any]:
        """Parse CLI parameters using POSIX '--' delimiter and play the pitch."""
        from pirlo.infrastructure.adapters.cli.cli_pitch_runner import (
            CliPitchRunner,
        )

        return CliPitchRunner.run(cls, playbook_name=playbook_name)
