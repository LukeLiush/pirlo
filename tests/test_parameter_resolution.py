import inspect
import sys
from pathlib import Path
from typing import Annotated, Any

import pytest

from pirlo.core.decorators import playbook
from pirlo.core.models.parameters import Parameter
from pirlo.core.models.run_result import RunResult
from pirlo.core.ports.playbook import Playbook


@playbook(
    name="dummy_resolution",
    description="Session subclass for testing parameter resolution.",
)
class DummyResolutionSession(Playbook):
    """Session subclass for testing parameter resolution."""

    async def execute(
        self,
        task: Annotated[
            str, Parameter(help="Task", env_name="TEST_TASK")
        ] = "default-task",
        count: Annotated[int, Parameter(help="Count", env_name="TEST_COUNT")] = 5,
        enabled: Annotated[
            bool, Parameter(help="Enabled", env_name="TEST_ENABLED")
        ] = False,
        items: Annotated[
            list[str] | None, Parameter(help="Items", env_name="TEST_ITEMS")
        ] = None,
        details: Annotated[
            dict | None, Parameter(help="Details", env_name="TEST_DETAILS")
        ] = None,
        path_val: Annotated[
            Path | None, Parameter(help="Path val", env_name="TEST_PATH")
        ] = None,
        multi_env: Annotated[
            str, Parameter(help="Multi env", env_name=["TEST_KEY_A", "TEST_KEY_B"])
        ] = "default-multi",
        *args: Any,
        **kwargs: Any,
    ) -> RunResult[Any]:
        return RunResult(
            run_id=(await self.prepared_run()).run_id,
            data={
                "task": task,
                "count": count,
                "enabled": enabled,
                "items": items,
                "details": details,
                "path_val": path_val,
                "multi_env": multi_env,
            },
        )

    play = execute


@pytest.mark.anyio
async def test_default_values_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("PIRLO_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["pirlo dummy_resolution"])

    captured_data = {}

    async def mock_play(
        self,
        task: Annotated[
            str, Parameter(help="Task", env_name="TEST_TASK")
        ] = "default-task",
        count: Annotated[int, Parameter(help="Count", env_name="TEST_COUNT")] = 5,
        enabled: Annotated[
            bool, Parameter(help="Enabled", env_name="TEST_ENABLED")
        ] = False,
        items: Annotated[
            list[str] | None, Parameter(help="Items", env_name="TEST_ITEMS")
        ] = None,
        details: Annotated[
            dict | None, Parameter(help="Details", env_name="TEST_DETAILS")
        ] = None,
        path_val: Annotated[
            Path | None, Parameter(help="Path val", env_name="TEST_PATH")
        ] = None,
        multi_env: Annotated[
            str, Parameter(help="Multi env", env_name=["TEST_KEY_A", "TEST_KEY_B"])
        ] = "default-multi",
        **kwargs,
    ):
        captured_data.update(
            {
                "task": task,
                "count": count,
                "enabled": enabled,
                "items": items or [],
                "details": details or {},
                "path_val": path_val,
                "multi_env": multi_env,
            }
        )
        return RunResult(run_id="test", data=captured_data)

    monkeypatch.setattr(DummyResolutionSession, "execute", mock_play)
    monkeypatch.setattr(DummyResolutionSession, "play", mock_play)
    res = DummyResolutionSession.cli("dummy_resolution")
    if inspect.isawaitable(res):
        await res

    assert captured_data["task"] == "default-task"
    assert captured_data["count"] == 5
    assert captured_data["enabled"] == False
    assert captured_data["items"] == []
    assert captured_data["details"] == {}
    assert captured_data["path_val"] == None
    assert captured_data["multi_env"] == "default-multi"


@pytest.mark.anyio
async def test_env_variables_resolution(monkeypatch, tmp_path):
    monkeypatch.setenv("PIRLO_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("TEST_TASK", "env-task")
    monkeypatch.setenv("TEST_COUNT", "42")
    monkeypatch.setenv("TEST_ENABLED", "true")
    monkeypatch.setenv("TEST_ITEMS", "a,b,c")
    monkeypatch.setenv("TEST_DETAILS", '{"foo": "bar"}')
    monkeypatch.setenv("TEST_PATH", "/var/log")
    monkeypatch.setenv("TEST_KEY_B", "value-b")

    monkeypatch.setattr(sys, "argv", ["pirlo dummy_resolution"])
    captured_data = {}

    async def mock_play(
        self,
        task: Annotated[
            str, Parameter(help="Task", env_name="TEST_TASK")
        ] = "default-task",
        count: Annotated[int, Parameter(help="Count", env_name="TEST_COUNT")] = 5,
        enabled: Annotated[
            bool, Parameter(help="Enabled", env_name="TEST_ENABLED")
        ] = False,
        items: Annotated[
            list[str] | None, Parameter(help="Items", env_name="TEST_ITEMS")
        ] = None,
        details: Annotated[
            dict | None, Parameter(help="Details", env_name="TEST_DETAILS")
        ] = None,
        path_val: Annotated[
            Path | None, Parameter(help="Path val", env_name="TEST_PATH")
        ] = None,
        multi_env: Annotated[
            str, Parameter(help="Multi env", env_name=["TEST_KEY_A", "TEST_KEY_B"])
        ] = "default-multi",
        **kwargs,
    ):
        captured_data.update(
            {
                "task": task,
                "count": count,
                "enabled": enabled,
                "items": items,
                "details": details,
                "path_val": path_val,
                "multi_env": multi_env,
            }
        )
        return RunResult(run_id="test", data=captured_data)

    monkeypatch.setattr(DummyResolutionSession, "execute", mock_play)
    monkeypatch.setattr(DummyResolutionSession, "play", mock_play)
    res = DummyResolutionSession.cli("dummy_resolution")
    if inspect.isawaitable(res):
        await res

    assert captured_data["task"] == "env-task"
    assert captured_data["count"] == 42
    assert captured_data["enabled"] == True
    assert captured_data["items"] == ["a", "b", "c"]
    assert captured_data["details"] == {"foo": "bar"}
    assert captured_data["path_val"] == Path("/var/log")
    assert captured_data["multi_env"] == "value-b"


@pytest.mark.anyio
async def test_cli_overrides_env_and_default(monkeypatch, tmp_path):
    monkeypatch.setenv("PIRLO_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("TEST_TASK", "env-task")
    monkeypatch.setenv("TEST_COUNT", "42")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "pirlo",
            "dummy_resolution",
            "--task",
            "cli-task",
            "--count",
            "100",
            "--enabled",
            "--items",
            "x",
            "y",
        ],
    )
    captured_data = {}

    async def mock_play(
        self,
        task: Annotated[
            str, Parameter(help="Task", env_name="TEST_TASK")
        ] = "default-task",
        count: Annotated[int, Parameter(help="Count", env_name="TEST_COUNT")] = 5,
        enabled: Annotated[
            bool, Parameter(help="Enabled", env_name="TEST_ENABLED")
        ] = False,
        items: Annotated[
            list[str] | None, Parameter(help="Items", env_name="TEST_ITEMS")
        ] = None,
        details: Annotated[
            dict | None, Parameter(help="Details", env_name="TEST_DETAILS")
        ] = None,
        path_val: Annotated[
            Path | None, Parameter(help="Path val", env_name="TEST_PATH")
        ] = None,
        multi_env: Annotated[
            str, Parameter(help="Multi env", env_name=["TEST_KEY_A", "TEST_KEY_B"])
        ] = "default-multi",
        **kwargs,
    ):
        captured_data.update(
            {
                "task": task,
                "count": count,
                "enabled": enabled,
                "items": items,
                "details": details,
                "path_val": path_val,
                "multi_env": multi_env,
            }
        )
        return RunResult(run_id="test", data=captured_data)

    monkeypatch.setattr(DummyResolutionSession, "execute", mock_play)
    monkeypatch.setattr(DummyResolutionSession, "play", mock_play)
    res = DummyResolutionSession.cli("dummy_resolution")
    if inspect.isawaitable(res):
        await res

    assert captured_data["task"] == "cli-task"
    assert captured_data["count"] == 100
    assert captured_data["enabled"] == True
    assert captured_data["items"] == ["x", "y"]
