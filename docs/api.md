# HTTP API

Diagram source: [backend.drawio](diagrams/backend.drawio).

Base path: `/api/v1`. All API routes require `Authorization: Bearer TOKEN`. `/health/live`, `/health/ready`, `/docs`,
and `/openapi.json` are public.

| Method | Path                                           | Result                                               |
|--------|------------------------------------------------|------------------------------------------------------|
| GET    | `/hosts`                                       | Configured host IDs and display names                |
| GET    | `/system/status?host=local`                     | Safe configuration and independent availability checks |
| GET    | `/hosts/{host}/containers`                     | Up to 200 inspected containers                       |
| GET    | `/hosts/{host}/containers/{id}`                | Sanitized snapshot                                   |
| GET    | `/hosts/{host}/containers/{id}/logs?lines=200` | Bounded timestamped logs                             |
| GET    | `/hosts/{host}/containers/{id}/stats`          | CPU/memory observations; unavailable values are null |
| GET    | `/hosts/{host}/stacks?kind=compose`            | Compose groups; `swarm` requires a manager           |
| GET    | `/widgets/schema`                              | Versioned JSON Schema for response cards             |
| POST   | `/chat/turns`                                  | Diagnostic SSE stream                                |
| POST   | `/actions`                                     | Prepare an action without executing it               |
| GET    | `/actions/{id}`                                | Current action outcome                               |
| POST   | `/actions/{id}/execute`                        | Explicitly confirmed execution                       |

Errors contain `code`, `message`, and a request ID where available. Validation errors omit submitted values. Request
bodies are limited to 16 KiB. Host IDs resolve through server configuration; callers cannot submit connection URLs. At
the byte limit, logs omit the incomplete trailing line before redaction.

Container and stack GET requests pass through HTTP routes, `RuntimeQueries`, and the Docker adapter. The Docker adapter
applies field allowlists and redaction before returning owned values; the HTTP adapter serializes them as JSON.

`GET /hosts` reads configured host metadata without contacting Docker. Diagnostic requests use the model loop below.

## Browser client

The React client in `frontend/` implements this API through streaming `fetch` and keeps its bearer token in memory.
Its separate, labeled Demo transport does not contact the API. Local Vite development and preview proxy `/api` to port
8000; a deployed static build needs a reverse proxy or an HTTPS API base with explicitly configured CORS.
See [frontend operation and limitations](frontend.md).

The browser polls the selected host's container list and the visible container's inspect endpoint 10 seconds after each
read settles. It pauses while hidden or offline and backs off failed reads to at most 60 seconds. Logs, stats, diagnostic
streams, and actions are not polled. Inventory remains bounded to 200 containers; only an exact inspect response with
`container_not_found` and HTTP 404 confirms removal of a selected container.

The browser checks `/system/status` every 60 seconds while visible and online, with failure backoff up to 300 seconds.
Panel access and foreground events recheck observations at least 30 seconds old. HTTP 401/403 stops automatic checks
until a manual retry verifies authorization or the connection changes. Status checks never invoke generation or actions.

## Dependency status

`GET /system/status` is authenticated and returns `Cache-Control: no-store`. Its optional `host` query selects a configured
host ID; an unknown ID is rejected before any external work. Without a host, Docker is `not_checked`. The response exposes
only the configured provider type and model name, never credentials, provider URLs, Docker URLs, or raw upstream errors.

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
remains HTTP 200 with an explicit result; authentication, validation, and unknown-host failures use normal HTTP errors.
Docker and provider checks run concurrently with three-second deadlines, including queue waits. The metadata HTTP client
has a two-second timeout, at most four connections, no redirects or retries, and a 256 KiB response limit. Docker uses
`ping`, a short SDK timeout, and the existing bounded worker pool; cancelled workers retain their slots until they finish.
The probe reuses the generation client's resolved base URL and authentication headers, including SDK environment defaults.

Native metadata probes use [Ollama show](https://docs.ollama.com/api/show),
[OpenAI model retrieval](https://developers.openai.com/api/reference/resources/models/methods/retrieve), and
[Anthropic model retrieval](https://platform.claude.com/docs/en/api/http/models/retrieve).
Compatible providers use their model catalog. An unlisted compatible alias, denied metadata access, unsupported endpoint,
or malformed metadata leaves the model `not_checked`. A native model lookup returning 404 reports `model_not_found`.
An unreachable provider leaves the model `not_checked`, keeping provider failure separate from a missing model.

These probes do not generate text, load or pull models, run tools, validate structured output, or change Docker state.
They do not establish generation health or tool compatibility. Full diagnostic validation requires an explicit diagnostic
request. `/health/live` still reports process liveness; `/health/ready` still reports successful configuration and wiring.

## Diagnostic stream

POST a JSON body containing `host`, `query` (1-4000 characters), and optionally `session_id`. Sessions are bound to the
authenticated operator and selected host. Use streaming `fetch`, an HTTP client, or `curl -N`; browser EventSource
cannot POST this request or attach its bearer header.

For a query such as "Why did this container exit?", the successful path is:

![Successful diagnostic request and Docker evidence collection](diagrams/diagnostic-overview.png)

In the overview, Backend includes HTTP handling, use cases, and outbound adapters. The detailed sequences expand these
parts and keep Docker Engine separate from the Docker adapter. Evidence means collected, sanitized Docker data with
server-issued reference IDs; a proposal is the model's suggested response.

<details>
<summary>Implementation details: tools, validation, and SSE events</summary>

![Diagnostic tools, evidence validation, and SSE events](diagrams/diagnostic-details.png)

Each requested tool emits its own progress events. Model and tool budgets bound exploration; finalization allows one
schema or evidence repair attempt. Container status cards prepare allowed actions through an internal `Actions.prepare`
call. Executing those actions requires the separate confirmation flow below.

Container status, log, and environment cards each reference exactly one container. A question about several containers
uses separate cards, with at most eight cards per response. Repair feedback includes the validation failure, valid
evidence IDs grouped by exact container, and available log/stack references. Schema errors omit submitted values and
replace unknown field names with a fixed marker.

</details>

Events carry `schema_version: 1`, `request_id`, and `turn_id`:

1. `turn.started` includes the session ID.
2. `tool.started` and `tool.completed` report progress without exposing arguments.
3. `answer.ready` includes the validated summary, evidence, and typed widgets.
4. Exactly one terminal event is `turn.completed` or `turn.failed`.

The stream also carries a diagnostic trace. `trace.started` follows `turn.started` with the public `provider`, `model`,
and server UTC `started_at`; unavailable identity fields are `null`. `trace.step` inserts or replaces a step by its `id`.
These events accompany model calls, budget-eligible tool calls, and schema/evidence validation, including the single
permitted repair attempt. Clients must retain received steps when the turn fails or the connection ends.

| Step field | Contract |
| --- | --- |
| `id`, `kind`, `operation` | Turn-scoped ID; `model`, `tool`, or `validation`; approved tool name or application phase |
| `state` | `running`, `succeeded`, or `failed`; receiving model output does not imply successful validation |
| `started_at`, `finished_at`, `duration_ms` | Server UTC timestamps and monotonic elapsed milliseconds; unfinished values are `null` |
| `input_tokens`, `output_tokens` | Provider-reported counts, including real zeroes; missing usage is `null` |
| `code`, `issues` | Safe failure code and at most eight validation codes/paths, without submitted values or unknown field names |
| `response`, `response_truncated` | Optional sanitized model response text and an explicit size-limit flag |

Exploration previews normalize the adapter reply as `content` and `tool_calls` (`id`, `name`, `arguments`), including empty
content and no-call replies. Tool calls and arguments are untrusted model proposals; the preview grants no permission to
execute them. Sensitive argument fields are masked, and recognized reasoning fields/blocks are omitted. Tool results,
prompts, native replay items, and hidden reasoning are excluded. Final response previews contain only schema-recognized
proposal fields before server card assembly. Invalid final JSON/schema bodies and
candidates over 64 KiB are withheld; validation codes and paths remain available. String values are redacted before JSON
serialization. A preview is at most 16 KiB of UTF-8 text, may have changed formatting, and may be clipped mid-JSON.
`response_truncated=true` also marks an oversized withheld candidate. Never interpret a preview as authoritative Docker
data or execute a proposed action directly from it.

Configured budgets allow at most 30 model calls, 100 tool executions, and two validation steps, yielding at most 132
trace steps. Calls beyond the tool budget still receive paired `tool_limit` results for provider replay and existing
tool-progress events; they perform no runtime read and add no execution trace step. Trace events share the request's
authentication and host scope, add no provider requests, are not persisted, and do not support replay.

SSE comments provide heartbeats. Failures after streaming starts remain HTTP 200 and are represented by `turn.failed`.
Disconnecting cancels diagnostic work. Streams do not support replay or automatic reconnection.

## Actions

Container status cards distinguish permitted operations from model recommendations. `actions` remains the authoritative
list of server-prepared operations for the observed exact target. Optional `recommendation` is `null` unless the model's
explicit `action` matches one of these permitted operations. It contains that existing `action_id` and an optional
sanitized `reason` of at most 240 characters. The model supplies only an operation and optional `action_reason`; it cannot
supply the linked ID or grant permission. Unsupported suggestions produce no recommendation. Reasons require an explicit
action and are never inferred from the summary. The card's evidence references provide the supporting observations.

Clients can highlight the recommended operation while keeping other permitted operations in an action disclosure.
Missing recommendation metadata from an older server means no recommendation. Both paths use the same separate
confirmation, expiry, exact-target revalidation, and idempotent execution flow below.

Prepare with `host`, an exact 64-character `container_id`, and `operation` (`restart` or `stop`). Cards can already
contain server-prepared action IDs: card assembly calls `Actions.prepare` internally, using the same preparation
workflow without an HTTP request.

The action ID must already be prepared before confirmation. There are two sources for it:

![Action preparation and explicitly confirmed execution](diagrams/action-overview.png)

The idempotency key identifies one execution attempt so a repeated request can reuse its result. A command whose target
changed is rejected before mutation. The [action lifecycle](architecture.md#prepared-action-lifecycle) explains the
possible outcomes, including an unknown Docker result.

<details>
<summary>Implementation details: preparation, duplicate requests, and execution</summary>

This sequence follows direct API preparation. During diagnosis, `ViewAssembler` calls the same `Actions.prepare`
workflow. A claim reserves one execution; a fingerprint records the observed container identity and state; a target
fence blocks further commands after an unknown result.

![Action claims, duplicate requests, revalidation, and execution outcomes](diagrams/action-details.png)

Invalid claims are rejected before execution. An unavailable initial audit output prevents mutation. Revalidation
failures end as `failed`; a started mutation with an unknown result ends as `indeterminate`.

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
describes the API request; inspect the returned action state to determine its outcome. Started mutations continue after
client disconnects. A timeout can leave the Docker outcome unknown and fences further mutations of that target for the
backend process lifetime.

State is not durable. After a backend restart, prepare fresh actions. Following an abrupt process loss, verify Docker
before preparing another mutation.
