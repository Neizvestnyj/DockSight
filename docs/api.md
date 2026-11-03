# HTTP API

Diagram source: [backend.drawio](diagrams/backend.drawio).

Base path: `/api/v1`. All API routes require `Authorization: Bearer TOKEN`. `/health/live`, `/health/ready`, `/docs`,
and `/openapi.json` are public. The token determines the actor: sessions and actions created with one token return
`session_not_found` or `action_not_found` to any other token. See [API tokens](configuration.md#api-tokens).

| Method | Path                                           | Result                                                 |
|--------|------------------------------------------------|--------------------------------------------------------|
| GET    | `/hosts`                                       | Configured host IDs and display names                  |
| GET    | `/system/status?host=local`                    | Safe configuration and independent availability checks |
| GET    | `/model-providers`                             | Configured providers and the default model             |
| GET    | `/model-providers/{provider}/models`           | Lazy, bounded model catalog and freshness              |
| GET    | `/hosts/{host}/containers`                     | Up to 200 inspected containers                         |
| GET    | `/hosts/{host}/containers/{id}`                | Sanitized snapshot                                     |
| GET    | `/hosts/{host}/containers/{id}/logs?lines=200` | Bounded timestamped logs                               |
| GET    | `/hosts/{host}/containers/{id}/stats`          | CPU/memory observations, null when unavailable         |
| GET    | `/hosts/{host}/stacks?kind=compose`            | Compose groups (`swarm` requires a manager)            |
| GET    | `/widgets/schema`                              | Versioned JSON Schema for response cards               |
| POST   | `/chat/turns`                                  | Diagnostic SSE stream                                  |
| POST   | `/actions`                                     | Prepare an action without executing it                 |
| GET    | `/actions/{id}`                                | Current action outcome                                 |
| POST   | `/actions/{id}/execute`                        | Explicitly confirmed execution                         |

## Requests and errors

- Errors contain `code`, `message`, and a request ID where available. Validation errors omit submitted values.
- Request bodies are limited to 16 KiB.
- Host IDs resolve through server configuration. Connection URLs are rejected.

An error code does not determine its HTTP status alone. For example, `provider_not_configured` is 422 for an invalid
model selection and 503 when the server has no model-selection service. Failure categories are internal and absent from
the public error envelope. Failures after streaming starts use
[`turn.failed` events](#diagnostic-stream).

## Read responses

`GET /hosts` returns configured metadata without contacting Docker. Container and stack responses use allowlisted,
redacted Docker data.

### Logs

- At the byte limit, retain the newest complete lines after redaction and discard incomplete leading fragments.
- Preserve Docker output order.
- Limit a finite tail scan to 8 MiB and the Docker timeout. Exceeding the scan limit returns `log_read_limit`.
- On timeout, return `runtime_timeout` without partial output. Abort the connection to release worker capacity,
  including during slow, continuous delivery.
- Diagnostic JSON clipping may shorten the oldest retained message and sets `truncated=true`.

### Container health

Container snapshots and Compose container members include `health`: `starting`, `healthy`, `unhealthy`, or `null`.
Health is independent of process `state`. A running process can be unhealthy. Missing observations and Docker's `none`
map to `null`. Probe commands, output, and healthcheck history are excluded.
Swarm service summaries do not infer container health from running replica counts and retain `health=null`.
See Docker's [healthcheck semantics](https://docs.docker.com/reference/dockerfile/#healthcheck).

## Browser client

The React client in `frontend/` implements this API through streaming `fetch` and keeps its bearer token in memory.
Its separate, labeled Demo transport does not contact the API. Local Vite development and preview proxy `/api` to port
8000. A deployed static build needs a reverse proxy or an HTTPS API base with explicitly configured CORS.
See [frontend contracts](frontend.md) for polling, refresh, and connection recovery.

## Dependency status

`GET /system/status` is authenticated and returns `Cache-Control: no-store`. Its optional `host` query selects a configured
host ID. An unknown ID is rejected before any external work. Without a host, Docker is `not_checked`. The response exposes
only the configured provider type and model name, never credentials, provider URLs, Docker URLs, or raw upstream errors.
Optional `provider` and `model` query parameters select another configured model. Supply both or neither.
The response identity and metadata checks belong to that selection. Omission retains the server default.

```json
{
  "schema_version": 1,
  "host": "local",
  "provider": "ollama",
  "model": "qwen3.5:9b",
  "docker": {
    "state": "available", "code": "ok", "message": "Availability check succeeded.",
    "checked_at": "2026-10-27T12:00:00Z"
  },
  "provider_check": {
    "state": "available", "code": "ok", "message": "Availability check succeeded.",
    "checked_at": "2026-10-27T12:00:00Z"
  },
  "model_check": {
    "state": "not_checked", "code": "unsupported",
    "message": "The provider does not expose a supported model metadata endpoint.",
    "checked_at": "2026-10-27T12:00:00Z"
  }
}
```

Each result has its own UTC completion time and state: `available`, `unavailable`, or `not_checked`. A dependency failure
returns HTTP 200 with an explicit result. Authentication, validation, and unknown-host failures use HTTP errors.
Docker and provider checks run concurrently with three-second deadlines, including queue waits. The metadata HTTP client
has a two-second timeout, at most four connections, no redirects or retries, and a 256 KiB response limit. Docker uses
`ping`, a short SDK timeout, and the bounded worker pool. Cancelled workers retain their slots until they finish.
The probe reuses the generation client's resolved base URL and authentication headers, including SDK environment defaults.

The `provider` field is `ollama`, `openai`, `anthropic`, `gemini`, or `compatible`.
Native metadata probes use [Ollama show](https://docs.ollama.com/api/show),
[OpenAI model retrieval](https://developers.openai.com/api/reference/resources/models/methods/retrieve),
[Gemini model retrieval](https://ai.google.dev/gemini-api/docs/openai#retrieve_a_model), and
[Anthropic model retrieval](https://platform.claude.com/docs/en/api/http/models/retrieve).
Compatible providers use their model catalog. An unlisted compatible alias, denied metadata access, unsupported endpoint,
or malformed metadata leaves the model `not_checked`. A native model lookup returning 404 reports `model_not_found`.
An unreachable provider leaves the model `not_checked`, keeping provider failure separate from a missing model.

Probes do not generate text, load or pull models, run tools, or change Docker state.
They do not verify generation, structured output, or tool compatibility. Run a diagnosis to check those paths.
`/health/live` reports process liveness. `/health/ready` reports successful configuration and wiring.

## Model selection

`GET /model-providers` returns `schema_version: 1`, `default: {provider, model}`, and up to five `providers`.
Each provider has `id`, `name`, `configured`, and nullable `default_model`. This read makes no provider request.
Credentials and endpoints are server settings. Unconfigured providers cannot be selected.

`GET /model-providers/{provider}/models` returns `schema_version: 1`, `provider`, `models: [{id}]`,
`state` (`ready`, `stale`, or `unavailable`), a safe `code`, nullable UTC `checked_at`, and `refreshing`.
Both endpoints require authentication and return `Cache-Control: no-store`.
Model IDs are 1–256 characters. Results contain at most 2,000 IDs, including explicit defaults and fallback aliases.

Catalogs load on demand and remain fresh for 300 seconds in process memory. Concurrent requests share one fetch.
Stale reads return prior rows immediately and start a background refresh. Initial reads wait at most five seconds.
`refresh=true` requests a manual refresh, sharing in-flight work and respecting the 30-second failure cooldown.
Failures preserve prior/default rows and expose safe codes, including `unsupported`, `timeout`, `metadata_forbidden`,
`credentials_rejected`, `invalid_response`, and `partial_catalog`. `checked_at` records the last attempt, including failure.
Metadata reads allow at most 20 pages, 256 KiB per page, and 1,900 external IDs. Partial catalogs are rejected.
Catalog listing does not establish generation access or diagnostic capability.

Turns accept optional `model_selection: {"provider":"ollama","model":"your-installed-model"}`.
The server validates the configured connection and catalog membership before streaming. Explicit default/fallback models
work without a catalog request. Unknown/unconfigured providers and unlisted models fail with HTTP 422.
Omitting selection uses the configured default model. Selection never changes the process-wide default or other callers.
Turns share existing session history, action state, redaction, and the global diagnostic concurrency budget.
The trace records the actual selected identity. The client retains selection only in tab memory and resets it on reconnect.

## Diagnostic stream

POST a JSON body containing `host`, `query` (1-4000 characters), and optionally `session_id`. Sessions are bound to the
authenticated operator and selected host. Use streaming `fetch`, an HTTP client, or `curl -N`.
Browser EventSource cannot POST this request or attach its bearer header.

Follow-up questions send the same `session_id` to retain bounded earlier questions and validated answer summaries.
Each turn collects fresh observations. Existing cards keep their original values. Starting a new investigation clears
the client session and draft. Explicit group-scope changes start a separate session.
Prior questions and summaries reach the model as a labeled context document, not replayed assistant conclusions.
They preserve references for follow-ups but do not establish current runtime state or cross-service causality.

Successful flow for a broad question such as "What happened?":

![Successful diagnostic request and Docker evidence collection](diagrams/diagnostic-overview.png)

Diagram terms:

- Backend: HTTP handling, use cases, and outbound adapters. The detail view shows these separately from Docker Engine.
- Evidence: sanitized Docker observations with server-issued reference IDs.
- Proposal: the model's suggested response.

<details>
<summary>Implementation details: tools, validation, and SSE events</summary>

![Diagnostic tools, evidence validation, and SSE events](diagrams/diagnostic-details.png)

Each requested tool emits its own progress events. Model and tool budgets bound exploration. Finalization allows one
schema or evidence repair attempt. Container status cards prepare allowed actions through an internal `Actions.prepare`
call. Executing those actions requires the separate confirmation flow below.
Within a turn, a repeated successful read with the same validated arguments and target scope returns
`{"already_collected":true,"evidence_ids":["e1"]}` instead of repeating the payload or calling Docker again.
Exact observed container names and full IDs share that read. Failed reads are not reused, and a narrowed scope cannot
reuse a wider result. A batch containing only reused reads ends exploration. Tool-call/result pairs remain intact.
Read reuse limits repeated context but does not cap total model tokens. New turns collect new observations.
Actions revalidate Docker before execution.

Final and repair JSON schemas constrain every `evidence_ids` array to IDs collected in the current turn. A compact
current-turn catalog identifies their observation kind and exact container. Quoted log messages are not reference IDs.
Available widget types depend on collected data:

- `compose_stack`: group evidence.
- Individual status and environment cards: container snapshots.
- Log cards: collected logs and a snapshot.

When no card type has supporting data, the model returns `widgets:null`, normalized to an empty public widget array.
Group and host reports remain server-owned.
Server validation still rejects unknown references or references that cannot support the requested card.
Validation checks references and card data. It does not verify causal explanations.
Final generation omits the last prose-only exploration draft and recaps at most eight latest per-resource lifecycle
snapshots, with an explicit truncation flag. It retains conversation context, tool-call/result pairs, and the current
evidence catalog. The final request repeats the redacted current question before the causal guidance.
Prompt guidance separates clean exits, confirmed OOM, unexplained exit 137, unhealthy probes, and historical request
errors. The opt-in [causal regression package](../CONTRIBUTING.md#live-docker-and-local-model-end-to-end-suite)
checks selected contradictions in model responses. Other claims still require review.

Container status, log, and environment cards each reference exactly one container. A question about several containers
uses separate cards. A model proposal contains at most eight cards. Server assembly retains collected facts and may
return up to sixteen cards. Repair feedback includes the validation failure, valid evidence IDs grouped by exact
container, and available log/stack references. Schema errors omit submitted values and
replace unknown field names with a fixed marker.

Container-scoped evidence includes `container_name`, captured with the snapshot used for that observation. This name
remains available in log-only answers without a status card. The name belongs to the observation, independent of current
inventory. Non-container observations use `null`. Older responses may omit the field. Clients can fall back to the ID.

</details>

Events carry `schema_version: 1`, `request_id`, and `turn_id`:

1. `turn.started` includes the session ID.
2. `tool.started` and `tool.completed` report progress without exposing arguments.
3. `answer.ready` includes the validated summary, evidence, and typed widgets, or `clarification.required` asks for a target.
4. Exactly one terminal event is `turn.completed` or `turn.failed`.

The stream also carries a diagnostic trace. `trace.started` follows `turn.started` with the public `provider`, `model`,
and server UTC `started_at`. Unavailable identity fields are `null`. `trace.step` inserts or replaces a step by its `id`.
These events accompany model calls, budget-eligible tool calls, and schema/evidence validation, including the single
permitted repair attempt. Clients must retain received steps when the turn fails or the connection ends.

| Step field                                 | Contract                                                                                                    |
|--------------------------------------------|-------------------------------------------------------------------------------------------------------------|
| `id`                                       | Turn-scoped ID                                                                                              |
| `kind`                                     | `model`, `tool`, or `validation`                                                                            |
| `operation`                                | Approved tool name or application phase                                                                     |
| `state`                                    | `running`, `succeeded`, or `failed`. Model output still requires validation                                 |
| `started_at`, `finished_at`, `duration_ms` | Server UTC timestamps and monotonic elapsed milliseconds. Unfinished values are `null`                      |
| `input_tokens`, `output_tokens`            | Provider-reported counts, including zero. Missing usage is `null`                                           |
| `code`, `issues`                           | Safe failure code and at most eight validation codes/paths, without submitted values or unknown field names |
| `response`, `response_truncated`           | Optional sanitized model response text and an explicit size-limit flag                                      |

Exploration previews normalize the adapter reply as `content` and `tool_calls` (`id`, `name`, `arguments`), including empty
content and no-call replies. Tool calls and arguments are untrusted model proposals. The preview grants no permission to
execute them. Sensitive argument fields are masked, and recognized reasoning fields/blocks are omitted. Tool results,
prompts, native replay items, and hidden reasoning are excluded. Final response previews contain only schema-recognized
proposal fields before server card assembly. Invalid final JSON/schema bodies and
candidates over 64 KiB are withheld. Validation codes and paths remain available. String values are redacted before JSON
serialization. A preview is at most 16 KiB of UTF-8 text, may have changed formatting, and may be clipped mid-JSON.
`response_truncated=true` also marks an oversized withheld candidate. Never interpret a preview as authoritative Docker
data or execute a proposed action directly from it.

Maximum trace size: 133 steps from 30 model calls, 100 tool executions, two validation steps, and one scope-discovery step.
Calls beyond the tool budget receive paired `tool_limit` results and tool-progress events.
They perform no runtime read and add no execution trace step. Trace events share the request's
authentication and host scope, add no provider requests, are not persisted, and do not support replay.

SSE comments provide heartbeats. Failures after streaming starts remain HTTP 200 and are represented by `turn.failed`.
Disconnecting cancels diagnostic work. Streams do not support replay or automatic reconnection.

Generation HTTP 404 errors use `model_unavailable`: the configured model is missing or inaccessible to the API key.
HTTP 400/422 rejections use `model_not_supported` for request or capability mismatches. Both map to HTTP 422 before
streaming starts. Provider response bodies are never included. The client provides guidance for these two diagnostic
codes and retains unknown server messages verbatim. Metadata checks do not verify generation access.

Native Ollama replies that fill the configured context window before the output budget use `model_context_limit`.
Output-budget exhaustion uses `model_truncated`. When usage is unavailable, truncation uses that generic code.
The client distinguishes these failures. Increasing the output limit alone cannot enlarge the context window shared
by the prompt and response.

## Host overview

Bare incident questions such as "What happened?" collect a bounded overview of the selected host before model
exploration. They do not require choosing a Compose project or Swarm stack. The model can
also request the read-only `inspect_host` tool for other broad questions. Explicit container or group scope cannot be
expanded into a host overview.

`answer.ready.answer.host_overview` is a nullable, server-owned report. Its `evidence_id` references a `host` observation
with `container_id: null`. Counts describe up to 200 distinct observed local containers, across Compose projects and
containers without an observed group. Remote Swarm replicas are not counted. `total`, `running`, and `attention` come
from Docker observations. Running counts describe processes, independently of healthchecks.

The report displays up to 32 members, prioritizing OOM, unhealthy, dead, restarting, and nonzero exits before weaker
signals. `attention` marks candidates for review. An exit with code zero may be expected.
Automatic log collection reads at most four displayed candidates, with at most 200 lines and 4 KiB per container.
`logs` distinguishes collected, failed, and skipped reads. Skipped candidates use `host_log_limit`. The model may request
additional read-only evidence within the turn budgets. Later attempts update coverage for displayed members.
Reads outside the preview retain their evidence without expanding the preview. Missing logs never mean that a container
was checked.

`truncated` signals an inventory, member, group-choice, or metadata limit. Overview metadata is bounded to 32 KiB and
the remaining turn evidence budget. Clipping preserves counts for the capped inventory. The model receives at most
eight prioritized member rows. The public report retains up to 32. Model tool results are bounded to 64 KiB.
`projection_truncated` marks omitted member detail or observations.
Host finalization retains collected evidence and omits the preceding unvalidated prose-only draft from its input.
Up to 32 canonical `targets` allow optional narrowing, prioritizing groups of displayed members.
A missing member group does not prove standalone ownership.
`discovery_code` preserves optional Swarm discovery failures without discarding local container observations.

The report and collected evidence remain available even when the model omits widgets. Assembly fills missing factual
cards within the sixteen-card response limit. Once a host overview is selected, the model cannot replace it with a
group-selection request. The client can start a separate investigation of an observed group or exact container.
The server revalidates that target and collects fresh observations. Earlier answers and the next-question draft remain
intact. Host overview collection performs no Docker mutation.

Container status cards retain historical observations when optional action preparation fails. `actions_code` carries
the typed failure, `actions` is empty, and no recommendation is returned. Unexpected preparation errors still fail
assembly. Typed preparation failures preserve the other collected observations.

## Group targets and cause assessment

### Target resolution

Before model exploration, exact project/stack names in the question are resolved against Docker metadata. A matching
Compose project is inspected automatically. Otherwise, stack names are discovered on a Swarm manager. Exact container
IDs/names preserve container scope. A whole query token with one substitution, insertion, deletion, or adjacent
transposition can match a known group name of at least six characters, only when no exact resource matches.
The complete canonical group name may use spaces in place of hyphens. A prefix alone is not an exact match.
Explicit container references, such as `container NAME`, take precedence over an identically named group. Explicit
Compose/Swarm references select that group namespace. An unqualified container/group collision produces typed choices
for the observed container and group, without calling the model or reading their logs.
A single explicit container name or full ID binds the turn's tool reads to that observed container, including inventory
results. Earlier group summaries remain conversational context and cannot expand the new target's scope.
The server collects its fresh snapshot and bounded logs before model exploration. A log-read failure retains any collected
snapshot so missing logs do not erase available container facts.
Collected status and log facts retain their cards even when the model omits them, using the same assembly policy as
collected problem members in a group report.
Resolved group reports include the canonical name. Ambiguous names produce `clarification.required` without a diagnosis.
Discovery returns the observed alternatives before model or individual log reads for deterministically ambiguous names.
An explicitly selected group continues the original question with bounded evidence from that group only.
The client's history keeps clarification and its selected-target request as one question, while the HTTP requests retain
distinct request/turn IDs. The displayed trace belongs to the active diagnosis attempt.
Malformed or redacted labels outside the target contract are excluded from automatic matching.
`resolve_target` emits progress and trace events without spending a model call.
Model tools accept full Docker IDs or exact observed names. ID prefixes and evidence IDs are rejected.
Optional Swarm discovery failures remain explicit without blocking ordinary container
diagnosis. An explicit Swarm request fails if its required metadata cannot be read.

For unresolved spelling, spaces, or another alphabet, the existing agent loop receives a bounded catalog of up to 32
observed groups. It can call `inspect_group` for a unique interpretation or `request_group_selection` for alternatives.
The server validates every proposed choice against discovery on the selected host. A shared prefix does not authorize
choosing between different suffixes or namespaces. Model interpretation can be wrong. Select a known group explicitly
when possible.
The server also requires a choice when an inferred `inspect_group` target has a nearly identical discovered alternative
and its canonical name was not stated in the question. This prevents a model tool call from bypassing that ambiguity.

### Clarification and explicit scope

`clarification.required` carries `selection: {"candidates":[{"kind":"compose","name":"infra"}]}` with 1–32 distinct
observed targets and no extra fields. Container choices have `kind: "container"`, a full 64-character Docker `id`, and
the observed `name`. Group choices use `kind: "compose" | "swarm"` and `name`. The event is followed by `turn.completed`,
without `answer.ready`. The frontend presents localized choices and continues the original question with its existing
`session_id`, preserving earlier conversation summaries. It sends the selected `group` or `container_id`. The server
revalidates the target against fresh Docker data. Pending choices are local to the tab, not durable conversation state.

`POST /chat/turns` also accepts an optional `group`: `{"kind":"compose","name":"infra"}` or
`{"kind":"swarm","name":"infra"}`. The name identifies an observed group on the configured host. Group objects
reject extra fields, including host overrides. Explicit targets are inspected before model exploration. A failed group
read produces `turn.failed` without falling back to an individual container.
An optional `container_id` instead binds reads to one full Docker ID observed on the configured host. ID prefixes and
requests containing both `group` and `container_id` are rejected. A removed or foreign container produces
`container_not_found` before model calls or individual reads. Its previous name never selects a replacement container.
Clarifying a pending question retains its session. Independently changing the selected scope starts a separate session.

### Group evidence

The read-only `inspect_group` tool provides the same workflow for model-discovered targets. It collects a group summary
and logs for at most four local problem containers, at most 200 configured lines and 4 KiB of returned log text per
container. Payloads and evidence references reach the model together. Failed and omitted reads remain distinct.
Tool calls emit progress and trace events. Group collection never prepares or executes a group-wide mutation.

Running members with `health=unhealthy` are included in that problem-log budget even without OOM or restarts.
`starting` alone is not a failure signal. Healthcheck failures establish a symptom, not its underlying cause.
Missing local inventory keeps unhealthy members visible with explicit uncollected log coverage.

Stack summaries add `members` and `truncated`. Compose members are containers with state and exit code. Swarm members
are services, grouped by `com.docker.stack.namespace`. Totals count desired/running task replicas. Standalone services
are excluded. Service/task reads and container identities are bounded to 200. Local container logs do not cover remote
Swarm nodes. Inventory caps and evidence-budget clipping set `truncated`. Counts remain observed totals for the retained
scope, and a clipped member list is not a complete inventory.

`answer.ready.answer.group` is a server-owned report or `null`, independent of model-selected widgets. It contains the
summary, its `evidence_id`, optional `inventory_code`, and per-container `logs`: `container_id`, `name`, `state`
(`collected`, `failed`, `not_collected`), optional evidence reference, and safe error/limit code. Report references remain
in response evidence even if the model omits their cards. The server fills missing state/log cards for the four collected
problem containers, without duplicating model-selected cards or inventing missing logs. Responses contain at most 16
widgets: eight model selections and up to eight factual additions. Subsequent inventory refresh does not replace the
report.
Added state cards use the latest snapshot collected for that member during the turn.

### Cause fields

Optional `cause` separates model-authored `immediate`, nullable `underlying`, `unknowns` (up to four), and supporting
`evidence_ids`. References are validated and narrative fields are redacted. For example, a database connection refusal
can explain startup failure while the reason for database unavailability remains unknown. The existing `uncertain`
field remains available for older clients and responses.
Final narrative values follow the question language unless the operator explicitly asks for another language.
Log entries, environment values, identifiers, and schema keys remain verbatim. Cause text containing only
machine codes, evidence IDs, or empty placeholders such as the string `[]` is rejected through the single repair attempt.
Unestablished causes use `null`. Unresolved questions use natural-language list entries.

## Actions

Container status cards distinguish permitted operations from model recommendations. `actions` remains the authoritative
list of server-prepared operations for the observed exact target. Optional `recommendation` is `null` unless the model's
explicit `action` matches one of these permitted operations. It contains that existing `action_id` and an optional
sanitized `reason` of at most 240 characters. The model supplies only an operation and optional `action_reason`. It cannot
supply the linked ID or grant permission. Unsupported suggestions produce no recommendation. Reasons require an explicit
action and are never inferred from the summary. The card's evidence references provide the supporting observations.

Clients can highlight the recommended operation while keeping other permitted operations in an action disclosure.
Missing recommendation metadata from an older server means no recommendation. Both paths use the same separate
confirmation, expiry, exact-target revalidation, and idempotent execution flow below.

Prepare with `host`, an exact 64-character `container_id`, and `operation` (`restart` or `stop`). Cards can already
contain server-prepared action IDs: card assembly calls `Actions.prepare` internally, using the same preparation
workflow without an HTTP request.

Prepare the action ID before confirmation, either through diagnosis or `POST /actions`:

![Action preparation and explicitly confirmed execution](diagrams/action-overview.png)

The idempotency key identifies one execution attempt so a repeated request can reuse its result. A command whose target
changed is rejected before mutation. The [action lifecycle](architecture.md#prepared-action-lifecycle) explains the
possible outcomes, including an unknown Docker result.

<details>
<summary>Implementation details: preparation, duplicate requests, and execution</summary>

The detail view shows direct API preparation. Diagnosis uses the same `Actions.prepare` workflow.

- Claim: reserves one execution.
- Fingerprint: records the observed container identity and state.
- Target fence: blocks further commands after an unknown result.

![Action claims, duplicate requests, revalidation, and execution outcomes](diagrams/action-details.png)

Invalid claims are rejected before execution. An unavailable initial audit output prevents mutation. Revalidation
failures end as `failed`. A started mutation with an unknown result ends as `indeterminate`.

</details>

Review the operation and target, then execute with:

```http
POST /api/v1/actions/ACTION_ID/execute
Authorization: Bearer TOKEN
Idempotency-Key: review-restart-1
Content-Type: application/json

{"confirmed": true}
```

Preparation expires after five minutes by default. The server rechecks the target identity and snapshot before
execution. A completed request can be replayed with the same key while its record is retained. Another key cannot
execute that action again. Concurrent mutations of the same target serialize.

Outcomes are `prepared`, `running`, `succeeded`, `failed`, `expired`, or `indeterminate`. An HTTP success status
describes the API request. Inspect the returned action state to determine its outcome. Started mutations continue after
client disconnects. A timeout can leave the Docker outcome unknown and fences further mutations of that target for the
backend process lifetime.

State is not durable. After a backend restart, prepare fresh actions. Following an abrupt process loss, verify Docker
before preparing another mutation.
