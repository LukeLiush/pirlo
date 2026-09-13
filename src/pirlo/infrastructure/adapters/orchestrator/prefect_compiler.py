# src/pirlo/infrastructure/adapters/orchestrator/prefect_compiler.py
from __future__ import annotations

import logging
import os
import sys
import time
from typing import Any, cast

from prefect import flow, tags, task
from prefect.futures import PrefectFuture
from prefect.task_runners import ProcessPoolTaskRunner

from pirlo.core.logging_context import (
    generate_short_run_id,
    get_current_run_id,
    play_logging_context,
    workflow_logging_context,
)
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
from pirlo.core.services.masking import mask_sensitive_data
from pirlo.infrastructure.adapters.cli.terminal_play_ui import TerminalPlayUI
from pirlo.infrastructure.adapters.orchestrator.prefect_model import (
    PrefectWorkflow,
)
from pirlo.infrastructure.services.log_streamer import capture_play_stdio

logger = logging.getLogger(__name__)


class _PrefectTaskLogForwardHandler(logging.Handler):
    """Forwards standard logging.LogRecord objects to a Prefect task runner logger."""

    def __init__(
        self, target_logger: logging.Logger | logging.LoggerAdapter[Any]
    ) -> None:
        super().__init__()
        self.target_logger: logging.Logger | logging.LoggerAdapter[Any] = target_logger
        self.pid: int = os.getpid()

    def emit(self, record: logging.LogRecord) -> None:
        self.target_logger.log(
            record.levelno, f"[(pid {self.pid})] {record.getMessage()}"
        )


class PrefectCompiler(BlueprintCompiler[PrefectWorkflow]):
    """Compiles a PlayBlueprint into an executable PrefectWorkflow model."""

    def __init__(self, validate_parameters: bool = False) -> None:
        self.validate_parameters: bool = validate_parameters

    def compile(
        self,
        blueprint: PlayBlueprint,
        run_id: str | None = None,
    ) -> PrefectWorkflow:
        """Dynamically constructs a master PrefectWorkflow from the PlayBlueprint."""
        if not blueprint.nodes:
            raise BlueprintError(f"Cannot compile empty blueprint '{blueprint.name}'.")

        active_run_id = run_id or get_current_run_id() or generate_short_run_id()

        @flow(
            name=blueprint.name,
            flow_run_name=active_run_id,
            validate_parameters=self.validate_parameters,
            task_runner=ProcessPoolTaskRunner(max_workers=os.cpu_count()),  # type: ignore[arg-type]
        )
        async def prefect_master_flow(
            **workflow_kwargs: object,
        ) -> PlayOutput | None:
            force: bool = bool(workflow_kwargs.get("force", False))
            show_logs: bool = bool(workflow_kwargs.get("show_logs", False))
            with (
                workflow_logging_context(active_run_id),
                tags(f"pirlo_id:{active_run_id}"),
            ):
                logger.info("Workflow starting (run-id %s):", active_run_id)

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

                def _build_task_fn(
                    target_cls: type[Any],
                    node_name: str,
                    task_play_name: str,
                ) -> Any:
                    async def _inner_task_fn(
                        **kwargs: object,
                    ) -> PlayOutput:
                        from pirlo.infrastructure.services.log_streamer import (
                            setup_pirlo_logging,
                        )

                        setup_pirlo_logging(show_logs=show_logs)

                        active_play_name = getattr(target_cls, "play_name", node_name)
                        play_version = getattr(target_cls, "play_version", "1.0")
                        identity = compute_play_identity(
                            active_play_name, kwargs, version=play_version
                        )
                        with play_logging_context(
                            identity.short_id, run_id=active_run_id
                        ):
                            try:
                                from prefect.logging import get_run_logger

                                task_logger: (
                                    logging.Logger | logging.LoggerAdapter[Any]
                                ) = get_run_logger()
                            except Exception:  # noqa: BLE001
                                task_logger = logger

                            # Forward custom self.logger calls directly into task_logger
                            play_custom_logger: logging.Logger = logging.getLogger(
                                f"pirlo.play.{active_play_name}"
                            )
                            orig_play_level: int = play_custom_logger.level
                            orig_propagate: bool = play_custom_logger.propagate
                            play_custom_logger.setLevel(logging.DEBUG)
                            play_custom_logger.propagate = False
                            forward_handler: logging.Handler = (
                                _PrefectTaskLogForwardHandler(task_logger)
                            )
                            play_custom_logger.addHandler(forward_handler)

                            masked_inputs: dict[str, Any] = mask_sensitive_data(
                                dict(kwargs)
                            )
                            worker_pid: int = os.getpid()
                            task_logger.info(
                                "[(pid %d)] Play START | inputs=%s",
                                worker_pid,
                                masked_inputs,
                            )
                            start_perf: float = time.perf_counter()
                            try:
                                try:
                                    instance: Any = target_cls(
                                        ui=TerminalPlayUI(
                                            play_name=identity.short_id,
                                            run_id=active_run_id,
                                        ),
                                        play_id=identity.full_id,
                                    )
                                except TypeError:
                                    try:
                                        instance = target_cls(
                                            ui=TerminalPlayUI(
                                                play_name=identity.short_id,
                                                run_id=active_run_id,
                                            )
                                        )
                                    except TypeError:
                                        instance = target_cls()

                                exec_kwargs: dict[str, object] = dict(kwargs)
                                import inspect

                                sig = inspect.signature(instance.execute)
                                has_var_keyword: bool = any(
                                    p.kind == inspect.Parameter.VAR_KEYWORD
                                    for p in sig.parameters.values()
                                )

                                # Injects resolved upstream requirements into instance.__dict__
                                if hasattr(target_cls, "get_upstream_requirements"):
                                    reqs = target_cls.get_upstream_requirements()
                                    for field_name in reqs:
                                        if field_name in kwargs:
                                            setattr(
                                                instance,
                                                field_name,
                                                kwargs[field_name],
                                            )
                                            if field_name not in sig.parameters:
                                                exec_kwargs.pop(field_name, None)

                                # Filter exec_kwargs to only accepted parameters if no **kwargs
                                if not has_var_keyword:
                                    exec_kwargs = {
                                        k: v
                                        for k, v in exec_kwargs.items()
                                        if k in sig.parameters
                                    }

                                # Executes execute() for Play with stdio captured to task_logger
                                with capture_play_stdio(
                                    on_line=lambda line: task_logger.info(
                                        "[(pid %d)] %s", worker_pid, line
                                    ),
                                    passthrough=not show_logs,
                                ):
                                    play_result: Any = await instance.execute(
                                        **exec_kwargs
                                    )
                                elapsed: float = time.perf_counter() - start_perf
                                output_data: PlayOutput = (
                                    play_result.data
                                    if isinstance(play_result, RunResult)
                                    and play_result.data
                                    else cast(PlayOutput, play_result)
                                )
                                output_repr: str = repr(output_data)
                                if len(output_repr) > 200:
                                    output_repr = output_repr[:197] + "..."

                                task_logger.info(
                                    "[(pid %d)] Play SUCCESS | duration=%.3fs | output=%s",
                                    worker_pid,
                                    elapsed,
                                    output_repr,
                                )
                                return output_data
                            except Exception as exc:
                                elapsed = time.perf_counter() - start_perf
                                task_logger.exception(
                                    "[(pid %d)] Play FAILED | duration=%.3fs | error=%s",
                                    worker_pid,
                                    elapsed,
                                    type(exc).__name__,
                                )
                                raise
                            finally:
                                play_custom_logger.removeHandler(forward_handler)
                                play_custom_logger.setLevel(orig_play_level)
                                play_custom_logger.propagate = orig_propagate

                    def _compute_task_run_name() -> str:
                        from prefect.context import TaskRunContext

                        ctx = TaskRunContext.get()
                        params: dict[str, Any] = ctx.parameters if ctx else {}
                        active_play_name: str = getattr(
                            target_cls, "play_name", node_name
                        )
                        play_version: str = getattr(target_cls, "play_version", "1.0")
                        identity = compute_play_identity(
                            active_play_name, params, version=play_version
                        )
                        return identity.short_id

                    _inner_task_fn.__name__ = f"execute_{task_play_name}"
                    _inner_task_fn.__qualname__ = f"execute_{task_play_name}"
                    return task(
                        name=f"Task: {task_play_name}",
                        task_run_name=_compute_task_run_name,
                        persist_result=True,
                    )(_inner_task_fn)

                execute_play_task = _build_task_fn(
                    play_cls, blueprint_node.playbook_name, play_name
                )

                parent_futures: list[PrefectFuture[PlayOutput]] = []
                for parent_id in blueprint_node.depends_on:
                    parent_val = futures[parent_id]
                    if isinstance(parent_val, list):
                        parent_futures.extend(parent_val)
                    else:
                        parent_futures.append(parent_val)

                from prefect.cache_policies import NO_CACHE

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

                    play_version: str = getattr(play_cls, "play_version", "1.0")

                    def _mapped_cache_key_fn(
                        ctx: Any,
                        params: dict[str, Any],
                        p_name: str = play_name,
                        p_ver: str = play_version,
                    ) -> str:
                        return compute_play_identity(
                            p_name, params, version=p_ver
                        ).full_id

                    configured_task = execute_play_task.with_options(
                        name=f"Task: {play_name}",
                        cache_policy=NO_CACHE if force else None,
                        cache_key_fn=None if force else _mapped_cache_key_fn,
                        persist_result=True,
                    )
                    mapped_future: Any = configured_task.map(  # type: ignore[call-overload]
                        wait_for=parent_futures,
                        **mapped_kwargs,
                        **unmapped_kwargs,
                    )
                    futures[blueprint_node.node_id] = mapped_future
                else:
                    play_version = getattr(play_cls, "play_version", "1.0")
                    identity = compute_play_identity(
                        play_name, resolved_kwargs, version=play_version
                    )
                    cache_key = identity.full_id

                    def _task_cache_key_fn(
                        ctx: Any,
                        params: dict[str, Any],
                        key: str = cache_key,
                    ) -> str:
                        return key

                    configured_task = execute_play_task.with_options(
                        name=f"Task: {play_name}",
                        task_run_name=identity.short_id,
                        cache_policy=NO_CACHE if force else None,
                        cache_key_fn=None if force else _task_cache_key_fn,
                        persist_result=True,
                    )
                    prefect_future: PrefectFuture[PlayOutput] = configured_task.submit(  # type: ignore[call-overload]
                        wait_for=parent_futures, **resolved_kwargs
                    )
                    futures[blueprint_node.node_id] = prefect_future

            if blueprint.output_node_id and blueprint.output_node_id in futures:
                final_prefect_future: PrefectFuture[PlayOutput] = futures[
                    blueprint.output_node_id
                ]
                final_result = await _resolve_future_result(final_prefect_future)
                with workflow_logging_context(active_run_id):
                    logger.info("Done!")
                return final_result

            with workflow_logging_context(active_run_id):
                logger.info("Done!")
            return None

        return PrefectWorkflow(
            name=blueprint.name,
            flow=prefect_master_flow,
            blueprint=blueprint,
        )

    def _resolve_play_class(self, play_name: str) -> type[Any]:
        import contextlib

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
                        and (
                            obj.__name__ == play_name
                            or getattr(obj, "play_name", None) == play_name
                        )
                    ):
                        return cast(type[Any], obj)

        # 2. Fallback to PlayScanner disk scanner
        from pirlo.infrastructure.services.play_scanner import PlayScanner

        class_object: type[object] = PlayScanner().get_play_class(play_name)
        return cast(type[Any], class_object)
