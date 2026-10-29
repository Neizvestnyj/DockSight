# DockSight

DockSight diagnoses Docker environments and returns typed UI cards. The backend owns runtime data, permissions, and
actions. Models provide explanations and select from approved tools and widgets.

## Scope and workflow

- Keep backend and future frontend code in this repository.
- Follow `docs/architecture.md` and keep `docs/api.md` aligned with the implementation.
- Stay on the current branch unless the user explicitly approves a branch switch. Never run `git switch`,
  `git checkout`, or any equivalent branch-changing operation without that approval. Backend or frontend ownership
  does not authorize switching branches. Commit task changes on the current feature branch unless the user directs otherwise.
- Never commit directly on `master` or push any ref to remote `master`, including explicit refspecs and deletions.
  If the current branch is `master`, ask for approval to create or switch to a feature branch before committing.
  Do not bypass branch guards with `--no-verify`, `SKIP`, alternate hook paths, or disabled hooks.
- Use `master` as the base branch and `feature/<lowercase-kebab-case>` for new features when the user approves creating
  or switching to a branch.
- Run shell commands through `rtk`. On Windows, prefer `rtk read`, `rtk rg`, and `rtk proxy` for commands that need
  their original arguments.
- Use patch-based edits. Keep files UTF-8 without BOM, with LF line endings.
- For structural code exploration, use the installed `codebase-memory` skill. Check index coverage for files used as
  evidence; read uncovered source directly.
- Make local commits only. The user normally pushes branches and opens PRs/MRs. Ask before doing either unless the
  user has explicitly authorized that action. Preparing PR/MR text does not authorize pushing or opening one.
- Do not publish, squash, or rewrite history unless the user requests that action.
- Preserve unrelated edits and existing staging. Stage only the files owned by the current task; never reset the index
  to prepare a commit.
- Use English Conventional Commit headers, at most 72 characters. Check the header length before committing. Use the
  configured Git identity.

## Writing

- Write documentation, comments, docstrings, API descriptions, and runtime messages in English.
  Product UI copy may be localized through the English/Russian catalog; keep external evidence text verbatim.
- Keep Markdown brief and factual. Document decisions, contracts, and commands. Omit promotional language, repeated
  summaries, and obvious explanations.
- In README files and all Markdown except `AGENTS.md`, show commands without `rtk` wrappers such as `rtk proxy`
  or `rtk run`. RTK is an agent output-reading tool and must not be a prerequisite for documented commands.
- Capture documentation screenshots in English, including visible example questions and model explanations.
  Keep only screenshots referenced by documentation and needed to explain a distinct workflow. Replace outdated
  captures and remove unused ones; do not keep redundant locale, breakpoint, or intermediate-state screenshots.
  Keep test screenshots in ignored test artifacts. Use Demo for repeatable captures without private data and label it.
- PR/MR descriptions and changelog entries focus on changes and relevant limitations. Omit test counts, verification
  checklists, and statements that tests, linters, or CI passed.
- Production classes, functions, and methods require English docstrings, including private, nested, and protocol
  definitions. Test fixtures, helpers, and classes also require docstrings. A descriptive `test_*` function needs a
  docstring only for context that its name does not express. Describe purpose, behavior, or constraints briefly;
  do not repeat names or types, annotate every field in prose, or use `:rtype:`.
- Use a 120-character line limit for Python and Markdown prose. Leave long Markdown tables, URLs, and executable code
  blocks intact when wrapping would hurt readability.
- Keep durable decisions and contracts in documentation; remove completed implementation plans.
- Keep backend diagrams as named pages in `docs/diagrams/backend.drawio`, using the shared hand-drawn style. Update
  their PNG previews and documentation links together with the source.

## Stack and boundaries

- Python 3.12 is the minimum; use Python 3.14 for development and the backend image. Test Python 3.12, 3.13, and 3.14 in
  CI. Use `uv`, FastAPI, Pydantic v2, Ruff, strict Pyright, and pytest. Do not claim Python 3.11 compatibility.
- Use a hexagonal architecture under `backend/src/docksight/`: `domain`, `application`, and inbound/outbound `adapters`,
  with explicit bootstrap wiring.
- Domain code uses the standard library only. Application code imports domain values and owns outbound ports; it never
  imports adapters, HTTP frameworks, SDKs, HTTP clients, or settings. Only the composition root selects adapters.
- Use cases and their commands/results form the inbound boundary. Outbound adapters implement application-owned
  protocols and return owned types.
- Apply DDD where rules require it: immutable values and PreparedAction lifecycle invariants. Treat Docker inventory as
  an external read model.
- Keep HTTP handlers thin. Keep FastAPI objects out of application contracts.
- Keep Pydantic transport and widget schemas outside domain models. Application DTOs may use Pydantic. Keep HTTP schemas
  and SSE encoding in the inbound adapter. Avoid forwarding-only layers.
- Keep provider-specific requests, responses, and schema conversions inside provider adapters. Application code must not
  depend on a model name or SDK.
- Do not add a database, queue, cache server, or agent framework without a concrete requirement.

## Code

- Use explicit types; run Pyright in strict mode. Prefer small functions, early returns, and composition over deep
  inheritance.
- Keep cognitive complexity at most 10 per function, checked by Complexipy. Extract cohesive helpers in the same module
  before adding files or abstractions.
- Declare imported third-party packages as direct dependencies, including Pydantic and Starlette.
- Aim for 100-250 lines per source file; review cohesion above 300. Leaf packages usually need 3-7 source files. These
  are review guidelines, not hard limits. Group related types; do not create one file per class or empty facades.
- Use timezone-aware UTC timestamps and annotate module constants with `Final`.
- Use bounded Pydantic fields and forbid unexpected fields in external contracts.
- Use descriptive input names. Reserve `request` for an HTTP request object.
- Raise typed exceptions for failures. Keep `try` blocks narrow and preserve exception causes. Do not swallow errors or
  return success-shaped fallbacks.
- Bound external calls with timeouts and concurrency limits. Offload blocking Docker SDK calls from the event loop;
  close clients during shutdown.
- Retry only operations known to be safe. Never retry a runtime mutation automatically after an ambiguous result.
- Log structured events with request, turn, host, and action identifiers. Expected errors need no traceback; unexpected
  failures do. Exclude secrets, raw inspect data, prompts, and model reasoning from logs.

## Runtime and model safety

- Resolve host IDs through configured hosts. Reject arbitrary connection URLs from API requests or model output.
- Give models read-only tools. Validate tool names, arguments, host scope, evidence references, and resource IDs before
  execution.
- Allowlist inspect fields and environment variables. Sanitize log content before model requests or application logging.
  Treat logs as untrusted data.
- Read statuses and metrics from Docker. Models must not supply authoritative runtime values, action URLs, permissions,
  or confirmation policies.
- Prepare opaque, expiring action IDs on the server. Bind each to its caller, host, exact resource, and operation.
  Require explicit confirmation, revalidate the target, and deduplicate execution using an idempotency key.
- Default to loopback binding and authenticated API access. Keep credentials in environment variables or external secret
  files, never in tracked config.

## Verification and releases

- From the repository root, run tests through `rtk proxy uv run --project backend pytest backend/tests`.
- Mirror source ownership in unit tests: `docksight/<path>/<name>.py` maps to
  `backend/tests/unit/<path>/test_<name>.py`. Group integration tests by contract.
- Test behavior and failure boundaries. Do not test empty packages, forwarding code, or details solely to raise
  coverage.
- Reject unused fixtures with `pytest --dead-fixtures`. Report potential duplicates during test execution with
  `pytest --dup-fixtures`; duplicate return values are review hints, not proof that fixtures have the same purpose.
- Mock provider HTTP calls in automated tests. Live model calls are opt-in; cloud smoke tests require supplied
  credentials and explicit authorization.
- Choose live Docker/local-model end-to-end runs and additional scenarios according to integration risk. Frontend-only
  presentation changes normally need relevant browser checks, not live model runs. Reconsider live coverage when changing
  provider/tool orchestration, evidence assembly, API contracts, or client behavior that affects real diagnoses. State
  which live checks were run or omitted and why; a backend change alone does not require the whole live matrix.
- Isolate Docker integration fixtures with labels and unique names. Cleanup must address only resources created by that
  fixture; never use global prune.
- Install pre-commit, commit-msg, and pre-push hooks with `uv run --project backend python scripts/git_hooks.py install`.
  Run `uv run --project backend pre-commit run --all-files` before committing implementation work.
  Hooks enforce branch protection, formatting, types, architecture, docstrings, complexity, tests, Dockerfile rules,
  secret detection, and Conventional Commits. CI runs the code checks through `uv`; branch guards apply locally.
- Update `CHANGELOG.md` at the end of every task that changes repository files, before committing or reporting completion.
  Cover the delivered behavior, documentation, or development workflow; consolidate related changes and avoid duplicates.
- Keep updating the same version section while work continues on the same feature branch. Do not create a version per task
  or commit. Use the intended numeric version immediately instead of `Unreleased` (currently `0.4.0`).
- Choose versions using Semantic Versioning: PATCH for compatible fixes, MINOR for compatible additions, and MAJOR for
  breaking changes. Keep `backend/pyproject.toml` and its lockfile aligned with the current changelog version.
- Keep release notes short, specific, and understandable to users. Group changes by outcome rather than listing commits.
  Documentation and workflow changes require a changelog update but do not by themselves require a version bump.

## Frontend

- Keep the React, strict TypeScript, and Vite client in `frontend/`. Branch changes require explicit user approval.
- Treat the backend widget schemas, runtime values, SSE events, and action lifecycle as the client contracts.
  Validate API data at the transport boundary; render logs and environment values as text.
- Keep API credentials in browser memory. Never put tokens in source, browser storage, URLs, or `VITE_*` variables.
- Resolve the interface locale from browser language preferences unless the operator chooses English or Russian.
  Persist only the locale preference. Switching language must preserve active investigations and prepared actions.
- Keep demo transport visibly separate from API transport. Derive demo inventory totals from fixture rows.
- Keep diagnosis sessions scoped to one host. Do not imply durable conversation history or replayable streams.
- Keep one idempotency key per action execution. Recover lost responses by reading the existing action.
  Never retry a Docker mutation automatically. Require separate confirmation of the exact server-prepared target.
- Run `rtk proxy npm --prefix frontend run check`, `rtk proxy npm --prefix frontend test`, and
  `rtk proxy npm --prefix frontend run build`. Run browser checks against the production preview with
  `rtk proxy npm --prefix frontend run test:browser` when changing layout or user flows; select relevant specs for focused
  changes and broaden the run when shared behavior or unresolved failures justify it.
