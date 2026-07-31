from pydantic import BaseModel, model_validator

from pirlo.core.models.actions import Action, NavigateAction

# =====================================================================
# WORKFLOW AGGREGATE ROOT
# =====================================================================


class WorkflowMetadata(BaseModel):
    # Creator Info
    creator: str
    creator_version: str

    # Browser Info
    browser_type: str
    browser_version: str

    # Task Context
    created_at: str
    original_task_prompt: str
    execution_duration_seconds: float

    # LLM Environment
    llm_provider: str
    llm_model_name: str

    # Runtime Environment
    os_platform: str
    git_commit_sha: str | None = None


class Workflow(BaseModel):
    workflow_id: str
    description: str
    metadata: WorkflowMetadata | None = None
    actions: list[Action]

    @model_validator(mode="after")
    def validate_workflow_invariants(self) -> "Workflow":
        # 1. Must contain at least one step
        if not self.actions:
            raise ValueError("A workflow sequence must contain at least one action.")

        # 2. Must start with a Navigate action
        first_action = self.actions[0]
        if not isinstance(first_action, NavigateAction):
            raise TypeError(
                f"Workflow sequence must start with a NavigateAction "
                f"(found: {type(first_action).__name__})."
            )

        return self
