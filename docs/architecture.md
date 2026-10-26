# Backend architecture

Diagram source: [backend.drawio](diagrams/backend.drawio).

## Decision

Use one hexagonal application, deployed as a monolith. Group related behavior inside its domain and application
packages. Keep external technologies in adapters and construct dependencies in one composition root.

A single hexagon keeps dependency boundaries explicit without repeating ports and wiring for each feature. Split a
feature into its own context when its language, rules, or ownership require that separation.

## Dependencies

Arrows show allowed source-code dependencies. Outbound adapters implement application-owned ports; `bootstrap.py`
selects the concrete implementations and injects them into use cases.

![Allowed source-code dependencies and application-owned ports](diagrams/code-dependencies.png)

`RuntimeQueries` serves Docker reads, `Diagnostics` coordinates model-assisted diagnosis, and `Actions` prepares and
executes confirmed commands. `Diagnostics` uses `ViewAssembler` to build typed responses. Ports are interfaces owned by
the application and implemented by outbound adapters.

- `domain` uses the standard library only. It owns values and business rules.
- `application` owns use cases, ports, tool orchestration, and output contracts. Pydantic may validate application DTOs
  and widget proposals; it must not become a base class for domain entities.
- `adapters` translate HTTP, Docker, provider SDKs, storage, and logging into application contracts. Application code
  never imports adapters or settings.
- `bootstrap.py` reads settings, selects adapters, injects dependencies, and manages resource lifetimes. `main.py`
  exposes the FastAPI application factory.
- Use-case functions/classes and their typed commands/results are the inbound ports. Do not add an interface that merely
  duplicates each use-case method.
- Outbound ports are application-owned `Protocol` types. Return owned values, not Docker SDK objects, HTTP responses, or
  provider message classes.

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
      state.py           # Session/action stores and audit sink
    diagnostics/         # Turn orchestration, tools, context, prompts
    actions.py           # Prepare and execute workflows
    queries.py           # Host/container read workflows
    events.py            # Transport-neutral turn events
    views/               # Widget proposals, registry, server assembly
  adapters/
    inbound/http/        # Routes, HTTP schemas, auth, error mapping, SSE
    outbound/
      docker/            # SDK connections, mapping, port implementations
      models/            # Ollama, OpenAI, Anthropic, compatible API adapters
      memory/            # Bounded session and action stores
      audit.py           # Structured action audit output
```

## DDD elements

- Use a consistent vocabulary: Host, ContainerSnapshot, EvidenceRef, DiagnosticTurn, PreparedAction, and ActionOutcome.
- Use immutable values for identities, evidence references, action targets, and observations. Keep related values in the
  same cohesive file.
- Treat runtime inventory as an external read model. A container snapshot is not an aggregate that pretends to control
  the Docker daemon.
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

`prepared` means awaiting confirmation; `running` means the execution request has been accepted. Expiry is recorded
when the first execution request arrives at or after the deadline. The same idempotency key reuses an existing
execution or retained outcome without another transition. An `indeterminate` outcome blocks further commands for that
target for the backend process lifetime. See the [execution sequence](api.md#actions).

## Boundaries that matter

- Diagnostics receive a read-only runtime port. Actions receive the mutation port. Model tool registration includes no
  mutation method.
- Collect allowlisted, sanitized evidence before model access. The model proposes evidence references, explanation text,
  and allowed widget types. The application validates references and builds cards from real snapshots.
- Widget schemas and their registry belong to application output contracts; HTTP request/envelope schemas and SSE
  encoding belong to the inbound adapter. Neither belongs in `domain`. Schema conversion for a model provider belongs in
  that provider's outbound adapter.
- Action preparation is also called directly by the diagnostic workflow when it needs to attach an allowed action to a
  card. It does not call its own API.
- Claim an action and deduplicate execution atomically; serialize mutations for the same host/container. Enforce those
  guarantees in the state adapter, while keeping authorization and action rules in the core.
- Cancel diagnostic work when its client disconnects. Once a mutation starts, track it to a known or indeterminate
  outcome even if its caller disconnects. A timed-out worker-thread call is not proof that Docker cancelled the action.
- An indeterminate action blocks new mutations for that target for this process lifetime. Inspect Docker and reconcile
  its outcome before restarting the backend. In-memory state provides no guarantee across an abrupt process loss.
- Inject a clock callable for time-based rules. Use small fake ports in core tests; Docker and model SDKs are
  unnecessary for those tests.

## Verification

- Enforce import direction in CI with `import-linter`. Verify that application imports no adapters, FastAPI, Docker SDK,
  HTTPX, provider SDKs, or settings; verify that domain imports no application, adapter, or third-party package.
- Test domain rules and use cases through fake ports. Test adapter mappings separately, then verify HTTP contracts and
  the real Docker example.

## References

- [Hexagonal architecture](https://alistair.cockburn.us/hexagonal-architecture)
- [DDD aggregates](https://martinfowler.com/bliki/DDD_Aggregate.html)
- [Import Linter forbidden contracts](https://import-linter.readthedocs.io/en/stable/contract_types/forbidden/)
