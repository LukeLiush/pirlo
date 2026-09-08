import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from pirlo.infrastructure.adapters.storage.json_file_parameter_storage import (
    JsonFileParameterStorage,
)
from pirlo.infrastructure.services.run_id_generator import IdentityFactory


class TestRunHistoryAndMVC(unittest.TestCase):
    def setUp(self) -> None:
        self.test_dir: Path = Path(tempfile.mkdtemp())
        self.parameter_storage: JsonFileParameterStorage = JsonFileParameterStorage(
            self.test_dir
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.test_dir)

    def test_run_id_generation_is_seeded_and_unique(self) -> None:
        playbook: str = "dummy"
        params: dict[str, object] = {"foo": "bar", "count": 10}

        factory1: IdentityFactory = IdentityFactory(playbook, params)
        factory2: IdentityFactory = IdentityFactory(playbook, params)

        run_name1: str = factory1.generate_run_name()
        run_name2: str = factory2.generate_run_name()
        self.assertEqual(run_name1, run_name2)

        run_id1: str = factory1.generate_run_id()
        run_id2: str = factory2.generate_run_id()
        self.assertNotEqual(run_id1, run_id2)
        self.assertEqual(len(run_id1), 8)
        self.assertEqual(len(run_id2), 8)

    def test_json_file_parameter_storage(self) -> None:
        params: dict[str, object] = {"url": "https://example.com", "headless": True}
        loc: str = "login/logs/test_run_params.json"

        self.parameter_storage.save_parameters(loc, params)

        abs_path: Path = self.test_dir / loc
        self.assertTrue(abs_path.exists())

        loaded: dict[str, object] = self.parameter_storage.load_parameters(loc)
        self.assertEqual(loaded, params)

    def test_playwright_adapter_step_callback(self) -> None:
        from pirlo.core.models.actions import (
            ClickAction,
            ElementContext,
            NavigateAction,
        )
        from pirlo.core.models.workflow import Workflow
        from pirlo.infrastructure.adapters.browser.playwright_adapter import (
            PlaywrightAdapter,
        )

        actions = [
            NavigateAction(url="https://www.google.com"),
            ClickAction(
                element_context=ElementContext(
                    xpath="//button", tag_name="button", text="click me"
                )
            ),
        ]
        workflow = Workflow(
            workflow_id="dummy-flow", description="test description", actions=actions
        )

        mock_page: AsyncMock = AsyncMock()
        mock_page.url = "https://www.google.com"
        mock_page.locator = MagicMock()

        mock_locator: AsyncMock = AsyncMock()
        mock_locator.scroll_into_view_if_needed = AsyncMock()
        mock_locator.evaluate = AsyncMock(
            side_effect=lambda js: "BUTTON" if "tagName" in js else {}
        )
        mock_locator.inner_text = AsyncMock(return_value="click me")
        mock_page.locator.return_value.first = mock_locator

        adapter: PlaywrightAdapter = PlaywrightAdapter(mock_page)
        adapter.execute_action = AsyncMock()

        called_steps: list[tuple[int, str]] = []

        async def on_step_update(step_num: int, action: object) -> None:
            called_steps.append((step_num, action.status.value))

        original_sleep = asyncio.sleep
        asyncio.sleep = AsyncMock()
        try:
            asyncio.run(
                adapter.execute_workflow(workflow, on_step_update=on_step_update)
            )
        finally:
            asyncio.sleep = original_sleep

        self.assertIn((1, "not_started"), called_steps)
        self.assertIn((2, "not_started"), called_steps)
        self.assertIn((1, "running"), called_steps)
        self.assertIn((1, "completed"), called_steps)
        self.assertIn((2, "running"), called_steps)
        self.assertIn((2, "completed"), called_steps)

    def test_workflow_runner_cache_key_and_step_history(self) -> None:
        from pirlo.core.models.actions import DoneAction, NavigateAction
        from pirlo.core.models.execution_context import ExecutionContext
        from pirlo.core.models.workflow import Workflow
        from pirlo.infrastructure.repository import JsonFileWorkflowRepository
        from pirlo.infrastructure.services.self_healing_workflow import (
            SelfHealingRunner,
        )

        cache_dir: Path = Path(tempfile.mkdtemp())
        try:
            repo: JsonFileWorkflowRepository = JsonFileWorkflowRepository(
                directory=cache_dir
            )
            mock_replay: MagicMock = MagicMock()
            mock_replay.run = MagicMock(
                side_effect=lambda task_prompt, context=None: asyncio.sleep(
                    0, result="replay result"
                )
            )
            mock_fallback: MagicMock = MagicMock()

            run_name: str = "regista-12345678"
            run_id: str = "regista-12345678-20260811_123456_000000"
            workflow: Workflow = Workflow(
                workflow_id=run_name,
                description="test task",
                actions=[
                    NavigateAction(url="https://google.com"),
                    DoneAction(text="done"),
                ],
            )
            repo.save(workflow)

            runner: SelfHealingRunner = SelfHealingRunner(
                replay_runner=mock_replay,
                fallback_runner=mock_fallback,
                repository=repo,
            )

            result: str = asyncio.run(
                runner.run(
                    task_prompt="test prompt",
                    context=ExecutionContext(cache_key=run_name, run_id=run_id),
                )
            )
            self.assertEqual(result, "replay result")
            self.assertTrue(repo.exists(run_name))
        finally:
            shutil.rmtree(cache_dir)

    def test_playwright_replay_runner_snapshots_workflow_to_run_dir(self) -> None:
        from pirlo.core.models.actions import DoneAction, NavigateAction
        from pirlo.core.models.browser_config import BrowserConfig
        from pirlo.core.models.execution_context import ExecutionContext
        from pirlo.core.models.workflow import Workflow
        from pirlo.infrastructure.repository import JsonFileWorkflowRepository
        from pirlo.infrastructure.services.playwright_workflow import (
            PlaywrightReplayRunner,
        )

        cache_dir: Path = Path(tempfile.mkdtemp())
        try:
            repo: JsonFileWorkflowRepository = JsonFileWorkflowRepository(
                directory=cache_dir
            )
            cache_key: str = "test_cache_key"
            run_id: str = "test_cache_key-20260811_123456_000000"
            wf: Workflow = Workflow(
                workflow_id=cache_key,
                description="test task",
                actions=[
                    NavigateAction(url="https://example.com"),
                    DoneAction(text="done"),
                ],
            )
            repo.save(wf)

            runner: PlaywrightReplayRunner = PlaywrightReplayRunner(
                repository=repo,
                browser_config=BrowserConfig(cdp_url=None),
            )

            with patch(
                "pirlo.infrastructure.services.playwright_workflow.async_playwright"
            ) as mock_pw:
                mock_p: MagicMock = MagicMock()
                mock_browser: AsyncMock = AsyncMock()
                mock_context: AsyncMock = AsyncMock()
                mock_page: AsyncMock = AsyncMock()
                mock_browser.new_context.return_value = mock_context
                mock_context.new_page.return_value = mock_page
                mock_p.chromium.launch = AsyncMock(return_value=mock_browser)
                mock_pw.return_value.__aenter__.return_value = mock_p

                with patch(
                    "pirlo.infrastructure.adapters.browser.playwright_adapter.PlaywrightAdapter.execute_workflow",
                    new_callable=AsyncMock,
                ):
                    asyncio.run(
                        runner.run(
                            task_prompt="test",
                            context=ExecutionContext(
                                cache_key=cache_key, run_id=run_id
                            ),
                        )
                    )

            snapshot_file: Path = cache_dir / run_id / f"{cache_key}_workflow.json"
            self.assertTrue(snapshot_file.exists())
        finally:
            shutil.rmtree(cache_dir)


if __name__ == "__main__":
    unittest.main()
