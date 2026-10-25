# DockSight

Docker diagnostics with evidence-linked UI cards and confirmed restart/stop
actions. This repository currently contains the backend and an HTTP demo client.

## Run locally

Requires Python 3.12+, uv, Docker Engine/Desktop, and a tool-capable model server.
Run commands from the repository root.

```powershell
uv sync --project backend --locked
Copy-Item .env.example .env
uv run --project backend python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Replace `DOCKSIGHT_API_TOKEN` in `.env` with the generated value. Start Ollama
and ensure `qwen3.5:9b` is available, or use a configuration from
`examples/providers/`. OpenAI and Anthropic also accept their standard API-key
environment variables. Choose a model that supports tools and structured output.

```powershell
uv run --project backend uvicorn docksight.main:create_app --factory --host 127.0.0.1 --port 8000 --workers 1
```

Open [API documentation](http://127.0.0.1:8000/docs) and enter the token through
Authorize. Health endpoints check application readiness without contacting
Docker or a model. Provider requests happen only during diagnostic turns.

On Linux/macOS, use `cp .env.example .env` instead of `Copy-Item`.

## Working example

The demo worker exits on its first start and runs after a confirmed restart.
Its retry marker is stored in a dedicated demo volume.

```powershell
docker compose -f examples/compose.yaml up -d
uv run --project backend python examples/demo.py diagnose
```

Review the diagnosis, evidence, and `actions` in the returned card. Copy an
action ID and confirm it explicitly:

```powershell
uv run --project backend python examples/demo.py execute ACTION_ID --confirm --key review-restart-1
uv run --project backend python examples/demo.py state ACTION_ID
docker compose -f examples/compose.yaml ps -a
```

Reuse the same idempotency key when retrying that execution request. To reset
the example, `docker compose -f examples/compose.yaml down -v` removes only this
demo stack and its state volume.

## Configuration

Settings use the `DOCKSIGHT_` prefix and can be loaded from the root `.env`.
Array settings use JSON, for example `DOCKSIGHT_ENV_ALLOWLIST=["APP_ENV"]`.

| Setting | Default | Purpose |
| --- | --- | --- |
| `PROVIDER` / `MODEL` | `ollama` / `qwen3.5:9b` | Independent provider and model selection |
| `MODEL_BASE_URL` / `MODEL_API_KEY` | Provider default / unset | Server endpoint and credentials |
| `MODEL_STRUCTURED_OUTPUT` | `native` | Compatible adapter also supports `tool` |
| `HOSTS_FILE` | unset | Configured hosts; see `examples/hosts.yaml` |
| `ENV_ALLOWLIST` / `CORS_ORIGINS` | `[]` / `[]` | Explicit environment fields and browser origins |
| `MAX_MODEL_CALLS` / `MAX_TOOL_CALLS` | `6` / `12` | Per-turn budgets, including finalization and repair |
| `MODEL_TIMEOUT` / `TURN_TIMEOUT` | `60` / `180` seconds | Request and total turn deadlines |
| `LOG_LINES` / `LOG_BYTES` | `200` / `65536` | Log response bounds |

Local Docker follows the current context and Docker environment variables.
SSH uses the Docker SDK's Paramiko transport, SSH agent/config, and verified
`~/.ssh/known_hosts`. Use `ProxyCommand` for jump hosts. TCP hosts require mTLS.
Inspect and environment fields are allowlisted; log redaction is best effort.
Cloud providers receive the sanitized evidence selected by the diagnostic loop.

## Development

```powershell
uv run --project backend ruff check backend examples
uv run --project backend ruff format --check backend examples
uv run --project backend pyright --project backend
uv run --project backend lint-imports --config backend/pyproject.toml
uv run --project backend pytest backend/tests
```

Docker tests are opt-in. Pull `python:3.12-alpine` first, then set
`DOCKSIGHT_TEST_DOCKER=1` and run `pytest backend/tests/integration -m docker`
through `uv run --project backend`. They remove only containers they create.
Live model tests use `DOCKSIGHT_TEST_LIVE_MODEL=1` and the configured provider;
cloud tests make paid API calls and are never enabled in CI.
Diagnostic cases are stored in `backend/tests/fixtures/diagnostics.json`.
Remote read tests use `DOCKSIGHT_TEST_REMOTE=1`, `DOCKSIGHT_HOSTS_FILE`, and
`DOCKSIGHT_TEST_HOST`. They never mutate the remote environment.

Build the backend image with `docker build -f backend/Dockerfile -t docksight-backend:local .`.
It runs as UID 10001. Mount host configuration and credentials read-only; grant
the socket's group explicitly if using a local Docker socket. When containerized,
Ollama's endpoint must be reachable from the container, for example through
`host.docker.internal` on Docker Desktop.
Set `DOCKSIGHT_TEST_BACKEND_IMAGE=docksight-backend:local` alongside the Docker
test flag to run the built-image health check.

Use one backend worker. Sessions, action records, and idempotency state live in
bounded memory and disappear on restart. An indeterminate action fences its
target until the operator checks Docker and restarts the backend. No frontend,
environment editing, or stack deployment is included in this release.

[Architecture](docs/architecture.md) · [API contract](docs/api.md) · [Backend plan](docs/backend-plan.md)
