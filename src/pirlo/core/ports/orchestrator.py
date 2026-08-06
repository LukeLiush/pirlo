from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from pirlo.core.models.link import LlmLink


class AutopassExecutionOptions(BaseModel):
    """Explicitly typed execution options for Autopass sessions."""

    playmaker: LlmLink = Field(description="LlmLink object for decision brain")
    analyst: LlmLink = Field(
        description="LlmLink object for DOM analysis & selector repair"
    )
    use_vision: bool = Field(default=False, description="Enable vision capabilities")
    max_failures: int = Field(
        default=5, description="Max failure attempts before stopping"
    )
    retry_delay: int = Field(default=10, description="Retry delay in seconds")
    generate_gif: bool = Field(
        default=False, description="Generate execution GIF artifact"
    )


class TaskOrchestrator(ABC):
    """Abstract Port defining the orchestration contract for Pirlo tasks."""

    @abstractmethod
    async def execute(
        self,
        task_prompt: str,
        profile_path: Path,
        options: AutopassExecutionOptions,
        headless: bool = False,
        cdp_port: int = 9222,
    ) -> Any:
        """
        Executes an orchestrated workflow.
        Generates and pre-registers run_id in pirlo.db (status = STARTED),
        delegates to SelfHealingRunner, and updates DB on completion.
        """
