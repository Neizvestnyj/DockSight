# Persistent investigations

Status: proposed engineering design for independent review. No implementation is authorized by this document.

## Scope

Deliver one feature PR with SQLite persistence, useful saved investigations, browser session recovery, and durable
action protection. PostgreSQL and Oracle are possible later adapters. They are not part of this implementation.

- Save sanitized questions, validated answers/cards/evidence with original UTC timestamps, and host/model identities.
- Show the latest 10 investigations belonging to the authenticated actor. Older investigations remain available.
- Restore the actor's last active investigation, draft, and configured selections. Reopen and continue saved chats.
- Keep running diagnostics alive across browser refresh and observer disconnect. Explicit Stop cancels diagnostics.
- Preserve execution claims, idempotency, audit, and indeterminate target blocks across backend restart.
- Keep bearer API/CLI access. Use an opaque persisted browser session for first-party browser login.
- Keep Demo separate and visibly labeled. Do not add a context-budget gauge, host editor, new roles, or cloud service.

Python 3.12 is the minimum. Develop with Python 3.14. Keep strict types, bounded contracts, English documentation and
runtime messages, localized UI copy, and a 120-character prose limit. Domain code remains standard-library-only.

All numeric limits and deployment choices below are proposed engineering defaults, not additional user requirements.

## Existing seams

`bootstrap.py` currently wires `MemorySessions`, `MemoryActions`, and `JsonAudit`. `SessionStore.lease` exposes mutable
model history. `ActionStore.get/claim` expose mutable `PreparedAction` objects. `Actions._run` calls `finish` without
saving. Replacing only these adapters would lose updates.

`main._authorize` accepts bearer headers, while the router independently requires `HTTPBearer`. Both must change.
`EventResponse` closes its source on disconnect, which currently closes diagnostic work. `useInvestigation` and `App`
keep turns, session IDs, drafts, models, and connection state only in React memory.

These findings use graph discovery plus direct current-source reads. Coverage reported `metadata_changed`, so the graph
was not treated as current-source proof.

## Storage and deployment

Use SQLAlchemy 2 ORM and Alembic. Mapped rows, engines, SQL, migrations, and transactions belong exclusively to
`adapters/outbound/persistence/`. Application-owned protocols return owned values or detached domain objects.
Do not introduce a generic repository framework, event bus, or database-wide unit-of-work API into the core.

Use Python's synchronous `sqlite3` driver through one dedicated database worker thread and one connection. A private
adapter runner offloads complete, short transactions. No ORM session or lazy-loaded object crosses the thread boundary.
Admit at most 32 pending operations, with a two-second admission timeout and a two-second SQLite busy timeout.
Accepted writes are awaited through cancellation until their transaction finishes. Never interpret cancellation as
proof that a write did not commit. A stalled filesystem cannot be given a false hard completion guarantee.

Use explicit modern transaction control (`autocommit=False`), foreign keys, rollback journal mode `DELETE`, and
`synchronous=FULL`. Serialize reads and writes for this MVP. WAL is unnecessary with one connection, and would add
checkpoint/backup constraints. Do not hold a transaction across Docker, provider, catalog, or network calls.
SQLAlchemy documents Python 3.12+ transaction configuration in its
[SQLite dialect reference](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html#transactions-with-sqlite-and-the-sqlite3-driver).

| Setting | Default | Contract |
|---------|---------|----------|
| `DOCKSIGHT_STATE_BACKEND` | `sqlite` | `memory` is explicit test/development mode with weaker restart guarantees |
| `DOCKSIGHT_STATE_PATH` | `.docksight/state.sqlite3` | Resolve relative to process working directory, then canonicalize |
| `DOCKSIGHT_BROWSER_ORIGIN` | Unset | Exact public browser origin when reverse-proxied, otherwise request origin |
| `DOCKSIGHT_COOKIE_SECURE` | `true` | `false` is accepted only for explicit loopback HTTP development |
| `DOCKSIGHT_BROWSER_SESSION_TTL` | `28800` seconds | Absolute browser session lifetime |
| `DOCKSIGHT_BROWSER_SESSION_IDLE_TTL` | `3600` seconds | Idle lifetime, capped by absolute expiry |

Use a cross-platform OS lock through `portalocker` on a sidecar beside the canonical database path. Hold its file handle
for the entire backend lifetime. A second backend worker, migration command, or reconciliation command must fail before
changing the database. The lock is released by process exit, never by a time-based lease. Support one process/worker on
a local filesystem. Network filesystems, shared multi-host volumes, and multiple database writers are unsupported.

Startup order is: validate configuration, acquire the process lock, open/check the database, apply packaged Alembic
upgrades, validate supported snapshot versions, recover abandoned work and revoke obsolete sessions in a transaction,
construct application services, then expose readiness. Refuse unknown newer schema revisions and failed migrations.
Never delete a database or silently fall back to memory. A migration failure leaves the process unready and exits.
Production upgrades require a stopped-process backup and use forward migrations. No automatic downgrade is provided.
Keep `STATE_TTL` and `MAX_SESSIONS` for explicit memory mode. They must not expire or evict persisted investigations.

Separate database ownership/opening from server initialization. `open_existing` acquires the lock and validates the
requested maintenance mode without running migrations, application recovery, session cleanup, or normal server wiring.
`status` is read-only and reports recovery-required instead of changing an unclean database. `backup` copies the main
file and any rollback journal under the lock before opening SQLite. It can validate a copied backup, never recover the
source first. `migrate` runs only its requested Alembic upgrade. `reconcile` opens a supported schema and performs only
its authorized reconciliation transaction. It does not start models, a turn runner, or normal startup recovery.

The backend image uses `/var/lib/docksight/state.sqlite3`. Create its parent directory for UID 10001 and mount the whole
directory as a durable named volume or bind mount. Do not mount only the database file. Ignore `.docksight/` in Git.
The packaged wheel and image must include Alembic scripts. Back up with the backend stopped and its exclusive lock
held by the backup command. Document restore permissions and the fact that this unencrypted database contains
sanitized operational history. SQLite journaling details are documented in the
[SQLite atomic commit reference](https://www.sqlite.org/atomiccommit.html).

Vite currently uses `changeOrigin: true`, so its backend Host differs from the browser Origin. Local cookie setup must
set `DOCKSIGHT_BROWSER_ORIGIN=http://127.0.0.1:5173` for development or `http://127.0.0.1:4173` for preview.
Set the explicit loopback `DOCKSIGHT_COOKIE_SECURE=false`. Use the actual origin if ports/hostnames differ.
The persistent browser fixture sets its allocated preview origin explicitly. An unset/wrong origin must fail
login/CSRF clearly, not bypass it.

After an unexpected storage/commit failure, mark storage unhealthy, stop accepting new diagnostic and mutation work,
and return `storage_unavailable`. Do not report an unsaved result as success. Reads can remain available only when
their storage operation succeeds. Keep action guards until startup recovery or explicit reconciliation resolves them.

## Persisted records and compatibility

| Record | Owned data and constraints |
|--------|----------------------------|
| `investigations` | UUID, actor, configured host ID, bounded title, created/updated UTC, workspace revision, draft, selected target/container/view, active turn ID, bounded model-context JSON |
| `turns` | UUID, investigation/actor/host, actor-unique submission UUID and normalized input digest, initial HTTP request ID, model identity, query, explicit target, clarification links, state, revision, timestamps, bounded public snapshot |
| `submission_receipts` | Unique `(actor, submission_id)`, logical input digest, turn/investigation IDs, accepted UTC, optional archive-deleted UTC, no question or answer content |
| `active_turn_scopes` | Unique `(actor, host)` and unique turn ID, held while a turn is running |
| `actor_workspaces` | Actor key, revision, last investigation ID, configured host ID, configured provider/model selection |
| `browser_sessions` | Session-token SHA-256 hash, actor, configured credential fingerprint, created/last-seen/absolute-expiry UTC, revocation UTC |
| `prepared_actions` | Domain action fields, idempotency key, revision, claim/dispatch timestamps and phase, terminal outcome |
| `target_guards` | Unique `(host, full_container_id)`, active action ID, blocked action ID, revision |
| `action_audit` | Append-only bounded event fields, UTC, actor, request/turn/action IDs where applicable, target, outcome, reconciliation reason |

Use relational keys and uniqueness for ownership and concurrency. Actions/audit/guards must not cascade-delete with
investigations or turns. Retain original correlation IDs in audit after a chat is deleted.
Store bounded versioned public snapshots as JSON,
not provider SDK/native messages. Serialize aware UTC consistently and restore aware values on every adapter read.
Snapshot envelope version starts at 1, independently of database revision and nested `DiagnosisResponse.schema_version`.
Validate writes and reads through application-owned Pydantic contracts with unexpected fields forbidden.
Keep a version dispatcher for stored envelopes. Future changes must migrate an old version or retain a supported reader.
An unsupported/corrupt row returns `history_unsupported` for that item. It cannot execute an action or enter a prompt.
Startup rejects a newer database revision before writes. Do not silently discard an unreadable archive.

Persist questions and drafts after existing redaction, including configured API/provider secrets. Persist validated,
sanitized public answers and allowlisted evidence. No raw inspect payload, prompt, provider-native replay data, model
reasoning, authentication header, cookie, or raw bearer/provider token enters the database or logs.
Persist trace IDs, operation names, timing, usage, safe codes, and schema issue paths. Force trace `response=null` and
`response_truncated=false` in persistent snapshots. Existing sanitized live previews may remain transient in the current
observer, but restored traces explain that output previews were not retained.

## Saved history and model context

The display archive and the model context are different records. Keep all accepted turns, including clarification,
failure, cancellation, and restart interruption, in the display archive. Derive the title from the first sanitized
question, at most 120 characters. Do not call a model to name chats.

Keep only the latest 10 completed question/validated-summary pairs in model context, with a total 32,000-character
limit. Remove whole oldest pairs until both limits hold. Reconstruct plain `ModelMessage` values without native data.
Only successful answers append context. Clarification attempts and failed/stopped turns do not append it.
Keep the existing historical-context labeling. Never load the full archive, stored cards, stale action permissions,
trace previews, or old evidence wholesale into the next prompt. Every continued turn collects fresh Docker evidence.
The deadline and existing model/tool budgets apply once per accepted turn, regardless of observers.

### Acceptance and execution

1. Create an investigation with a browser-generated UUID and a configured host. Duplicate creation for the same actor
   and host returns the existing investigation. Reuse for different input conflicts.
2. After authentication/transport validation, create a lifespan-owned admission task before any acceptance write.
   It owns lookup, validation, commit, and diagnostic-task registration. Shield the HTTP await from cancellation and
   retain a strong task reference. Browser/HTTP cancellation cannot interrupt the commit-to-registration handoff.
3. Compute the digest from canonical JSON of immutable logical submitted fields: investigation ID, trimmed question
   for a question submission, exact submitted target, requested model selection including null, and clarification parent
   ID when present. A clarification submits no replacement question. Exclude expected workspace/parent revisions,
   HTTP/request/turn IDs, timestamps, and resolved server defaults. Compute before redaction/config resolution and
   persist only its SHA-256 digest. Never persist/log the unhashed canonical input if it contains secrets.
4. Look up `(actor, submission_id)` first. An identical receipt returns the original turn without checking current
   workspace/parent revisions, configured models/hosts, catalog availability, capacity, or active scope. Different
   logical input conflicts. A receipt for explicitly deleted content returns `history_deleted`, never new work.
5. For a new submission, validate current configuration/catalog and then atomically recheck receipt ownership/digest
   before all mutable admission checks. Save receipt, turn/request IDs, query, selection, quota reservation, active
   actor/host scope, matching draft clear, and last active together. On a validation error, recheck the receipt once
   before returning the error so a concurrently committed identical submission still wins. A busy scope is `turn_busy`.
6. Commit before model/runtime work. The same retained admission task immediately registers exactly one diagnostic
   task with the supervisor. Task-creation failure records a failed turn and releases reservations. If that write
   fails, storage admission closes and the persisted scope remains protected for restart recovery. Never detach an
   unowned running row. A process crash after commit is recovered as interrupted, never automatically retried.
7. Persist each bounded progress/trace update before notifying observers. Buffer the final answer/clarification event
   until the terminal transaction saves the validated result, context update, timestamps, and lease release together.
   Only then publish completion. Never emit a success result that was not committed.

Turn states are `running`, `completed`, `awaiting_selection`, `failed`, `stopped`, and `interrupted`.
A terminal transition uses compare-and-swap on revision and can happen once. Stop and completion share that boundary.
Stop requests cancellation of the owned task and awaits cleanup before recording `stopped` and releasing its scope.
An already completed turn remains completed. Observer cancellation only detaches the observer.

On controlled shutdown, stop accepting submissions, allow diagnostics up to five seconds to finish, cancel the rest,
record them interrupted, then drain action workflows according to their existing deadlines before closing adapters.
Admission tasks are part of that drain and must finish registration or record rejection before database close.
On startup, abandoned running turns become `interrupted` and active trace steps remain unfinished with no invented
duration. Clear their active scope rows in the same recovery transaction. Never auto-resume a model call.

### Clarification

Persist the candidate set and original question in the parent turn. A continuation submits a new submission UUID,
`clarification_of`, the parent's current revision, and one exact candidate identity. The server verifies actor, host,
awaiting-selection state, and membership, then atomically records `resolved_by_turn_id` and accepts one child attempt.
The child inherits the original sanitized question. It revalidates the target with fresh Docker reads and fails safely
if the resource disappeared. It cannot fall back to a different resource. The UI groups the attempts under one question
while preserving each trace and selected identity. Duplicate/lost continuation responses cannot run another attempt.

## Browser authentication

The supported persistent-login deployment is first-party/same-origin: static frontend plus `/api` reverse proxy,
including Vite's local proxy. Probe `/api/v1/auth/session` before choosing API, signed-out, or Demo mode on page load.
A valid cookie restores API mode and the server workspace. A 401 shows signed-out connection controls with explicit
Demo entry. Network/bootstrap failures offer retry and do not silently show fictional data as a recovered API session.

The connection dialog keeps separate-origin HTTPS API bases usable through existing in-memory bearer mode.
That mode is explicitly transient and requires reconnecting after refresh. It does not promise third-party cookies or
persist a remote endpoint/token. The persistent-cookie login endpoint rejects foreign browser origins even if a bearer
API origin is allowed by CORS. Do not add `SameSite=None` as a workaround.

- `POST /auth/login` uses the supplied bearer header once, never a token in the URL. Validate exact browser Origin and
  JSON content type. Rotate/revoke any previous presented browser session and issue 32 random bytes as a new cookie.
- Store only the cookie token's SHA-256 hash. Bind its actor to a SHA-256 fingerprint of actor, a null separator, and
  the current configured bearer token. Never persist the raw credential used to compute it.
  Authenticate against current configured actors/fingerprints on each request. Token rotation/removal invalidates old
  sessions immediately after configuration reload/restart. Historical data stays owned by the stable actor name.
- Cookie: `docksight_session`, host-only, `Path=/api/v1`, `HttpOnly`, `Secure`, `SameSite=Lax`, `Max-Age=28800`.
  No Domain attribute. The loopback-only development exception must be explicit. Do not infer HTTPS from untrusted
  forwarded headers. Document trusted proxy configuration.
- Expire server sessions after eight hours absolute or one hour idle. Coalesce last-seen writes to once per minute.
  Browser expiry never extends absolute server expiry. Return no-store responses and redact cookie/header logging.
- `GET /auth/session` returns actor, expiry, and a session-bound CSRF value: base64url HMAC-SHA256 using the decoded
  cookie token as key and the literal `docksight-csrf-v1` as message.
  Keep that value only in JavaScript memory. Do not store the raw cookie or CSRF value in browser storage or the DB.
- Cookie-authenticated unsafe methods require JSON, exact configured/same-origin Origin, and `X-CSRF-Token`, verified
  in constant time. Reject missing/null/foreign Origin. Reject cross-site Fetch Metadata when present. Login has no
  cookie authority and requires its bearer plus the same Origin checks. GET endpoints do not mutate runtime state.
- `POST /auth/logout` requires cookie CSRF, revokes that session, and expires its cookie. It leaves saved history and
  already accepted work intact. Logging out in one tab causes the shared cookie's other tabs to become signed out.
- An explicit Authorization header takes precedence. Invalid/unsupported bearer credentials fail with 401 and never
  fall back to a cookie. Valid bearer calls do not require CSRF, but browser Origin allowlisting still applies.

Replace the router's mandatory `HTTPBearer()` dependency with the shared authenticated-principal dependency and
describe bearer/cookie alternatives in OpenAPI. Align middleware exemptions for login/bootstrap, actor assignment,
origin checks, and no-store headers. Keep CORS outermost so allowed preflights/errors receive correct headers.
List exact origins/methods/headers. Never use wildcard origins with credentials. Persistent cookie mode uses same-origin
requests with `credentials: same-origin`. Bearer split-origin requests use `credentials: omit`.
The [FastAPI CORS reference](https://fastapi.tiangolo.com/tutorial/cors/) documents explicit credentialed allowlists.
The [OWASP session guidance](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html) and
[CSRF guidance](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)
support separate cookie confidentiality, lifetime, origin, and CSRF protections. HttpOnly alone does not prevent CSRF.

## API and browser recovery

All new history/session endpoints use `Cache-Control: no-store`. Actor identity comes only from authentication.
Foreign investigation/turn/action IDs return the same not-found result as missing IDs.

| Method and path under `/api/v1` | Result |
|--------------------------------|--------|
| `POST /auth/login`, `GET /auth/session`, `POST /auth/logout` | Browser session lifecycle |
| `GET /me/workspace`, `PATCH /me/workspace` | Revisioned actor preferences and last active investigation |
| `POST /investigations` | Idempotent UUID-based creation |
| `GET /investigations?limit=10&before=CURSOR` | Actor-owned summaries, newest activity first |
| `GET /investigations/{id}` | Metadata/workspace plus newest turn page and active turn ID |
| `GET /investigations/{id}/turns?limit=20&before=CURSOR` | Older immutable turn pages |
| `PATCH /investigations/{id}/workspace` | Revisioned draft, target, selected container, and view |
| `DELETE /investigations/{id}` | Explicit owned archive deletion, conflict while a turn runs |
| `POST /investigations/{id}/turns` | 202 with the accepted/existing turn snapshot |
| `GET /turns/{id}` | Authoritative revisioned public snapshot, safe to repeat |
| `GET /turns/{id}/events` | Live observation beginning with the latest snapshot, no model work |
| `POST /turns/{id}/cancel` | Explicit idempotent diagnostic Stop |

Use opaque bounded keyset cursors with `(updated_at, id)` ordering and actor scope. Validate cursors against their
query/actor. Initial list size is 10, maximum list page is 50. Turn pages are 20, maximum 50, returned in display order.
Refreshing pagination may change activity ordering. Deduplicate IDs client-side without skipping older stable pages.

The new observer SSE emits versioned `turn.snapshot` frames with the full latest public turn snapshot and monotonically
increasing revision. Send an initial snapshot, updates after committed changes, ten-second heartbeats, and close after
a terminal snapshot. Intermediate revisions can coalesce. This is state recovery, not replay of every original event.
Bound observer count to four per turn. An HTTP observer revalidates its browser session at updates/heartbeats and closes
independently when that session is revoked/expired. This authorization check does not belong in the turn runner.

The existing bearer `POST /chat/turns` remains a compatible event stream over the same supervisor. Its `session_id`
becomes the investigation ID. Add optional `submission_id` for duplicate protection. Old callers without it create one
accepted turn per explicit POST. Disconnect detaches even on this route. Existing event names/answer schemas remain.
Persist acceptance before response streaming, and use the stored initial request ID in turn history. Observer HTTP
requests have their own request IDs. Do not overwrite the originating one on reconnect.

The browser posts once, then observes the accepted turn. On F5, bootstrap loads last active history and GETs the same
active turn. A dropped observer retries read/observation with bounded backoff of 1, 2, 4, 8, then 10 seconds while
visible/online. It never repeats a submit automatically. HTTP 401/403 stops reconnect attempts until authentication.
Unmounting, changing chats/hosts, or entering Demo detaches observation without sending Stop.

### Concurrent tabs and selections

Actor workspace and investigation workspace each have independent integer revisions. PATCH requires
`expected_revision`. Reject stale writes with `workspace_conflict` and the current safe snapshot. Debounce draft saves
by 300 ms. Serialize local writes, preserve dirty local text on conflict, and offer explicit reload/use-this-draft.
Submission includes the current investigation workspace revision, so a stale tab cannot clear another tab's new draft.
Expose saving/unsaved status. F5 restores the last acknowledged draft. Do not promise unsent keystrokes survive a crash.

Restore last-active only at bootstrap. Another tab changing it must not navigate the current tab. Refresh open history
on focus and after successful submissions/deletions. Per-tab generation guards reject late host/chat responses.
Save model preference only after validation against current server-owned choices. Missing configured hosts/providers
leave archived history readable and disable continuation until a valid configured choice is made. Never substitute
another host for the saved investigation. Container removal keeps its exact historical identity and requires fresh
inspect before current reads/diagnosis. Do not restore selections by container name.

On reopening an archived action card, fetch `/actions/{id}` before enabling confirmation. Loading an archive never
prepares or executes a replacement. Show expired/missing/foreign/blocked actions as unavailable. `GET action` calculates
current expiry. Confirmation displays current server target/operation/expiry and must be renewed after reopening.
Never restore an open confirmation dialog or queued mutation. If an execution was already claimed, read its stored
state without sending another mutation. Keep the original per-execution idempotency key during a live attempt.

## Durable action lifecycle

Keep `PreparedAction.claim`, expiry, and legal `finish` transitions in the domain. Stores hydrate detached copies.
Replace implicit shared-object saves with explicit compare-and-swap operations:

- `claim(...) -> ActionClaim`: atomically domain-validate, reserve the target guard, save `running/claimed`, key and
  revision, and append `action.claimed` audit. The same key returns the retained outcome even after restart.
- `mark_dispatch(action_id, expected_revision, now) -> StoredAction`: save `dispatching` and audit before Docker send.
- `complete(action_id, expected_revision, outcome, now) -> StoredAction`: domain-validate the terminal transition and
  atomically save outcome/audit, release the active guard, and keep an indeterminate target block when required.
- `get(..., now)` expires an unclaimed prepared action durably. `add` saves preparation/audit together.

Authoritative audit belongs in the same database transaction as state and target guards. `JsonAudit` becomes a sanitized
best-effort mirror after commit. Logger failure cannot undo durable audit or authorize an unrecorded command.
No Docker command starts if claim, revalidation, dispatch marker, or audit persistence fails.

`Actions.execute` registers a lifespan-owned admission task before calling `claim`. That tracked task owns the claim
transaction and immediate registration of the shielded execution workflow. The HTTP caller awaits it through a shield.
A cancelled caller cannot leave a committed `claimed` action without an owner in the live process. Registration failure
completes it failed-before-dispatch and releases the guard atomically. Persistence failure closes admission and retains
the guard for recovery. Shutdown drains both admission and execution registries before closing storage.

| Crash/failure window | Recovery |
|----------------------|----------|
| Before claim commit | No accepted execution or Docker command |
| After claim, before dispatch marker | Mark failed/interrupted-before-dispatch, audit, release guard |
| After dispatch marker, before sending | Mark indeterminate and block, although Docker may never have received it |
| During Docker call, or after Docker returns before terminal commit | Mark indeterminate and block |
| After terminal commit, before HTTP delivery | Return stored outcome on GET/same-key request |

Revalidate the full container fingerprint after claim and before the dispatch marker, without a DB transaction held.
The persisted guard excludes other mutations for that host/full ID. A timeout after dispatch is indeterminate even if
the SDK thread later returns. Track the SDK task until it settles and never rewrite the declared outcome automatically.
A persistence failure after dispatch returns storage failure, trips mutation admission closed, and preserves the guard.
No design here provides exactly-once execution across Docker and SQLite. Conservative false uncertainty is intentional.

On startup, recover every claimed/dispatching action with the above rules and append audit atomically before readiness.
Prepared expiry, process restart, chat deletion, token removal, and action retention never clear indeterminate guards.
Keep claimed actions, their idempotency keys, and audit indefinitely by default. `MAX_ACTIONS` limits live/unclaimed
preparations, not deletion of execution protection. Unclaimed expired preparations may be removed after 24 hours.

### Operator reconciliation

Provide an offline, OS-operator-only `python -m docksight.state_cli reconcile` command. There is no browser/admin HTTP
unblock endpoint and no new actor role. The command requires the backend stopped and acquires the same exclusive lock.
It uses the normal application reconciliation use case and configured host reader, never direct ad-hoc SQL updates.

1. Inspect the blocked action/target and fresh Docker state. Show revision, exact identity, observed UTC, and all
   unresolved actions. Missing Docker access does not permit unblocking. Verified target removal is an allowed result.
2. The operator independently verifies that the old process and any Docker operation have settled. A current running
   snapshot alone is not proof that a timed-out restart never ran. Keep the old action `indeterminate`.
3. Require explicit `--action-id`, `--expected-revision`, `--confirm-target HOST/FULL_ID`, `--actor CONFIGURED_ACTOR`,
   bounded `--reason`, and `--acknowledge-unknown-outcome`. Audit the actual OS operator identity and configured actor
   label. Reread Docker and validate the unchanged guard revision.
4. Atomically append reconciliation audit, invalidate remaining prepared actions for the exact target, mark the guard
   reconciled, and clear its block. Reconciliation never resends Docker. A later mutation needs a newly prepared action
   and ordinary explicit confirmation. A failed audit/commit leaves the target blocked.

Expose status/backup/migrate maintenance commands through the same lock owner. Document exact safe commands after the
implementation establishes their argument parser. Never recommend restarting, deleting the DB, or editing rows to
unblock.

## Capacity and deletion

Default limits are 500 investigations per actor, 200 accepted turns per investigation, 32 MiB per investigation,
256 MiB per actor, and 2 MiB per serialized public turn snapshot. Reserve a turn's maximum storage allowance during
acceptance, then release unused allowance on completion. Include UTF-8 JSON size and trace/progress in accounting.
Cap progress entries at 100 and trace steps at 133. Truncation is explicit for progress only. An oversized validated
answer fails with `history_capacity` before publication, rather than saving a success with missing evidence.

No automatic age-based deletion of chats is enabled. Capacity rejects new work with a clear code and preserves existing
history. The UI offers explicit deletion of an owned inactive chat. Delete its turns/context/workspace, then choose the
next owned last-active chat atomically. Do not delete actions, action audit, idempotency, or target guards.
Keep content-free submission receipts as deletion tombstones so stale requests cannot recreate deleted work.
Expired/revoked browser sessions are cleaned in batches of at most 100. Disk-full/storage errors fail closed.

## Verification and delivery

Use common memory/SQLite port contracts where guarantees match. Document that memory mode loses everything on restart.
Use real temporary SQLite files and separate processes for lock, commit, crash, migration, and recovery tests.
Mock automated provider HTTP. Browser F5 tests must exercise a real local backend with SQLite and deterministic fake
model/runtime ports, not only mocked history endpoints. Cover login, logout, actor isolation, drafts, clarification,
lost acceptance, active-turn reload, Stop, archived action refresh, and two tabs with stale drafts.
Include barriers that cancel the HTTP task after a commit but before work registration for both diagnosis acceptance
and action claim. Assert that the live process reaches one owned terminal workflow without needing a restart.

Risk-based live checks use uniquely labeled Docker fixtures: confirmed restart, lost response, retained idempotency,
and a controlled crash window that preserves an indeterminate block. Run one local-model continuation with fresh
evidence and an in-flight browser refresh. Do not run a cloud model without supplied credentials and explicit approval.
Record unavailable live checks and their reason in the final implementation report.

Target feature version is 0.8.0. Align changelog, `backend/pyproject.toml`, and `backend/uv.lock`. Keep one feature PR,
local commits, and the current branch until the user authorizes a feature branch. Before each implementation commit,
run the required all-files hooks without bypassing guards and stage only task-owned files.

The final implementation commit updates normal architecture/API/frontend/configuration documentation and the relevant
named pages in `docs/diagrams/backend.drawio`, including diagnostic ownership/recovery and durable action transitions.
Add a named persistence/recovery page if needed. Re-export corresponding PNGs in the shared hand-drawn style and update
diagram links/index together. Update stale UI/help and AGENTS frontend lifetime rules. Remove the completed plan and
this proposal after moving durable contracts into normal documentation. No diagram edit is part of planning-only work.
