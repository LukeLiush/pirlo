# pirlo

A declarative DAG runner. You define plays as typed Python classes and declare
upstream dependencies with `requires(...)`; pirlo extracts a `PlayBlueprint` IR
and compiles it onto an orchestrator (Prefect today), giving you a zero-config
CLI, scheduling, idempotent caching and run history.

Clean architecture: `core/ports` defines interfaces, `infrastructure/adapters`
implements them, plays live in `playbooks/`.

## Programming model

    @play(name="my_play", description="...")
    class MyPlay(Play[MyOutput]):
        parent: ParentOutput = requires(ParentPlay)             # broadcast
        item: str = requires(ParentPlay, each="items")           # fan out per item

        async def execute(self) -> MyOutput: ...

- `requires(Cls)` injects the parent's whole output; `requires(Cls, each="field")`
  fans out one instance per item, and downstream plays fan them back in as
  `list[ParentOutput]`.
- `BlueprintExtractor` turns the class graph into a `PlayBlueprint`; a compiler
  (`PrefectCompiler`) lowers that onto the orchestrator. **Plays never import the
  orchestrator** — nothing under `playbooks/` imports `prefect`. Keep it that way.

## Commands

    uv sync                       # install (Python >=3.12, managed by uv)
    uv run pirlo <play_name>      # run a play; --help shows its DAG and params
    uv run pytest                 # tests
    make all                      # ruff format + ruff check + mypy

Play names are discovered by AST-scanning `src/` for `@play(name=...)`.
No registration step — the name *is* the CLI subcommand.

## Tests

Prefect's ephemeral server and the run-history store write outside the repo.
If either path is read-only, point them somewhere writable:

    PREFECT_HOME=/tmp/prefect-home PIRLO_WORKSPACE=/tmp/pirlo-pitch uv run pytest

Defaults are `~/.prefect` and `~/.pirlo-pitch` (`PIRLO_WORKSPACE`, see
`core/config.py`).

## Extend, don't edit

Add behaviour by writing a new implementation of an existing port and composing
it in. Don't teach a working class a second job.

- New behaviour → new class implementing the relevant `core/ports` interface,
  wired through its factory. See `FallbackBlueprintRenderer` (try one renderer,
  degrade to another) and `CompositeLinkRepository` (overlay, then static).
- Fixing a defect in existing behaviour → edit that code directly. A bug fix is
  not an extension; don't build a wrapper to avoid touching it.
- No port exists yet? Extracting one is the right move — say so in the plan first.
- Never clone a class into `FooV2` or `EnhancedFoo`. When two implementations
  share logic, extract a helper (see `visualization/node_labels.py`).

Smell that says you edited the wrong file: your test has to monkeypatch a
third-party internal to reach the new branch. Move the behaviour into its own
class and test it against a stub.

## Other conventions

- Adapters honour their port's contract; degrade rather than raise when the
  contract promises a value (`BlueprintRenderer.render` returns `str`).
- Don't widen `except Exception`. Catch the specific error and log at `warning`
  or above — CLI logging is unconfigured during argument parsing, so `debug` and
  `info` are invisible.

## Legacy — do not build on

The browser-automation layer is vestigial since `autopass` was removed and is
slated for deletion: `core/ports/browser_agent_factory.py` (which wrongly imports
`browser_use` into the core layer), plus `infrastructure/services/llm_workflow.py`,
`workflow_service.py`, `playwright_workflow.py`, `self_healing_workflow.py`.
No playbook uses it. Don't extend it; don't add plays that depend on it.

`README.md` still documents `pirlo autopass` and describes pirlo as a browser
runner — it is stale.
