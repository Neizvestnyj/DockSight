import os
import signal
import socket
import sys
import time
from functools import partial
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import FrameType


def dependency() -> None:
    """Fail startup on an actual refused connection inside this isolated container."""
    startup_history()
    try:
        with socket.create_connection(("127.0.0.1", 5432), timeout=2):
            pass
    except OSError:
        print(
            "DatabaseConnectionError: PostgreSQL connection refused at 127.0.0.1:5432 during startup migration"
        )
        raise SystemExit(1) from None
    raise RuntimeError("The fixture unexpectedly reached a database")


def startup_history() -> None:
    """Opt into finite synthetic startup history that fills a production four-KiB automatic log read."""
    if os.environ.get("DOCKSIGHT_E2E_DENSE_LOGS") != "1":
        return
    for index in range(32):
        print(
            f"2026-10-31T10:12:{index:02d}.125Z level=INFO service=fixture-worker "
            f"trace_id={index * 7919:032x} span_id={index * 104729:016x} "
            f"phase=startup component=migration step={index:02d} elapsed_ms={index * 137} "
            "operation=validate_schema database=fixture_app attempt=1 result=pending"
        )


def standalone() -> None:
    """Emit bounded startup context before an independently observable non-Compose failure."""
    startup_history()
    print("StandaloneStartupError: startup failed")
    raise SystemExit(1)


def oom() -> None:
    """Exceed the container memory limit so Docker records a real OOM kill."""
    print("Starting a 256 MiB allocation; the container memory limit is 64 MiB")
    allocation = bytearray(256 * 1024 * 1024)
    print(len(allocation))
    raise RuntimeError("The engine did not enforce the fixture memory limit")


def logs() -> None:
    """Generate bounded synthetic application output that exceeds the diagnostic byte budget."""
    for index in range(800):
        print(f"batch={index:04d} Processing fixture records " + "x" * 160)
    Path("/tmp/ready").touch()
    while True:
        time.sleep(1)


def database_history(records: int) -> None:
    """Emit finite synthetic PostgreSQL-style request failures and recovery; no database engine is hosted."""
    for index in range(records):
        print(
            f'ERROR: invalid input value for enum login_provider: "invalid_provider" request={index}'
        )
        print(
            'ERROR: insert or update on table "event" violates foreign key constraint "event_item_id_fkey"'
        )
        print('DETAIL: Key (item_id)=(2000000000) is not present in table "item".')
    print("LOG: automatic recovery in progress")
    print("LOG: invalid record length at 14/5A179788: expected at least 24, got 0")
    print("LOG: redo done at 14/5A179750")
    print("LOG: database system is ready to accept connections")


def shutdown_logs() -> None:
    """Record the workload's orderly stop sequence without identifying who requested it."""
    print("LOG: received fast shutdown request")
    print("LOG: aborting any active transactions")
    print("LOG: shutting down")
    print("LOG: checkpoint complete")
    print("LOG: database system is shut down")


def database_logs(shutdown: bool = False, records: int = 60) -> None:
    """Follow synthetic request history with a running process or an immediate clean exit."""
    database_history(records)
    if shutdown:
        shutdown_logs()
        return
    Path("/tmp/ready").touch()
    while True:
        time.sleep(1)


def graceful() -> None:
    """Remain running until Docker delivers SIGTERM, then actually exit cleanly after old request errors."""

    def terminate(signum: int, frame: FrameType | None) -> None:
        """Handle the real stop signal without claiming to know its initiator."""
        shutdown_logs()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, terminate)
    database_logs(records=8)


class HealthHandler(BaseHTTPRequestHandler):
    """Serve real probe failures while the container's main process continues to run."""

    def do_GET(self) -> None:
        """Return an observable HTTP 503 for health probes without inventing a deeper cause."""
        self.send_response(503 if self.path == "/health" else 200)
        self.end_headers()
        self.wfile.write(b"unavailable\n" if self.path == "/health" else b"running\n")


def unhealthy() -> None:
    """Run a real HTTP endpoint polled by Docker's configured healthcheck."""
    with HTTPServer(("127.0.0.1", 8080), HealthHandler) as server:
        print("HTTP server listening on 127.0.0.1:8080")
        server.serve_forever()


def crash() -> None:
    """Fail initialization so Docker's restart policy produces a genuine crash loop."""
    print("ConfigurationError: REQUIRED_SETTING is missing; initialization aborted")
    raise SystemExit(1)


def unknown() -> None:
    """Exit with 137 without triggering an OOM or recording a cause; this does not simulate SIGKILL."""
    print("Worker ended without recording the reason for termination")
    raise SystemExit(137)


def main() -> None:
    """Run one explicit workload without contacting the host or any external network."""
    modes = {
        "dependency": dependency,
        "standalone": standalone,
        "oom": oom,
        "logs": logs,
        "database-logs": database_logs,
        "database-current": partial(database_logs, records=8),
        "database-shutdown": partial(database_logs, shutdown=True),
        "clean-shutdown": graceful,
        "unhealthy": unhealthy,
        "crash": crash,
        "unknown": unknown,
    }
    if sys.argv[1] not in modes:
        raise ValueError("Unknown fixture workload")
    modes[sys.argv[1]]()


if __name__ == "__main__":
    main()
