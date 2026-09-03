# tests/test_prefect_compiler.py
from __future__ import annotations

from typing import Any, Callable

from pirlo.core.decorators import playbook
from pirlo.core.models.blueprint import PlaybookBlueprint, PlaybookOutput
from pirlo.core.ports.pitch import Pitch, PlayerNode
from pirlo.infrastructure.adapters.orchestrator.prefect_compiler import (
    PrefectCompiler,
)


class LoginOutput(PlaybookOutput):
    auth_token: str
    user_id: str


class VerifyOutput(PlaybookOutput):
    verification_code: str


class CheckoutOutput(PlaybookOutput):
    order_id: str


class LoginCompilerTestPlaybook(Pitch[LoginOutput]):
    async def play(self, profile: str = "default") -> LoginOutput:
        return LoginOutput(
            auth_token="token_prefect_123", user_id="user_prefect_99"
        )


class VerifyCompilerTestPlaybook(Pitch[VerifyOutput]):
    async def play(self, user_id: str = "") -> VerifyOutput:
        return VerifyOutput(verification_code="code_prefect_555")


class CheckoutCompilerTestPlaybook(Pitch[CheckoutOutput]):
    async def play(
        self,
        auth_token: str = "",
        verification_code: str = "",
        item_id: str = "",
    ) -> CheckoutOutput:
        return CheckoutOutput(
            order_id=f"order_{item_id}_{auth_token}_{verification_code}"
        )


@playbook(name="test_prefect_compiler_dag")
class PrefectCompilerDAGPlaybook(Pitch[CheckoutOutput]):
    async def play(self, item_id: str = "item_88") -> CheckoutOutput:
        p1: PlayerNode = self.player(LoginCompilerTestPlaybook, profile="prod")
        p2: PlayerNode = self.player(
            VerifyCompilerTestPlaybook, user_id=p1.ball.user_id
        )
        p3: PlayerNode = self.player(
            CheckoutCompilerTestPlaybook,
            auth_token=p1.ball.auth_token,
            verification_code=p2.ball.verification_code,
            item_id=item_id,
        ).after(p1, p2)

        return await self.kickoff([p1, p2, p3])


def test_prefect_compiler_flow_generation():
    workflow = PrefectCompilerDAGPlaybook()
    blueprint: PlaybookBlueprint = workflow.extract_blueprint()

    # Compile PlaybookBlueprint to master Prefect flow
    master_flow: Callable[..., Any] = PrefectCompiler.compile(blueprint)

    assert master_flow is not None
    assert getattr(master_flow, "name", None) == blueprint.name
