# Install DockSight

DockSight runs as two containers: a private backend and a web interface on `http://127.0.0.1:8080`.
The images are built for Linux `amd64` and `arm64`.
Model access from Docker Desktop on macOS and Windows is not verified yet.

## Requirements

- Docker Engine 25 or later, or Docker Desktop, with Docker Compose v2.24 or later.
- A local Docker socket at `/var/run/docker.sock`.
- A model provider for diagnoses. The default configuration uses Ollama on the same computer.

## Quick install

Linux and macOS:

```sh
curl -fsSL https://github.com/Neizvestnyj/DockSight/releases/latest/download/install.sh | sh
```

Windows PowerShell:

```powershell
irm https://github.com/Neizvestnyj/DockSight/releases/latest/download/install.ps1 | iex
```

The installer:

1. Checks Docker and Docker Compose.
2. Downloads this release's files into `~/.docksight` (Windows: `%LOCALAPPDATA%\DockSight`) and verifies
   `compose.yaml` against the checksum built into the installer.
3. On the first install, creates `.env` with a generated API token, the Docker socket group, and the port.
4. Starts DockSight and prints the address and the API token.

Open the printed address, select **Connect API**, and enter the token. To review the script first, download it,
read it, and then run it with `sh install.sh` or `.\install.ps1`.

### Installer settings

Set these environment variables before running the installer:

| Variable               | Default                          | Purpose                                      |
|------------------------|----------------------------------|----------------------------------------------|
| `DOCKSIGHT_DIR`        | `~/.docksight`                   | Install directory                            |
| `DOCKSIGHT_PORT`       | `8080`                           | Local web port                               |
| `DOCKSIGHT_COMPONENTS` | `all`                            | `backend` installs only the API              |
| `DOCKSIGHT_API_PORT`   | `8000`                           | Local API port when only the API is running  |
| `DOCKSIGHT_PROJECT`    | `docksight`                      | Docker Compose project name                  |

For example, `curl -fsSL …/install.sh | DOCKSIGHT_PORT=9090 sh` or `$env:DOCKSIGHT_PORT = '9090'` in PowerShell.
Settings are saved in `.env` and reused by later runs.

### Backend only

Run the backend without the web interface, for API clients or your own frontend:

```sh
curl -fsSL https://github.com/Neizvestnyj/DockSight/releases/latest/download/install.sh | DOCKSIGHT_COMPONENTS=backend sh
```

The API is then available at `http://127.0.0.1:8000/api/v1` with the bearer token from `.env`. Run the installer
with `DOCKSIGHT_COMPONENTS=all` to add the web interface again.

Both images are also published separately, for example `ghcr.io/neizvestnyj/docksight-backend:vX.Y.Z`. To run the
backend image directly, see the [backend image](https://github.com/Neizvestnyj/DockSight/blob/master/docs/configuration.md#backend-image)
reference.

## Update

Run the quick install command again. It downloads the latest release, keeps `.env` and the saved state, and restarts
DockSight with the new images. Read the release notes first and back up the state for major updates.

## Stop and uninstall

```sh
cd ~/.docksight
docker compose down
```

`docker compose down --volumes` also deletes saved investigations, sessions, and action records. Then delete the
install directory.

## Model provider

The backend container reaches the Docker host as `host.docker.internal`.

On Linux, Ollama listens on `127.0.0.1` by default, which containers cannot reach. Make it listen on an address that
the Docker bridge can reach and restrict that port to local traffic with your firewall:

```sh
sudo systemctl edit ollama
```

```ini
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
```

```sh
sudo systemctl restart ollama
ollama pull qwen3.5:9b
```

For another endpoint, set `DOCKSIGHT_MODEL_BASE_URL` in `.env` and rerun the installer. Cloud providers are opt-in.
Set the provider, model, and API key in `.env`. Cloud providers receive the sanitized Docker evidence selected during
diagnosis. See the [configuration reference](https://github.com/Neizvestnyj/DockSight/blob/master/docs/configuration.md).

## Remote access

The web service is published on loopback only. The backend has no published port unless only the API is installed.
To reach DockSight from another machine, put an HTTPS reverse proxy in front of the web port. Then set
`DOCKSIGHT_BROWSER_ORIGIN` to the public HTTPS origin and `DOCKSIGHT_COOKIE_SECURE=true` in `.env`.

## State

Investigations, browser sessions, and action records are stored in SQLite on the `state` named volume. Run only one
backend container per volume. Back up the volume with the services stopped:

```sh
cd ~/.docksight
docker compose stop
docker run --rm --volume docksight_state:/state:ro --volume "$PWD":/backup alpine \
  tar -czf /backup/docksight-state.tar.gz -C /state .
docker compose start
```

With a custom `DOCKSIGHT_PROJECT`, the volume is named `<project>_state`.

## Manual install

Use this when the installer cannot run.

1. Download `compose.yaml` and `docksight.env.example` from the release into an empty directory.
2. Copy `docksight.env.example` to `.env`.
3. Set `DOCKSIGHT_API_TOKEN` to a generated token, for example `openssl rand -hex 32`.
4. Set `DOCKSIGHT_DOCKER_GID` to the numeric group of the Docker socket, for example
   `stat -c %g /var/run/docker.sock`. The backend runs as UID 10001 and reads Docker only through this group.
5. Start DockSight with `docker compose up --detach --wait`.

## Troubleshooting

| Symptom                               | Check                                                                     |
|---------------------------------------|---------------------------------------------------------------------------|
| `Docker is not running`               | Start Docker, or add your user to the `docker` group on Linux             |
| Checksum error during install         | Retry the download. Never edit `compose.yaml` from a release              |
| Docker inventory is unavailable       | `DOCKSIGHT_DOCKER_GID` matches the socket group                           |
| Login returns 401                     | The browser token matches `DOCKSIGHT_API_TOKEN` in `.env`                 |
| Login is rejected for origin          | The browser address matches `DOCKSIGHT_BROWSER_ORIGIN` exactly            |
| Model is unavailable                  | Ollama listens on a bridge-reachable address and the model is pulled      |

```sh
docker compose ps
docker compose logs backend
```
