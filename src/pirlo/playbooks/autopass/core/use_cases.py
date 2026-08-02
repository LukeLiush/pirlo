from pathlib import Path
from typing import Any

from pirlo.playbooks.autopass.core.ports import (
    BrowserManager,
    CdpChecker,
    ProgressListener,
    WorkflowExecutor,
)


class RunAutopassUseCase:
    """Application Service (Use Case) that coordinates the browser automation process."""

    def __init__(
        self,
        browser_manager: BrowserManager,
        cdp_checker: CdpChecker,
        workflow_executor: WorkflowExecutor,
    ):
        self.browser_manager = browser_manager
        self.cdp_checker = cdp_checker
        self.workflow_executor = workflow_executor

    async def run(
        self,
        task_prompt: str,
        profile_path: Path,
        headless: bool,
        cdp_port: int,
        listener: ProgressListener,
    ) -> Any:
        # 1. Launch the browser context
        with listener.status_context("Launching browser session..."):
            await self.browser_manager.launch(profile_path, headless, cdp_port)

        try:
            # 2. Wait for CDP connection readiness
            with listener.status_context("Waiting for browser CDP listener port..."):
                await self.cdp_checker.wait_until_ready()

            # 3. Execute the autonomous workflow
            with listener.status_context("Executing autonomous autopass play..."):
                result = await self.workflow_executor.execute(task_prompt)

            listener.show_goal(
                "Play completed successfully!", detail=f"Result: {result}"
            )
            return result
        except Exception as e:
            listener.show_red_card("Play failed with error!", detail=str(e))
            raise
        finally:
            # 4. Clean up browser context
            with listener.status_context("Closing browser..."):
                await self.browser_manager.close()
