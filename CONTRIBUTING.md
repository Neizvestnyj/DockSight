# Contributing

## Development setup

Use Python 3.14, uv, Node.js 24 LTS, and Git. The backend supports Python 3.12+. CI covers 3.12, 3.13, and 3.14.
Docker and a model provider are needed for real diagnostics, but not for unit tests or the browser demo.

From the repository root:

```sh
uv sync --project backend --locked
npm --prefix frontend ci
uv run --project backend python scripts/git_hooks.py install
```

Follow the [quick start](README.md#quick-start) to run the application. See [configuration](docs/configuration.md)
for provider credentials and remote hosts. Never commit `.env` files, tokens, private keys, or raw Docker inspect
output.
The installer preserves custom hooks and stops if an active hook and its `.legacy` backup both exist.
Resolve that conflict without deleting needed hooks before reinstalling.

### Make commands

Optional shortcuts require GNU Make. Run `make` or `make help` from the repository root to list them.
Recipes work on Windows and Linux/macOS without Bash or Unix text utilities. Other targets also require uv and/or npm.

```sh
make install
make hooks
make backend
```

Run `make frontend` in another terminal. Backend configuration and credentials follow the
[quick start](README.md#connect-your-docker-environment).

| Command | Behavior |
|---------|----------|
| `make update-deps` | Upgrade backend and frontend runtime and dev dependencies within declared version ranges |
| `make check` | Run backend and frontend static checks |
| `make check-backend` / `make check-frontend` | Check one side only |
| `make test` | Run backend tests and frontend unit tests |
| `make test-backend` / `make test-frontend` | Test one side only |
| `make test-browser` | Build the frontend, then run browser tests (requires Chrome) |
| `make build` | Build the frontend |
| `make verify` | Run all shared hooks, frontend static and unit checks, and browser tests with a fresh build |

Targets run sequentially even with `make -j` to avoid concurrent frontend checks and builds.
Docker and live-model tests remain separate opt-in commands described below.

`make update-deps` updates both lockfiles and local environments. Review the diff, then run `make verify`.
If a security fix requires a version outside the declared range, update that constraint first.

Pytest stays below `9.2` while `pytest-deadfixtures` relies on removed fixture internals.
Remove this limit when the plugin supports newer pytest versions.

The frontend overrides minimatch to `^11.0.1` for
[CVE-2026-118764](https://github.com/advisories/GHSA-g3hv-75wg-m249).
Remove the override when ESLint and TypeScript ESLint require a fixed version.

## Making changes

- Start feature branches from `master` with names matching `feature/<lowercase-kebab-case>`.
- Never commit directly on `master` or push to remote `master`. Submit changes through a pull request.
  Hooks reject local commits on `master` and every outgoing update to `refs/heads/master`, including deletions.
  Do not bypass these guards. Re-run the installation command after moving the checkout or recreating its Python
  environment.
- Keep changes focused. Explain the problem, resulting behavior, and relevant limitations in the pull request.
- Use English Conventional Commit headers of at most 72 characters, such as `docs: simplify the quick start`.
- Update [API contracts](docs/api.md) when transport behavior changes and [architecture](docs/architecture.md)
  when boundaries change.
- Before finishing a task or committing, update [CHANGELOG.md](CHANGELOG.md), including documentation and workflow
  changes.
  Group related outcomes in the current version section. Use the intended numeric version, not `Unreleased`.
  Keep that section for ongoing work on the same branch.
  Choose PATCH for compatible fixes, MINOR for compatible additions, and MAJOR for breaking changes.
  Keep the backend package metadata and lockfile aligned. Documentation alone needs no bump.
  Follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/): group notable outcomes under applicable categories and
  omit empty ones. Use linked `[version] - YYYY-MM-DD` headings for merged versions, dated by the merge into `master`
  unless a separate release date is recorded. Several commits can contribute to one entry.

### Writing

- Keep Python and Markdown prose within 120 characters per line. Use UTF-8 without BOM and LF line endings.
- Write documentation, comments, docstrings, and runtime messages in English. Product copy belongs in the message
  catalog.
- Use short, direct sentences. Avoid semicolons in prose, rhetorical headings, repeated summaries, and narration about
  the document. Use steps for procedures and lists or tables for related facts.
- Give production functions and classes brief docstrings, including private helpers. Test helpers and fixtures also
  need docstrings. Descriptive `test_*` names need one only for additional context.

## Code boundaries

- Backend code lives in `backend/src/docksight/`. Domain code uses the standard library. Application code owns ports
  and use cases. Adapters own HTTP, Docker, and provider integration. Bootstrap selects implementations.
- Frontend code lives in `frontend/` and uses React with strict TypeScript. Validate API data at the transport boundary.
- Models receive read-only tools. Runtime values, permissions, target validation, and action execution remain
  server-owned.
- Keep bearer tokens and CSRF values in browser memory. First-party login may persist only its opaque HttpOnly cookie.
  The locale is the only JavaScript browser-storage preference. Keep secrets out of logs.
- Keep SQL and ORM details in outbound adapters. SQLite runs with one backend process/worker on a local filesystem.
  Never hold a transaction across Docker or model calls and never silently fall back to memory.
- Never automatically retry an ambiguous Docker mutation. Retain durable action protection after history deletion.

See [backend architecture](docs/architecture.md) and [frontend contracts](docs/frontend.md) before changing those
boundaries.

## Checks

Run the shared hooks before submitting changes:

```sh
uv run --project backend pre-commit run --all-files
```

Hooks cover formatting, Markdown, Dockerfile rules, secret detection, Python types, architecture, docstrings,
complexity, tests, and fixture usage. The first run downloads hook environments. Keep `uv` on the Git process's PATH.

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
collection-only fixture checks and focused test runs. Use the full suite to check the 90% backend coverage requirement.
Individual Docker and image checks in CI use `--no-cov` because they do not represent the full suite.

For frontend changes:

```sh
npm --prefix frontend run check
npm --prefix frontend test
npm --prefix frontend run build
npm --prefix frontend run test:browser
```

The ordinary browser suite requires installed Chrome and uses the production preview with mocked HTTP responses.
Build first.
Set `PLAYWRIGHT_PORT` if the default preview port is occupied. Reports and failure screenshots are temporary test
artifacts.

Persistence recovery checks use a real local backend and temporary SQLite with deterministic model/runtime ports.
Mocked history endpoints alone cannot verify restart, active-turn reload, or cross-tab revisions. Isolate each state
directory and backend process. Cover acknowledged drafts, conflict controls, saved clarification, exact Stop ownership,
logout/actor isolation, and archived action reads without automatic submission or execution.
Use separate processes for locking, migration, crash windows, and recovery. Explicit memory mode is temporary and loses
history and execution protection on exit.
See [state maintenance](docs/configuration.md#offline-status-backup-and-migration) for stopped-backend backup, restore,
and reconciliation procedures.

After building the client, run the dedicated real-SQLite browser suite:

```sh
npm --prefix frontend run test:browser:persistence
uv run --project backend pytest backend/tests/integration/test_persistent_browser.py --no-cov
```

The browser suite owns temporary backend/preview processes, exact loopback origins, synthetic actor credentials, and
isolated SQLite directories. It disables traces, videos, and screenshots. It does not mock history endpoints.
The ordinary browser command excludes these cases. Default recovery checks use deterministic model/runtime ports.

For the opt-in Docker and local-model recovery cases, start Docker and local Ollama with the existing `qwen3.5:9b`
model and pull `python:3.12-alpine` before running:

```powershell
$env:DOCKSIGHT_PERSISTENCE_LIVE = '1'
npm --prefix frontend run test:browser:persistence
uv run --project backend pytest backend/tests/integration/persistence/test_live.py --no-cov
Remove-Item Env:DOCKSIGHT_PERSISTENCE_LIVE
```

These cases use one uniquely named and labeled container, verify its full ID before mutation or cleanup, and keep
local generation on loopback. They do not inspect unrelated workloads, download a model, or call cloud providers.
The Docker case explicitly restarts its owned fixture to exercise lost delivery, retained keys, and crash protection.

## Protecting master on GitHub

In repository Settings, configure a branch rule for `master`:

- Require pull requests and the Backend and Frontend checks. `Backend checks` enforces the 90% coverage threshold.
- Apply the rule to administrators.
- Disable force pushes and branch deletion.
- For a solo maintainer, require pull requests without requiring another reviewer's approval.

Only required checks block merging. Server-side protection applies to every client, including those bypassing local
hooks. CI runs after a push and cannot reject an already accepted update.

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
To check a built backend image, also set `DOCKSIGHT_TEST_BACKEND_IMAGE=docksight-backend:local` as an environment
variable and run `backend/tests/integration/test_image.py` with the Docker test flag enabled.

Live model tests require `DOCKSIGHT_TEST_LIVE_MODEL=1` and a configured provider. Cloud tests make paid API calls.
Run them only with supplied credentials and explicit authorization. They are disabled in CI.
Diagnostic cases live in `backend/tests/fixtures/diagnostics.json`.

### Live Docker and local-model end-to-end suite

The suite runs the real HTTP/SSE API, Docker adapter, and Ollama adapter.

- Each case creates a unique Compose project with pinned images, an internal network, and no published container ports.
- The model sees only fixture resources. Setup and cleanup use the run's ownership labels.
- The API uses a random in-memory token, an ephemeral loopback port, and isolated settings.
- The suite does not read `.env` or call your running backend.

Start Docker and local Ollama, install the desired models yourself, then run from the repository root:

```sh
uv run --project backend pytest backend/tests/integration/live_e2e --no-cov --live-e2e --e2e-model qwen3.5:9b --e2e-model ministral-3:8b-instruct-2512-q4_K_M -vv -s
```

Repeat `--e2e-model` to add models. `--e2e-model-url` accepts loopback endpoints only.
Install models before running. Missing models fail preflight. Docker pulls missing pinned fixture images.
Run cases sequentially, without xdist.
Ollama aliases marked as remote/cloud models are rejected before fixture setup or generation.
The workloads cover a refused database connection and invalid Grafana alerting configuration alongside healthy nginx,
an actual memory-limited OOM kill, a crash loop, truncated logs, and an exit 137 without an OOM kill.
Additional cases stop an owned Python process through Docker SIGTERM, observe a running HTTP server with an unhealthy
503 probe, and retain old request errors while a process remains running. PostgreSQL-style histories are synthetic.
These workloads do not host a database engine. The non-OOM exit 137 comes from an explicit process exit, without
SIGKILL.

Select a smaller matrix with repeated `--e2e-case` options: `compose-healthy`, `compose-explicit`, `compose-chat`,
`compose-typo`, `compose-spaced`, `compose-cyrillic`, `compose-ambiguous`, `oom`, `crash-loop`, `truncated-logs`,
`unknown-exit`, `clean-shutdown`, `unhealthy`, or `running-history`.
`compose-healthy` collects no individual snapshots or problem logs. Its group report must work without unsupported
container cards.

All supported question languages run by default. Use `--e2e-language en` for English only.
Assertions check runtime facts, exact resources, card coverage, log content, and evidence references.
Language checks inspect each summary, cause, unresolved detail, and action reason separately. They exclude quoted logs,
code, resource IDs, and common fixture terms such as PostgreSQL and Telegram. They detect language mismatches without
grading translation or reasoning.

Run the causal regression package with the default language matrix:

```sh
uv run --project backend pytest backend/tests/integration/live_e2e --no-cov --live-e2e --e2e-model qwen3.5:9b --e2e-suite causal -vv -s
```

Packages and repeated `--e2e-case` selections combine without duplicate runs. The `causal` package includes these
single-container cases and the noisy/shutdown follow-ups below:

| Case              | Observed fixture facts                                      | Explanation constraint                            |
|-------------------|-------------------------------------------------------------|---------------------------------------------------|
| `clean-shutdown`  | Real SIGTERM, exit 0, orderly stop after old request errors | Stop initiator and reason remain unknown          |
| `unknown-exit`    | Exit 137, `OOMKilled=false`                                 | Neither OOM nor SIGKILL is established            |
| `oom`             | Memory limit enforced, exit 137, `OOMKilled=true`           | Recognize the observed OOM kill                   |
| `unhealthy`       | Running process, Docker health `unhealthy`, HTTP 503        | Failed probes do not mean process termination     |
| `running-history` | Running process after synthetic SQL errors                  | Request errors do not establish a crash or health |

Single-container cases and shutdown follow-ups use production log budgets. The noisy follow-up uses smaller budgets
to exercise truncation and final-line retention.

Causal checks inspect summaries, immediate/deeper causes, unknowns, and action reasons:

- Allow "exited after errors" with an unknown stop reason. Require evidence for "exited because of errors".
- Reject database/dependency outage claims and guaranteed restart cures based only on an unhealthy 503 probe.
- Reject categorical "unrelated" claims based only on different project names or failure modes. Qualified hypotheses
  remain allowed.
- Handle negation, hypotheses, and quoted logs. Exact resource identifiers must not hide unsupported assertions.
- Keep acceptance and rejection examples when adding phrase rules. Check unrelated negation and omitted synonyms.

These test-only heuristics cover known phrase families for one target. Runtime schema validation does not apply them.
Review saved responses for unfamiliar phrasing and causal claims. Valid schemas and factual cards do not establish the
stop reason. Retain failed artifacts for model selection. Keep the same causal requirements when a model fails them.

Group cases also create an independently failing peer Compose project. Spaced and Cyrillic questions must resolve to the
target without including that peer. The ambiguous case gives both projects the same human-readable prefix: the first
turn must ask for the two observed choices without individual evidence reads, and a second request selects the target.

Follow-up cases diagnose a primary project, then ask about a dependency in the same session. They check fresh scoped
cards and actual log content, retaining the first turn in the ignored report. No case executes product actions.

| Case | Dependency and checks |
|------|-----------------------|
| `compose-follow-up` | Existing failure workload, with equal container/project names. No database engine |
| `compose-follow-up-noisy` | Running dependency with long synthetic SQL history and retained final log lines |
| `compose-follow-up-shutdown` | Real SIGTERM/exit 0, final log lines, and a follow-up on its single-member Compose group |

Select each with `--e2e-case`. Noisy and shutdown cases cover explicit containers and container/project clarification.
Causal checks reject old request errors presented as the stop reason.

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
Free chat uses a different UI locale from the question to check the explanation's language.
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
needed to explain a distinct workflow. Replace outdated captures and delete unused ones. Breakpoint and locale checks
belong in temporary test artifacts.

Edit backend diagrams in [backend.drawio](docs/diagrams/backend.drawio), preserving named pages and the shared
hand-drawn style. Update the PNG preview and its documentation link together.
See [export commands](docs/diagrams/README.md).
