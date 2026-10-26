# HTTP API

Base path: `/api/v1`. All API routes require `Authorization: Bearer TOKEN`. `/health/live`, `/health/ready`, `/docs`,
and `/openapi.json` are public.

| Method | Path                                           | Result                                               |
|--------|------------------------------------------------|------------------------------------------------------|
| GET    | `/hosts`                                       | Configured host IDs and display names                |
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

Container and stack GET requests follow this read path. The Docker adapter applies field allowlists and redaction
before returning owned values; the HTTP adapter serializes them as JSON.

```text
Client -> HTTP adapter -> RuntimeQueries -> Docker adapter -> Docker Engine
Client <- JSON response <- owned runtime values <- sanitized observations
```

`GET /hosts` reads configured host metadata without contacting Docker. Diagnostic requests use the model loop below.

## Diagnostic stream

POST a JSON body containing `host`, `query` (1-4000 characters), and optionally `session_id`. Sessions are bound to the
authenticated operator and selected host. Use streaming `fetch`, an HTTP client, or `curl -N`; browser EventSource
cannot POST this request or attach its bearer header.

For a query such as "Why did this container exit?", the successful path is:

```mermaid
sequenceDiagram
    autonumber
    participant client as User / HTTP client
    participant backend as DockSight Backend
    participant model as Model provider
    participant docker as Docker Engine

    client->>backend: Ask why a container exited
    loop Collect the required Docker facts
        backend->>model: Question, history, and allowed reads
        model-->>backend: Requested reads
        backend->>docker: Read state, logs, or metrics
        docker-->>backend: Actual Docker data
    end
    backend->>model: Final request with sanitized facts
    model-->>backend: Proposed diagnosis
    backend->>backend: Validate reply and build response
    backend-->>client: Explanation and Docker data via SSE
```

In the overview, Backend includes HTTP handling, use cases, and outbound adapters. The detailed sequences expand these
parts and keep Docker Engine separate from the Docker adapter. Evidence means collected, sanitized Docker data with
server-issued reference IDs; a proposal is the model's suggested response.

<details>
<summary>Implementation details: tools, validation, and SSE events</summary>

```mermaid
sequenceDiagram
    participant client as Operator / client
    participant backend as HTTP / Diagnostics
    participant model as Model provider
    participant reads as DiagnosticTools
    participant runtime as Docker adapter
    participant docker as Docker Engine
    participant views as ViewAssembler

    client->>backend: POST /api/v1/chat/turns
    backend->>backend: Validate host and lease scoped session
    backend-->>client: SSE turn.started
    alt Turn succeeds
        loop Bounded evidence collection
            backend->>model: Query, history, and allowed tools
            model-->>backend: Tool calls or end of exploration
            loop Each requested read-only tool
                backend-->>client: SSE tool.started
                backend->>reads: Validate tool name and arguments
                reads->>runtime: Read the selected host
                runtime->>docker: Inspect / logs / stats / stacks
                docker-->>runtime: Runtime observations
                runtime->>runtime: Allowlist and redact
                runtime-->>reads: Sanitized runtime values
                reads->>reads: Record evidence IDs
                reads-->>backend: Sanitized evidence with IDs
                backend-->>client: SSE tool.completed
            end
        end
        backend->>model: Final structured diagnosis request
        model-->>backend: DiagnosisProposal
        backend->>backend: Validate proposal schema
        backend->>views: Validate evidence and assemble cards
        views-->>backend: Typed cards and optional prepared actions
        backend->>backend: Save query and summary in session
        backend-->>client: SSE answer.ready
        backend-->>client: SSE turn.completed
    else Failure after the stream opens
        backend-->>client: SSE turn.failed
    end
```

Each requested tool emits its own progress events. Model and tool budgets bound exploration; finalization allows one
schema or evidence repair attempt. Container status cards prepare allowed actions through an internal `Actions.prepare`
call. Executing those actions requires the separate confirmation flow below.

</details>

Events carry `schema_version: 1`, `request_id`, and `turn_id`:

1. `turn.started` includes the session ID.
2. `tool.started` and `tool.completed` report progress without exposing arguments.
3. `answer.ready` includes the validated summary, evidence, and typed widgets.
4. Exactly one terminal event is `turn.completed` or `turn.failed`.

SSE comments provide heartbeats. Failures after streaming starts remain HTTP 200 and are represented by `turn.failed`.
Disconnecting cancels diagnostic work. Streams do not support replay or automatic reconnection.

## Actions

Prepare with `host`, an exact 64-character `container_id`, and `operation` (`restart` or `stop`). Cards can already
contain server-prepared action IDs: card assembly calls `Actions.prepare` internally, using the same preparation
workflow without an HTTP request.

The action ID must already be prepared before confirmation. There are two sources for it:

```mermaid
sequenceDiagram
    autonumber
    participant client as User / HTTP client
    participant backend as DockSight Backend
    participant docker as Docker Engine

    alt Command prepared during diagnosis
        backend-->>client: Diagnosis with prepared command and ID
    else User requests preparation
        client->>backend: POST /actions: target and operation
        backend->>docker: Inspect exact target
        docker-->>backend: Current container data
        backend->>backend: Prepare a permitted command
        backend-->>client: Prepared command and ID
    end
    client->>backend: Confirm ID with an idempotency key
    backend->>backend: Validate confirmation and prevent duplicates
    backend->>docker: Recheck target, then restart or stop
    docker-->>backend: Operation outcome
    backend-->>client: Command result
```

The idempotency key identifies one execution attempt so a repeated request can reuse its result. A command whose target
changed is rejected before mutation. The [action lifecycle](architecture.md#prepared-action-lifecycle) explains the
possible outcomes, including an unknown Docker result.

<details>
<summary>Implementation details: preparation, duplicate requests, and execution</summary>

This sequence follows direct API preparation. During diagnosis, `ViewAssembler` calls the same `Actions.prepare`
workflow. A claim reserves one execution; a fingerprint records the observed container identity and state; a target
fence blocks further commands after an unknown result.

```mermaid
sequenceDiagram
    participant client as Operator / client
    participant actions as HTTP / Actions
    participant state as MemoryActions
    participant action as PreparedAction
    participant runtime as Docker adapter
    participant docker as Docker Engine
    participant audit as Audit output

    client->>actions: POST /api/v1/actions
    actions->>runtime: Inspect exact container
    runtime->>docker: Inspect target
    docker-->>runtime: Runtime observations
    runtime-->>actions: Sanitized snapshot and fingerprint
    actions->>actions: Check allowed operation
    actions->>action: Create with owner, target, and expiry
    actions->>state: Store prepared action
    actions-->>client: 201: opaque action ID and target
    client->>client: Review and confirm operation and target
    client->>actions: POST /actions/{id}/execute: confirmed + key
    actions->>state: Claim with actor, key, confirmation, and time
    state->>action: Check ownership, confirmation, expiry, and key
    action-->>state: New claim or replay
    state-->>actions: New claim or existing execution
    alt Same key already claimed
        actions-->>client: Wait for existing execution or return outcome
    else New claim
        actions->>audit: Record action.started
        actions->>state: Lock target and check indeterminate fence
        actions->>runtime: Re-inspect exact target
        runtime->>docker: Inspect target
        docker-->>runtime: Current observations
        runtime-->>actions: Sanitized current snapshot
        actions->>actions: Validate identity, fingerprint, and operation
        alt Revalidation fails
            actions->>action: Finish as failed without mutation
        else Target remains valid
            actions->>runtime: Restart / stop
            runtime->>docker: Execute operation
            docker-->>runtime: Completion or runtime error
            runtime-->>actions: Result or typed failure
            actions->>action: Finish as succeeded / failed / indeterminate
        end
        opt Outcome is indeterminate
            actions->>state: Fence target for this process
        end
        actions->>audit: Record terminal outcome
        actions-->>client: ActionView with current outcome
    end
```

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
