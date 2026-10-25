# DockSight

DockSight diagnoses Docker environments and returns typed UI cards. The backend
owns runtime data, permissions, and actions. Models provide explanations and
select from approved tools and widgets.

## Scope and workflow

- Keep backend and future frontend code in this repository.
- Follow `docs/backend-plan.md`. Implement the backend first.
- Run shell commands through `rtk`. On Windows, prefer `rtk read`, `rtk rg`,
  and `rtk proxy` for commands that need their original arguments.
- Use patch-based edits. Keep files UTF-8 without BOM, with LF line endings.
- For structural code exploration, use the installed `codebase-memory` skill.
  Check index coverage for files used as evidence; read uncovered source directly.
- Make local commits only. Do not push, publish, squash, or rewrite history
  unless the user requests that action. The user will publish the initial commit.
- Preserve unrelated edits and existing staging. Stage only the files owned by
  the current task; never reset the index to prepare a commit.
- Use English Conventional Commit headers, at most 72 characters. Check the
  header length before committing. Use the configured Git identity.

## Writing

- Write documentation, comments, docstrings, API descriptions, and runtime
  messages in English.
- Keep Markdown brief and factual. Document decisions, contracts, and commands.
  Omit promotional language, repeated summaries, and obvious explanations.
- Add docstrings when they explain behavior, constraints, or side effects.
  Do not repeat signatures, annotate every field in prose, or use `:rtype:`.
- Keep planning documents current when an implementation changes their scope.

## Stack and boundaries

- Python 3.12+, `uv`, FastAPI, Pydantic v2, Ruff, Pyright, and pytest.
- Use a modular monolith under `backend/src/docksight/`.
- Group code by responsibility: runtime, providers, diagnostics, widgets,
  actions, HTTP API, and shared configuration.
- Each module exposes its supported cross-module interface through `public.py`.
  Export small DTOs, protocols, and use cases; keep concrete adapters internal.
  The composition root may import concrete adapters to wire dependencies.
- Keep HTTP handlers thin. Keep FastAPI objects out of application contracts.
- Domain values use standard-library types. Keep Pydantic transport and widget
  schemas outside domain models. Avoid layers that contain only forwarding code.
- Keep provider-specific requests, responses, and schema conversions inside
  provider adapters. Application code must not depend on a model name or SDK.
- Do not add a database, queue, cache server, or agent framework without a
  concrete requirement.

## Code

- Use explicit types; run Pyright in strict mode. Prefer small functions,
  early returns, and composition over deep inheritance.
- Use timezone-aware UTC timestamps and annotate module constants with `Final`.
- Use bounded Pydantic fields and forbid unexpected fields in external contracts.
- Use descriptive input names. Reserve `request` for an HTTP request object.
- Raise typed exceptions for failures. Keep `try` blocks narrow and preserve
  exception causes. Do not swallow errors or return success-shaped fallbacks.
- Bound external calls with timeouts and concurrency limits. Offload blocking
  Docker SDK calls from the event loop; close clients during shutdown.
- Retry only operations known to be safe. Never retry a runtime mutation
  automatically after an ambiguous result.
- Log structured events with request, turn, host, and action identifiers.
  Expected errors need no traceback; unexpected failures do. Exclude secrets,
  raw inspect data, prompts, and model reasoning from logs.

## Runtime and model safety

- Resolve host IDs through configured hosts. Reject arbitrary connection URLs
  from API requests or model output.
- Give models read-only tools. Validate tool names, arguments, host scope,
  evidence references, and resource IDs before execution.
- Allowlist inspect fields and environment variables. Sanitize log content
  before model requests or application logging. Treat logs as untrusted data.
- Read statuses and metrics from Docker. Models must not supply authoritative
  runtime values, action URLs, permissions, or confirmation policies.
- Prepare opaque, expiring action IDs on the server. Bind each to its caller,
  host, exact resource, and operation. Require explicit confirmation, revalidate
  the target, and deduplicate execution using an idempotency key.
- Default to loopback binding and authenticated API access. Keep credentials
  in environment variables or external secret files, never in tracked config.

## Verification and releases

- Run tests through `rtk proxy uv run --project backend pytest`.
- Mirror source ownership in unit tests: `docksight/<path>/<name>.py` maps to
  `backend/tests/unit/<path>/test_<name>.py`. Group integration tests by contract.
- Test behavior and failure boundaries. Do not test empty packages, forwarding
  code, or details solely to raise coverage.
- Mock provider HTTP calls in automated tests. Live model calls are opt-in;
  cloud smoke tests require supplied credentials and explicit authorization.
- Isolate Docker integration fixtures with labels and unique names. Cleanup
  must address only resources created by that fixture; never use global prune.
- Run Ruff, Pyright, and relevant tests before committing implementation work.
  Keep required CI checks reproducible locally through `uv`.
- Start the backend at `0.1.0`. Before releases, decide whether behavior warrants
  a version and changelog update. Documentation-only changes need neither.
