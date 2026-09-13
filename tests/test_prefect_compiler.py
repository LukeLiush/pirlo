# tests/test_prefect_compiler.py
from __future__ import annotations

from pirlo.core.decorators import play
from pirlo.core.models.blueprint import PlayBlueprint, PlayOutput
from pirlo.core.ports.play import Play, requires
from pirlo.infrastructure.adapters.orchestrator.prefect_compiler import (
    PrefectCompiler,
)


class LoginOutput(PlayOutput):
    auth_token: str
    user_id: str


class VerifyOutput(PlayOutput):
    verification_code: str


class CheckoutOutput(PlayOutput):
    order_id: str


class LoginCompilerTestPlay(Play[LoginOutput]):
    async def execute(self, profile: str = "default") -> LoginOutput:
        return LoginOutput(auth_token="token_prefect_123", user_id="user_prefect_99")


class VerifyCompilerTestPlay(Play[VerifyOutput]):
    login: LoginOutput = requires(LoginCompilerTestPlay)

    async def execute(self) -> VerifyOutput:
        return VerifyOutput(verification_code="code_prefect_555")


@play(name="test_prefect_dag")
class PrefectCompilerDAGPlay(Play[CheckoutOutput]):
    login: LoginOutput = requires(LoginCompilerTestPlay, profile="prod")
    verify: VerifyOutput = requires(VerifyCompilerTestPlay)

    async def execute(self, item_id: str = "item_88") -> CheckoutOutput:
        return CheckoutOutput(
            order_id=f"prefect_order_{item_id}_{self.login.auth_token}_{self.verify.verification_code}"
        )


def test_prefect_compiler_flow_generation():
    workflow = PrefectCompilerDAGPlay()
    blueprint: PlayBlueprint = workflow.extract_blueprint()

    # Compile PlayBlueprint to PrefectWorkflow
    compiler = PrefectCompiler()
    prefect_workflow = compiler.compile(blueprint)

    assert prefect_workflow is not None
    assert prefect_workflow.name == blueprint.name
    assert callable(prefect_workflow.flow)


def test_prefect_task_log_forward_handler():
    import logging
    from unittest.mock import MagicMock

    from pirlo.infrastructure.adapters.orchestrator.prefect_compiler import (
        _PrefectTaskLogForwardHandler,
    )

    mock_logger = MagicMock()
    handler = _PrefectTaskLogForwardHandler(mock_logger)
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="Custom play log message",
        args=(),
        exc_info=None,
    )
    handler.emit(record)
    mock_logger.log.assert_called_once_with(
        logging.INFO, f"[(pid {handler.pid})] Custom play log message"
    )
