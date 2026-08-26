import re
from pathlib import Path
from typing import Any

from pirlo.core.services import WorkflowRunner
from pirlo.playbooks.autopass.core.ports import (
    BrowserManager,
    CdpChecker,
    ProgressListener,
)


def slugify(text: str) -> str:
    """Converts a task prompt into a safe, normalized string identifier for cache keys."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"[\s_-]+", "_", text)[:50]


class RunAutopassUseCase:
    """Application Service (Use Case) that coordinates the browser automation process."""

    def __init__(
        self,
        browser_manager: BrowserManager,
        cdp_checker: CdpChecker,
        workflow_runner: WorkflowRunner,
    ):
        self.browser_manager = browser_manager
        self.cdp_checker = cdp_checker
        self.workflow_runner = workflow_runner

    async def run(
        self,
        task_prompt: str,
        profile_path: Path,
        headless: bool,
        cdp_port: int,
        listener: ProgressListener,
        run_name: str | None = None,
        run_id: str | None = None,
    ) -> Any:
        # 1. Launch the browser context
        with listener.status_context("Launching browser session..."):
            await self.browser_manager.launch(profile_path, headless, cdp_port)

        try:
            # 2. Wait for CDP connection readiness
            with listener.status_context("Waiting for browser CDP listener port..."):
                await self.cdp_checker.wait_until_ready()

            # 3. Formulate cache key: run_name + slugify(task_prompt)
            slug_prompt = slugify(task_prompt)
            cache_key = f"{run_name}_{slug_prompt}" if run_name else slug_prompt

            # 4. Execute the autonomous workflow
            with listener.status_context("Executing autonomous autopass play..."):
                result = await self.workflow_runner.run(
                    task_prompt=task_prompt,
                    cache_key=cache_key,
                    run_id=run_id,
                )

            listener.show_goal(
                "Play completed successfully!", detail=f"Result: {result}"
            )
            return result
        except Exception as e:
            listener.show_red_card("Play failed with error!", detail=str(e))
            raise
        finally:
            # 5. Clean up browser context
            with listener.status_context("Closing browser..."):
                await self.browser_manager.close()
