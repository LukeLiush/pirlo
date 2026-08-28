import re
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
    """Application Service (Use Case) coordinating workflow execution on active browser pages."""

    def __init__(
            self,
            workflow_runner: WorkflowRunner,
            browser_manager: BrowserManager | None = None,
            cdp_checker: CdpChecker | None = None,
    ):
        self.workflow_runner = workflow_runner
        self._browser_manager = browser_manager
        self.cdp_checker = cdp_checker

    async def run(
            self,
            task_prompt: str,
            listener: ProgressListener,
            browser_manager: BrowserManager | None = None,
            run_name: str | None = None,
            run_id: str | None = None,
    ) -> Any:
        mgr = browser_manager or self._browser_manager
        if not mgr:
            raise ValueError("A BrowserManager instance is required.")

        async with mgr.new_page() as page:
            slug_prompt = slugify(task_prompt)
            cache_key = f"{run_name}_{slug_prompt}" if run_name else slug_prompt

            try:
                with listener.status_context("Executing autonomous autopass play..."):
                    result = await self.workflow_runner.run(
                        task_prompt=task_prompt,
                        page=page,
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
