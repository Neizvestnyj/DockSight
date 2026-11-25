"""Serve deterministic native Ollama replies for the packaged release smoke test."""

from __future__ import annotations

import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Final

PORT: Final[int] = 11434
MODEL: Final[str] = "smoke-model"
RELEASE_TIMEOUT: Final[float] = 90.0
MAX_BODY: Final[int] = 4 * 1024 * 1024
FINAL_ANSWER: Final[dict[str, object]] = {
    "summary": "Release smoke diagnosis completed.",
    "evidence_ids": [],
    "uncertain": True,
    "widgets": None,
}


def release_flag() -> Path:
    """Locate the file whose presence releases held chat replies."""
    return Path(
        os.environ.get("DOCKSIGHT_STUB_RELEASE_FILE", "/tmp/docksight-smoke-release")
    )


def wait_for_release() -> bool:
    """Hold a chat reply until the smoke test releases it or the bounded wait expires."""
    deadline = time.monotonic() + RELEASE_TIMEOUT
    while time.monotonic() < deadline:
        if release_flag().exists():
            return True
        time.sleep(0.1)
    return False


def chat_reply(wants_schema: bool) -> dict[str, object]:
    """Return a final schema answer when requested and end exploration otherwise."""
    content = json.dumps(FINAL_ANSWER) if wants_schema else "Ready"
    return {
        "model": MODEL,
        "message": {"role": "assistant", "content": content},
        "done": True,
        "done_reason": "stop",
        "prompt_eval_count": 1,
        "eval_count": 1,
    }


class StubHandler(BaseHTTPRequestHandler):
    """Answer the native Ollama endpoints that DockSight calls during a diagnosis."""

    def do_GET(self) -> None:
        """Report the stub model for catalog and version reads."""
        if self.path == "/api/tags":
            self.send_json(200, {"models": [{"name": MODEL, "model": MODEL}]})
        elif self.path == "/api/version":
            self.send_json(200, {"version": "0.0.0-smoke"})
        else:
            self.send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        """Hold chat replies until release, then answer deterministically."""
        length = int(self.headers.get("Content-Length", "0"))
        if self.path != "/api/chat" or not 0 < length <= MAX_BODY:
            self.send_json(404, {"error": "not found"})
            return
        body: object = json.loads(self.rfile.read(length))
        if not isinstance(body, dict):
            self.send_json(400, {"error": "invalid request"})
            return
        if not wait_for_release():
            self.send_json(503, {"error": "smoke release timed out"})
            return
        self.send_json(200, chat_reply("format" in body))

    def send_json(self, status: int, payload: dict[str, object]) -> None:
        """Write one complete JSON response."""
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    """Serve until the container stops."""
    ThreadingHTTPServer(("0.0.0.0", PORT), StubHandler).serve_forever()


if __name__ == "__main__":
    main()
