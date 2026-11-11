# Frontend

[Quick start](../README.md#quick-start) · [Usage examples](examples.md) ·
[Deployment](configuration.md#frontend-deployment)

## Boundaries

- Stack: React, strict TypeScript, and Vite in `frontend/`.
- Transport: validated contracts, authenticated reads, saved-turn snapshots, explicit Stop, and confirmed actions.
- Credentials: bearer tokens and CSRF values stay in memory. First-party login uses an opaque HttpOnly cookie.
- Investigations: actor-owned backend history, with each chat scoped to one configured host.
- Demo: separate, labeled transport with fictional hosts and fixtures matching backend contracts. No Docker or model
  calls. Scenario and error controls are disabled during collection.

Demo logs are fixed. Browser tests use mocked API responses for longer log scrolling.
See [contributor checks](../CONTRIBUTING.md#checks).

## Connection and recovery

Page load checks the first-party `/api/v1/auth/session` before opening a workspace. A valid cookie restores API mode.
An unauthorized response shows **Sign in to DockSight** with **Connect API** and **Explore Demo**. A failed network read
shows **Could not restore your session.** and **Retry connection**. Demo always requires explicit entry.

In **Connect API**, a same-origin base such as `/api/v1` exchanges the supplied bearer token once for an HttpOnly
cookie. The token input clears after the exchange attempt. JavaScript keeps the session identity and CSRF value in
memory. The browser manages the opaque cookie. **Sign out** revokes that session without deleting history or stopping
accepted diagnoses. Other tabs sharing the cookie lose authority on their next request or observer check.

A separate-origin API uses transient bearer access with cookies omitted. Its endpoint and token stay only in memory,
so refresh requires reconnecting. The backend still owns saved chats. Reconnect as the same actor to read them.
No endpoint, API token, or CSRF value enters browser storage or a URL. Provider credentials stay on the backend.
See [public-origin setup](configuration.md#public-origin-and-proxy-setup) for Vite origins and HTTPS proxy rules.

## Saved chats and drafts

**Saved chats** lists the latest ten owned chats by activity. **Older chats** loads another page. Ten is a page size,
not a retention limit. Open a row to read its archive. **New investigation** creates another chat without deleting
earlier ones. On smaller screens, saved chats remain available in **Host & containers**.

The browser restores the last-active chat only at bootstrap. Focus refreshes the open chat and saved list. Another
tab's navigation cannot move this tab to a different chat. **Delete saved chat** requires **Delete chat** confirmation.
A running diagnosis must finish or be stopped first. Deletion removes that archive and its context, while server action
protection remains. Server capacity can reject new work without removing older SQLite history.

Drafts save after 300 ms of inactivity. **Saving draft…**, **Draft saved**, and **Draft unsaved** show acknowledgement.
Refresh restores only acknowledged text. Unsent keystrokes can be lost. Workspace changes and actor preferences use
independent revisions and serialized writes.
Opening a saved row, including the selected row, or starting a new chat or host waits for pending saves. A save failure
or unresolved conflict retains the current workspace and draft.

A stale write keeps local text and shows **This chat changed in another tab. Your draft is unsaved.** Choose
**Reload saved draft** to discard local changes or **Use this draft** to save the local draft against the current
workspace. **Retry save** repeats a failed save explicitly. Focus refresh cannot silently advance a dirty workspace's
revision. A pending local save settles before its refresh result is applied.

Saved host, model, scope, container selection, and view come from the server workspace. A new account without a saved
host can use its sole configured host. Multiple configured hosts require a choice. Removed saved hosts or models leave
the archive readable and continuation disabled until an explicit valid choice. A different host starts another chat.
Opening a removed-host archive still remembers it as last active without changing the configured host preference.
An unavailable container keeps its full historical ID. A new container with the same name never replaces it.

## Questions and observation

**Investigate** submits one question after pending workspace saves settle. A clarification choice continues the saved
original question with its exact observed target and parent revision, without a replacement query. Attempts remain
grouped under that question. **Older answers** loads earlier saved turns independently of model context.

An accepted API turn belongs to the backend. Refresh or focus can discover a running turn, read it, and observe that
same server turn. Dropped reads/observation retry after 1, 2, 4, 8, then 10 seconds while visible and online.
Authorization failures stop retries. Refresh and reconnect never submit a question or execute an action again.
A lost submission response is recovered through saved-history reads. If recovery is unavailable, check saved history
before submitting manually.

**Stop diagnosis** cancels the exact active turn. A late response to an earlier Stop cannot detach a newer turn.
Changing chats, hosts, connections, or entering Demo detaches observation. Accepted work continues on the backend.
Backend restart marks abandoned running turns as interrupted and does not resume model generation.

Saved answers retain cards, dated evidence, original request IDs, and safe trace metadata as historical snapshots.
Continuing collects fresh Docker observations. Observation resumes from committed snapshots and can omit intermediate
progress. It does not replay the original stream.
See [saved-turn contracts](api.md#saved-investigations-and-workspaces).

## Interface and evidence

The workspace keeps model explanations separate from Docker observations. Explanation links select a widget and its
source observation. Evidence references apply to the whole response. The client must not invent per-sentence citations.
The evidence inspector shows the original source kind, host, container, UTC time, and sanitized data.

Broad incident questions show a server-owned **Host overview** before individual cards. It includes local inventory
counts, process and health state, observed groups, log coverage, and explicit clipping or discovery warnings. Counts
exclude remote Swarm replicas, and **Needs review** does not prove a failure. The overview's **Source** opens its `host`
observation. Log links open exact-container observations.

**Investigate container** and group choices submit a question with an explicit target and fresh reads. They preserve
earlier answers and the next-question draft. Ambiguous named resources continue the saved original question through
clarification. See [host overview contracts](api.md#host-overview).

IBM Plex Sans is used for interface text and IBM Plex Mono for code and identifiers. The logo and favicon live in
`frontend/public/brand/`. Status colors describe runtime state, uncertainty, and action outcomes.
Logs, environment values, observation JSON, and model text render as text, never executable HTML.

| Control | Behavior |
|---------|----------|
| Tab / Enter / Escape | Follow reading order / activate / close dialogs or cancel a menu choice |
| Ctrl/Cmd+Enter | Submit a query |
| Selection menus | Arrow keys, Home/End, and typeahead |
| Scope help | Available on hover, focus, or tap |
| Outside dialog click | Close the dialog. Content clicks, padding clicks, and text drags keep it open |
| Close action review | Preserve the prepared action without confirming it |
| **Ask DockSight** / source link | Focus the composer / selected observation |
| Workspace breadcrumb | Open host selection, including on mobile |

Closing host selection or choosing the current host preserves the draft, investigation, and prepared actions.
Changing hosts opens a separate chat. Changing connections detaches the old account's reads and clears its client state.
Accepted API diagnoses continue unless **Stop diagnosis** is selected.

## Inventory and container reads

Container process state and healthcheck results are separate in inventory, facts, cards, and Compose rows.

| Observation                                       | Display                                        |
|---------------------------------------------------|------------------------------------------------|
| Missing or null health, including older responses | Not reported                                   |
| Running count                                     | Running processes, independent of healthchecks |
| Diagnostic card header                            | Process state                                  |
| Healthcheck                                       | Separate fact row and compact-list label       |
| Stopped process healthcheck                       | **Last healthcheck**                           |
| Exited process / nonzero exit code                | Neutral status / highlighted exit code         |

API inventory refreshes 10 seconds after each read settles. Polling pauses while hidden or offline.
Returning online, becoming visible, or focusing the page triggers a read. Failures back off to 20, 40, and at most
60 seconds. Success restores 10 seconds. Reads do not overlap. Demo refresh is manual.

Refresh retains the last successful inventory, selection by exact container ID, keyboard focus, and investigation state.
Failures label retained rows as stale and offer retry. The receipt timestamp changes only on success and records browser
receipt, not a Docker observation. Manual refresh announces loading and shows success for two seconds.
Refresh icons rotate during reads unless reduced motion is enabled. Historical diagnostic observations never change.

Selecting a container opens its read-only overview without using the model or preparing actions. Inspect, `/stats`,
and `/logs?lines=200` load independently. Inspect includes allowlisted environment values. These reads are not atomic.
The overview has no direct restart or stop controls.

Visible inspect refreshes with inventory polling. Logs and metrics refresh manually.
**Refresh data** rereads all sources.
Leaving the overview cancels its requests and polling. Reopening rereads its sources.
A failed source retains its last successful values. Other sources remain usable.

State and environment use the server's `observed_at`. Metrics and log batches show browser receipt time as **Received**.
Individual logs retain Docker timestamps.

Only inspect returning `container_not_found` with HTTP 404 confirms removal and stops that container's automatic reads.
Absence from the inventory, which is bounded to 200 containers, does not prove deletion.
A new container with the same name never replaces the selected ID. Inspect failures disable diagnosis until an explicit
successful read. **Diagnose** starts a question for the exact selected container. Prior API answers remain saved.
Returning to the investigation preserves its draft, evidence, prepared action IDs, and execution keys.

## Actions

Server-prepared `actions` define the permitted operations. Optional `recommendation` metadata links an explicit model
suggestion to an existing action ID. Its review button includes the model reason and links to supporting observations.
The client never infers a recommendation from narrative text, container state, or action order. Older responses without
that metadata list every operation under **Actions**.

An `actions_code` labels unavailable action preparation while keeping the observed container facts visible. Such cards
expose no executable action or recommendation. Refresh or diagnose again to collect current observations.

The action disclosure closes on selection, Escape, or an outside click. Cancelling confirmation restores focus to the
stable trigger. An archive opens with action review closed. Opening review reads the existing action before enabling
confirmation and verifies its ID, host, full container ID, and operation. Review never prepares a replacement or
executes it. Missing, foreign, expired, or indeterminate actions cannot be confirmed. Execution requires renewed
confirmation of the current server target, operation, and expiry. The live attempt keeps one idempotency key.

A lost execution response triggers an action read, never an automatic Docker mutation retry. A confirmed request may
be repeated with its original key only after reading that the action is still prepared. An `indeterminate` outcome
requires operator inspection and [offline reconciliation](configuration.md#action-reconciliation). Reload never restores
a queued mutation or an open confirmation. Historical cards retain original observations and recommendations.
See [confirmation example](examples.md#browser-investigation) and [server action contracts](api.md#actions).

## Diagnostic trace

Each turn has a collapsed **Diagnostic trace** disclosure with public provider/model identity, request/turn IDs,
recorded steps, measured duration, and optional token usage. Selecting a step reveals safe failure details.
Desktop shows steps beside details. Smaller screens use one pane at a time.
**Back to steps** restores focus to the selected step.

Saved API traces omit model-output previews. Demo can show simulated previews. Trace metadata grants no execution
permission. Missing usage differs from zero.

Updates remain attached to their turn. Failed or detached API turns retain committed trace snapshots.
Unfinished steps show interruption without invented completion or duration. Turns without trace metadata display
**Not recorded**. Demo traces are simulated and make no API or model request.

**Copy trace** excludes the operator query, credentials, and action execution keys. Safe API trace metadata stays with
the saved turn. Inventory polling never replaces historical trace data.
See [snapshot observation](api.md#snapshot-observation) and [legacy trace contracts](api.md#diagnostic-stream).

## System status

The top bar shows API/Docker status and a separate model selector. The status panel includes provider/model details.

- Check after connection and host discovery, on host changes, and through **Check again**.
- In API mode, repeat 60 seconds after settlement while visible and online. Demo checks are manual.
- On panel opening or foreground return, recheck results at least 30 seconds old. Recent results keep the next check.
- Do not overlap reads. Manual retry during a read queues one follow-up.

Transport failures or unavailable dependencies back off to 120, 240, and at most 300 seconds. Healthy or unchecked
dependencies restore 60 seconds. HTTP 401/403 stops automatic checks until a manual retry verifies authorization
or the connection changes. A successful authorized response resumes polling even if a dependency remains unavailable.

Rechecks retain prior results and timestamps. Failed API checks mark retained dependency results as stale.
Success replaces results for that host only. Dependency times come from the server. API times record browser receipt
or failure. The panel shows polling, backoff, or stopped checks and exposes no credentials or provider URLs.

Metadata availability does not verify generation, tools, or structured output. Unsupported checks stay `not_checked`
and allow explicit diagnosis. Confirmed unavailability disables new diagnoses, including keyboard submission and retry,
while preserving drafts, history, and action state. Provider/model failures leave direct Docker reads available.
See [dependency status](api.md#dependency-status).

## Model selection

The header names the active provider/model. **Choose model** opens configured providers, a searchable model list,
and **Refresh models**. Unconfigured providers are disabled. Demo uses visibly simulated catalogs and makes no requests.
Catalogs load only on opening the picker or selecting a provider. The client reuses results for five minutes.
Stale rows remain visible during refresh. Errors retain previous/configured choices and the active model.

Selecting a row applies to the next question and updates its status checks. It preserves the current draft, session,
evidence, historical trace, prepared actions, and execution keys. Switching is disabled during a diagnostic turn.
API model preferences save on the backend after server validation and restore at bootstrap. An unavailable saved model
does not replace archived results and blocks continuation until a valid choice. Demo choices remain in the tab.
Provider keys stay in server environment settings. Neither keys nor model preferences enter browser storage.
Catalog availability does not verify tool support.

![Demo: provider and model selection in the header](screenshots/model-selection.jpg)

## Browser state and lifetime

The locale preference (`docksight.locale`) is the only JavaScript browser-storage preference.
Its default follows browser language preferences. Logs, environment values, identifiers, and API/model text remain
verbatim.
The browser may persist the opaque HttpOnly login cookie. API/provider tokens and CSRF values are never persisted there.

SQLite retains API history and acknowledged workspace state across backend restart. Explicit memory mode can expire
inactive history and loses all state on restart. Demo history lives only in the tab. The client has no metric history,
environment editing, or stack deployment. Refresh the container overview for current facts or continue a chat for fresh
evidence. See [process state and recovery](configuration.md#process-state-and-recovery).
