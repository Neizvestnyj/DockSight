# Frontend

## Design

The workspace answers: what happened to the container, what supports that conclusion, and what can the operator do?
The selected direction is Framed sheet (seed `196156103`). Data terminal favors monitoring; Achromatic ledger favors
records. Framed sheet gives a diagnostic investigation a clear reading surface, with evidence beside the explanation.

The cold grey frame, IBM Plex Sans, and a container-shaped sight mark identify DockSight. IBM Plex Mono is reserved
for code and identifiers. Color describes runtime state, uncertainty, and operation outcomes. There are no time-series
charts because the backend provides observations rather than history.

The supplied Recraft logo lives in `frontend/public/brand/docksight.svg`. Its viewBox trims the export's empty canvas;
paths, letterforms, and colors remain unchanged. The sidebar and responsive header use the full wordmark. The favicon,
`docksight-mark.svg`, reuses the five symbol paths without the lettering.

The signature is a functional evidence chain: explanation references select a widget and an evidence observation.
The backend returns response-level evidence, without per-sentence citations. The UI must not invent those citations.
The evidence inspector shows the original source kind, host, container, UTC time, and sanitized data.

## Boundaries

React, strict TypeScript, and Vite live in `frontend/`. Runtime-validated transport contracts mirror the backend.
The API client handles authenticated reads, POST SSE, cancellation, and explicit action execution. React owns transient
host-scoped investigations; there is no persisted conversation history. Credentials exist only in browser memory.

Demo is a separate transport with labeled fixtures matching backend contracts. It never contacts Docker. Its scenarios
cover crash loops, OOM, failed dependencies, truncated logs, an unconfirmed SIGKILL, and a running container with zero CPU.
Operation outcomes are selectable under Test error states. Demo observations and operations are simulations.

Action confirmation uses only server-issued IDs and shows the exact host, container ID, operation, and expiry.
One execution keeps one idempotency key. A dropped execution response triggers an action read; it never triggers another
mutation automatically. Indeterminate means the Docker result is unknown and must be checked by the operator.

## Run and verify

Run commands from the repository root with Node.js 24 LTS:

```powershell
rtk proxy npm --prefix frontend ci
rtk proxy npm --prefix frontend run dev
```

The initial workspace is a labeled simulation. `demo-eu` contains six fixture-backed containers; `demo-empty` is an
empty host. Both names identify fictional hosts. The scenario selector chooses an example without a network request.
Test error states explains connection failures, a terminal stream error, and empty inventory. Connection settings apply
to inventory reads and subsequent questions. The action-result selector applies after a separate action confirmation;
existing evidence stays unchanged. These controls are disabled during collection.

Log entries come from the selected fixture. OOM and unconfirmed-exit examples keep empty logs; no control generates
replacement rows. Browser tests exercise 200-line scrolling through mocked API responses.

Choose **Connect API**, use `/api/v1` with the local backend on port 8000, and enter its bearer token. For remote
connections, enter an HTTPS API base ending in `/api/v1` and configure backend CORS for the frontend's origin. Tokens
are not stored in localStorage, sessionStorage, source, URLs, or build environment variables. Reload returns to Demo.

```powershell
rtk proxy npm --prefix frontend run check
rtk proxy npm --prefix frontend test
rtk proxy npm --prefix frontend run build
rtk proxy npm --prefix frontend run preview -- --port 4173
rtk proxy npm --prefix frontend run test:browser
```

Browser tests use installed Chrome and mocked HTTP responses. They do not contact Docker or model providers.
Build first; Playwright starts the production preview or reuses an existing local preview. Set `PLAYWRIGHT_PORT`
to use another port. In CI, Playwright always owns its preview server, rejects focused tests, and produces an HTML report.
The Frontend GitHub Actions workflow uses Node.js 24 and `npm ci`, installs Chrome with its system dependencies,
and retains browser reports, screenshots, and failure traces for seven days.
The production build self-hosts IBM Plex fonts. For deployment, serve `frontend/dist/` and reverse-proxy `/api` to
DockSight, or enter a separately hosted HTTPS API base. Vite's proxy is for local development and preview only.

Keyboard: Tab follows reading order, Enter activates controls, Escape closes dialogs, and Ctrl/Cmd+Enter submits a query.
**Ask DockSight** focuses the composer without covering evidence. Source links move focus to the selected observation.

The workspace breadcrumb opens configured-host selection, including on mobile. Closing it or choosing the current
host preserves the investigation, draft, and prepared actions. Choosing another host starts a separate session.

In API mode, inventory refreshes 10 seconds after the previous request settles. Polling pauses while the page is hidden
or offline; returning to a visible online page or focusing it triggers a read. Failed reads back off to 20, 40, and at
most 60 seconds, returning to 10 seconds after success. Requests do not overlap. Demo remains manual.

Inventory refresh keeps the last received rows visible, including after failure. Manual refresh announces loading and
acknowledges success with a check for two seconds. Refresh icons rotate during manual and background requests without
replacing existing rows with loading placeholders; reduced-motion preferences disable rotation. The receipt timestamp
records browser receipt, not a Docker observation, and changes only on success. Errors mark the retained list as stale
and offer a manual retry. Refresh preserves selection by exact container ID, keyboard focus, and investigation state.
Diagnostic cards and prepared actions retain their original observations until a new diagnosis is run.

## Container reads

Selecting a container opens its read-only overview without calling the model or preparing actions. The client requests
the exact container snapshot, `/stats`, and `/logs?lines=200` independently. The snapshot includes the allowlisted
environment. No direct restart or stop controls are exposed here.

In API mode, the visible overview refreshes inspect with the inventory polling interval and pause/backoff rules.
Logs and metrics remain manual. Returning to the investigation cancels overview requests and polling; reopening the
overview rereads its sources. **Refresh data** manually rereads all sources. A failed source retains its last successful
values and timestamp while other sources remain usable. State and environment show the server's `observed_at`. Metrics
and log batches have no server observation timestamp, so their footers show browser receipt time as **Received**. Log
entries retain their individual Docker timestamps. These separate requests are not an atomic snapshot.

An exact inspect returning `container_not_found` with HTTP 404 marks the selected container as removed and stops its
automatic reads. Retained observations stay labeled; diagnosis is disabled until a successful explicit read. A new
container with the same name never replaces the selected ID. Absence from the bounded inventory alone does not prove
deletion. Other inspect failures also disable diagnosis until a successful read.

**Diagnose** starts a new model session with the selected host and exact container ID in the question. It retains prior
answers in this tab; follow-up questions use the new session. Returning to the investigation preserves its draft,
evidence, prepared action IDs, and execution keys. Direct refresh never replaces diagnostic card data. Host or connection
changes cancel outstanding reads and discard the previous workspace.

## Diagnostic trace

Each diagnostic turn has a collapsed **Diagnostic trace** disclosure with public model identity, request/turn IDs,
recorded steps, measured duration, and optional provider usage. Selecting a step shows its safe failure details or
sanitized final proposal before card assembly. Desktop keeps the step list beside its details. Tablet and mobile open
one pane at a time; **Back to steps** restores keyboard focus to the selected step.

Step updates replace their original row by ID and stay attached to that turn. Failed, stopped, and disconnected turns
retain received steps. An unfinished step is labeled interrupted after the stream ends; its completion and duration are
not invented. Previous turns and older servers without trace events remain usable and show **Not recorded**.

**Copy trace** copies only the public trace and its scope/identifiers, excluding the operator query, action execution
keys, and credentials. Text is rendered verbatim without HTML or Markdown interpretation. Invalid/oversized proposal
bodies are withheld, clipped previews are marked, and missing token usage differs from zero. Traces stay in browser
memory with the current tab's investigation; changing language preserves them. Demo trace steps are explicitly simulated
and make no API or model request. Inventory polling never replaces historical trace data.

## System status

The top-bar status control opens independent API/authentication, Docker, provider, and model results. Checks run after
connection and host discovery, on host changes, and through **Check again**. API mode repeats checks 60 seconds after
settlement while the page is visible and online. Opening the panel or returning to the page rechecks results at least
30 seconds old. Recent foreground events preserve the next scheduled check. Requests do not overlap; a manual request
during a pending check queues one follow-up. Demo remains manual.

Transport failures and confirmed unavailable dependencies increase the interval to 120, 240, and at most 300 seconds.
Healthy or unchecked dependencies restore the 60-second interval. HTTP 401/403 stops automatic attempts until an explicit
manual retry or a connection change; a failed manual retry keeps automatic attempts stopped. A successful authorized
response resumes polling even if a dependency still needs recovery. The panel describes normal polling, backoff, or
stopped checks. Rechecks keep previous dependency values and timestamps until the new result arrives. Failed API checks
retain previous dependency results with an explicit stale notice; successful checks replace the result for that host only.

The client derives API authorization and connection failures from HTTP/transport outcomes. Dependency timestamps come
from the server; the API row records browser receipt or failure time. Unsupported status APIs and metadata checks stay
`not_checked`. A confirmed unavailable dependency disables new diagnosis submissions, including keyboard submit and retry;
it does not discard drafts, past cards, action IDs, or execution keys. Unchecked models remain usable for explicit diagnosis.
Provider/model failures do not block direct Docker reads. Docker failures explain why diagnosis cannot collect evidence.

The panel exposes only the server-selected provider and model. Metadata availability does not verify generation, tools,
or structured output. Those require an explicit diagnostic request. Demo results are labeled simulations and never contact
any dependency. Provider selection remains server configuration.

## Language

The language control beside Ask DockSight offers System, English, and Русский. System resolves the first supported
language from `navigator.languages`, falling back to English; it follows browser `languagechange` events. Browsers
provide language preferences rather than direct access to operating-system settings.

Only the preference is stored under `docksight.locale` in localStorage. Invalid preferences or unavailable storage
fall back to System; a manual selection still works in memory if storage is blocked. The root document language and
tab title follow the selected locale. Switching preserves connections, host sessions, questions, drafts, evidence,
server-issued action IDs, and execution keys.

Typed UI copy, status labels, accessibility names, counts, and numeric formatting are localized. Raw API/model text,
container/image/host identities, log messages and timestamps, environment keys/values, and observation JSON remain
verbatim. Authored demo questions and explanations have English/Russian translations; operator-entered questions stay
verbatim. Example provenance allows language changes without replacing observations or prepared actions. A real API
explanation stays verbatim even when it exactly matches a built-in demo narrative. Self-hosted Latin/Cyrillic font
subsets use distinct unicode ranges. Code, comments, documentation, and transport contracts remain in English.

## Limitations

All initial example names, images, log messages, and observations in `frontend/src/demo.ts` are simulated; fixture state
comes from `backend/tests/fixtures/diagnostics.json`. They remain confined to Demo and are not production configuration.
The app has no conversation-list API, durable history, metric history, environment editing, or stack deployment.
Tool progress records events actually received; streams never reconnect automatically. A running action can be checked
manually. A confirmed execution may be retried with its original key only after reading that the action is still prepared.
Diagnostic observations retain their original timestamps after an operation. Refresh the container overview for current
facts, or start a new diagnosis for an explanation and fresh action proposals.
