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
| `MODEL_STRUCTURED_OUTPUT` | `native` | Compatible and Gemini providers also support `tool` |
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
| Gemini | [Gemini](../examples/providers/gemini.env.example) |
| Compatible API | [Compatible server](../examples/providers/compatible.env.example) |

OpenAI, Anthropic, and Gemini also accept `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, and `GEMINI_API_KEY`, respectively.
`DOCKSIGHT_MODEL_API_KEY` takes precedence. Cloud providers receive the sanitized
Docker evidence selected by the diagnostic loop. Log redaction is best effort; review what your workload writes to logs.

The header model selector also offers secondary providers configured on the server. Set `DOCKSIGHT_OPENAI_API_KEY`,
`DOCKSIGHT_ANTHROPIC_API_KEY`, or `DOCKSIGHT_GEMINI_API_KEY`; these take precedence over the standard key names above.
Both forms load from the root `.env` file. Optional `DOCKSIGHT_<PROVIDER>_BASE_URL` settings override secondary endpoints,
where `<PROVIDER>` is `OLLAMA`, `OPENAI`, `ANTHROPIC`, `GEMINI`, or `COMPATIBLE`. Ollama defaults to loopback.
Compatible requires `DOCKSIGHT_COMPATIBLE_BASE_URL` and optionally `DOCKSIGHT_COMPATIBLE_API_KEY`.
`DOCKSIGHT_OLLAMA_API_KEY` supports authenticated Ollama gateways.
Legacy `DOCKSIGHT_PROVIDER`, `DOCKSIGHT_MODEL`, `DOCKSIGHT_MODEL_BASE_URL`, and `DOCKSIGHT_MODEL_API_KEY` continue to
define the default connection. Provider-specific endpoint settings apply to secondary connections.
For secondary compatible/Gemini endpoints requiring schema output through a forced tool, set
`DOCKSIGHT_COMPATIBLE_STRUCTURED_OUTPUT=tool` or `DOCKSIGHT_GEMINI_STRUCTURED_OUTPUT=tool` (default: `native`).
The default connection continues to use `DOCKSIGHT_MODEL_STRUCTURED_OUTPUT`.

For aliases or providers without a catalog endpoint, explicitly allow fallback IDs using a JSON object of arrays:

```dotenv
DOCKSIGHT_PROVIDER_FALLBACK_MODELS={"openai":["your-model-alias"],"compatible":["your-local-model"]}
```

Use at most 100 IDs of 1–256 characters per provider. The first fallback is the secondary provider's default model;
without one, the operator chooses a catalog row. The legacy default model is always allowed without a catalog request.
The browser cannot submit endpoints or keys. Provider/model selection affects the next question and its status check;
sessions, history, prepared actions, redaction, and the global turn concurrency budget remain shared.

Catalogs load lazily, retain successful rows for five minutes, and share concurrent refresh requests. Stale rows return
immediately while refreshing in the background. Requests have a five-second total deadline; failures retain prior rows
and impose a 30-second retry cooldown, including manual refresh. Each metadata page is limited to 256 KiB, with at most
20 pages and 1,900 catalog IDs. Partial or unsupported catalogs return an explicit failure code and preserve fallbacks.
Metadata listings do not verify generation access, tool calling, or structured output. Cache and clients live in the
backend process and close at shutdown.

Gemini uses Google's [OpenAI-compatible API](https://ai.google.dev/gemini-api/docs/openai) at
`https://generativelanguage.googleapis.com/v1beta/openai/` by default. Remove an old `DOCKSIGHT_MODEL_BASE_URL`
override when switching providers. Tool-call signatures are retained internally for multi-step Gemini diagnostics.
Server-created preliminary reads use Google's documented signature marker; model-issued signatures replay unchanged.
Use `gemini-3.5-flash-lite`. Google rejects generation with `gemini-2.5-flash-lite` for new users, even when its
metadata lookup succeeds. A successful metadata check does not guarantee access to generation.
For a Compose service, put these settings in its `environment` mapping and supply the key from your local environment:

```yaml
environment:
  DOCKSIGHT_PROVIDER: gemini
  DOCKSIGHT_MODEL: gemini-3.5-flash-lite
  DOCKSIGHT_MODEL_API_KEY: ${GEMINI_API_KEY:?Set GEMINI_API_KEY}
```

Keep `DOCKSIGHT_API_TOKEN` as the separate credential used by the browser to authenticate to DockSight.

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
