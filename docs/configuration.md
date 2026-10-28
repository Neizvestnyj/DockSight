# Configuration and deployment

See the [quick start](../README.md#connect-your-docker-environment) for local setup.
Settings use the `DOCKSIGHT_` prefix and load from environment variables or the root `.env` file.
Keep credentials in environment variables or external secret files; never put them in tracked configuration.

## Settings

Names below omit the `DOCKSIGHT_` prefix. Array values use JSON, for example `DOCKSIGHT_ENV_ALLOWLIST=["APP_ENV"]`.

| Setting | Default | Purpose |
|---------|---------|---------|
| `API_TOKEN` | Required | Bearer token of at least 24 characters |
| `PROVIDER` / `MODEL` | `ollama` / `qwen3.5:9b` | Independent provider and model selection |
| `MODEL_BASE_URL` / `MODEL_API_KEY` | Provider default / unset | Model endpoint and credentials |
| `MODEL_STRUCTURED_OUTPUT` | `native` | Compatible adapter also supports `tool` |
| `OLLAMA_CONTEXT_LENGTH` | `16384` tokens | Native Ollama context for prompts, tools, and replies |
| `HOSTS_FILE` | Unset | Configured Docker hosts; see [hosts.yaml](../examples/hosts.yaml) |
| `ENV_ALLOWLIST` / `CORS_ORIGINS` | `[]` / `[]` | Environment fields and allowed browser origins |
| `MAX_MODEL_CALLS` / `MAX_TOOL_CALLS` | `6` / `12` | Per-turn budgets, including finalization and repair |
| `MODEL_TIMEOUT` / `TURN_TIMEOUT` | `60` / `180` seconds | Model request and total turn deadlines |
| `LOG_LINES` / `LOG_BYTES` | `200` / `65536` | Log response bounds |

The [.env example](../.env.example) includes browser origins for local development and preview.
Generate a token with:

```sh
uv run --project backend python -c "import secrets; print(secrets.token_urlsafe(32))"
```

## Model providers

Choose a model that supports tool calls and structured output. Use the matching example as the model-settings portion
of your root `.env`, retaining your API token and browser settings:

| Provider | Configuration example |
|----------|-----------------------|
| Ollama | [Local Ollama](../examples/providers/ollama.env.example) |
| OpenAI | [OpenAI](../examples/providers/openai.env.example) |
| Anthropic | [Anthropic](../examples/providers/anthropic.env.example) |
| Compatible API | [Compatible server](../examples/providers/compatible.env.example) |

OpenAI and Anthropic also accept their standard API-key environment variables. Cloud providers receive the sanitized
Docker evidence selected by the diagnostic loop. Log redaction is best effort; review what your workload writes to logs.

Native Ollama requests set an explicit context window. A small server default can truncate the query and tool results.
Increase `DOCKSIGHT_OLLAMA_CONTEXT_LENGTH` for larger inventories or logs; larger contexts need more memory.

The UI system-status panel checks Docker availability and provider/model metadata. It does not verify generation,
tool calling, or structured output. Those require a diagnostic request. Public health endpoints check process liveness
and application wiring without contacting Docker or a model. See [dependency status](api.md#dependency-status).

## Docker hosts

Without a hosts file, local Docker follows the current Docker context and Docker environment variables.
For explicit hosts, set `DOCKSIGHT_HOSTS_FILE` to a YAML file based on [hosts.yaml](../examples/hosts.yaml).
API requests select a configured host ID; they cannot supply arbitrary connection URLs.

- **Local:** omit the host URL to use the current Docker context and environment.
- **SSH:** uses the Docker SDK's Paramiko transport, SSH agent/config, and verified `~/.ssh/known_hosts`.
  Use `ProxyCommand` for jump hosts.
- **TCP:** requires mTLS with CA, client certificate, and private key paths.

SSH connection, banner, authentication, and channel waits have bounded timeouts. DNS resolution, SSH agent operations,
and external `ProxyCommand` processes also depend on system-level limits. Inspect and environment fields are allowlisted.

## Frontend deployment

Build and preview locally:

```sh
npm --prefix frontend run build
npm --prefix frontend run preview -- --port 4173
```

Vite development and preview forward `/api` to `http://127.0.0.1:8000`. For deployment, serve `frontend/dist/` and
reverse-proxy `/api` to the backend, or enter a separately hosted HTTPS API base ending in `/api/v1`.
For a separate origin, include the exact frontend origin in `DOCKSIGHT_CORS_ORIGINS`.
The production build self-hosts IBM Plex fonts.

The browser holds API credentials in memory. Never put tokens in source, browser storage, URLs, or `VITE_*` variables.
Reload returns to Demo and requires reconnecting. Only the locale preference is persisted.

## Backend image

```sh
docker build -f backend/Dockerfile -t docksight-backend:local .
```

The image uses Python 3.14 on Debian slim and runs as UID 10001. Slim retains glibc compatibility for native wheels;
Alpine uses musl and is reserved for the demo worker. Mount host configuration and credentials read-only. Grant the
Docker socket's group explicitly when using a local socket.

Ollama must be reachable from inside the container. On Docker Desktop, use `host.docker.internal` in its configured
endpoint instead of the container's loopback address. Bind the API to loopback by default and require authentication.

## Process state and recovery

Run one backend worker. Sessions, action records, and idempotency state live in bounded process memory and disappear
on restart. Browser investigations live in the current tab; streams have no replay or automatic reconnection.

An `indeterminate` action means Docker may have accepted the operation. It blocks further mutations of that target
for the backend process lifetime. Check Docker directly before restarting the backend or preparing another action.
Never retry a Docker mutation automatically after an ambiguous result. See [action outcomes](api.md#actions).
