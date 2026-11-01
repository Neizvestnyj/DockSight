# Contributing

## Development setup

Use Python 3.14, uv, Node.js 24 LTS, and Git. The backend supports Python 3.12+; CI covers 3.12, 3.13, and 3.14.
Docker and a model provider are needed for real diagnostics, but not for unit tests or the browser demo.

From the repository root:

```sh
uv sync --project backend --locked
npm --prefix frontend ci
uv run --project backend python scripts/git_hooks.py install
```

Follow the [quick start](README.md#quick-start) to run the application. See [configuration](docs/configuration.md)
for provider credentials and remote hosts. Never commit `.env` files, tokens, private keys, or raw Docker inspect output.
The installer preserves custom hooks and stops if an active hook and its `.legacy` backup both exist.
Resolve that conflict without deleting needed hooks before reinstalling.

### Make commands

With GNU Make installed, run `make` or `make help` from the repository root to list the available commands.
Make is optional; the direct commands in this guide remain available. Recipes work on Windows and Linux/macOS
without Bash or Unix text utilities. Help requires only GNU Make; other targets require uv and/or npm.

```sh
make install
make hooks
make backend
```

Run `make frontend` in another terminal. Backend configuration and credentials follow the
[quick start](README.md#connect-your-docker-environment).

| Command | Behavior |
|---------|----------|
| `make check` | Run backend and frontend static checks |
| `make check-backend` / `make check-frontend` | Check one side only |
| `make test` | Run backend tests and frontend unit tests |
| `make test-backend` / `make test-frontend` | Test one side only |
| `make test-browser` | Build the frontend, then run browser tests; requires Chrome |
| `make build` | Build the frontend |
| `make verify` | Run all shared hooks, frontend static and unit checks, and browser tests with a fresh build |

Targets run sequentially even with `make -j` to avoid concurrent frontend checks and builds.
Docker and live-model tests remain separate opt-in commands described below.

## Making changes

- Start branches from `master`; use `feature/<lowercase-kebab-case>` for features.
- Never commit directly on `master` or push to remote `master`. Submit changes through a pull request.
  Hooks reject local commits on `master` and every outgoing update to `refs/heads/master`, including deletions.
  Do not bypass these guards. Re-run the installation command after moving the checkout or recreating its Python environment.
- Keep changes focused. Explain the problem, resulting behavior, and relevant limitations in the pull request.
- Use English Conventional Commit headers of at most 72 characters, such as `docs: simplify the quick start`.
- Update [API contracts](docs/api.md) when transport behavior changes and [architecture](docs/architecture.md)
  when boundaries change.
- Before finishing a task or committing, update [CHANGELOG.md](CHANGELOG.md), including documentation and workflow changes.
  Keep entries brief and group related outcomes. Reuse the current version section for ongoing work on the same branch;
  do not create a version per task or commit. Use the intended numeric version immediately, not `Unreleased`.
  Choose PATCH for compatible fixes, MINOR for compatible additions, and MAJOR for breaking changes; keep the backend
  package metadata and lockfile aligned. Documentation alone needs no bump.
  Follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/): group notable outcomes under applicable categories and
  omit empty ones. Use linked `[version] - YYYY-MM-DD` headings for merged versions, dated by the merge into `master`
  unless a separate release date is recorded. Several commits can contribute to one entry.

Keep Python and Markdown prose within 120 characters per line. Use UTF-8 without BOM and LF line endings.
Write documentation, comments, docstrings, and runtime messages in English; product copy belongs in the localization
catalog. Production functions and classes, including private helpers, need brief docstrings. Test helpers and fixtures
need docstrings; descriptive `test_*` names need one only for additional context.

## Code boundaries

- Backend code lives in `backend/src/docksight/`. Domain code uses the standard library; application code owns ports
  and use cases; adapters own HTTP, Docker, and provider integration. Bootstrap selects implementations.
- Frontend code lives in `frontend/` and uses React with strict TypeScript. Validate API data at the transport boundary.
- Models receive read-only tools. Runtime values, permissions, target validation, and action execution remain server-owned.
- Keep credentials in browser memory and secrets out of logs. Never automatically retry an ambiguous Docker mutation.

See [backend architecture](docs/architecture.md) and [frontend contracts](docs/frontend.md) before changing those boundaries.

## Checks

Run the shared hooks before submitting changes:

```sh
uv run --project backend pre-commit run --all-files
```

Hooks cover formatting, Markdown, Dockerfile rules, secret detection, Python types, architecture, docstrings, complexity,
tests, and fixture usage. The first run downloads hook environments. Keep `uv` on the Git process's PATH.

For focused backend checks:

```sh
uv run --project backend ruff check backend examples scripts
uv run --project backend ruff format --check backend examples scripts
uv run --project backend pyright --project backend
uv run --project backend lint-imports --config backend/pyproject.toml
uv run --project backend interrogate -c backend/pyproject.toml backend/src backend/tests examples scripts
uv run --directory backend complexipy src tests ../examples ../scripts --plain --failed
uv run --project backend pytest backend/tests --dup-fixtures
uv run --project backend pytest backend/tests --dead-fixtures --no-cov
```

Backend test runs measure line and branch coverage for the entire `docksight` package, including modules not imported
by tests. The terminal report lists missing lines and branches and hides fully covered files. Local hooks and CI use
the same defaults and fail below 90% combined line and branch coverage. Opt-in external tests stay disabled by default.

From the repository root, generate a browsable report with:

```sh
uv run --project backend pytest backend/tests --cov-report=html
```

Open `htmlcov/index.html`. Coverage data and HTML reports are ignored by Git. Use `--no-cov` for debugging or
collection-only fixture checks and focused test runs. Use the full suite to check the 90% backend coverage requirement;
individual Docker and image checks in CI use `--no-cov` because they do not represent the full suite.

For frontend changes:

```sh
npm --prefix frontend run check
npm --prefix frontend test
npm --prefix frontend run build
npm --prefix frontend run test:browser
```

Browser tests require installed Chrome and run against the production preview with mocked HTTP responses. Build first.
Set `PLAYWRIGHT_PORT` if the default preview port is occupied. Reports and failure screenshots are temporary test artifacts.

## Protecting master on GitHub

In repository Settings, protect `master` with a branch rule requiring pull requests and the Backend and Frontend checks.
Require `Backend checks` so coverage below 90% blocks merging. A failing workflow alone does not
block merging unless its check is required by the branch rule.
Apply the rule to administrators as well, disable force pushes, and prevent branch deletion. A solo maintainer can require
pull requests without requiring another reviewer's approval. Local hooks can be bypassed; server-side protection enforces
the policy for every client. CI runs after a push and cannot reject an already accepted update.

The local branch guard is excluded from the CI hook run so checks still run on `master` after a pull request merge.

## Tests that use external services

Unit and contract tests must mock provider HTTP calls. Mirror source paths in unit tests:
`docksight/<path>/<name>.py` maps to `backend/tests/unit/<path>/test_<name>.py`. Group integration tests by contract.
Test behavior and failure boundaries. Duplicate fixture return values are review hints, not proof of duplicate purpose.

External tests are opt-in. The following examples use PowerShell environment-variable syntax.

For Docker integration tests, start Docker and pull `python:3.12-alpine`, then run:

```powershell
$env:DOCKSIGHT_TEST_DOCKER = "1"
uv run --project backend pytest backend/tests/integration -m docker --no-cov
Remove-Item Env:DOCKSIGHT_TEST_DOCKER
```

Fixtures must use unique names and labels and remove only resources they create. Never use global prune.
To check a built backend image, also set `DOCKSIGHT_TEST_BACKEND_IMAGE=docksight-backend:local` as an environment variable
and run `backend/tests/integration/test_image.py` with the Docker test flag enabled.

Live model tests require `DOCKSIGHT_TEST_LIVE_MODEL=1` and a configured provider. Cloud tests make paid API calls;
run them only with supplied credentials and explicit authorization. They are disabled in CI.
Diagnostic cases live in `backend/tests/fixtures/diagnostics.json`.

### Live Docker and local-model end-to-end suite

This separate suite runs the real HTTP/SSE API, Docker adapter, and Ollama adapter. It creates a unique Compose project
per case with pinned images and an internal network, publishes no container ports, and exposes only fixture resources
to the model. Setup and cleanup are restricted to the run's ownership labels. The API uses a random in-memory token,
an ephemeral loopback port, and isolated settings; it does not read your `.env` or call your running backend.

Start Docker and local Ollama, install the desired models yourself, then run from the repository root:

```sh
uv run --project backend pytest backend/tests/integration/live_e2e --no-cov --live-e2e --e2e-model qwen3.5:9b --e2e-model ministral-3:8b-instruct-2512-q4_K_M -vv -s
```

Repeat `--e2e-model` to add models. `--e2e-model-url` accepts loopback endpoints only. Models are never downloaded by the
suite; missing models fail preflight. Docker pulls missing pinned fixture images. Run cases sequentially, without xdist.
Ollama aliases marked as remote/cloud models are rejected before fixture setup or generation.
The workloads cover a refused database connection and invalid Grafana alerting configuration alongside healthy nginx,
an actual memory-limited OOM kill, a crash loop, truncated logs, and an exit 137 without an OOM kill.
Additional cases stop an owned Python process through Docker SIGTERM, observe a running HTTP server with an unhealthy
503 probe, and retain old request errors while a process remains running. PostgreSQL-style histories are synthetic;
these workloads do not host a database engine. Exit 137 without OOM is an explicit process exit, not an injected SIGKILL.

Select a smaller matrix with repeated `--e2e-case` options: `compose-healthy`, `compose-explicit`, `compose-chat`,
`compose-typo`, `compose-spaced`, `compose-cyrillic`, `compose-ambiguous`, `oom`, `crash-loop`, `truncated-logs`,
`unknown-exit`, `clean-shutdown`, `unhealthy`, or `running-history`.
`compose-healthy` asks about a healthy group with no precollected individual snapshots or problem logs; its group report
must remain usable without unsupported container cards.
All supported question languages run by default; use `--e2e-language en` to restrict the matrix to one language.
Assertions check runtime facts, exact resource identities, card coverage, observed log content, and evidence references
rather than exact model prose. A script-based language check covers each
summary, cause, unresolved detail, and action recommendation independently, excluding quoted observed log messages,
inline/fenced code, resource identifiers, and common fixture terms such as PostgreSQL and Telegram.
This detects response-language mismatches; it does not grade translation quality or model reasoning.

Run the causal regression package with the default language matrix:

```sh
uv run --project backend pytest backend/tests/integration/live_e2e --no-cov --live-e2e --e2e-model qwen3.5:9b --e2e-suite causal -vv -s
```

Packages and repeated `--e2e-case` selections combine without duplicate runs. The `causal` package includes these
single-container cases and the noisy/shutdown follow-ups below:

| Case              | Observed fixture facts                                      | Narrative boundary                                |
|-------------------|-------------------------------------------------------------|---------------------------------------------------|
| `clean-shutdown`  | Real SIGTERM, exit 0, orderly stop after old request errors | Stop initiator and reason remain unknown          |
| `unknown-exit`    | Exit 137, `OOMKilled=false`                                 | Neither OOM nor SIGKILL is established            |
| `oom`             | Memory limit enforced, exit 137, `OOMKilled=true`           | Recognize the observed OOM kill                   |
| `unhealthy`       | Running process, Docker health `unhealthy`, HTTP 503        | Failed probes do not mean process termination     |
| `running-history` | Running process after synthetic SQL errors                  | Request errors do not establish a crash or health |

These single-container cases and shutdown follow-ups use production log budgets. The noisy follow-up keeps smaller
budgets to exercise truncation and final-line retention. Checks inspect summary, immediate/deeper cause, unknowns, and
action reasons, using narrative fixtures with negation, hypotheses, and quoted collected logs. They are bounded
clause heuristics for one target, not a universal factuality judge; unfamiliar phrasing and causal claims still need
manual review of saved responses. Runtime schema validation does not apply this test-only heuristic.
Temporal ordering alone does not assert a cause: "exited after errors" is allowed when the stop reason remains unknown;
"exited because of errors" requires supporting evidence. Keep both acceptance and rejection examples when calibrating
new phrasing so unrelated negation or omitted synonyms do not mask a genuine contradiction.
The unhealthy fixture also rejects authored database/dependency outage claims and guaranteed restart cures;
its observed 503 response establishes neither. Exact collected resource identifiers cannot hide those assertions.
Follow-ups also reject categorical "unrelated"/"not related" claims: different project names and failure modes do not
establish independence. Qualified hypotheses remain allowed; this check covers only the fixture phrase families.
Live runs evaluate the selected model as well as the integration. A valid schema and factual cards do not ensure that
the explanation preserves an unresolved stop reason, especially in follow-ups across projects. Retain failed response
artifacts and review them when choosing a model; do not weaken causal expectations to obtain a passing run.

Group cases also create an independently failing peer Compose project. Spaced and Cyrillic questions must resolve to the
target without including that peer. The ambiguous case gives both projects the same human-readable prefix: the first
turn must ask for the two observed choices without individual evidence reads, and a second request selects the target.

`--e2e-case compose-follow-up` selects an independent two-turn HTTP scenario: diagnose the primary project, then ask about
an explicitly named dependency container whose name equals its Compose project. The second request reuses the session,
checks fresh dependency cards and actual log content, and retains the first turn in the ignored report. It reuses the
existing failure workload; it does not simulate a database engine or execute product actions.

`compose-follow-up-noisy` uses a running dependency with long SQL-style history; `compose-follow-up-shutdown` uses the
actual SIGTERM/exit-0 dependency. Both exercise explicit container and mixed container/project clarification paths.
The shutdown case also follows up on its single-member Compose group. They require fresh scoped cards and actual final
log lines; causal checks reject old request errors being presented as the reason for stopping.

`--e2e-case compose-unscoped` asks a general incident question with 21 containers across two observed projects
and an ungrouped failure: 16 running processes, four failed exits, and one normal exit. It uses production log limits.
It requires a host overview without a project chooser, then checks counts, exact member identities, process and health
state, bounded log coverage, factual cards, and their references against Docker. Browser runs also require the overview.

To include real browser flows, install frontend dependencies and Chrome, build the client, and add `--e2e-browser`:

```sh
npm --prefix frontend run build
uv run --project backend pytest backend/tests/integration/live_e2e --no-cov --live-e2e --e2e-browser --e2e-model qwen3.5:9b --e2e-case compose-chat --e2e-case compose-explicit -vv -s
```

Chrome connects to the isolated API using its temporary token. These flows do not mock routes: they submit a free-form
question or select the Compose group, then compare rendered cards and source navigation with the actual SSE answer.
The ambiguous case chooses the observed group in the UI and checks that the original question and exact scope are sent.
Free chat uses a different UI locale from the question to check that narrative follows the operator's question.
Preview servers use separate loopback ports and are stopped after each case. Browser traces, videos, and automatic
error-context snapshots are disabled to avoid recording the connection form. Public responses and screenshots remain
in ignored test artifacts.
The regular browser suite stays mocked and requires neither Docker nor a model.

Public SSE responses and allowlisted fixture facts are saved under `.test-artifacts/live-e2e/` for successful and failed
diagnoses. These files are ignored by Git and contain no API token or request headers. Ordinary test runs skip live
diagnoses before any Docker/model access. The existing fake-runtime live-model tests remain separate.

Remote read tests require `DOCKSIGHT_TEST_REMOTE=1`, `DOCKSIGHT_HOSTS_FILE`, and `DOCKSIGHT_TEST_HOST`.
They must not mutate the remote environment.

## Documentation images

Capture the running application in English, including example questions and model explanations. Use Demo for repeatable
screens without private data and label simulated observations. Keep only screenshots referenced by documentation and
needed to explain a distinct workflow. Replace outdated captures and delete unused ones; breakpoint and locale checks
belong in temporary test artifacts.

Edit backend diagrams in [backend.drawio](docs/diagrams/backend.drawio), preserving named pages and the shared hand-drawn
style. Update the PNG preview and its documentation link together. See [export commands](docs/diagrams/README.md).
