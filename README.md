# DockSight

![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-20232A?logo=react&logoColor=61DAFB)
![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?logo=typescript&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white)

**Docker troubleshooting with AI explanations and runtime evidence.**

Inspect Docker containers, Compose projects, and Swarm stacks through a local web interface. DockSight collects runtime
state and bounded logs, asks an LLM to explain the observations, and offers restart or stop actions for confirmation.

![DockSight explaining a container restart loop alongside Docker state, logs, and evidence](docs/screenshots/investigation.jpg)

*Demo workspace with simulated observations. No Docker connection or model is required to try it.*

- **Follow the evidence.** Inspect container state, logs, metrics, allowlisted environment values, and Compose context.
- **Ask follow-up questions.** Investigate a problem in a session scoped to one Docker host.
- **Choose your model.** Use Ollama locally, OpenAI, Anthropic, Gemini, or a compatible API.
- **Review before acting.** Models have read-only tools; restart and stop require separate confirmation.
- **Work in English or Russian.** Switch the interface language without losing the active investigation.

## Why use it instead of pasting logs into a chat?

DockSight reads the selected Docker environment and links explanations to collected observations. Container state,
healthchecks, metrics, and available actions come from the backend. Follow-up questions collect fresh evidence;
restart and stop use expiring, server-prepared actions with separate confirmation.

Model explanations can still be wrong. Evidence-reference validation checks that an observation exists; it does not
prove the model's interpretation or root-cause claim. Review the linked facts before acting.

## Quick start

Clone the repository and run the commands below from its root:

```sh
git clone https://github.com/Neizvestnyj/DockSight.git
cd DockSight
```

### Try the demo

Requires [Node.js 24 LTS](https://nodejs.org/).

```sh
npm --prefix frontend ci
npm --prefix frontend run dev
```

Open the printed URL, normally [localhost:5173](http://localhost:5173). Choose a scenario such as **Crash loop** or
**Out of memory**, inspect its evidence, and review a simulated action. Demo never changes Docker resources.

### Connect your Docker environment

Also requires [Python 3.12+](https://www.python.org/), [uv](https://docs.astral.sh/uv/),
[Docker Engine or Desktop](https://docs.docker.com/get-started/get-docker/), and [Ollama](https://ollama.com/).
Development uses Python 3.14. Start Docker and Ollama before continuing.

**1. Prepare the backend.** The commands below use PowerShell; on Linux/macOS, replace `Copy-Item` with `cp`.

```powershell
uv sync --project backend --locked
Copy-Item .env.example .env
uv run --project backend python -c "import secrets; print(secrets.token_urlsafe(32))"
ollama pull qwen3.5:9b
```

Set `DOCKSIGHT_API_TOKEN` in `.env` to the generated token. Keep the other defaults for local Ollama, or choose
[another provider](docs/configuration.md#model-providers).
The backend reads `.env` from the working directory, so run it from the repository root.

**2. Start the backend in one terminal.**

```sh
uv run --project backend uvicorn docksight.main:create_app --factory --host 127.0.0.1 --port 8000 --workers 1
```

**3. Keep the frontend running in another terminal** using the demo commands above. Choose **Connect API**, keep
`/api/v1`, and enter the same token. Select a host and container, then ask what went wrong. The token stays in browser
memory. Interactive API documentation is available at [localhost:8000/docs](http://localhost:8000/docs).
If port 8000 is occupied, follow the [alternate-port instructions](docs/configuration.md#local-ports-and-connection-errors).

To investigate the whole host, leave **Investigation scope** on **Automatic** and ask "What happened?". Name a container,
Compose project, or Swarm stack to narrow the question. Ambiguous names require a target choice.

For a reproducible failure and confirmed restart, follow the [working example](docs/examples.md#docker-example).

## How it works

The backend collects Docker observations, asks the model to explain them, validates its evidence references, and returns
typed UI cards. Runtime values and permissions come from the backend. Confirmed actions use a separate execution path.

![Diagnostic data flow between the browser, backend, Docker, and model](docs/diagrams/system-overview.png)

Sessions and action records are temporary. Use one backend worker; restarting it clears that state. DockSight provides
diagnosis and confirmed container actions; it has no persistent monitoring history or stack deployment workflow.

This is an early MVP for operator-assisted diagnosis. Host overviews and logs are bounded and disclose collection gaps.
Swarm diagnostics cannot read logs from remote nodes. Docker healthchecks describe probe results separately from process
state. A clean exit or an old error message alone does not establish why a container stopped.

## Configuration

Settings are loaded from environment variables or the root `.env` file.

| Variable                   | Purpose                                                              |
|----------------------------|----------------------------------------------------------------------|
| `DOCKSIGHT_API_TOKEN`      | Bearer token, at least 24 characters                                 |
| `DOCKSIGHT_API_TOKENS`     | Optional named tokens for several operators, as a JSON object        |
| `DOCKSIGHT_PROVIDER`       | `ollama` (default), `openai`, `anthropic`, `gemini`, or `compatible` |
| `DOCKSIGHT_MODEL`          | Model name; defaults to `qwen3.5:9b`                                 |
| `DOCKSIGHT_MODEL_BASE_URL` | Custom model endpoint                                                |
| `DOCKSIGHT_MODEL_API_KEY`  | Credentials for the selected provider                                |
| `DOCKSIGHT_HOSTS_FILE`     | YAML configuration for local, SSH, or mTLS Docker hosts              |

See [configuration and deployment](docs/configuration.md) for provider examples, CORS, limits, and Docker connections.

## Documentation

- [Documentation index](docs/README.md) — guides and technical references.
- [Usage examples](docs/examples.md) — browser investigation and a reproducible Docker failure.
- [HTTP API](docs/api.md) — authentication, reads, diagnostic streams, and confirmed actions.
- [Architecture](docs/architecture.md) — backend boundaries and diagrams.
- [Contributing](CONTRIBUTING.md) — development setup, checks, and contribution guidelines.
- [Changelog](CHANGELOG.md) — release changes.

For development shortcuts, optional [Make commands](CONTRIBUTING.md#make-commands) provide setup, server,
check, test, and build targets. Run `make help` to list them.

## License

DockSight is licensed under [Apache-2.0](LICENSE). Frontend builds include
[third-party notices](frontend/public/licenses/) for IBM Plex, React/ReactDOM/Scheduler, Zod, and Lucide/Feather.
