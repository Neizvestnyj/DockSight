import socket
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

import uvicorn
from fastapi import FastAPI


@contextmanager
def http_server(factory: Callable[[str], FastAPI]) -> Iterator[str]:
    """Run an isolated real HTTP server with lifespan and an OS-allocated loopback port."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
        server = uvicorn.Server(uvicorn.Config(factory(origin), log_level="error", lifespan="on"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        deadline = time.monotonic() + 10
        try:
            while not server.started:
                if not thread.is_alive() or time.monotonic() > deadline:
                    raise RuntimeError("Test HTTP server did not become ready")
                time.sleep(0.01)
            yield origin
        finally:
            server.should_exit = True
            thread.join(10)
            if thread.is_alive():
                raise RuntimeError("Test HTTP server did not stop")
