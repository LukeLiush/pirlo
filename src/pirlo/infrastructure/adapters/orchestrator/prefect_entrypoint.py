# src/pirlo/infrastructure/adapters/orchestrator/prefect_entrypoint.py
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Any, Literal

from prefect import flow


@flow(name="pirlo_remote_runner")
async def run_play_remote(
    play_name: str,
    parameters: dict[str, Any] | None = None,
    code_ref: str | None = None,
    storage_type: Literal["in_memory", "prefect_artifact"] = "in_memory",
    force: bool = False,
    show_logs: bool = True,
) -> Any:
    """Top-level entrypoint executed by remote Prefect workers.

    1. Streams and extracts the code snapshot directly to disk into a temp dir.
    2. Prepends the unpacked directory to sys.path.
    3. Discovers the play class, compiles the DAG, and executes all tasks.
    """
    import os

    from pirlo.infrastructure.services.code_bundler import (
        CodeStorageBackend,
        get_code_storage_backend,
    )

    cwd = Path.cwd().resolve()
    paths_to_add: list[str] = [str(cwd)]
    if (cwd / "src").exists():
        paths_to_add.append(str(cwd / "src"))

    if code_ref:
        storage: CodeStorageBackend = get_code_storage_backend(storage_type)
        temp_dir: Path = Path(tempfile.mkdtemp(prefix="pirlo_code_"))
        code_dir: Path = await storage.extract(code_ref, temp_dir)
        paths_to_add.extend([str(code_dir), str(code_dir / "src")])

    for p in reversed(paths_to_add):
        if p not in sys.path:
            sys.path.insert(0, p)

    existing_pythonpath = os.environ.get("PYTHONPATH", "")
    new_pythonpath = os.pathsep.join(paths_to_add)
    if existing_pythonpath:
        new_pythonpath = f"{new_pythonpath}{os.pathsep}{existing_pythonpath}"
    os.environ["PYTHONPATH"] = new_pythonpath

    from pirlo.core.services.blueprint_extractor import (
        BlueprintExtractor,
    )
    from pirlo.infrastructure.adapters.orchestrator.prefect_compiler import (
        PrefectCompiler,
    )

    compiler = PrefectCompiler()
    play_cls: type[Any] = compiler._resolve_play_class(play_name)
    resolved_params: dict[str, Any] = parameters or {}
    blueprint = BlueprintExtractor.extract_from_play(
        play_cls, user_kwargs=resolved_params
    )
    workflow = compiler.compile(blueprint)
    return await workflow(force=force, show_logs=show_logs, **resolved_params)
