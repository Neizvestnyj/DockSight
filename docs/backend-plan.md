# Backend implementation plan

Build a runnable Docker diagnostic API that returns validated UI cards and
executes confirmed actions. Keep the frontend for the next iteration.

Use the hexagonal boundaries and selective DDD rules in
[Backend architecture](architecture.md).

## Repository

```text
backend/
  pyproject.toml
  uv.lock
  src/docksight/
    main.py          # HTTP application factory
    bootstrap.py     # Settings, dependency wiring, lifecycle
    domain/          # Values, evidence, action invariants
    application/     # Use cases, owned ports, events, widget contracts
    adapters/
      inbound/http/  # Routes, authentication, HTTP schemas, SSE
      outbound/      # Docker, model providers, state stores, audit
  tests/{unit,integration}/
examples/            # Demo Compose stack, client, provider configurations
docs/                # Architecture, API contracts, development notes
.github/workflows/   # Backend checks
```

Add `frontend/` in the next iteration. The application owns the runtime, model,
state, and audit ports. Adapters implement those ports; only the composition
root selects concrete implementations. Keep widgets and Pydantic schemas out
of the domain. Group related behavior without repeating a hexagon per feature.

## Decisions

- Use Python 3.12+, FastAPI, Pydantic v2, `pydantic-settings`, `uv`, Ruff,
  Pyright strict, import-linter, pytest, pytest-asyncio, and HTTPX.
- Use Docker SDK for Python, with bounded worker-thread calls. Support local
  Unix sockets, Windows named pipes, SSH through the system client, and mTLS.
- Implement native Ollama, OpenAI Responses, and Anthropic Messages adapters,
  plus an OpenAI-compatible Chat Completions adapter for other servers.
  Use HTTPX for Ollama and official SDKs for OpenAI and Anthropic.
- Configure provider, model, endpoint, credentials, and limits independently.
  `qwen3.5:9b` is the local example, not an application dependency. Check model
  capabilities; return a clear error when required features are unavailable.
- Start with one backend worker and bounded in-memory conversation/action
  stores. State expires and is lost on restart. No database or task queue.
- Treat this release as a single-operator, self-hosted service. Bind to
  `127.0.0.1`, require a configured bearer token, and restrict browser origins.

## Delivery order

Each implementation step includes focused tests and a local commit. Run Ruff,
Pyright, and the relevant tests before that commit. Keep all Markdown and
docstrings concise and in English.

1. **Foundation.** Add package configuration, locked dependencies, app factory,
   settings, structured logging, error responses, health endpoints, `.gitignore`,
   `.gitattributes`, `.env.example`, and CI. Enforce inward import dependencies
   with import-linter. Provide direct `uv` commands for Windows and Linux. Done
   when the API starts, invalid settings fail clearly, and forbidden dependency
   fixtures fail the architecture checks.

2. **Contracts.** Define domain values and PreparedAction state rules, then
   application-owned ports, provider messages, tool calls, and response/events.
   Use separate runtime read/mutation ports and owned store/audit contracts. Add
   `container_status`, `log_anomalies`, `compose_stack`, and read-only
   `env_inspector` application view contracts. Keep HTTP schemas in the inbound
   adapter, OOM evidence separate from container state, and missing metrics
   explicit. Done when domain transitions and contract validation
   reject invalid actions, widgets, references, and unexpected fields.

3. **Docker access.** Implement configured host resolution, listing, inspect,
   bounded logs, stats, and Compose grouping. Add Swarm service summaries on
   manager hosts; report unsupported operations explicitly. Verify SSH host
   keys and TLS certificates. Allowlist inspect/env fields and sanitize logs
   before they enter model context or application logs. Done when real local
   Docker fixtures pass; SSH and mTLS smoke tests remain opt-in with explicit
   host configuration.

4. **Model providers.** Normalize tool calls/results, structured responses,
   refusal, usage, timeout, rate-limit, and cancellation behavior. Convert schemas
   for each provider and validate outputs against the original application
   schema. Keep credentials out of API responses. Done when representative HTTP
   fixtures exercise all adapters without a running model or paid requests.

5. **Diagnostics.** Implement read-only tools and the bounded agent loop.
   Gather evidence, produce a diagnosis, then request the final card selection
   under a JSON schema. Assemble factual card fields from stored snapshots.
   Default limits: 6 model calls including finalization/repair, 12 tool calls,
   200 log lines and 64 KiB per log result, and 180 seconds per turn; make them
   configurable. Allow at most one schema-repair attempt within that budget.
   Done when known failures produce supported conclusions and insufficient
   evidence produces an explicit uncertainty response.

6. **Actions.** Implement restart and stop through a separate application
   service. The server prepares caller-bound action IDs with a five-minute
   expiry; execution requires confirmation and an idempotency key. Recheck the
   exact container ID and relevant state, serialize mutations per target, and
   record outcomes through the audit port. Track started mutations even if their
   client disconnects. Return an indeterminate outcome after an ambiguous Docker
   timeout; do not retry it. Done when duplicate, expired, unconfirmed, and stale
   actions cannot cause an unintended mutation. Models receive no write tools.

7. **HTTP and streaming.** Expose `/api/v1/hosts`, scoped container reads,
   `POST /api/v1/chat/turns`, `POST /api/v1/actions`,
   `POST /api/v1/actions/{action_id}/execute`, and
   `GET /api/v1/widgets/schema`. Stream turn/tool progress and heartbeats over
   SSE; publish answer text and cards only after validation. Define one terminal
   completion/failure event, request IDs, bounded sessions, and disconnect
   cancellation. Document POST streaming through `fetch` or a streaming HTTP
   client. Done when HTTP contract tests cover authentication, host isolation,
   errors, SSE ordering, cancellation, and concurrent requests.

8. **Working example.** Add an isolated Compose stack with a failing worker,
   an HTTP demo client, a backend Dockerfile, and a short README. Demonstrate
   diagnosis, evidence-linked cards, explicit restart confirmation, and updated
   container state. Add opt-in live smoke tests for configured providers and
   preserve a small diagnostic evaluation set. Done when a clean checkout can
   run the full example with Ollama; switching to OpenAI or Anthropic requires
   only configuration and credentials. Report which live paths were exercised.

## Acceptance cases

- Domain rules and use cases run against fake ports without FastAPI, Docker,
  provider SDKs, or network access. CI rejects imports that cross core boundaries.
- A healthy container, a crash loop, OOM evidence, a failed dependency, and
  missing/truncated logs produce valid responses grounded in collected evidence.
- Instructions embedded in logs cannot introduce tools, hosts, or actions.
  Secret fixtures do not appear in model requests, responses, or audit output.
- Malformed/refused model output, unavailable hosts, Docker timeouts, and client
  disconnects terminate predictably without leaking credentials or resources.
- Two identical execution requests trigger at most one Docker mutation while
  their action record is retained. A backend restart invalidates all outstanding
  action IDs.
- CI runs without cloud credentials. Real Docker fixtures clean up only their
  own resources. Remote transport and paid-provider checks are explicit opt-ins.

## Later iterations

Frontend rendering; environment editing with container recreation; Compose and
Swarm deployments; persistent sessions/audit storage; multi-user access control;
additional runtimes and third-party widget plugins.

## References

- [Docker SDK client](https://docker-py.readthedocs.io/en/stable/client.html)
- [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs)
- [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling)
- [Anthropic structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
