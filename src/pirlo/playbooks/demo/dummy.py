import asyncio
from typing import Annotated, Any

from pirlo.core.decorators import play
from pirlo.core.models.blueprint import PlaybookOutput
from pirlo.core.models.parameters import Parameter
from pirlo.core.ports.play import Play


class DummyOutput(PlaybookOutput):
    target: str
    retries: int


@play(name="demo_dummy", description="Dummy test session for console verification.")
class DummySession(Play[DummyOutput]):
    """Dummy test session for console verification."""

    async def execute(
        self,
        target: Annotated[
            str, Parameter(help="Target host and port")
        ] = "localhost:8080",
        retries: Annotated[int, Parameter(help="Number of retry attempts")] = 3,
        verbose: Annotated[bool, Parameter(help="Enable verbose logging")] = True,
        message: Annotated[
            str, Parameter(help="Message to print")
        ] = "Initialization sequence started...",
        *args: Any,
        **kwargs: Any,
    ) -> DummyOutput:
        # 1. Header (Banner)
        self.ui.header(
            "Dummy Session CLI",
            subtitle="Mock testing console integrations",
        )

        # 2. Print initial inputs
        self.ui.commentary("[INFO] Starting dummy command...")
        self.ui.commentary(f"[INFO] Target: {target}")
        self.ui.commentary(f"[INFO] Retries set to: {retries}")
        self.ui.commentary(f"[INFO] Verbose mode: {verbose}")
        with self.ui.status("Initializing deployment..."):
            await asyncio.sleep(1)
            # 3. Simulate processing steps
            for i in range(1, retries + 1):
                self.ui.commentary(
                    f"[INFO] Executing deployment steps (Attempt {i}/{retries})..."
                )
                await asyncio.sleep(0.6)

                if verbose:
                    self.ui.commentary(f"[LOG] Processing details: {message}")
                    await asyncio.sleep(0.4)

        self.ui.commentary("[INFO] Verifying deployment... OK")
        await asyncio.sleep(0.5)

        # 4. Goal! (Success box)
        self.ui.goal(
            "Dummy command completed successfully!",
            detail=f"Target {target} is fully initialized.",
        )
        return DummyOutput(target=target, retries=retries)


DummyPlay = DummySession

if __name__ == "__main__":
    DummySession.cli()
