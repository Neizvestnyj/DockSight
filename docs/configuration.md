# Configuration and deployment

See the [quick start](../README.md#connect-your-docker-environment) for local setup.
Settings use the `DOCKSIGHT_` prefix and load from environment variables or the root `.env` file.
Keep credentials in environment variables or external secret files; never put them in tracked configuration.

## Settings

Names below omit the `DOCKSIGHT_` prefix. Array values use JSON, for example `DOCKSIGHT_ENV_ALLOWLIST=["APP_ENV"]`.

| Setting                              | Default                  | Purpose                                                           |
|--------------------------------------|--------------------------|-------------------------------------------------------------------|
| `API_TOKEN`                          | Required                 | Bearer token of at least 24 characters                            |
| `PROVIDER` / `MODEL`                 | `ollama` / `qwen3.5:9b`  | Independent provider and model selection                          |
| `MODEL_BASE_URL` / `MODEL_API_KEY`   | Provider default / unset | Model endpoint and credentials                                    |
| `MODEL_STRUCTURED_OUTPUT`            | `native`                 | Compatible and Gemini providers also support `tool`               |
| `OLLAMA_CONTEXT_LENGTH`              | `16384` tokens           | Native Ollama context for prompts, tools, and replies             |
| `HOSTS_FILE`                         | Unset                    | Configured Docker hosts; see [hosts.yaml](../examples/hosts.yaml) |
| `ENV_ALLOWLIST` / `CORS_ORIGINS`     | `[]` / `[]`              | Environment fields and allowed browser origins                    |
| `MAX_MODEL_CALLS` / `MAX_TOOL_CALLS` | `6` / `12`               | Per-turn budgets, including finalization and repair               |
| `MODEL_TIMEOUT` / `TURN_TIMEOUT`     | `60` / `180` seconds     | Model request and total turn deadlines                            |
| `LOG_LINES` / `LOG_BYTES`            | `200` / `65536`          | Log response bounds                                               |

The [.env example](../.env.example) includes browser origins for local development and preview.
Generate a token with:

```sh
uv run --project backend python -c "import secrets; print(secrets.token_urlsafe(32))"
```

## Model providers

Choose a model that supports tool calls and structured output. Use the matching example as the model-settings portion
of your root `.env`, retaining your API token and browser settings:

| Provider       | Configuration example                                             |
|----------------|-------------------------------------------------------------------|
| Ollama         | [Local Ollama](../examples/providers/ollama.env.example)          |
| OpenAI         | [OpenAI](../examples/providers/openai.env.example)                |
| Anthropic      | [Anthropic](../examples/providers/anthropic.env.example)          |
| Gemini         | [Gemini](../examples/providers/gemini.env.example)                |
| Compatible API | [Compatible server](../examples/providers/compatible.env.example) |

Cloud providers receive the sanitized Docker evidence selected by the diagnostic loop. Log redaction is best effort;
review what your workload writes to logs.

### Default model

`DOCKSIGHT_PROVIDER` and `DOCKSIGHT_MODEL` select the default model. Use `DOCKSIGHT_MODEL_BASE_URL` for its endpoint,
`DOCKSIGHT_MODEL_API_KEY` for its credentials, and `DOCKSIGHT_MODEL_STRUCTURED_OUTPUT` for its output mode.
Requests without a model selection use this connection.

OpenAI, Anthropic, and Gemini also accept `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, and `GEMINI_API_KEY`, respectively.
The corresponding `DOCKSIGHT_OPENAI_API_KEY`, `DOCKSIGHT_ANTHROPIC_API_KEY`, or `DOCKSIGHT_GEMINI_API_KEY` takes precedence
over the standard name. `DOCKSIGHT_MODEL_API_KEY` overrides both for the default model. These settings load from the root
`.env` file or environment variables.

### Additional providers

The header model selector offers other providers configured on the server. Their settings are independent of the
default connection:

| Provider       | Enable it                                            | Optional settings                                                        |
|----------------|------------------------------------------------------|--------------------------------------------------------------------------|
| Ollama         | Available at loopback by default                     | `DOCKSIGHT_OLLAMA_BASE_URL`, `DOCKSIGHT_OLLAMA_API_KEY`                  |
| OpenAI         | `DOCKSIGHT_OPENAI_API_KEY` or `OPENAI_API_KEY`       | `DOCKSIGHT_OPENAI_BASE_URL`                                              |
| Anthropic      | `DOCKSIGHT_ANTHROPIC_API_KEY` or `ANTHROPIC_API_KEY` | `DOCKSIGHT_ANTHROPIC_BASE_URL`                                           |
| Gemini         | `DOCKSIGHT_GEMINI_API_KEY` or `GEMINI_API_KEY`       | `DOCKSIGHT_GEMINI_BASE_URL`, `DOCKSIGHT_GEMINI_STRUCTURED_OUTPUT`        |
| Compatible API | `DOCKSIGHT_COMPATIBLE_BASE_URL`                      | `DOCKSIGHT_COMPATIBLE_API_KEY`, `DOCKSIGHT_COMPATIBLE_STRUCTURED_OUTPUT` |

For additional Gemini or compatible endpoints that require schema output through a forced tool, set their
`STRUCTURED_OUTPUT` setting to `tool` (default: `native`). Provider-specific endpoint and output-mode settings apply only
when that provider is not the default; the default uses the `DOCKSIGHT_MODEL_*` settings above.

The browser selects only provider/model identities; it cannot submit endpoints or keys. Selection affects the next
question and its status check. Sessions, prepared actions, and the global turn concurrency budget remain shared.

### Model catalogs

For aliases or providers without a catalog endpoint, allow model IDs using a JSON object of arrays:

```dotenv
DOCKSIGHT_PROVIDER_FALLBACK_MODELS={"openai":["your-model-alias"],"compatible":["your-local-model"]}
```

Use at most 100 IDs of 1–256 characters per provider. The first ID is the initial model for an additional provider;
without one, the operator chooses a catalog row. The configured default model is allowed without a catalog request.

Catalogs load lazily, retain successful rows for five minutes, and share concurrent refresh requests. Stale rows return
immediately while refreshing in the background. Requests have a five-second total deadline; failures retain prior rows
and impose a 30-second retry cooldown, including manual refresh. Each metadata page is limited to 256 KiB, with at most
20 pages and 1,900 catalog IDs. Partial or unsupported catalogs return an explicit failure code and preserve fallbacks.
Metadata listings do not verify generation access, tool calling, or structured output. Cache and clients live in the
backend process and close at shutdown.

### Provider notes

Gemini uses Google's [OpenAI-compatible API](https://ai.google.dev/gemini-api/docs/openai) at
`https://generativelanguage.googleapis.com/v1beta/openai/` by default. Remove an old `DOCKSIGHT_MODEL_BASE_URL`
override when switching providers. Tool-call signatures are retained internally for multi-step Gemini diagnostics.
Server-created preliminary reads use Google's documented signature marker; model-issued signatures replay unchanged.
Choose a model enabled for your API key from the provider's catalog. A successful metadata check does not guarantee
access to generation; available IDs and access depend on the provider and account.
For a Compose service, put these settings in its `environment` mapping and supply the key from your local environment:

```yaml
environment:
  DOCKSIGHT_PROVIDER: gemini
  DOCKSIGHT_MODEL: your-enabled-gemini-model
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

### Local ports and connection errors

Run commands from the repository root so the backend loads the intended `.env`. Environment variables take precedence
over that file; check for older `DOCKSIGHT_*` settings when a fresh configuration behaves unexpectedly.

If port 8000 is occupied, start a separate backend on a free port:

```sh
uv run --project backend uvicorn docksight.main:create_app --factory --host 127.0.0.1 --port 18080 --workers 1
```

In **Connect API**, replace `/api/v1` with `http://127.0.0.1:18080/api/v1` and enter the new backend's token.
The Vite proxy still targets port 8000. For direct connections, `.env.example` allows frontend origins on ports 5173 and
4173; add the exact origin if Vite prints another port. Restart the backend after changing its settings.

A 401 response usually means the browser token differs from the backend token. A working `/health/live` endpoint does
not verify Docker or model access. Open the status panel for dependency checks, then run a diagnosis to verify generation.

`invalid_diagnosis` means the model's proposed response failed schema or evidence checks after one repair attempt.
Selecting an exact container and choosing **Diagnose** collects its snapshot and logs for a focused investigation;
it does not bypass response validation.

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
