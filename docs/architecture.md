# Backend architecture

## Decision

Use one hexagonal application, deployed as a monolith. Group related behavior
inside its domain and application packages. Keep external technologies in
adapters and construct dependencies in one composition root.

Two layouts were considered. A complete hexagon per feature gives stronger
feature isolation but repeats ports, wiring, and directories. A single hexagon
provides the required dependency boundaries with fewer files and is the proposed
layout for this backend. Split a feature into its own context only when its
language, rules, or ownership require that separation.

## Dependencies

These are allowed source-code dependencies, not the direction of runtime calls:

```text
inbound adapters  -> application -> domain
outbound adapters -> application ports + domain
bootstrap         -> application + adapters
```

- `domain` uses the standard library only. It owns values and business rules.
- `application` owns use cases, ports, tool orchestration, and output contracts.
  Pydantic may validate application DTOs and widget proposals; it must not
  become a base class for domain entities.
- `adapters` translate HTTP, Docker, provider SDKs, storage, and logging into
  application contracts. Application code never imports adapters or settings.
- `bootstrap.py` reads settings, selects adapters, injects dependencies, and
  manages resource lifetimes. `main.py` exposes the FastAPI application factory.
- Use-case functions/classes and their typed commands/results are the inbound
  ports. Do not add an interface that merely duplicates each use-case method.
- Outbound ports are application-owned `Protocol` types. Return owned values,
  not Docker SDK objects, HTTP responses, or provider message classes.

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

This is an ownership map. Create files when their behavior is implemented;
do not scaffold unused packages. Adapters enter through use cases and implement
application-owned ports. Core code does not reach into adapters.

## DDD elements

- Use a consistent vocabulary: Host, ContainerSnapshot, EvidenceRef,
  DiagnosticTurn, PreparedAction, and ActionOutcome.
- Use immutable values for identities, evidence references, action targets,
  and observations. Keep related values in the same cohesive file.
- Treat runtime inventory as an external read model. A container snapshot is
  not an aggregate that pretends to control the Docker daemon.
- `PreparedAction` owns its actor, target, operation, expiry, and legal state
  transitions. Its execution state is the consistency boundary. A store must
  atomically claim it before a runtime mutation can start.
- Keep expiry, confirmation, and transition checks in domain behavior. The
  application supplies the current time and actor, coordinates state access,
  calls the runtime, and records the outcome.
- Domain invariants do not make remote Docker calls transactional. Preserve
  an indeterminate outcome when execution cannot be confirmed.
- Add repositories only for stored state actually used by a workflow. Domain
  events, a generic unit of work, CQRS infrastructure, and an event bus are not
  required for this release.

## Boundaries that matter

- Diagnostics receive a read-only runtime port. Actions receive the mutation
  port. Model tool registration includes no mutation method.
- Collect allowlisted, sanitized evidence before model access. The model
  proposes evidence references, explanation text, and allowed widget types.
  The application validates references and builds cards from real snapshots.
- Widget schemas and their registry belong to application output contracts;
  HTTP request/envelope schemas and SSE encoding belong to the inbound adapter.
  Neither belongs in `domain`. Schema conversion for a model provider belongs
  in that provider's outbound adapter.
- Action preparation is also called directly by the diagnostic workflow when
  it needs to attach an allowed action to a card. It does not call its own API.
- Claim an action and deduplicate execution atomically; serialize mutations
  for the same host/container. Enforce those guarantees in the state adapter,
  while keeping authorization and action rules in the core.
- Cancel diagnostic work when its client disconnects. Once a mutation starts,
  track it to a known or indeterminate outcome even if its caller disconnects.
  A timed-out worker-thread call is not proof that Docker cancelled the action.
- An indeterminate action blocks new mutations for that target for this process
  lifetime. Inspect Docker and reconcile its outcome before restarting the
  backend. In-memory state provides no guarantee across an abrupt process loss.
- Inject a clock callable for time-based rules. Use small fake ports in core
  tests; Docker and model SDKs are unnecessary for those tests.

## File size and verification

- Aim for roughly 100-250 lines per source file; review responsibility and
  cohesion when a file exceeds 300. These are review triggers, not hard limits.
- A leaf package will usually need 3-7 source files. Reconsider its ownership
  when it grows; do not split merely to meet a count or line target.
- Keep related DTOs, enums, and small helpers together. Avoid one file per
  class, empty facades, generic base services, and pass-through layers.
- Add a subpackage when code has a separate responsibility or reason to change.
  Keep HTTP endpoints grouped by resource and provider adapters by provider.
- Enforce import direction in CI with `import-linter`. Verify that application
  imports no adapters, FastAPI, Docker SDK, HTTPX, provider SDKs, or settings;
  verify that domain imports no application, adapter, or third-party package.
- Test domain rules and use cases through fake ports. Test adapter mappings
  separately, then verify HTTP contracts and the real Docker example.

## References

- [Hexagonal architecture](https://alistair.cockburn.us/hexagonal-architecture)
- [DDD aggregates](https://martinfowler.com/bliki/DDD_Aggregate.html)
- [Import Linter forbidden contracts](https://import-linter.readthedocs.io/en/stable/contract_types/forbidden/)
