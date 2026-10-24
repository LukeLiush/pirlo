# src/pirlo/playbooks/demo/shell_demo.py
from __future__ import annotations

from typing import Annotated

from pirlo.core.decorators import play
from pirlo.core.models.blueprint import PlayOutput
from pirlo.core.models.parameters import Parameter
from pirlo.core.ports.play import Play


class ShellDemoOutput(PlayOutput):
    output: str
    log_path: str


@play(name="demo_shell", description="Runs a local command and reports its output")
class ShellDemoPlay(Play[ShellDemoOutput]):
    async def execute(
        self,
        message: Annotated[str, Parameter(help="Text to echo")] = "hello",
    ) -> ShellDemoOutput:
        result = await self.shell.run("echo", message)
        self.ui.goal(message="Command finished", detail=f"Log: {result.log_path}")
        return ShellDemoOutput(output=result.output_tail, log_path=str(result.log_path))


if __name__ == "__main__":
    ShellDemoPlay.cli()
