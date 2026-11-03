# Persistent Investigations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Save and reopen actor-owned investigations, recover browser sessions/running turns, and retain action safety
across backend crashes.

**Architecture:** Application-owned storage ports separate saved history, bounded model context, browser sessions,
and atomic action state. A SQLAlchemy/Alembic SQLite adapter owns persistence and recovery. A lifespan-owned supervisor
runs diagnostics independently of observers, and React restores validated server state through cookie bootstrap.

**Tech Stack:** Python 3.12+, development Python 3.14, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, SQLite, portalocker,
React, strict TypeScript, Vite, Zod, pytest, and Playwright.

**Spec:** [Persistent investigations design](../specs/2026-11-03-persistent-investigations-design.md).

## Global constraints

- Python 3.12 is the minimum. Develop with Python 3.14.
- Domain code remains standard-library-only.
- Keep strict types, bounded contracts, English documentation and runtime messages, localized UI copy, and a
  120-character prose limit.
- No SQLAlchemy, SQL, HTTP, SDKs, clients, or settings in application/domain contracts.
- Never hold a database transaction across Docker/model/catalog calls. Never automatically retry a Docker mutation.
- One local-filesystem database, one active backend process/worker, no silent memory fallback.
- No raw bearer/provider token, cookie, prompt, reasoning, or provider-native replay data in the DB or logs.
- Latest 10 chats is a list size. It is not retention or deletion permission.
- No context-budget gauge, host editor, new roles, cloud service, or PostgreSQL/Oracle implementation.
- Stay on the current branch until explicit branch authorization. Never commit on master, push, open a PR, or bypass
  hooks.
- Use patch edits and preserve unrelated edits/staging. Shell execution uses RTK. Documented commands below omit RTK.
- Before each implementation commit run `uv run --project backend pre-commit run --all-files`.
- Update the same 0.8.0 changelog section, pyproject version, and lockfile. Do not retain completed plans.

## Review focus

- A lost submit response followed by F5 finds the committed turn and performs no second generation: Tasks 3, 5, and 7.
- A crash around Docker dispatch preserves a block even when no command was sent: Tasks 2 and 7.
- Cookie/bearer disagreement never selects the wrong actor or bypasses CSRF: Task 4.
- A stale tab cannot clear a newer draft, choose an old clarification, or move the current tab: Tasks 3, 6, and 7.
- Removed config IDs, unsupported snapshots, and oversized histories remain readable/fail safely: Tasks 1, 3, and 6.

## File map

Paths are repository-relative. New modules should stay cohesive, normally 100–250 lines. Split only at the named
responsibility boundaries below. Unit tests mirror source ownership. Add ordinary package `__init__.py` files as needed.

| Files | Responsibility |
|-------|----------------|
| `application/investigations/contracts.py`, `ports.py`, `service.py`, `runner.py` | Owned snapshots/commands, archive port, acceptance/history/workspace use cases, diagnostic supervision |
| `application/browser_sessions.py`, `application/ports/browser_sessions.py` | Session values/use case and session storage protocol |
| `application/ports/state.py`, `application/actions.py`, `application/action_reconciliation.py`, `domain/actions.py` | Explicit domain-checked durable action transitions and offline reconciliation |
| `adapters/outbound/persistence/database.py`, `rows.py`, `investigations.py`, `browser_sessions.py`, `actions.py`, `recovery.py` | Single database thread/lock, mappings, port adapters, startup recovery |
| `adapters/outbound/persistence/migrations/` | Packaged Alembic environment and `versions/0001_persistent_state.py` |
| `adapters/outbound/memory/investigations.py`, `browser_sessions.py`, `actions.py` | Matching explicit contracts for tests/development |
| `adapters/inbound/http/auth.py`, `investigations.py`, `schemas.py`, `routes.py`, `streaming.py` | Auth/CSRF, history HTTP endpoints, schemas, legacy stream bridge, snapshot observer encoding |
| `bootstrap.py`, `main.py`, `state_cli.py` | Wiring, ordered startup/shutdown, OS-operator maintenance entrypoint |
| `frontend/src/investigation-contracts.ts`, `useWorkspace.ts`, `useSavedInvestigations.ts`, `SavedInvestigations.tsx` | Validated history/session schemas, revisioned workspace, list/read state, saved-chat navigation |
| Existing frontend `api.ts`, `contracts.ts`, `stream.ts`, `App.tsx`, `useInvestigation.ts`, `Connection.tsx`, `Sidebar.tsx`, `Investigation.tsx`, `ActionReview.tsx`, `demo.ts`, `messages.ts`, `styles.css` | Transport/bootstrap, recovery, UI integration, authoritative action review, Demo parity and copy |

Backend paths in this table are below `backend/src/docksight/`. Existing relevant source was checked directly after
index coverage reported metadata changes. Recheck current files before editing. This map is not an instruction to
restructure unrelated source or retain forwarding-only modules.

## Interface vocabulary

Define these immutable/bounded application DTOs in `application/investigations/contracts.py`:

- `InvestigationView`, `InvestigationSummary`, `InvestigationPage`, `TurnPage`, `InvestigationWorkspace`,
  `ActorWorkspace`.
- `StartTurn`: investigation ID, submission UUID, expected workspace revision, submitted query, target/model selection,
  optional clarification parent ID and expected parent revision.
  Make question and clarification submissions a discriminated union. Clarification carries no replacement query.
  The trimmed submitted query is retained only in memory. Compute its canonical digest before redaction, then pass
  only a redacted command copy plus that digest to `TurnStore.accept`. Model use also receives only redacted text.
- `AcceptedTurn`: `snapshot: SavedTurn`, `created: bool`. `SavedTurn` contains persisted IDs, state, revision,
  timestamps, query/target/model, clarification links, safe progress/trace, answer/selection/error, and version 1.
- `TurnUpdate` for nonterminal progress, `TurnOutcome` for a terminal validated answer/clarification/failure, and
  `WorkspacePatch` / `ActorWorkspacePatch` with required `expected_revision`.
- `DiagnosticCommand`: preallocated turn/investigation IDs, actor, host, query, target, identity, and bounded context.

Use UUID strings inside application contracts and bounded transport UUID fields at HTTP boundaries. Domain values
remain standard-library types. `SavedTurn.answer` uses the existing `DiagnosisResponse`. Keep no provider-native types.

### Task 1: Persistent storage foundation and explicit ports

**Files:**

- Create the contracts/ports, persistence database/rows/migration modules, and the minimal working
  `adapters/outbound/persistence/investigations.py` archive adapter. Create its matching memory archive adapter and
  `application/ports/browser_sessions.py`. Browser-session persistence is implemented in Task 4.
- Modify `backend/pyproject.toml`, `backend/uv.lock`, `backend/Dockerfile`, `.gitignore`, and `CHANGELOG.md`.
- Test `backend/tests/unit/application/investigations/test_contracts.py` and
  `backend/tests/unit/adapters/outbound/persistence/test_database.py`.
- Test common contracts in `backend/tests/integration/test_state_storage.py` and migrations/process ownership in
  `backend/tests/integration/test_state_lifecycle.py`.

**Interfaces:**

- Produce and implement `InvestigationArchive.create(actor, investigation_id, host, now) -> InvestigationView`;
  `list_owned(actor, limit, cursor) -> InvestigationPage`; `read(actor, investigation_id) -> InvestigationView`;
  `turns(actor, investigation_id, limit, cursor) -> TurnPage`; `read_turn(actor, turn_id) -> SavedTurn`.
- Produce `patch_workspace(actor, investigation_id, patch, now) -> InvestigationWorkspace`;
  `workspace(actor) -> ActorWorkspace`; `patch_actor_workspace(actor, patch, now) -> ActorWorkspace`;
  `delete(actor, investigation_id, now) -> None`.
- Define `TurnStore` separately for Task 3 acceptance/progress/context methods. Task 1 must implement the complete
  archive/workspace read-write contract it tests, not placeholders that depend on Task 3.
- Produce `PersistentDatabase.open_existing(mode: MaintenanceMode) -> None`, `initialize_server() -> RecoveryReport`,
  `close() -> None`, and `healthy: bool`. Maintenance modes are `status`, `backup`, `migrate`, and `reconcile`.
  Its private transaction runner is adapter-owned and returns fully materialized values.

- [ ] Write contract tests that run against memory and file-backed SQLite: foreign actor reads are not found,
  returned values are detached, cursor scope cannot cross actors, old pages remain accessible after the latest 10,
  and unsupported snapshot envelopes fail with `history_unsupported` without deleting data.
- [ ] Write lifecycle tests: second process cannot acquire the same canonical state path, failed migration leaves
  existing data intact/unready, newer schema refuses writes, unwritable/corrupt DB never chooses memory, queued
  transactions do not block the event loop, and accepted cancellation never reports a committed write as absent.
- [ ] Write maintenance tests against an old schema with abandoned work: status and pre-migration backup leave schema,
  turn/action lifecycle, and audit unchanged. Backup preserves original main/journal bytes before any source SQLite
  recovery. Reconcile construction does not invoke normal startup, models, turn admission, or unrelated cleanup.
- [ ] Run those tests to observe missing-contract/adapter failures. Use temporary paths and no real credentials.
- [ ] Implement the spec's schema/limits, packaged Alembic upgrade, modern SQLite transaction configuration,
  single-thread admission, OS lock, typed storage errors, and snapshot dispatch. Add SQLAlchemy/Alembic/portalocker
  as direct dependencies. Extend import-linter forbidden packages and its regression test to cover these libraries.
  Implement real archive CRUD, workspace compare-and-swap, pagination, scoped reads, deletion, and detached mapping
  now. Use fixture-seeded bounded turn snapshots to test older pages. Acceptance/supervision comes in Task 3.
  Keep automatic startup wiring disabled until Task 5 supplies all recovery services.
- [ ] Set feature version 0.8.0 and prepare image directory/env/volume documentation inputs. Package migrations in
  wheels/images, ignore only the intended local state directory, and update the feature changelog entry.
- [ ] Run focused storage tests. Expected: contracts pass for both adapters where guarantees match.

```sh
uv run --project backend pytest backend/tests/integration/test_state_storage.py backend/tests/integration/test_state_lifecycle.py backend/tests/unit/application/investigations backend/tests/unit/adapters/outbound/persistence --no-cov
```

- [ ] Run all-files pre-commit, stage only owned files, and commit `feat: add persistent state storage foundation`.

### Task 2: Durable action transitions and offline reconciliation

**Files:**

- Modify `backend/src/docksight/domain/actions.py`, `application/ports/state.py`, `application/actions.py`,
  `adapters/outbound/memory/actions.py`, and `adapters/outbound/audit.py`.
- Create `application/action_reconciliation.py`, persistence `actions.py`, `recovery.py`, and `state_cli.py`.
- Test mirrored `test_actions.py`, `test_action_reconciliation.py`, and `test_recovery.py` modules plus
  `backend/tests/integration/test_action_recovery.py`.

**Interfaces:**

- Produce `StoredAction` with `action: PreparedAction`, `revision: int`, and
  `phase: Literal['prepared', 'claimed', 'dispatching', 'terminal']` in `application/ports/state.py`.
  Produce `ActionClaim(stored: StoredAction, claimed: bool)` there.
- Change `ActionStore.add(action, now) -> StoredAction`, `get(action_id, actor, now) -> StoredAction`,
  `claim(action_id, actor, key, confirmed, now) -> ActionClaim`;
  add `mark_dispatch(action_id, expected_revision, now) -> StoredAction` and
  `complete(action_id, expected_revision, state, message, now) -> StoredAction`.
- Replace `target_lock/block_target` with atomic target reservation/blocking inside those operations. Add
  `inspect_block(action_id) -> BlockedTarget` and
  `reconcile(command: ReconcileTarget, observation: ReconciliationObservation, now) -> BlockedTarget`.
- Produce `ActionReconciliation.inspect(action_id) -> BlockedTarget` and
  `reconcile(command: ReconcileTarget) -> BlockedTarget`, consuming configured runtime reads and the action store.
- Add domain `PreparedAction.expire(now) -> bool` and an explicit invalidation method for operator reconciliation.
  Keep claim/finish invariant checks in the domain and test them independently of SQLAlchemy.

- [ ] Write failing detached-store tests proving that an action succeeds only after `complete`, a failed audit/state
  commit prevents dispatch, repeated keys survive reopening the DB, wrong keys conflict, expiry is saved despite a
  rejected execution, and two actions for the same exact target cannot dispatch together.
  Parametrize matching explicit action contracts over memory and SQLite.
- [ ] Write subprocess/fault-barrier tests for death after claim, after dispatch marker before Docker send, after
  fake Docker success before terminal commit, and after terminal commit before response. Assert exact fake dispatch
  counts, retained keys, durable audit, and block persistence after a second restart.
- [ ] Write a live-process cancellation-barrier test that cancels the HTTP execution task immediately after claim
  commit and before `_run` registration. Assert a retained admission owner starts exactly one workflow and produces
  a terminal result/guard without restarting. Test registration failure and shutdown during that handoff.
- [ ] Write reconciliation tests: backend-lock conflict, unavailable Docker, changed revision, missing acknowledgement,
  and audit failure retain the block. Explicit confirmed reconciliation leaves the old outcome indeterminate,
  invalidates old preparations, records actor/reason/observation UTC, and never calls the mutation port.
- [ ] Run the new tests and confirm their expected failures before changing execution behavior.
- [ ] Implement claim/dispatch/complete transactions with domain calls and compare-and-swap revisions. Refactor
  `Actions._run` to persist every transition explicitly. Make durable audit authoritative and JSON logging a mirror.
  Preserve shielded SDK tracking and the conservative crash matrix. Storage failure closes mutation admission.
  Add a strong-reference admission registry in `Actions.execute` before the claim write. Its shielded owned task
  spans claim → workflow registration and records failed-before-dispatch if registration fails.
- [ ] Implement startup recovery plus the offline CLI preview/confirm workflow from the spec. Reuse the exclusive
  database owner. Add `status`, `migrate`, and stopped-backend `backup` commands without direct operator SQL.
  Construct only command-specific maintenance services. Backup precedes source SQLite opening/recovery. Reconcile
  verifies the current supported schema and changes only the explicitly confirmed target/audit transaction.
- [ ] Run focused action tests. Expected: all crash windows remain protected and no uncertain mutation is repeated.

```sh
uv run --project backend pytest backend/tests/unit/domain/test_actions.py backend/tests/unit/application/test_actions.py backend/tests/unit/application/test_action_reconciliation.py backend/tests/integration/test_action_recovery.py --no-cov
```

- [ ] Update changelog, run all-files pre-commit, stage only owned files, and commit
  `feat: persist action claims and crash recovery guards`.

### Task 3: Saved investigations, bounded context, and task supervision

**Files:**

- Create `backend/src/docksight/application/investigations/service.py` and `runner.py`.
- Implement persistence `investigations.py` and matching memory contracts.
- Modify `application/diagnostics/use_case.py`, `application/diagnostics/trace.py`, `application/events.py`, and
  `application/ports/state.py`. Remove obsolete mutable session storage only after its callers migrate.
- Test mirrored `test_service.py`, `test_runner.py`, diagnostic `test_use_case.py`, and
  `backend/tests/integration/test_investigation_recovery.py`.

**Interfaces:**

- Produce `Investigations.create/list_owned/read/turns/workspace/patch_workspace/delete` using Task 1 ports.
- Produce `TurnStore.submission(actor, submission_id, input_digest) -> SavedTurn | None`,
  `accept(actor, command: StartTurn, input_digest, request_id, now) -> AcceptedTurn`,
  `update(turn_id, expected_revision, update: TurnUpdate, now) -> SavedTurn`,
  `finish(turn_id, expected_revision, outcome: TurnOutcome, now) -> SavedTurn`, and
  `context(actor, investigation_id) -> tuple[ModelMessage, ...]`. Deleted receipts raise `history_deleted`.
- Produce `TurnRunner.submit(actor, command: StartTurn, request_id) -> AcceptedTurn`,
  `start(turn_id) -> None`, `observe(actor, turn_id) -> AsyncIterator[SavedTurn]`,
  `cancel(actor, turn_id) -> SavedTurn`, and `close() -> None`.
- Produce `Diagnostics.run(command: DiagnosticCommand) -> AsyncGenerator[TurnEvent]` with preallocated IDs and bounded
  context. It does not mutate `Session.history` or own a storage lease. Keep the old `stream` entrypoint as a temporary
  compatibility wrapper until Task 5 migrates HTTP callers. Remove that wrapper and its mutable session adapter there.
- The runner consumes selected diagnostics from a typed async factory, preserves shared global capacity, and commits
  normalized updates/terminal outcomes through Task 1. Application code does not import bootstrap or settings.

- [ ] Write tests for actor/host isolation, actor-unique submission deduplication and conflicting content, one running
  actor/host scope, capacity reservations, revision conflicts, and create/submit commit-before-scheduling.
  Replay the same logical request with its stale pre-accept revision, changed/removed config, unavailable catalog,
  full quota, active scope, and resolved clarification parent. Each replay returns the original committed turn and
  makes no model call. Changed revision/request ID alone does not change the logical digest.
- [ ] Write a cancellation-barrier test after acceptance commit but before diagnostic-task registration. Cancel the
  HTTP task and assert the lifespan-owned admission task registers exactly one worker without a backend restart.
  Cover task-registration failure, concurrent identical submissions, and shutdown during admission.
- [ ] Write tests for duplicate/lost clarification responses, stale parent revision, foreign candidate, removed exact
  target, and single-question grouping metadata. Assert no extra model work on any rejected/duplicate submission.
- [ ] Write tests showing that 11+ completed turns remain archived while context keeps at most 10 whole pairs and
  32,000 characters. Failure/selection/stopped/interrupted turns append no context. Continuing collects fresh evidence.
- [ ] Write runner tests: observer disconnect does not cancel work, explicit Stop does, completion/Stop race has one
  winner, uncaught tasks are retrieved, shutdown records interruption, restarted running work is never auto-resumed,
  and progress persistence excludes response previews/prompts/reasoning/secrets.
- [ ] Run these tests to confirm missing lifecycle behavior, then implement the service, runner, detached DTO updates,
  bounded snapshots, context trimming, quota accounting, and active-scope release in terminal transactions.
  Persist final answer/context together before publication. Keep existing model/tool/deadline limits unchanged.
  Follow the spec's exact canonical-digest fields and lookup → new-input validation → atomic duplicate recheck order.
  Retain admission tasks before any acceptance write and shield the caller await through worker registration.
- [ ] Run focused investigation tests. Expected: accepted work survives observer loss, explicit cancellation settles,
  and restart produces interruption.

```sh
uv run --project backend pytest backend/tests/unit/application/investigations backend/tests/unit/application/diagnostics backend/tests/integration/test_investigation_recovery.py --no-cov
```

- [ ] Update changelog, run all-files pre-commit, stage only owned files, and commit
  `feat: save investigations and supervise diagnostic turns`.

### Task 4: Persisted first-party browser sessions and CSRF

**Files:**

- Create `backend/src/docksight/application/browser_sessions.py`, persistence/memory `browser_sessions.py`, and
  `adapters/inbound/http/auth.py`.
- Modify `main.py`, `adapters/inbound/http/routes.py`, `schemas.py`, `errors.py`, and `bootstrap.py`.
- Test mirrored `test_browser_sessions.py`, HTTP `test_auth.py`, `test_middleware.py`, and
  `backend/tests/integration/test_browser_auth.py`.

**Interfaces:**

- Produce `BrowserSessionStore.add(record: BrowserSession) -> None`, `get(token_hash: str) -> BrowserSession | None`,
  `touch(token_hash: str, now: datetime) -> None`, `revoke(token_hash: str, now: datetime) -> None`, and
  `revoke_obsolete(fingerprints: Mapping[str, str], now: datetime) -> int`. Only hashed session values are stored.
- Produce `BrowserSessions.login(actor, credential_fingerprint) -> IssuedBrowserSession`,
  `authenticate(cookie, current_credentials) -> BrowserPrincipal`, `logout(cookie) -> None`.
- Produce an HTTP principal resolver shared by middleware and routes. It selects explicit bearer before cookie,
  validates Origin/CSRF for cookie unsafe methods, and documents both security schemes.
- Produce `/auth/login`, `/auth/session`, `/auth/logout` using the exact cookie, lifetime, and deployment rules in
  the spec. The session response carries actor, absolute expiry, and an in-memory-only derived CSRF value.

- [ ] Write auth tests for login rotation, hashed-at-rest cookie, absolute/idle expiry, coalesced last seen, logout,
  actor/token removal and rotation, invalid bearer plus valid cookie, and valid bearer selecting its own actor.
- [ ] Write HTTP tests for missing/null/foreign Origin, missing/wrong CSRF, non-JSON unsafe requests, login CSRF,
  explicit loopback Secure exception, untrusted forwarded headers, preflight, OpenAPI alternatives, and no-store.
  Inspect persisted bytes and captured logs for raw submitted bearer/session/provider values.
- [ ] Run the tests to verify failure, then implement application session behavior, store methods, and shared HTTP
  authentication. Remove the router's bearer-only blocker. Keep foreign-origin bearer CORS usable with cookies omitted.
  Do not enable cross-site cookie login or persist a browser endpoint.
- [ ] Run focused auth tests. Expected: cookie reads work, unsafe cookie requests require CSRF, and bearer/CLI access
  remains compatible.

```sh
uv run --project backend pytest backend/tests/integration/test_browser_auth.py backend/tests/integration/test_api.py backend/tests/unit/adapters/inbound/http backend/tests/unit/application/test_browser_sessions.py --no-cov
```

- [ ] Update changelog, run all-files pre-commit, stage only owned files, and commit
  `feat: restore first-party browser sessions securely`.

### Task 5: History HTTP, snapshot observation, and startup wiring

**Files:**

- Create `backend/src/docksight/adapters/inbound/http/investigations.py`.
- Modify HTTP `routes.py`, `schemas.py`, `streaming.py`, `bootstrap.py`, and `main.py`.
- Test HTTP `test_streaming.py`, bootstrap tests, `backend/tests/integration/test_investigations_api.py`, and legacy
  `test_api.py`, `test_target_clarification.py`, `test_model_selection.py`.

**Interfaces:**

- Produce every endpoint in the spec API table with strict UUID/revision/cursor bounds and actor-scoped calls.
- Produce `SnapshotResponse` over `AsyncIterator[SavedTurn]`, encoded as version-1 `turn.snapshot` SSE with heartbeat.
  It detaches on disconnect and never owns the diagnostic task.
- Retain legacy `POST /chat/turns` and existing event names through the same runner, with optional `submission_id` and
  investigation ID mapped to `session_id`. Preserve old clients' response shape and explicit target semantics.
  Remove Task 3's temporary `Diagnostics.stream` wrapper and obsolete mutable `SessionStore` implementation.
- Add `Components.start() -> None` for the normal server-only lock/migration/recovery sequence before readiness.
  It uses `initialize_server`, while maintenance CLI paths use `open_existing` and command-specific operations.
  Close admission registries/runner/actions before
  provider/runtime/database adapters. `build_components` can accept explicitly injected stores for isolated tests.

- [ ] Write API tests for owned latest-10 and older pages, CRUD/workspace conflicts, invalid cursors, schema/size
  failures, authoritative IDs, history deletion preserving actions/guards, and removed configured host history.
- [ ] Write real-server tests disconnecting legacy and snapshot streams while a blocking fake model continues.
  Assert GET/history returns the same turn, repeated observers do not generate, four-observer capacity is enforced,
  and revoked sessions close their observer without cancelling work.
- [ ] Write startup tests asserting lock → migration → session revocation/recovery → readiness ordering, no model call
  during recovery, and shutdown interruption before DB close. Use a temporary database for every application fixture.
- [ ] Run these tests to establish failure, then implement thin endpoints, legacy event bridging, snapshot encoding,
  safe error mappings, configuration validation, startup/shutdown ownership, and persistent defaults.
  Return 202 only after acceptance commit. Preserve original request IDs across recovered observers.
- [ ] Run focused API tests. Expected: old bearer API and new persisted history/recovery contracts both hold.

```sh
uv run --project backend pytest backend/tests/integration/test_investigations_api.py backend/tests/integration/test_api.py backend/tests/integration/test_target_clarification.py backend/tests/integration/test_model_selection.py backend/tests/unit/test_bootstrap.py backend/tests/unit/adapters/inbound/http --no-cov
```

- [ ] Update changelog, run all-files pre-commit, stage only owned files, and commit
  `feat: expose saved history and recoverable turn observation`.

### Task 6: Saved-chat UI, restored workspaces, and current action state

**Files:**

- Create the four frontend modules from the file map and mirrored `.test.ts(x)` files.
- Modify existing frontend files listed in the file map, `useInvestigation.test.tsx`, `api.test.ts`,
  `workspace.test.tsx`, `card-actions.test.tsx`, and relevant locale/model/clarification tests.
  Update existing browser setup that assumes automatic Demo entry to choose Demo explicitly.

**Interfaces:**

- Produce `ApiClient.login(token)`, `session()`, `logout()`, history/workspace methods matching Task 5, and
  `observeTurn(id, receive, signal)`. First-party mode retains only CSRF/principal in memory after login.
- Produce `useWorkspace` with bootstrap state, serialized revisioned saves, dirty/conflict handling, and validated IDs.
- Produce `useSavedInvestigations` and `SavedInvestigations` for latest 10, older pages, open/new/delete, loading/error,
  and current selection. Use server IDs and timestamps, no invented local durable history.
- Refactor `useInvestigation` around saved IDs/snapshots. Keep Demo methods ephemeral and visibly simulated through
  explicit capability/state discrimination. `stop()` calls cancellation, unmount only detaches observation.

- [ ] Write unit tests for cookie bootstrap selecting API before Demo, signed-out/network retry states, transient
  split-origin bearer mode, no browser credential storage, and login input clearing after exchange.
- [ ] Write tests for revisioned draft saves and conflict recovery, stale host/chat responses, removed host/model IDs,
  latest-10 pagination, clarification attempt grouping, and action read-before-confirm on restored cards.
  Assert archive reads never prepare/execute and restored confirmation stays closed.
- [ ] Run the tests to establish missing behavior. Implement Zod transport validation, bootstrap, history navigation,
  draft save status/debounce, explicit conflict controls, read-only recovery/backoff, authoritative action hydration,
  and localized copy. Preserve focus, mobile navigation, locale changes, and current inventory/evidence behavior.
- [ ] Make new-chat/scope changes detach without cancellation and preserve prior saved investigations. Keep old evidence
  dated, use fresh reads on continue, and render restored traces without retained output previews.
- [ ] Run `npm --prefix frontend run check`, `npm --prefix frontend test`, and `npm --prefix frontend run build`.
  Expected: strict TypeScript, unit behavior, and production bundle succeed with no credential storage regression.
- [ ] Update changelog, run all-files pre-commit, stage only owned files, and commit
  `feat: reopen saved chats and restore browser workspaces`.

### Task 7: Cross-process and real-browser recovery verification

**Files:**

- Create `backend/tests/integration/test_persistent_browser.py` and a reusable deterministic persistent-API fixture
  under `backend/tests/integration/persistence/`.
- Create `frontend/tests/persistence.spec.ts`, `frontend/playwright.persistence.config.ts`, and
  `frontend/tests/fixtures/persistent-api.ts`.
- Extend `test_action_recovery.py`, `test_investigation_recovery.py`, and opt-in Docker/local-model harness files only
  where required for the selected crash/F5 scenarios. Add a package command for the dedicated browser suite.

**Interfaces:**

- The Python fixture owns a real HTTP subprocess with temp SQLite and deterministic fake runtime/model ports.
  It reports test-only barriers/counters to its owning test process, never adds production debug endpoints.
- The dedicated Playwright fixture owns that backend and production Vite preview. Each test owns an isolated DB.
  Run alongside ordinary mocked-browser specs without contaminating their startup/default Demo behavior.
  Set `DOCKSIGHT_BROWSER_ORIGIN` to the exact allocated preview origin and explicitly allow loopback HTTP cookies.
  Cover the existing `changeOrigin: true` proxy with successful configured login and rejected wrong/unset origin.
- Add `test:browser:persistence` to `frontend/package.json` as
  `playwright test --config playwright.persistence.config.ts`. Exclude the dedicated spec from the normal config.

- [ ] Write browser cases for login → question → F5 → same saved answer; F5 during a blocked turn → same turn/model
  call count; lost acceptance response → bootstrap recovers; logout across tabs; own-history isolation; draft/model/
  exact-target restoration; clarification continuation after F5; explicit Stop; pagination past 10; and stale-tab draft
  conflict. Assert no automatic submit/execute on page load or observer reconnection.
- [ ] Write the archived-action browser case using server state that changed after snapshot creation. Confirmation
  waits for the authoritative read, expired/indeterminate states disable execution, and F5 after claimed execution
  reads the existing action instead of sending another mutation.
- [ ] Run `npm --prefix frontend run test:browser:persistence`.
  Expected: real backend/browser recovery cases pass on production preview.
  Also run focused existing workspace, clarification, card-actions, model-selection, and locale browser specs.
- [ ] Run `uv run --project backend pytest backend/tests`, then check fixture usage.
  Expected: no failure or unused fixture.
  Inspect duplicate hints rather than removing fixtures solely because they return equal values.

```sh
uv run --project backend pytest backend/tests --dead-fixtures --dup-fixtures
```

- [ ] Run the risk-based live Docker/local-model checks in the spec. Use labeled unique fixture resources and bounded
  cleanup. Do not run cloud providers. If prerequisites are unavailable, record the omitted check and practical limit.
- [ ] Update changelog, run all-files pre-commit, stage only owned files, and commit
  `test: verify persistent recovery across crashes and reloads`.

### Task 8: Final contracts, diagrams, and feature review

**Files:**

- Modify `docs/architecture.md`, `docs/api.md`, `docs/frontend.md`, `docs/configuration.md`, `README.md`,
  `CONTRIBUTING.md`, `.env.example`, `AGENTS.md`, and `CHANGELOG.md` only where actual behavior requires updates.
- Update named pages in `docs/diagrams/backend.drawio`, corresponding PNG exports, and `docs/diagrams/README.md`.
- Replace documentation screenshots only if changed workflows need them. Keep only referenced English Demo captures.
- Remove this completed plan and its proposal after durable contracts have moved into normal documentation.

**Interfaces:**

- Produce user/operator contracts matching implemented API/schema/CLI flags, cookie deployment scope, local volume,
  backup/migration/reconciliation procedure, history capacity/deletion, and memory-mode limitations.
- Produce synchronized hand-drawn diagram source/previews covering storage ports, task/observer ownership, startup
  recovery, and durable action claim/dispatch/terminal/block/reconciliation transitions.

- [ ] Reconcile normal documentation against actual routes/settings/types. Remove claims that browser refresh resets
  all API sessions, disconnect cancels work, only locale can persist, or backend restart clears action guards.
  Explicitly distinguish first-party cookie recovery from transient separate-origin bearer mode.
- [ ] Edit relevant existing named diagram pages and add a persistence/recovery named page if needed. Export PNGs using
  the command/style in `docs/diagrams/README.md`, inspect every changed preview, and keep exports below 500 KiB.
  Update page IDs/index/links with source and previews in this final implementation commit.
- [ ] Document exact offline reconciliation and stopped-backend backup/restore commands. Check that examples contain no
  real secrets, commands have no RTK wrappers, image volumes retain state, and version is consistently 0.8.0.
  Pin `.env.example` and local instructions to Vite's actual public origin and explicit loopback Secure exception.
  Document the different preview origin rather than assuming proxy Host preservation.
- [ ] Run all backend/frontend required checks and all-files pre-commit after final changes. Reuse passing results
  when no later change affects them. Inspect final diff/staging and review security, crash windows, scope, and docs.
- [ ] Request independent implementation review through the user's chosen execution method, fix actionable findings,
  and repeat affected verification. Do not push or open a PR without separate authorization.
- [ ] Remove completed plans, update changelog, run all-files pre-commit, stage only owned files, and commit
  `docs: document persistent investigations and recovery`.

## Planning self-review

The eight tasks cover every design section. Task 1 owns schema/packaging/locking, Task 2 crash-safe mutations and
reconciliation, Task 3 archive/context/supervision, Task 4 browser auth, Task 5 public lifecycle/wiring, Task 6 UI,
Task 7 owns actual reload/crash boundaries. Task 8 owns durable docs/diagrams. No budget gauge or host editor is added.
Independent review and user plan review precede implementation. Branch authorization is required before any commit.
