class Parameter:
    """CLI Metadata container used inside typing.Annotated."""

    def __init__(
        self,
        help: str | None = None,
        env_name: str | list[str] | None = None,
        short: str | None = None,
    ) -> None:
        self.help: str | None = help
        self.env_name: str | list[str] | None = env_name
        self.short: str | None = short


class LinkParameter(Parameter):
    """Specialized metadata tag for parameters that resolve to LlmLink domain objects."""
