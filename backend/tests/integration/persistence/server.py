import argparse
import asyncio
import json
import os
import socket
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import uvicorn
from fastapi import Request, Response

from docksight.adapters.outbound.models.ollama import OllamaModel
from docksight.bootstrap import Settings, build_components
from docksight.main import create_app
from tests.integration.persistence.live_ports import CountedModel, ScopedDocker
from tests.integration.persistence.ports import PersistentModel, PersistentRuntime, barrier, wait_until
from tests.integration.persistence.process import BOB_TOKEN, TOKEN


async def serve(directory: Path, port: int, origin: str | None) -> None:
    """Own real TCP, production bootstrap, and SQLite without test HTTP control endpoints."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", port))
        listener.listen(128)
        allocated_origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
        public_origin = allocated_origin if origin is None else origin
        settings = Settings(
            api_tokens={"alice": TOKEN, "bob": BOB_TOKEN},
            state_path=directory / "state.sqlite3",
            browser_origin=public_origin or None,
            cookie_secure=not bool(public_origin),
            action_ttl=300,
            turn_timeout=120,
            model_timeout=110,
            _env_file=None,
        )
        runtime = PersistentRuntime(directory)
        live_path = directory / "live.json"
        live_runtime = ScopedDocker(directory, json.loads(live_path.read_text())["id"]) if live_path.exists() else None
        local_client = httpx.AsyncClient(base_url="http://127.0.0.1:11434", timeout=90, trust_env=False)
        local_model = CountedModel(directory, OllamaModel(local_client, "qwen3.5:9b"))
        live_model = (directory / "live-model").exists()
        components = build_components(
            settings,
            reader=live_runtime or runtime,
            writer=live_runtime or runtime,
            model=local_model if live_model else PersistentModel(directory),
        )
        components.closers.append(local_client.aclose)
        if live_runtime is not None:
            components.closers.append(live_runtime.close)

        def action_clock() -> datetime:
            """Advance only action expiry through a test-owned deterministic clock offset."""
            offset = directory / "action-clock.txt"
            return datetime.now(UTC) + timedelta(seconds=int(offset.read_text()) if offset.exists() else 0)

        components.actions.clock = action_clock
        components.actions.timeout = 120
        components.runner.shutdown_timeout = 0.1
        app = create_app(settings, components)

        @app.middleware("http")
        async def delayed_delivery(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
            """Hold only test-owned action response delivery after the real use case has settled."""
            response = await call_next(request)
            if request.url.path.endswith("/execute"):
                await barrier(directory, "delivery")
            return response

        server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))

        async def announce() -> None:
            """Publish readiness only after real application lifespan and recovery finish."""
            await asyncio.to_thread(wait_until, lambda: server.started, 20)
            temporary = directory / "ready.tmp"
            temporary.write_text(json.dumps({"origin": allocated_origin, "pid": os.getpid()}), encoding="utf-8")
            temporary.replace(directory / "ready.json")

        async with asyncio.TaskGroup() as group:
            group.create_task(announce())
            group.create_task(server.serve(sockets=[listener]))


def main() -> None:
    """Start only the directory and port explicitly assigned by the owning test."""
    for name in tuple(os.environ):
        if name.startswith("DOCKSIGHT_") or name in {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"}:
            del os.environ[name]
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--origin")
    arguments = parser.parse_args()
    asyncio.run(serve(arguments.directory, arguments.port, arguments.origin))


if __name__ == "__main__":
    main()
