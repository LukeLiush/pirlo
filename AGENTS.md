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
    uv run pirlo serve            # local Prefect server on 127.0.0.1 (--status, --stop)
    uv run pytest                 # tests
    make all                      # ruff format + ruff check + mypy

Play names are discovered by AST-scanning `src/` for `@play(name=...)`.
No registration step — the name *is* the CLI subcommand.

## Tests

Prefect's ephemeral server and the run-history store write outside the repo.
If either path is read-only, point them somewhere writable:

    PREFECT_HOME=/tmp/prefect-home PIRLO_WORKSPACE=/tmp/pirlo-pitch uv run pytest

Defaults are `~/.prefect` and `~/.pirlo-pitch` (`PIRLO_WORKSPACE`, see
`core/config.py`). `tests/conftest.py` gives every test `PIRLO_SERVER=off`, its
own `PIRLO_WORKSPACE` and a temporary Prefect profiles file, so tests never
report to a Prefect server you configured or started with `pirlo serve`.

## Prefect runtime

- **Where a run goes** is decided once, as a `PrefectTarget` (`prefect_target.py`):
  `EPHEMERAL` (no server), `IN_PROCESS` (run here, report to a server) or
  `WORK_POOL` (submit; a worker runs it). `PlayRunnerFactory.get_runner()` builds
  it with `resolve_default_target()`; `PrefectRunner` only reads it.
- **Which server** comes from `discover_prefect_server_url()`: a configured
  `PREFECT_API_URL` (read fresh with `prefect.settings.Settings()`, never
  `PREFECT_API_URL.value()`, which is fixed at import), else the server
  `pirlo serve` recorded in `$PIRLO_WORKSPACE/serve/prefect-server.json`.
  Discovery never starts a server.
- **`pirlo serve`** (`cli/serve_commands.py`) is a built-in command on purpose,
  not a play: it manages the server that plays run on. It drives two ports:
  `LocalServer` (`PrefectLocalServer`) and `WorkerFleet` (`PrefectHostWorker`,
  one `prefect worker` on this host). Both use `services/detached_process.py`
  for the background process, its state file and its shutdown.
- **The host worker** gets pirlo's virtualenv `bin` first on `PATH` (the
  flow-run bootstrap calls `python3`) and does not inherit pirlo's quiet
  Prefect console setting, so its log shows each submitted run. Plain runs stay
  in-process; only routines go through the pool until worker containers exist.
- **Dashboard links** use the Prefect UI's real routes: `/runs/flow-run/<id>`
  and `/deployments/deployment/<id>`. The UI is a single-page app, so a plain
  HTTP GET can't tell you whether a route exists; check the router in the
  bundle under `prefect/server/ui`.

## Extend, don't edit

Add behaviour by writing a new implementation of an existing port and composing
it in. Don't teach a working class a second job.

- New behaviour → new class implementing the relevant `core/ports` interface,
  wired through its factory. See `FallbackBlueprintRenderer` (try one renderer,
  degrade to another).
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
- Anything pirlo starts listens on `127.0.0.1` only. Reach it from another
  machine with `ssh -L`, never by binding wider.

## Removed — don't reintroduce

pirlo targets one host: a Prefect server on that host and, later, worker
containers. These were removed for that reason; ask before bringing any back.

- `pirlo connect` (SSH tunnels to a remote `pirlo serve`): no remote
  orchestrator to reach; use `ssh -L` for the UI.
- Orchestrator links (`pirlo orchestrator`, `--orchestrator`, `PrefectLink`) and
  runtime engine selection (`OrchestratorRegistry`, the `-- <engine>` argument
  delimiter): there is one engine. Keep the engine-agnostic `PlayBlueprint`;
  add a second runner behind `PlayRunner` only when a second engine is real.
- The Docker/Ollama `pirlo serve`: Prefect now runs on the host, and its stock
  worker image could not run pirlo plays.

## Legacy — do not build on

The browser-automation layer was removed with `autopass`. Two leftovers remain
and are slated for deletion: the `pirlo profile` command (browser profiles) and
the `browser_use` logger handling in `infrastructure/services/log_streamer.py`.
Don't extend them; don't add plays that need a browser.
