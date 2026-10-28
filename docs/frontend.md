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

Inventory refresh keeps the last received rows visible during the request. The sidebar announces loading, acknowledges
success with a check for two seconds, and retains its receipt timestamp. This timestamp records browser receipt, not a
Docker observation. Refresh failures retain the previous list and offer a manual retry. Diagnostic cards remain
historical observations until a new diagnosis is run.

## Container reads

Selecting a container opens its read-only overview without calling the model or preparing actions. The client requests
the exact container snapshot, `/stats`, and `/logs?lines=200` independently. The snapshot includes the allowlisted
environment. No direct restart or stop controls are exposed here.

**Refresh data** manually rereads these sources; no polling runs. A failed source retains its last successful values and
timestamp while other sources remain usable. State and environment show the server's `observed_at`. Metrics and log
batches have no server observation timestamp, so their footers show browser receipt time as **Received**. Log entries
retain their individual Docker timestamps. These separate requests are not an atomic snapshot.

**Diagnose** starts a new model session with the selected host and exact container ID in the question. It retains prior
answers in this tab; follow-up questions use the new session. Returning to the investigation preserves its draft,
evidence, prepared action IDs, and execution keys. Direct refresh never replaces diagnostic card data. Host or connection
changes cancel outstanding reads and discard the previous workspace.

## System status

The top-bar status control opens independent API/authentication, Docker, provider, and model results. Checks run after
connection and host discovery, on host changes, and through **Check again**. There is no background polling or automatic
retry. Rechecks keep the previous dependency values and timestamps until the new result arrives. Failed API checks retain
previous dependency results with an explicit stale notice; successful checks replace the result for that host only.

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
