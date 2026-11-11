# DockSight

[![Backend CI][backend-ci-badge]][backend-ci]
[![Frontend CI][frontend-ci-badge]][frontend-ci]
[![License: Apache-2.0][license-badge]](LICENSE)
![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white)

DockSight is a local web interface for diagnosing Docker containers, Compose projects, and Swarm stacks.
It collects Docker state and logs, links model explanations to those observations, and prepares restart or stop actions.
Each action requires confirmation.

![Demo diagnosis with Docker state, logs, and linked evidence](docs/screenshots/investigation.jpg)

*Demo with simulated observations. Requires no Docker connection or model.*

- Container state, healthchecks, logs, metrics, allowlisted environment values, and Compose context.
- Follow-up questions within one Docker host, with fresh observations on each turn.
- Saved API chats, acknowledged drafts, and first-party session recovery after refresh.
- Local Ollama, OpenAI, Anthropic, Gemini, and compatible APIs.
- Read-only model tools and expiring action IDs prepared by the backend.

Model explanations can be wrong. Valid evidence references do not prove a root-cause claim.
Review the linked observations before acting.

## Quick start

Clone the repository:

```sh
git clone https://github.com/Neizvestnyj/DockSight.git
cd DockSight
```

Run all commands below from the repository root.

### Try the demo

Requires [Node.js 24 LTS](https://nodejs.org/).

```sh
npm --prefix frontend ci
npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173
```

Open the printed URL, normally [127.0.0.1:5173](http://127.0.0.1:5173), and choose **Explore Demo**.
Choose a scenario such as **Crash loop** or **Out of memory**, inspect its evidence, and review a simulated action.
Demo never changes Docker resources. If the initial session read fails, **Retry connection** retries it.

### Connect your Docker environment

Also requires [Python 3.12+](https://www.python.org/), [uv](https://docs.astral.sh/uv/),
[Docker Engine or Desktop](https://docs.docker.com/get-started/get-docker/), and [Ollama](https://ollama.com/).
Development uses Python 3.14. Start Docker and Ollama before continuing.

**1. Prepare the backend.** These commands use PowerShell. On Linux/macOS, replace `Copy-Item` with `cp`.

```powershell
uv sync --project backend --locked
Copy-Item .env.example .env
uv run --project backend python -c "import secrets; print(secrets.token_urlsafe(32))"
ollama pull qwen3.5:9b
```

Set `DOCKSIGHT_API_TOKEN` in `.env` to the generated token. Keep the other defaults for local Ollama, or choose
[another provider](docs/configuration.md#model-providers).
The example sets `DOCKSIGHT_BROWSER_ORIGIN=http://127.0.0.1:5173` and the explicit loopback HTTP exception
`DOCKSIGHT_COOKIE_SECURE=false`. Match Vite's printed origin if it selects another port. Vite changes the backend Host
header, so the public origin must be configured explicitly. Use Secure cookies for production HTTPS.
The backend reads `.env` from the working directory, so run it from the repository root.

**2. Start the backend in one terminal.**

```sh
uv run --project backend uvicorn docksight.main:create_app --factory --host 127.0.0.1 --port 8000 --workers 1
```

**3. Keep the frontend running in another terminal** using the demo commands above. Choose **Connect API**, keep
`/api/v1`, and enter the same token. Select a host and container, then ask what went wrong. Same-origin login exchanges
the token for an HttpOnly cookie and clears the input. Refresh restores the owned workspace through that cookie.
**Saved chats** opens earlier answers. **Older chats** pages beyond the latest ten. **Draft saved** confirms text that
can be restored. **Stop diagnosis** explicitly cancels accepted work. Closing or reloading a tab only detaches it.
Interactive API documentation is available at [127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).
If port 8000 is occupied, follow the
[alternate-port instructions](docs/configuration.md#local-ports-and-connection-errors).

A separate-origin API uses a bearer token only in tab memory and requires reconnecting after refresh. Its endpoint and
token are never stored in browser storage. For a production-build preview, use the distinct public origin
`http://127.0.0.1:4173` and restart the backend after changing its settings.
See [frontend deployment](docs/configuration.md#frontend-deployment).

To investigate the whole host, leave **Investigation scope** on **Automatic** and ask "What happened?".
Name a container, Compose project, or Swarm stack to narrow the question. Ambiguous names require a target choice.

For a reproducible failure and confirmed restart, follow the [working example](docs/examples.md#docker-example).

## How it works

The backend collects Docker observations and sends them to the model. It validates the returned evidence references and
builds typed UI cards. Runtime values, permissions, and action execution belong to the backend.

![Diagnostic data flow between the browser, backend, Docker, and model](docs/diagrams/system-overview.png)

Current limitations:

- SQLite state requires one backend process/worker and a writable local volume. Keep the whole state directory across
  upgrades. Explicit memory mode expires inactive history and loses all state on restart.
- Saved evidence is historical. Continuing collects fresh observations. Interrupted turns do not resume automatically.
- Unknown Docker outcomes retain an exact-target block across SQLite restart. Resolve them through the
  [offline reconciliation procedure](docs/configuration.md#action-reconciliation), without automatically retrying.
- Host overviews and logs have collection limits. Reports identify missing or clipped data.
- Swarm diagnostics cannot read logs from remote nodes.
- Healthchecks report probe results separately from process state. A clean exit or old error alone cannot explain
  a stop.
- Persistent monitoring history and stack deployment are not supported.

## Configuration

Settings are loaded from environment variables or the root `.env` file.

| Variable                   | Purpose                                                              |
|----------------------------|----------------------------------------------------------------------|
| `DOCKSIGHT_API_TOKEN`      | Bearer token, at least 24 characters                                 |
| `DOCKSIGHT_API_TOKENS`     | Optional named tokens for several operators, as a JSON object        |
| `DOCKSIGHT_PROVIDER`       | `ollama` (default), `openai`, `anthropic`, `gemini`, or `compatible` |
| `DOCKSIGHT_MODEL`          | Model name (default: `qwen3.5:9b`)                                   |
| `DOCKSIGHT_MODEL_BASE_URL` | Custom model endpoint                                                |
| `DOCKSIGHT_MODEL_API_KEY`  | Credentials for the selected provider                                |
| `DOCKSIGHT_HOSTS_FILE`     | YAML configuration for local, SSH, or mTLS Docker hosts              |
| `DOCKSIGHT_STATE_BACKEND`  | `sqlite` by default, or explicit temporary `memory` mode             |
| `DOCKSIGHT_STATE_PATH`     | Local SQLite file, default `.docksight/state.sqlite3`                |
| `DOCKSIGHT_BROWSER_ORIGIN` | Exact public frontend origin for first-party login                   |
| `DOCKSIGHT_COOKIE_SECURE`  | `true` for HTTPS, explicit `false` only for loopback HTTP            |

See [configuration and deployment](docs/configuration.md) for provider examples, CORS, limits, and Docker connections.

## Documentation

- [Documentation index](docs/README.md)
- [Usage examples](docs/examples.md)
- [HTTP API](docs/api.md)
- [Architecture](docs/architecture.md)
- [Contributing](CONTRIBUTING.md)
- [Changelog](CHANGELOG.md)

Optional [Make commands](CONTRIBUTING.md#make-commands) cover setup, servers, checks, tests, and builds.
Run `make help` to list them.

## License

DockSight is licensed under [Apache-2.0](LICENSE). Frontend builds include
[third-party notices](frontend/public/licenses/) for IBM Plex, React/ReactDOM/Scheduler, Zod, and Lucide/Feather.

[backend-ci-badge]: https://github.com/Neizvestnyj/DockSight/actions/workflows/backend.yml/badge.svg?branch=master
[backend-ci]: https://github.com/Neizvestnyj/DockSight/actions/workflows/backend.yml
[frontend-ci-badge]: https://github.com/Neizvestnyj/DockSight/actions/workflows/frontend.yml/badge.svg?branch=master
[frontend-ci]: https://github.com/Neizvestnyj/DockSight/actions/workflows/frontend.yml
[license-badge]: https://img.shields.io/badge/license-Apache--2.0-blue
