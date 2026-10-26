# Pirlo

Pirlo is a declarative DAG runner for typed Python plays. You write each step
as a class, declare which steps it depends on, and pirlo builds the graph, gives
every play a CLI subcommand, runs it on [Prefect](https://www.prefect.io/), caches
results, and keeps a run history.

```python
# Excerpt; the complete, runnable file is in "Write your own play" below.
@play(name="greet", description="Greets one name")
class GreetPlay(Play[Greeting]):
    name: str = requires(
        NamesPlay, each="names"
    )  # one instance per name, run in parallel

    async def execute(self) -> Greeting:
        result = await self.shell.run("echo", f"hello {self.name}")
        return Greeting(text=result.output_tail)
```

```bash
pirlo greet --help   # shows the DAG and every parameter
pirlo greet          # runs NamesPlay, then one GreetPlay per name
```

## Install

Requires Python 3.12 or newer.

```bash
pip install pirlo          # or: uv tool install pirlo
pirlo --help               # lists built-in commands and every discovered play
```

## Quickstart: the built-in demo

```bash
pirlo demo_report_dag --help   # prints the DAG below, then its options
pirlo demo_report_dag          # runs it; prints a Run ID and the output payload
pirlo run show <RUN_ID>        # status, parameters and plays of that run
pirlo run log <RUN_ID>/<PLAY_ID>   # logs of one play (PLAY_ID is listed by `run show`)
```

```
    +-------------------+
    | demo_select_dates |
    +-------------------+
               *
+----------------------------+                   +--------------------------+
| demo_download_report [map] |                   | demo_fetch_budget_target |
+----------------------------+                   +--------------------------+
                         *****                   *****
                           +----------------------+
                           | demo_extract_summary |
                           +----------------------+
                                       *
                              +-----------------+
                              | demo_report_dag |
                              +-----------------+
```

`[map]` marks a fanned-out play. The demo source is
[`src/pirlo/playbooks/demo/report_dag.py`](src/pirlo/playbooks/demo/report_dag.py).

## Write your own play

Create `playbooks/hello.py` in your project directory:

```python
from typing import Annotated

from pirlo.core.decorators import play
from pirlo.core.models.blueprint import PlayOutput
from pirlo.core.models.parameters import Parameter
from pirlo.core.ports.play import Play, requires


class Names(PlayOutput):
    names: list[str]


class Greeting(PlayOutput):
    text: str


class Report(PlayOutput):
    lines: list[str]


@play(name="hello_names", description="Lists who to greet")
class NamesPlay(Play[Names]):
    async def execute(
        self,
        names: Annotated[
            str, Parameter(help="Comma-separated names", env_name="HELLO_NAMES")
        ] = "ada,linus",
    ) -> Names:
        return Names(names=names.split(","))


@play(name="hello_greet", description="Greets one name", retries=1, timeout=60)
class GreetPlay(Play[Greeting]):
    name: str = requires(NamesPlay, each="names")

    async def execute(self) -> Greeting:
        result = await self.shell.run("echo", f"hello {self.name}")
        return Greeting(text=result.output_tail)


@play(name="hello", description="Collects every greeting")
class ReportPlay(Play[Report]):
    greetings: list[Greeting] = requires(GreetPlay)

    async def execute(self) -> Report:
        return Report(lines=sorted(g.text for g in self.greetings))


if __name__ == "__main__":
    ReportPlay.cli()  # lets `python playbooks/hello.py` work too
```

Then, from that directory:

```bash
pirlo hello --help
pirlo hello                 # output: {"lines": ["hello ada", "hello linus"]}
HELLO_NAMES=x,y pirlo hello_names
```

There is no registration step: the `name` in `@play(name=...)` is the subcommand.

### Where pirlo looks for plays

Pirlo finds plays by parsing source files for `@play(name=...)`, without
importing them. It scans, in this order (a later match with the same name wins):

1. Built-in plays in `pirlo/playbooks/`.
2. `./src/` and `./playbooks/` under the current working directory.
3. `$PIRLO_WORKSPACE/src/` and `$PIRLO_WORKSPACE/playbooks/`.
4. Installed packages whose top-level name starts with `pirlo_`.
5. Entries in `[tool.pirlo.playbooks]` of `./pyproject.toml`, as
   `name = "module.path:ClassName"`, used only when the name was not found above.

## Programming model

| Construct | Meaning |
|---|---|
| `class MyPlay(Play[Out])` with `async def execute(self, ...) -> Out` | One step. `Out` subclasses `PlayOutput` (a pydantic model). |
| `@play(name=, description=, version="1.0", retries=0, retry_delay=0, timeout=None)` | Registers the play under `name`. Retries, delay and timeout are in seconds. |
| `x: ParentOut = requires(ParentPlay)` | Inject the parent's whole output (broadcast). |
| `x: str = requires(ParentPlay, field="greeting")` | Inject one field of the parent's output. |
| `x: str = requires(ParentPlay, each="names")` | Fan out: one instance of this play per item of the parent's list field. |
| `xs: list[ChildOut] = requires(FannedOutPlay)` | Fan in: receive every fanned-out instance's output as a list. |
| `requires(ParentPlay, quarter="Q1")` | Pin a parameter of the parent for this edge. |
| `execute(self, p: Annotated[str, Parameter(help=..., env_name=..., short="-p", sensitive=False)] = default)` | A parameter. It becomes `--p` on the CLI. |

**Parameter values** come from, lowest to highest precedence: the default in
`execute`, the environment variable named by `env_name`, then the CLI flag.
Parameters of upstream plays are flags of the target play too (`--help` lists
them under "Upstream Dependency Options"). A value is passed to every play in
the DAG that declares a parameter with that name, so give play-specific
parameters specific names.

**Masking.** A parameter's value is replaced with `***` in task logs and in run
history (`pirlo run show`, `pirlo run list`) when it is declared with
`Parameter(sensitive=True)` or its name contains `password`, `secret`, `token`,
`api_key`, `credential`, `auth` or `private_key`. This includes fields nested
inside links, so a link's API key is never stored in run history.

**Inside `execute`**, a play has `self.logger` (logging, routed into the play's
task log), `self.ui` (`commentary`, `goal`, `header` for terminal output),
`self.shell` (below) and `self.play_id`.

**Caching.** Each execution gets a content-addressed id from the play name,
`version` and inputs. A later run with the same id reuses the stored result.
Pass `--force` (alias `--no-cache`) to rerun everything, or bump `version=` to
invalidate one play.

**Python API.** `await ReportPlay.run_play(param=value)` runs the play and its
upstream plays and returns the typed output.

**Rule:** code under `playbooks/` never imports `prefect`. The orchestrator is
an implementation detail behind the compiler.

## Run external commands: `self.shell`

```python
from pirlo.core.services.shell import CommandFailed

result = await self.shell.run("ls", "-la", cwd=project_dir, timeout_s=30)
result.exit_code, result.output_tail, result.log_path, result.duration_s
```

- Arguments are passed as a list, never through a shell, so parameter values
  cannot inject shell syntax.
- Output streams line by line into the play's log as it is printed (stdout and
  stderr combined; `\r` progress updates count as lines).
- The full raw output is written to `$PIRLO_WORKSPACE/shell-logs/<id>.log`;
  `output_tail` holds the last 200 lines.
- It raises `CommandFailed` (with `.result`) on a timeout or an exit code outside
  `ok_codes` (default `(0,)`). Use `ok_codes={1}` when failure is the expected
  outcome, e.g. a bug reproduction step.
- On timeout or cancellation the whole process group is terminated.
- `cwd=` and `env=` (added to the inherited environment) are optional.

## Links: credentials for LLM providers

A link is a named provider account (provider, API key, optional base URL and
optional default model), so plays never hold secrets.

```bash
pirlo link create                     # interactive wizard
pirlo link create my-gemini --provider gemini --api-key "$GEMINI_API_KEY" --model gemini-2.5-flash
pirlo link list
pirlo link show NAME                  # API key masked
pirlo link delete NAME
pirlo link test NAME [--model MODEL]  # sends one short prompt
```

Providers: `dashscope`, `gemini`, `openai`, `anthropic`, `ollama`. `--model` is
optional: it sets the link's default, and code can pass a different model per
call. With neither, a call fails with `MissingModelError` instead of letting the
provider choose.

Use a link in a play by declaring a `LinkParameter`; the CLI takes the link name
and the play receives the resolved `LlmLink`:

```python
from pirlo.core.models.link import LlmLink
from pirlo.core.models.parameters import LinkParameter


async def execute(
    self, llm: Annotated[LlmLink, LinkParameter(help="LLM link name")]
) -> Out:
    model = llm.resolve_model(None)  # explicit model, else the link default
```

```bash
pirlo my_play --llm my-gemini
```

Links are stored in `$PIRLO_WORKSPACE/links.json`.

## Run history

```bash
pirlo run list [-n LIMIT] [-s STATUS] [-p PLAY]   # newest first (aliases: ls)
pirlo run show RUN_ID                             # alias: inspect
pirlo run log RUN_ID[/PLAY_ID] [-n TAIL] [-f]     # -f follows live logs (alias: logs)
pirlo <play> -l                                   # stream logs to the terminal while running
```

## Prefect server and scheduling

A play runs once, immediately. While a Prefect server is running, the run,
its logs and a dashboard link show up in that server's UI; otherwise the play
uses a temporary server that stops when the run ends.

```bash
pirlo serve                      # start a Prefect server on 127.0.0.1 (4200 if free)
pirlo <play>                     # reports to it; the summary links to the run
pirlo serve --status             # URL, pid, log file
pirlo serve --stop
PIRLO_SERVER=off pirlo <play>    # temporary server for this run
pirlo <play> --routine daily     # or hourly, weekly, monthly, or a cron string
```

`pirlo serve` runs the server as a background process on the host, records it
in `$PIRLO_WORKSPACE/serve/`, and creates the `pirlo-pool` work pool. To use a
Prefect server you run yourself instead, set `PREFECT_API_URL` (in the
environment or with `prefect config set`); it takes precedence. From another
machine, forward the port over SSH: `ssh -L 4200:127.0.0.1:4200 <user>@<host>`.

`--routine` registers a Prefect deployment on `pirlo-pool`. It only fires while
the server is running and a worker serves the pool; against the temporary
server it registers but never runs.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `PIRLO_WORKSPACE` | `~/.pirlo-pitch` | Links, run directories, shell logs, extra plays. |
| `PIRLO_LOG_LEVEL` | `INFO` | Pirlo log level. |
| `PREFECT_HOME` | `~/.prefect` | Prefect's own state, including the temporary server's database. |
| `PREFECT_API_URL` | unset | A Prefect server of your own for runs and `pirlo run`, overriding the one `pirlo serve` starts. Set it in the environment or with `prefect config set`; if it doesn't answer, pirlo warns and uses a temporary server. |
| `PIRLO_SERVER` | `auto` | `off` makes every run use a temporary Prefect server, even when `PREFECT_API_URL` is set. A set `CI` variable has the same effect. |

## Known issues

- **Scheduled runs send secrets to the Prefect server.** With `--routine`,
  resolved parameter values, including link API keys, are part of the
  deployment payload stored by that server, because the worker needs them to
  run the play. Local runs (the default) do not store them.

## Architecture

Ports and adapters: `core/ports` defines interfaces, `infrastructure/adapters`
implements them, `playbooks/` holds plays.

```
Play classes ──BlueprintExtractor──▶ PlayBlueprint (engine-agnostic DAG)
             ──PrefectCompiler─────▶ Prefect flow ──PrefectRunner──▶ result + run history
```

| Path | Contents |
|---|---|
| `src/pirlo/core/models/` | Blueprint, links, commands, parameters. |
| `src/pirlo/core/ports/` | `Play`, `CommandRunner`, `LinkRepository`, `BlueprintCompiler`, ... |
| `src/pirlo/core/services/` | Blueprint extraction, idempotency ids, `Shell`, masking. |
| `src/pirlo/infrastructure/adapters/` | CLI, Prefect orchestrator, local command runner, JSON link storage, DAG rendering. |
| `src/pirlo/playbooks/` | Built-in demo plays. |

New behaviour goes in a new class implementing an existing port; see
[`AGENTS.md`](AGENTS.md) for contributor rules.

## Development

```bash
uv sync                    # install (managed by uv)
uv run pytest              # tests
make all                   # ruff format + ruff check + mypy
```

If `~/.prefect` or `~/.pirlo-pitch` is not writable (e.g. in a sandbox):

```bash
PREFECT_HOME=/tmp/prefect-home PIRLO_WORKSPACE=/tmp/pirlo-pitch uv run pytest
```

Release: bump `__version__` in `src/pirlo/__init__.py`, commit on `main`, then
push a tag `v<version>`. The tag triggers the PyPI release workflow, which fails
if the tag and `__version__` differ.

## Glossary

Pirlo is named after the Italian midfielder Andrea Pirlo.

| Term | Meaning |
|---|---|
| Play | One step: a `Play` subclass registered with `@play`. |
| Playbook | A module of plays, e.g. `playbooks/hello.py`. |
| Pitch | The workspace directory, `~/.pirlo-pitch` by default. |
| Link | A named connection to an LLM provider account. |
| Routine | A recurring schedule for a play (`--routine`). |
