# Configuration and deployment

See the [quick start](../README.md#connect-your-docker-environment) for local setup.
Settings use the `DOCKSIGHT_` prefix and load from environment variables or the root `.env` file.
Keep credentials in environment variables or external secret files. Never put them in tracked configuration.

## Settings

Names below omit the `DOCKSIGHT_` prefix. Array values use JSON, for example `DOCKSIGHT_ENV_ALLOWLIST=["APP_ENV"]`.

| Setting                              | Default                    | Purpose                                                                   |
|--------------------------------------|----------------------------|---------------------------------------------------------------------------|
| `API_TOKEN`                          | Required or `API_TOKENS`   | Bearer token of at least 24 characters, actor `operator`                  |
| `API_TOKENS`                         | `{}`                       | [Named operator tokens](#api-tokens)                                      |
| `PROVIDER` / `MODEL`                 | `ollama` / `qwen3.5:9b`    | Independent provider and model selection                                  |
| `MODEL_BASE_URL` / `MODEL_API_KEY`   | Provider default / unset   | Model endpoint and credentials                                            |
| `MODEL_STRUCTURED_OUTPUT`            | `native`                   | Compatible and Gemini providers also support `tool`                       |
| `OLLAMA_CONTEXT_LENGTH`              | `16384` tokens             | Native Ollama context for prompts, tools, and replies                     |
| `HOSTS_FILE`                         | Unset                      | [Docker host configuration](../examples/hosts.yaml)                       |
| `ENV_ALLOWLIST` / `CORS_ORIGINS`     | `[]` / `[]`                | Environment fields and allowed browser origins                            |
| `MAX_MODEL_CALLS` / `MAX_TOOL_CALLS` | `6` / `12`                 | Per-turn budgets, including finalization and repair                       |
| `MODEL_TIMEOUT` / `TURN_TIMEOUT`     | `60` / `180` seconds       | Model request and total turn deadlines                                    |
| `LOG_LINES` / `LOG_BYTES`            | `200` / `65536`            | Log response bounds                                                       |
| `STATE_BACKEND`                      | `sqlite`                   | `memory` explicitly selects temporary development/test state              |
| `STATE_PATH`                         | `.docksight/state.sqlite3` | Local SQLite path, relative to the process working directory              |
| `BROWSER_ORIGIN`                     | Unset                      | Exact public browser origin, required with a proxy that changes Host      |
| `COOKIE_SECURE`                      | `true`                     | `false` requires an explicit loopback HTTP browser origin                 |
| `BROWSER_SESSION_TTL`                | `28800` seconds            | Absolute cookie-session lifetime, 60..28800 seconds                       |
| `BROWSER_SESSION_IDLE_TTL`           | `3600` seconds             | Idle cookie-session lifetime, 120..3600 seconds                           |
| `MAX_SESSIONS` / `STATE_TTL`         | `100` / `1800` seconds     | Explicit memory-mode history capacity and inactive expiry                 |
| `MAX_ACTIONS`                        | `1000`                     | Live unclaimed preparations, independent of retained execution protection |

The [.env example](../.env.example) includes browser origins for local development and preview.
Generate a token with:

```sh
uv run --project backend python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### API tokens

Each token identifies one actor. Investigations, workspaces, and prepared actions belong to that actor.
Other actors cannot read or continue its history or read or execute its actions. Audit records name the actor.

For several operators, give each one a separate token:

```dotenv
DOCKSIGHT_API_TOKENS={"alice":"generated-token-1","ci-bot":"generated-token-2"}
```

Actor names use 1–64 letters, digits, dots, underscores, or hyphens. Tokens must be distinct and at least
24 characters. `DOCKSIGHT_API_TOKEN` can be used alongside them as the `operator` actor, so `API_TOKENS` cannot also
define `operator`. All tokens have the same permissions.

Removing or rotating a configured token invalidates its browser sessions when the configuration is reloaded at
restart. History remains owned by the stable actor name. The database contains session hashes and credential
fingerprints, never raw bearer tokens or cookies.

## Model providers

Choose a model with tool calls and structured output. Copy its provider settings into the root `.env`.
Keep your existing API token and browser settings.

| Provider       | Configuration example                                             |
|----------------|-------------------------------------------------------------------|
| Ollama         | [Local Ollama](../examples/providers/ollama.env.example)          |
| OpenAI         | [OpenAI](../examples/providers/openai.env.example)                |
| Anthropic      | [Anthropic](../examples/providers/anthropic.env.example)          |
| Gemini         | [Gemini](../examples/providers/gemini.env.example)                |
| Compatible API | [Compatible server](../examples/providers/compatible.env.example) |

Cloud providers receive the sanitized Docker evidence selected during diagnosis. Redaction may miss secrets.
Review what your workload writes to logs.

### Default model

`DOCKSIGHT_PROVIDER` and `DOCKSIGHT_MODEL` select the default model. Use `DOCKSIGHT_MODEL_BASE_URL` for its endpoint,
`DOCKSIGHT_MODEL_API_KEY` for its credentials, and `DOCKSIGHT_MODEL_STRUCTURED_OUTPUT` for its output mode.
Requests without a model selection use this connection.

OpenAI, Anthropic, and Gemini also accept `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, and `GEMINI_API_KEY`, respectively.
The corresponding `DOCKSIGHT_OPENAI_API_KEY`, `DOCKSIGHT_ANTHROPIC_API_KEY`, or `DOCKSIGHT_GEMINI_API_KEY` takes
precedence
over the standard name. `DOCKSIGHT_MODEL_API_KEY` overrides both for the default model. These settings load from the
root
`.env` file or environment variables. The compatible provider uses only `DOCKSIGHT_MODEL_API_KEY` or
`DOCKSIGHT_COMPATIBLE_API_KEY`. It never sends another provider's key.

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
`STRUCTURED_OUTPUT` setting to `tool` (default: `native`). Provider-specific endpoint and output-mode settings apply
only
when that provider is not the default. The default uses `DOCKSIGHT_MODEL_*`.

The browser selects provider/model identities and cannot submit endpoints or keys. Selection affects the next
question and its status check. Sessions, prepared actions, and the global turn concurrency budget remain shared.

### Model catalogs

For aliases or providers without a catalog endpoint, allow model IDs using a JSON object of arrays:

```dotenv
DOCKSIGHT_PROVIDER_FALLBACK_MODELS={"openai":["your-model-alias"],"compatible":["your-local-model"]}
```

Use at most 100 IDs of 1–256 characters per provider. The first ID is the initial model for an additional provider.
Without a fallback ID, the operator chooses a catalog row. The configured default needs no catalog request.

- Catalogs load on demand. Results stay fresh for five minutes. Concurrent refresh requests share one fetch.
- Stale rows return immediately during background refresh. Requests have a five-second deadline.
- Failures retain prior rows and delay retries for 30 seconds, including manual refresh.
- Catalog reads allow at most 20 pages, 256 KiB per page, and 1,900 external IDs.
- Partial or unsupported catalogs return a failure code and preserve fallback IDs.
- Listings do not verify generation access, tool calls, or structured output.
- The cache and clients live in the backend process and close at shutdown.

### Provider notes

Gemini uses Google's [OpenAI-compatible API](https://ai.google.dev/gemini-api/docs/openai) at
`https://generativelanguage.googleapis.com/v1beta/openai/` by default. Remove an old `DOCKSIGHT_MODEL_BASE_URL`
override when switching providers. Tool-call signatures are retained internally for multi-step Gemini diagnostics.
Server-created preliminary reads use Google's documented signature marker. Model-issued signatures replay unchanged.
Choose a model enabled for your API key from the provider's catalog. A successful metadata check does not guarantee
access to generation. Available IDs and access depend on the provider and account.
For a Compose service, put these settings in its `environment` mapping and supply the key from your local environment:

```yaml
environment:
  DOCKSIGHT_PROVIDER: gemini
  DOCKSIGHT_MODEL: your-enabled-gemini-model
  DOCKSIGHT_MODEL_API_KEY: ${GEMINI_API_KEY:?Set GEMINI_API_KEY}
```

Keep `DOCKSIGHT_API_TOKEN` as the separate credential used by the browser to authenticate to DockSight.

Native Ollama requests set an explicit context window. A small server default can truncate the query and tool results.
Increase `DOCKSIGHT_OLLAMA_CONTEXT_LENGTH` for larger inventories or logs. Larger contexts need more memory.

The UI system-status panel checks Docker availability and provider/model metadata. It does not verify generation,
tool calling, or structured output. Those require a diagnostic request. Public health endpoints check process liveness
and completed storage initialization/recovery without contacting Docker or a model.
See [dependency status](api.md#dependency-status).

## Docker hosts

Without a hosts file, local Docker follows the current Docker context and Docker environment variables.
For explicit hosts, set `DOCKSIGHT_HOSTS_FILE` to a YAML file based on [hosts.yaml](../examples/hosts.yaml).
API requests select a configured host ID. Arbitrary connection URLs are rejected.

- **Local:** omit the host URL to use the current Docker context and environment.
- **SSH:** uses the Docker SDK's Paramiko transport, SSH agent/config, and verified `~/.ssh/known_hosts`.
  Use `ProxyCommand` for jump hosts.
- **TCP:** requires mTLS with CA, client certificate, and private key paths.

SSH connection, banner, authentication, and channel waits have bounded timeouts. DNS resolution, SSH agent operations,
and external `ProxyCommand` processes also depend on system-level limits. Inspect and environment fields are
allowlisted.

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

First-party deployments serve the frontend and `/api` through the same public origin. Login exchanges a bearer token
for an HttpOnly browser cookie and clears the token input. Page load checks that session before opening the saved
workspace. Unauthorized bootstrap shows **Connect API** and **Explore Demo**.
Network failures offer **Retry connection**.
A valid cookie restores owned history and acknowledged drafts. It never repeats a submission or action execution.

Separate-origin HTTPS connections, or loopback HTTP during development, use transient bearer authority and require
reconnecting after refresh. They omit cookies and do not persist the remote endpoint or token. Sign in as the same
stable actor to reopen that actor's backend history. Demo is an explicit simulated mode with tab-only history.

The browser holds bearer credentials and CSRF values in memory. Never put tokens in source, browser storage, URLs, or
`VITE_*` variables. The locale is the only JavaScript browser-storage preference. The browser may persist the opaque
session cookie, which is host-only, `Path=/api/v1`, `HttpOnly`, `Secure`, and `SameSite=Lax`.
Its absolute lifetime defaults to eight hours, with one-hour idle expiry. Activity writes coalesce at 60 seconds and
never extend absolute expiry. Login and cookie writes require exact Origin and JSON. Cookie writes also require the
session-bound `X-CSRF-Token`. Logout revokes that cookie without deleting history or cancelling accepted work.

### Public origin and proxy setup

Vite's `/api` proxy sets `changeOrigin: true`. Set the public browser origin explicitly because the backend Host can
differ from the browser Origin. Use the exact origin printed by Vite, including hostname and port:

```dotenv
# Development: start Vite with --host 127.0.0.1 --port 5173.
DOCKSIGHT_BROWSER_ORIGIN=http://127.0.0.1:5173
DOCKSIGHT_COOKIE_SECURE=false
```

For the production-build preview, start preview with `--host 127.0.0.1 --port 4173`, replace `BROWSER_ORIGIN` with
`http://127.0.0.1:4173`, and restart the backend. If Vite chooses another port, use its printed origin. `localhost` and
`127.0.0.1` are distinct origins. CORS configuration alone does not authorize first-party cookie login.

For production HTTPS, set `DOCKSIGHT_BROWSER_ORIGIN=https://your-public-host` and `DOCKSIGHT_COOKIE_SECURE=true`.
Route `/api` to the private backend and prevent direct public access to it. Trust forwarded headers only from a known
proxy at the server deployment layer. DockSight does not select cookie authority or Secure from arbitrary forwarded
host/proto headers. `COOKIE_SECURE=false` is accepted only with an explicit loopback HTTP origin.

### Local ports and connection errors

Run commands from the repository root so the backend loads the intended `.env`. Environment variables take precedence
over that file. Check for older `DOCKSIGHT_*` settings when a fresh configuration behaves unexpectedly.

If port 8000 is occupied, start a separate backend on a free port:

```sh
uv run --project backend uvicorn docksight.main:create_app --factory --host 127.0.0.1 --port 18080 --workers 1
```

In **Connect API**, replace `/api/v1` with `http://127.0.0.1:18080/api/v1` and enter the new backend's token.
The Vite proxy still targets port 8000. For direct connections, `.env.example` allows frontend origins on ports 5173 and
4173. Add the exact origin if Vite prints another port. Restart the backend after changing its settings.

A 401 response usually means the browser token differs from the backend token. A working `/health/live` endpoint does
not verify Docker or model access. Open the status panel for dependency checks, then run a diagnosis to verify
generation.

`invalid_diagnosis` means the model's proposed response failed schema or evidence checks after one repair attempt.
Selecting an exact container and choosing **Diagnose** collects its snapshot and logs. Response validation still
applies.

## Backend image

```sh
docker build -f backend/Dockerfile -t docksight-backend:local .
```

The image uses Python 3.14 on Debian slim and runs as UID 10001. Debian slim provides glibc for native wheels.
The demo worker uses Alpine with musl. Mount host configuration and credentials read-only.
Grant the Docker socket's group explicitly when using a local socket.

The image stores SQLite at `/var/lib/docksight/state.sqlite3` and declares `/var/lib/docksight` as a volume. Mount the
whole directory so the main file, rollback journal, and sidecar lock share durable local storage:

```sh
docker volume create docksight-state
docker run --name docksight --publish 127.0.0.1:8000:8000 --env-file .env \
  --env DOCKSIGHT_STATE_PATH=/var/lib/docksight/state.sqlite3 \
  --mount source=docksight-state,target=/var/lib/docksight docksight-backend:local
```

A bind-mounted directory must be writable by UID/GID `10001:10001`. A new named volume inherits the image directory's
ownership. Do not mount only the database file or use a shared/network filesystem. Retain the volume across upgrades.

Ollama must be reachable from inside the container. On Docker Desktop, use `host.docker.internal` in its configured
endpoint instead of the container's loopback address. Bind the API to loopback by default and require authentication.

## Process state and recovery

SQLite is the default state backend. Run one backend process with one worker on a local filesystem. The canonical
database path has a lifetime OS lock at `STATE_PATH.lock`. Another backend or maintenance command fails with
`storage_locked` before changing state. There is no silent memory fallback. The sanitized operational database is
unencrypted. Restrict directory and backup access according to the sensitivity of the saved evidence.

Startup checks integrity/schema, applies packaged forward migrations, and commits recovery before readiness. Abandoned
running turns become `interrupted`. They never restart generation automatically. Abandoned claims without a dispatch
marker fail before dispatch. A durable dispatch marker becomes indeterminate even if the crash preceded the SDK send.
Its exact-target block survives restart, history deletion, credential rotation, and preparation expiry.

An unexpected storage failure closes write admission and returns `storage_unavailable`. An unsaved answer or mutation
result is never reported as saved success. Reads remain available only when their own storage operation succeeds.
Stop the backend and preserve state before investigating corruption or disk failures. Do not delete state to unblock.

Default history bounds are 500 investigations per actor, 200 accepted turns per investigation, 32 MiB per investigation,
256 MiB per actor, and 2 MiB per public turn snapshot. The server reserves the maximum snapshot allowance at acceptance.
Capacity rejects new work with `history_capacity` and preserves saved content. SQLite does not evict old investigations.
The latest-ten history page is pagination, not retention. Delete an owned inactive investigation explicitly to reclaim
its turns, model context, and workspace. Actions, audit, guards, and content-free submission tombstones remain.

Only `DOCKSIGHT_STATE_BACKEND=memory` uses `MAX_SESSIONS` and `STATE_TTL`. It expires inactive history through ordinary
deletion, retaining content-free receipt tombstones. New chat creation fails with `session_capacity` if the remaining
global count reaches `MAX_SESSIONS`. Active diagnoses are not evicted. All memory state and execution protection
disappear on process exit.

### Offline status, backup, and migration

Run maintenance from the repository root with the backend stopped. The global `--state-path` option comes before the
subcommand. It overrides `DOCKSIGHT_STATE_PATH` and the root `.env` value. The default is `.docksight/state.sqlite3`.
The commands acquire the same exclusive lock as the server. Choose a new backup filename in an existing safe directory:

```sh
uv run --project backend python -m docksight.state_cli --state-path .docksight/state.sqlite3 status
uv run --project backend python -m docksight.state_cli --state-path .docksight/state.sqlite3 \
  backup --destination backups/state-before-upgrade.sqlite3
uv run --project backend python -m docksight.state_cli --state-path .docksight/state.sqlite3 migrate
```

`status` reports `schema_revision`, `recovery_required`, and `journal_present` from a disposable immutable copy.
If a source journal exists, it reports recovery required without opening SQLite. `backup` copies the original main file
and any `-journal` bytes under the OS lock before opening source SQLite. Both the destination main filename and its
`-journal` filename must be absent, even when the source has no journal. A failed copy removes only files created by
that invocation. Preserve every returned file together. `migrate` applies only packaged forward schema upgrades.
It does not run server recovery,
session cleanup, models, or diagnostic workers. Unknown schema revisions and failed migrations fail closed.

Restore procedure:

1. Stop the backend and every maintenance process. Keep an offline backup of the current main/journal pair first.
2. Restore the selected backup into a separate empty state directory, preserving the main filename and matching
   `-journal` suffix when present. Do not copy a process lock from another directory or mix journals from other backups.
3. Give the backend account access to that directory. For the image, set ownership to `10001:10001` and mount the whole
   directory at `/var/lib/docksight`. Point `STATE_PATH` at the restored main file.
4. Inspect status, perform the explicit forward migration if needed, and start one backend worker. Startup performs
   normal crash recovery before readiness. Verify saved history and retained action blocks before accepting new work.

For example, restore that backup to a new directory in PowerShell after completing step 1:

```powershell
if (Test-Path -LiteralPath .docksight-restored) { throw 'Choose a new restore directory' }
New-Item -ItemType Directory -Path .docksight-restored -ErrorAction Stop
Copy-Item -LiteralPath backups/state-before-upgrade.sqlite3 -Destination .docksight-restored/state.sqlite3 -ErrorAction Stop
if (Test-Path -LiteralPath backups/state-before-upgrade.sqlite3-journal) {
  Copy-Item -LiteralPath backups/state-before-upgrade.sqlite3-journal `
    -Destination .docksight-restored/state.sqlite3-journal -ErrorAction Stop
}
$env:DOCKSIGHT_STATE_PATH = '.docksight-restored/state.sqlite3'
uv run --project backend python -m docksight.state_cli status
uv run --project backend python -m docksight.state_cli migrate
uv run --project backend uvicorn docksight.main:create_app --factory --host 127.0.0.1 --port 8000 --workers 1
```

### Action reconciliation

An `indeterminate` action means Docker may have accepted the operation. Never automatically retry it. Stop the backend
and inspect the blocked target using configured Docker access:

```sh
uv run --project backend python -m docksight.state_cli --state-path .docksight/state.sqlite3 \
  reconcile --action-id ACTION_UUID
```

The preview returns the exact host/full container ID, current guard revision, unresolved actions, and fresh observation.
Independently verify that the old backend and any Docker operation have settled. Current container state alone cannot
prove that a timed-out command never ran. Missing Docker access cannot authorize reconciliation. Verified target removal
is allowed. Confirm the preview's exact target and revision, using a configured actor and a specific reason:

```sh
uv run --project backend python -m docksight.state_cli --state-path .docksight/state.sqlite3 \
  reconcile --action-id ACTION_UUID --expected-revision REVISION \
  --confirm-target HOST/FULL_CONTAINER_ID --actor CONFIGURED_ACTOR \
  --reason "Verified the old process and operation have settled" --acknowledge-unknown-outcome
```

All confirmation flags are required together. The CLI records the native OS account separately from the configured
actor, rereads Docker, and checks the unchanged revision. It atomically audits reconciliation, invalidates remaining
preparations for that exact target, and clears the block. A failed commit leaves the block intact. The old action stays
indeterminate. Reconciliation never sends a mutation. A later mutation needs a new preparation and explicit
confirmation.
There is no browser unblock endpoint and no distributed exactly-once guarantee across SQLite and Docker.
