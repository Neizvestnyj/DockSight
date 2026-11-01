# Frontend

Container process state and healthcheck results remain separate in inventory, current facts, diagnostic cards, and
Compose member rows. Missing or null health is displayed as not reported, including responses from older servers.
Running counts continue to describe processes; they do not imply successful healthchecks.
Russian health badges use compact labels; their tooltip identifies the Docker healthcheck.
Diagnostic card headers show process state only. Healthchecks have a separate fact row; stopped processes show
**Last healthcheck** to distinguish the retained result from an active check. Compact lists label health separately.
An exited process has a neutral status; a nonzero exit code is highlighted in the container facts and inventory.

See the [quick start](../README.md#quick-start) to run the client,
[usage examples](examples.md) for an investigation, and [deployment](configuration.md#frontend-deployment)
for static hosting and reverse proxy setup.

## Boundaries

React, strict TypeScript, and Vite live in `frontend/`. Runtime-validated transport contracts mirror the backend.
The API client handles authenticated reads, POST SSE, cancellation, and explicit action execution.
Credentials exist only in browser memory. Investigations are scoped to one configured host and the current tab.

Demo is a separate, labeled transport with fictional hosts and fixtures matching backend contracts. It never contacts
Docker or a model. Scenario and error controls are disabled during collection. Fixture logs remain unchanged; browser
tests exercise longer log scrolling through mocked API responses. See [contributor checks](../CONTRIBUTING.md#checks).

## Interface and evidence

The workspace keeps model explanations separate from Docker observations. Explanation links select a widget and its
source observation. Evidence references apply to the response; the client must not invent per-sentence citations.
The evidence inspector shows the original source kind, host, container, UTC time, and sanitized data.

Broad incident questions show a server-owned **Host overview** before individual cards. It includes local inventory
counts, process and health state, observed groups, log coverage, and explicit clipping or discovery warnings. Counts
exclude remote Swarm replicas, and **Needs review** does not prove a failure. The overview's **Source** opens its `host`
observation; log links open exact-container observations.

**Investigate container** and group choices start a separate session with an explicit target and fresh reads. They
preserve earlier answers and the next-question draft. Ambiguous named resources retain the clarification flow in the
existing session. See [host overview contracts](api.md#host-overview).

IBM Plex Sans is used for interface text and IBM Plex Mono for code and identifiers. The logo and favicon live in
`frontend/public/brand/`. Status colors describe runtime state, uncertainty, and action outcomes.
Logs, environment values, observation JSON, and model text render as text, never executable HTML.

Tab follows reading order, Enter activates controls, Escape closes dialogs, and Ctrl/Cmd+Enter submits a query.
Selection menus support arrow keys, Home/End, and typing to find an option. Escape cancels a pending choice.
The help button beside **Investigation scope** explains automatic scope on hover, keyboard focus, or tap.
Clicking outside a dialog also closes it; clicks inside its content or padding and text drags do not.
Closing action review preserves the prepared action and never confirms execution.
**Ask DockSight** focuses the composer. Source links focus the selected observation.
The workspace breadcrumb opens host selection, including on mobile. Closing it or choosing the current host preserves
the draft, investigation, and prepared actions. Changing hosts or connections cancels outstanding work and discards
the previous workspace.

## Inventory and container reads

In API mode, inventory refreshes 10 seconds after each read settles. Polling pauses while hidden or offline;
returning online, becoming visible, or focusing the page triggers a read. Failures back off to 20, 40, and at most
60 seconds, returning to 10 seconds after success. Reads do not overlap. Demo refresh remains manual.

Refresh retains the last successful inventory, selection by exact container ID, keyboard focus, and investigation state.
Failures label retained rows as stale and offer retry. The receipt timestamp changes only on success and records browser
receipt, not a Docker observation. Manual refresh announces loading and shows success for two seconds.
Refresh icons rotate during reads unless reduced motion is enabled. Historical diagnostic cards and actions never change.

Selecting a container opens its read-only overview without using the model or preparing actions. Inspect, `/stats`,
and `/logs?lines=200` load independently; inspect includes allowlisted environment values. These reads are not atomic.
The overview has no direct restart or stop controls.

Visible inspect refreshes with inventory polling; logs and metrics remain manual. **Refresh data** rereads all sources.
Leaving the overview cancels its requests and polling; reopening rereads its sources. A failed source keeps its last
successful values while other sources remain usable. State and environment use the server's `observed_at`;
metrics and log batches show browser receipt time as **Received**. Individual logs retain Docker timestamps.

Only inspect returning `container_not_found` with HTTP 404 confirms removal and stops automatic reads for that container.
Absence from the inventory, which is bounded to 200 containers, does not prove deletion.
A new container with the same name never replaces the selected ID. Inspect failures disable diagnosis until an explicit
successful read. **Diagnose** starts a new session for the exact selected container; prior answers stay in this tab.
Returning to the investigation preserves its draft, evidence, prepared action IDs, and execution keys.

## Actions

Server-prepared `actions` define the permitted operations. Optional `recommendation` metadata links an explicit model
suggestion to an existing action ID. Its review button includes the model reason and links to supporting observations.
The client never infers a recommendation from narrative text, container state, or action order. Older responses without
that metadata list every operation under **Actions**.

An `actions_code` labels unavailable action preparation while keeping the observed container facts visible. Such cards
expose no executable action or recommendation; refreshing or diagnosing again collects current observations.

The action disclosure closes on selection, Escape, or an outside click. Cancelling confirmation restores focus to the
stable trigger. Reviewing an action never executes it. Execution requires separate confirmation of the exact host,
container, operation, and expiry, and keeps one idempotency key.

A lost execution response triggers an action read, never an automatic Docker mutation retry. A confirmed request may
be repeated with its original key only after reading that the action is still prepared. An `indeterminate` outcome
requires operator inspection of Docker. Historical cards retain original observations and recommendations.
See [confirmation example](examples.md#browser-investigation) and [server action contracts](api.md#actions).

## Diagnostic trace

Each turn has a collapsed **Diagnostic trace** disclosure with public provider/model identity, request/turn IDs,
recorded steps, measured duration, and optional token usage. Selecting a step reveals safe failure details or sanitized
model output before server card assembly. Desktop shows steps beside details; smaller screens use one pane at a time.
**Back to steps** restores focus to the selected step.

Model steps expose normalized assistant `content` and requested `tool_calls`, including IDs, names, and redacted arguments.
These are adapter output and untrusted proposals, not unchanged provider responses or permission to execute tools.
Invalid or oversized final proposals are withheld; clipped previews are labeled. Missing usage differs from zero.

Updates replace steps by ID and remain attached to their turn. Failed or disconnected turns retain received steps;
unfinished steps become interrupted without invented completion or duration. Older servers and previous turns without
trace events display **Not recorded**. Demo traces are simulated and make no API or model request.

**Copy trace** excludes the operator query, credentials, and action execution keys. Trace data stays in browser memory.
Locale changes preserve it; inventory polling never replaces historical trace data.
See [SSE and trace contracts](api.md#diagnostic-stream).

## System status

The top bar keeps API/Docker status separate from the model selector; the status panel includes provider/model details.
Checks run after connection and
host discovery, on host changes, and through **Check again**. API mode repeats checks 60 seconds after settlement while
visible and online. Opening the panel or returning to the foreground rechecks results at least 30 seconds old.
Recent foreground events preserve the next check. Reads do not overlap; manual retry during a read queues one follow-up.
Demo checks remain manual.

Transport failures or unavailable dependencies back off to 120, 240, and at most 300 seconds. Healthy or unchecked
dependencies restore 60 seconds. HTTP 401/403 stops automatic checks until a manual retry verifies authorization
or the connection changes. A successful authorized response resumes polling even if a dependency remains unavailable.

Rechecks retain prior results and timestamps. Failed API checks label retained dependency results as stale;
successful checks replace results for that host only. Dependency times come from the server; API times record browser
receipt or failure. The panel describes polling, backoff, or stopped checks and exposes no credentials or provider URLs.

Metadata availability does not verify generation, tools, or structured output. Unsupported checks stay `not_checked`
and allow explicit diagnosis. Confirmed unavailability disables new diagnoses, including keyboard submission and retry,
while preserving drafts, history, and action state. Provider/model failures leave direct Docker reads available.
See [dependency status](api.md#dependency-status).

## Model selection

The header names the active provider/model. **Choose model** opens configured providers, a searchable model list,
and **Refresh models**. Unconfigured providers are disabled. Demo uses visibly simulated catalogs and makes no requests.
Catalogs load only on opening the picker or selecting a provider. The client reuses recent results for five minutes;
stale rows remain visible while the backend refreshes. Errors retain previous/configured choices and the active model.

Selecting a row applies to the next question and updates its status checks. It preserves the current draft, session,
evidence, historical trace, prepared actions, and execution keys. Switching is disabled during a diagnostic turn.
The choice stays in this tab across host changes; reconnecting or reloading resets it. No provider key or model preference
is written to browser storage. Keys remain in server environment settings; catalog availability does not verify tools.

![Demo: provider and model selection in the header](screenshots/model-selection.jpg)

## Language and lifetime

Language follows `navigator.languages` unless the operator selects English or Russian. System mode follows browser
`languagechange` events and falls back to English. Only `docksight.locale` is stored in localStorage; invalid or unavailable
storage falls back to System. Manual selection still works in memory. Document language and title follow the locale.

Switching language preserves connections, sessions, drafts, evidence, traces, actions, and execution keys.
Interface copy and numeric formatting are localized. Logs, environment values, identifiers, and API/model text remain
verbatim. Demo questions and explanations have authored translations; operator-entered text is unchanged.
An API explanation remains verbatim even if it matches demo text. Self-hosted fonts include Latin and Cyrillic subsets.

The client has no durable conversation history, metric history, environment editing, or stack deployment.
Streams cannot replay or reconnect automatically. Refresh the container overview for current facts or run a new diagnosis
for fresh evidence. See [process state and recovery](configuration.md#process-state-and-recovery).
