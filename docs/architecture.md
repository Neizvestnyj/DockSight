# Backend architecture

Diagram source: [backend.drawio](diagrams/backend.drawio).

See the [system overview](../README.md#how-it-works) for the diagnostic data flow.

## Decision

The backend is a monolith with one hexagonal boundary. Related behavior shares domain and application packages.
Adapters contain external technologies. The composition root constructs dependencies.
Split a feature into its own context when its language, rules, or ownership require it.

![Hexagonal backend with core-owned ports and technology adapters](diagrams/hexagonal-architecture.png)

Arrows show runtime calls. Source-code dependencies point inward: the core does not import adapters. Memory adapters
run in the same process as the core.

## Dependencies

Arrows show allowed source-code dependencies. Outbound adapters implement application-owned ports. `bootstrap.py`
selects the concrete implementations and injects them into use cases.
Inbound and outbound adapters do not import each other, directly or indirectly. They interact through application-owned
contracts. The composition root may import both to construct the application.

![Allowed source-code dependencies and application-owned ports](diagrams/code-dependencies.png)

| Component | Responsibility |
|-----------|----------------|
| `RuntimeQueries` | Docker reads |
| `Diagnostics` | Model calls, tools, and evidence collection |
| `ViewAssembler` | Typed responses built from model proposals and collected facts |
| `Actions` | Action preparation and confirmed execution |
| `SystemStatus` | Docker and provider metadata checks |
| `ModelChoices` | Provider/model selection against server-owned catalogs |
| `CatalogCache` | Shared metadata fetches, freshness, failure cooldown, and cancellation |

- `domain` uses the standard library only. It owns values and business rules.
- `application` owns use cases, ports, tool orchestration, and output contracts. Pydantic may validate application DTOs
  and widget proposals. Domain entities do not inherit from Pydantic.
- `adapters` translate HTTP, Docker, provider SDKs, storage, and logging into application contracts. Application code
  never imports adapters or settings.
- `bootstrap.py` reads settings, selects adapters, injects dependencies, and manages resource lifetimes. `main.py`
  exposes the FastAPI application factory.
- Use-case functions/classes and their typed commands/results are the inbound ports. Do not add an interface that merely
  duplicates each use-case method.
- Outbound ports are application-owned `Protocol` types. Return owned values, not Docker SDK objects, HTTP responses, or
  provider message classes.

### Diagnostic turns

- Scope discovery supplies observed Compose/Swarm identities to the model tool loop.
- Broad incident questions collect a bounded local-host overview before model exploration. Counts, member state,
  collection limits, and fact cards belong to the server. A model cannot replace the overview with a group chooser.
- Narrowing to a group or exact container starts a separate investigation with fresh observations.
- Ambiguous names require a choice validated against discovery. That turn ends without a diagnosis or history entry.
  Container/group collisions include the container's exact identity. The client continues the same question and session
  with an explicit target, revalidated against fresh Docker data.
- Each turn owns a bounded evidence context and read-result memo. Repeated successful reads with the same arguments and
  scope return existing evidence references. Failures are not cached. A batch of only reused reads ends exploration.
- Final generation omits unvalidated prose drafts and includes a bounded recap of the latest lifecycle facts.
  Earlier questions and summaries are labeled as historical context.
- Schema and evidence-reference validation do not verify explanations. Causal regression tests detect selected known
  contradictions. They do not filter runtime responses.

### Status and model connections

`SystemStatus` uses `RuntimeReadPort.ping` and `ModelStatusPort`, with independent deadlines, public reason codes, and UTC
check times. It never calls `ModelPort.complete` or changes diagnostic or action state.
The metadata adapter owns provider-specific HTTP routes and credentials.

The catalog adapter owns pagination and HTTP handling. Bootstrap creates one reusable connection per configured
provider on demand. Selected adapters share those clients. `Diagnostics` instances share sessions, redaction, action
assembly, and the concurrency semaphore. Each turn keeps its own model and trace identity.

## Layout

```text
backend/src/docksight/
  main.py
  bootstrap.py
  domain/
    runtime.py           # Host/container identity and runtime snapshots
    diagnostics.py       # Evidence references and diagnostic conclusions
    actions.py           # PreparedAction and execution-state rules
    errors.py            # Domain failures
  application/
    ports/
      runtime.py         # Separate runtime read and mutation protocols
      models.py          # Provider-neutral model protocol and messages
      status.py          # Non-generative provider metadata checks
      state.py           # Session/action stores and audit sink
    diagnostics/         # Turn orchestration, bounded trace, tools, context, prompts
    actions.py           # Prepare and execute workflows
    queries.py           # Host/container read workflows
    system_status.py     # Bounded dependency checks and safe public results
    model_catalog.py     # Public model metadata and bounded in-memory refreshes
    model_choices.py     # Validated provider/model selection
    events.py            # Transport-neutral turn events
    views/               # Widget proposals, registry, server assembly
  adapters/
    inbound/http/        # Routes, HTTP schemas, auth, error mapping, SSE
    outbound/
      docker/            # SDK connections, mapping, port implementations
      models/            # Ollama, OpenAI, Anthropic, Gemini/compatible API adapters
      memory/            # Bounded session and action stores
      audit.py           # Structured action audit output
```

## DDD elements

- Use a consistent vocabulary: Host, ContainerSnapshot, EvidenceRef, DiagnosticTurn, PreparedAction, and ActionOutcome.
- Use immutable values for identities, evidence references, action targets, and observations. Keep related values in the
  same cohesive file.
- Treat runtime inventory as an external read model. Container snapshots do not control the Docker daemon.
- `PreparedAction` owns its actor, target, operation, expiry, and legal state transitions. Its execution state is the
  consistency boundary. A store must atomically claim it before a runtime mutation can start.
- Keep expiry, confirmation, and transition checks in domain behavior. The application supplies the current time and
  actor, coordinates state access, calls the runtime, and records the outcome.
- Domain invariants do not make remote Docker calls transactional. Preserve an indeterminate outcome when execution
  cannot be confirmed.
- Add repositories only for stored state actually used by a workflow. Domain events, a generic unit of work, CQRS
  infrastructure, and an event bus are not required for this release.

### Prepared action lifecycle

![Prepared action states and permitted transitions](diagrams/action-lifecycle.png)

`prepared` awaits confirmation. `running` records acceptance of an execution request. Expiry is recorded
when the first execution request arrives at or after the deadline. The same idempotency key reuses an existing
execution or retained outcome without another transition. An `indeterminate` outcome blocks further commands for that
target for the backend process lifetime. See the [execution sequence](api.md#actions).

## Runtime boundaries

- `DockSightError` carries a safe public code, message, and transport-independent `ErrorKind`. The HTTP adapter maps
  the category to a response status. One public code may have different categories depending on context.
  Core rules and outbound adapters do not select HTTP statuses.
- Diagnostics receive a read-only runtime port. Actions receive the mutation port. Model tool registration includes no
  mutation method.
- Collect allowlisted, sanitized evidence before model access. The model proposes evidence references, explanation text,
  and allowed widget types. The application validates references and builds cards from real snapshots.
- Widget schemas and their registry belong to application output contracts. HTTP request/envelope schemas and SSE
  encoding belong to the inbound adapter. Neither belongs in `domain`. Schema conversion for a model provider belongs in
  that provider's outbound adapter.
- Diagnostics call action preparation directly to attach permitted actions to cards.
- Claim an action and deduplicate execution atomically. Serialize mutations for the same host/container. Enforce those
  guarantees in the state adapter, while keeping authorization and action rules in the core.
- Cancel diagnostic work when its client disconnects. Once a mutation starts, track it to a known or indeterminate
  outcome even if its caller disconnects. A timed-out worker-thread call is not proof that Docker cancelled the action.
- An indeterminate action blocks new mutations for that target for this process lifetime. Inspect Docker and reconcile
  its outcome before restarting the backend. In-memory state provides no guarantee across an abrupt process loss.
- Inject a clock callable for time-based rules. Core tests use small fake ports without Docker or model SDKs.

## Verification

- Enforce import direction in CI with `import-linter`. Verify that application imports no adapters, FastAPI, Docker SDK,
  HTTPX, provider SDKs, or settings. Verify that domain imports no application, adapter, or third-party package.
  An independence contract rejects direct and indirect imports between inbound and outbound adapters.
- Test domain rules and use cases through fake ports. Test adapter mappings separately, then verify HTTP contracts and
  the real Docker example.

## References

- [Hexagonal architecture](https://alistair.cockburn.us/hexagonal-architecture)
- [DDD aggregates](https://martinfowler.com/bliki/DDD_Aggregate.html)
- [Import Linter forbidden contracts](https://import-linter.readthedocs.io/en/stable/contract_types/forbidden/)
