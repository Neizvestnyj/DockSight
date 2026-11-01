import asyncio
import json
import struct
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.client import HTTPResponse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging import ERROR
from threading import Event, Thread
from time import monotonic
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from docker import DockerClient
from docker.api.client import APIClient
from paramiko import Channel
from requests import Response

from docksight.adapters.outbound.docker.hosts import HostConfig
from docksight.adapters.outbound.docker.logs import read_logs
from docksight.adapters.outbound.docker.runtime import DockerRuntime
from docksight.application.redaction import Redactor
from docksight.domain.errors import DockSightError


@dataclass
class LogServer:
    """Serve real SDK requests while controlling finite or stalled Docker log bodies."""

    url: str = ""
    tty: bool = False
    mode: str = "stalled"
    status: int = 200
    release: Event = field(default_factory=Event)
    opened: Event = field(default_factory=Event)

    def connect(self, host: HostConfig, timeout: float) -> DockerClient:
        """Use the real SDK against an isolated loopback endpoint without version discovery."""
        return DockerClient(base_url=self.url, version="1.45", timeout=timeout)

    def body(self) -> bytes:
        """Return timestamped TTY bytes or Docker's multiplexed stdout/stderr frames."""
        if self.mode == "empty":
            return b""
        if self.mode == "short_header":
            return b"\x01\x00\x00"
        if self.mode == "short_payload":
            return struct.pack(">BxxxI", 1, 10) + b"ab"
        rows = (b"2026-01-01T00:00:00Z password=secret-value\n", b"2026-01-01T00:00:01Z final event\n")
        if self.tty:
            return b"".join(rows)
        return b"".join(struct.pack(">BxxxI", stream, len(row)) + row for stream, row in enumerate(rows, 1))

    def trickle_chunk(self) -> bytes:
        """Keep slow delivery valid for the selected Docker log transport."""
        return b"x" if self.tty else struct.pack(">BxxxI", 1, 1) + b"x"


@pytest.fixture
def log_server() -> Iterator[LogServer]:
    """Keep server threads and sockets confined to each test, including failed timeout assertions."""
    state = LogServer()

    class Handler(BaseHTTPRequestHandler):
        """Implement only the inspect, finite-log, and ping endpoints used by the adapter."""

        def do_GET(self) -> None:
            """Send valid Docker metadata or a log body that can deliberately stop progressing."""
            if self.path.endswith("/json"):
                body = json.dumps({"Config": {"Tty": state.tty, "Env": ["DB_PASSWORD=secret-value"]}}).encode()
                self.reply(body)
            elif self.path.endswith("/_ping"):
                self.reply(b"OK")
            else:
                self.log_body()

        def reply(self, body: bytes) -> None:
            """Finish a normal bounded HTTP response."""
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_body(self) -> None:
            """Keep a declared response incomplete until cancellation or fixture cleanup."""
            state.opened.set()
            if state.mode == "headers":
                state.release.wait(2)
                return
            body = state.body()
            finite = state.mode in {"finite", "empty", "short_header", "short_payload"}
            self.send_response(state.status)
            self.send_header("Content-Length", str(len(body) if finite else 1048576))
            self.end_headers()
            try:
                self.wfile.write(body)
                self.wfile.flush()
                if finite:
                    return
                while not state.release.wait(0.02):
                    if state.mode == "trickle":
                        self.wfile.write(state.trickle_chunk())
                        self.wfile.flush()
            except (ConnectionError, OSError):
                return

        def log_message(self, format: str, *args: object) -> None:
            """Keep test-server request details out of application logs."""

    class Server(ThreadingHTTPServer):
        """Accept all eight workers without TCP backlog retries affecting the read-deadline test."""

        request_queue_size = 32

    server = Server(("127.0.0.1", 0), Handler)
    state.url = f"tcp://127.0.0.1:{server.server_port}"
    worker = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    worker.start()
    try:
        yield state
    finally:
        state.release.set()
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


@pytest.mark.parametrize("tty", [False, True], ids=["multiplexed", "tty"])
@pytest.mark.parametrize("mode", ["stalled", "trickle"])
async def test_log_deadline_releases_all_workers_without_returning_partial_success(
    log_server: LogServer, tty: bool, mode: str
) -> None:
    log_server.tty, log_server.mode = tty, mode
    runtime = DockerRuntime((HostConfig(id="local"),), Redactor(), timeout=0.2)
    try:
        with patch("docksight.adapters.outbound.docker.runtime.connect", side_effect=log_server.connect):
            outcomes = await asyncio.wait_for(
                asyncio.gather(*(runtime.logs("local", "a" * 64, 200, 4096) for _ in range(8)), return_exceptions=True),
                timeout=2,
            )
            assert all(isinstance(error, DockSightError) and error.code == "runtime_timeout" for error in outcomes), (
                outcomes
            )
            await asyncio.wait_for(runtime.ping("local"), timeout=1)
            await asyncio.wait_for(runtime.close(), timeout=1)
    finally:
        log_server.release.set()
        await asyncio.wait_for(runtime.close(), timeout=2)


@pytest.mark.parametrize("tty", [False, True], ids=["multiplexed", "tty"])
async def test_finite_logs_keep_decoding_redaction_and_the_actual_final_event(log_server: LogServer, tty: bool) -> None:
    log_server.tty, log_server.mode = tty, "finite"
    runtime = DockerRuntime((HostConfig(id="local"),), Redactor(), timeout=1)
    try:
        with patch("docksight.adapters.outbound.docker.runtime.connect", side_effect=log_server.connect):
            result = await runtime.logs("local", "a" * 64, 200, 4096)
        assert [entry.message for entry in result.entries] == ["password=[REDACTED]", "final event"]
        assert all(entry.timestamp is not None for entry in result.entries)
        assert not result.truncated
    finally:
        await runtime.close()


async def test_log_deadline_also_bounds_the_wait_for_response_headers(log_server: LogServer) -> None:
    log_server.mode = "headers"
    runtime = DockerRuntime((HostConfig(id="local"),), Redactor(), timeout=0.2)
    try:
        with (
            patch("docksight.adapters.outbound.docker.runtime.connect", side_effect=log_server.connect),
            pytest.raises(DockSightError) as caught,
        ):
            await asyncio.wait_for(runtime.logs("local", "a" * 64, 200, 4096), timeout=1)
        assert caught.value.code == "runtime_timeout"
    finally:
        log_server.release.set()
        await runtime.close()


async def test_cancelled_log_caller_leaves_no_worker_blocking_shutdown(
    log_server: LogServer, caplog: pytest.LogCaptureFixture
) -> None:
    runtime = DockerRuntime((HostConfig(id="local"),), Redactor(), timeout=0.2)
    try:
        with patch("docksight.adapters.outbound.docker.runtime.connect", side_effect=log_server.connect):
            pending = asyncio.create_task(runtime.logs("local", "a" * 64, 200, 4096))
            assert await asyncio.to_thread(log_server.opened.wait, 1)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            await asyncio.wait_for(runtime.close(), timeout=1)
            assert not [record for record in caplog.records if record.levelno >= ERROR]
    finally:
        log_server.release.set()
        await asyncio.wait_for(runtime.close(), timeout=2)


@pytest.mark.parametrize("mode", ["short_header", "short_payload"])
async def test_incomplete_docker_frames_fail_instead_of_returning_partial_logs(
    log_server: LogServer, mode: str
) -> None:
    log_server.mode = mode
    runtime = DockerRuntime((HostConfig(id="local"),), Redactor(), timeout=1)
    try:
        with (
            patch("docksight.adapters.outbound.docker.runtime.connect", side_effect=log_server.connect),
            pytest.raises(DockSightError) as caught,
        ):
            await runtime.logs("local", "a" * 64, 200, 4096)
        assert caught.value.code == "runtime_unavailable"
    finally:
        await runtime.close()


@pytest.mark.parametrize("tty", [False, True], ids=["multiplexed", "tty"])
async def test_empty_log_responses_remain_successful(log_server: LogServer, tty: bool) -> None:
    log_server.tty, log_server.mode = tty, "empty"
    runtime = DockerRuntime((HostConfig(id="local"),), Redactor(), timeout=1)
    try:
        with patch("docksight.adapters.outbound.docker.runtime.connect", side_effect=log_server.connect):
            result = await runtime.logs("local", "a" * 64, 200, 4096)
        assert result.entries == ()
        assert not result.truncated
    finally:
        await runtime.close()


@pytest.mark.parametrize(("status", "code"), [(404, "container_not_found"), (500, "runtime_unavailable")])
async def test_error_status_does_not_consume_a_slow_untrusted_body(
    log_server: LogServer, status: int, code: str
) -> None:
    log_server.status, log_server.mode = status, "trickle"
    runtime = DockerRuntime((HostConfig(id="local"),), Redactor(), timeout=0.1)
    try:
        with (
            patch("docksight.adapters.outbound.docker.runtime.connect", side_effect=log_server.connect),
            pytest.raises(DockSightError) as caught,
        ):
            await asyncio.wait_for(runtime.logs("local", "a" * 64, 200, 4096), timeout=0.6)
        assert caught.value.code == code
    finally:
        log_server.release.set()
        await asyncio.wait_for(runtime.close(), timeout=1)


@pytest.mark.parametrize("tty", [False, True], ids=["multiplexed", "tty"])
async def test_ssh_deadline_interrupts_buffered_channel_reads(tty: bool) -> None:
    channel = Channel(1)
    channel.active = True
    channel.transport = MagicMock()
    channel.settimeout(0.1)
    channel.in_buffer.feed(b"HTTP/1.1 200 OK\r\nContent-Length: 2097152\r\n\r\n")
    if not tty:
        channel.in_buffer.feed(struct.pack(">BxxxI", 1, 1048576))
    channel.in_buffer.feed(b"x")
    http_response = HTTPResponse(channel)
    http_response.begin()
    response = Response()
    response.status_code = 200
    response.raw = SimpleNamespace(_fp=http_response, read=http_response.read, close=http_response.close)
    client = APIClient(base_url="tcp://127.0.0.1:1", version="1.45")
    client.base_url = "http+docker://ssh"
    stopped = Event()

    def trickle() -> None:
        """Model SSH transport delivery that continually resets the channel's inactivity timeout."""
        while not stopped.wait(0.01):
            channel.in_buffer.feed(b"x")

    feeder = Thread(target=trickle, daemon=True)
    feeder.start()
    pending: asyncio.Task[bytes] | None = None
    try:
        with patch.object(client, "_get", return_value=response), pytest.raises(DockSightError) as caught:
            pending = asyncio.create_task(
                asyncio.to_thread(read_logs, client, "a" * 64, tty, 200, monotonic() + 0.1, 8388608)
            )
            await asyncio.wait_for(asyncio.shield(pending), timeout=0.6)
        assert caught.value.code == "runtime_timeout"
    finally:
        stopped.set()
        channel.in_buffer.close()
        feeder.join(timeout=1)
        if pending:
            await asyncio.gather(pending, return_exceptions=True)
        channel.close()
        client.close()


@pytest.mark.parametrize("tty", [False, True], ids=["multiplexed", "tty"])
async def test_log_scan_limit_rejects_oversized_tails_without_returning_a_middle_excerpt(
    log_server: LogServer, tty: bool
) -> None:
    log_server.tty, log_server.mode = tty, "finite"
    runtime = DockerRuntime((HostConfig(id="local"),), Redactor(), timeout=1)
    try:
        with (
            patch("docksight.adapters.outbound.docker.runtime.connect", side_effect=log_server.connect),
            patch("docksight.adapters.outbound.docker.runtime.MAX_LOG_SCAN_BYTES", 32),
            pytest.raises(DockSightError) as caught,
        ):
            await runtime.logs("local", "a" * 64, 200, 4096)
        assert caught.value.code == "log_read_limit"
    finally:
        await runtime.close()
