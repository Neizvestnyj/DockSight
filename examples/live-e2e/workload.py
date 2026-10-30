import socket
import sys
import time
from pathlib import Path


def dependency() -> None:
    """Fail startup on an actual refused connection inside this isolated container."""
    try:
        with socket.create_connection(("127.0.0.1", 5432), timeout=2):
            pass
    except OSError:
        print(
            "DatabaseConnectionError: PostgreSQL connection refused at 127.0.0.1:5432 during startup migration"
        )
        raise SystemExit(1) from None
    raise RuntimeError("The fixture unexpectedly reached a database")


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


def database_logs() -> None:
    """Emit synthetic PostgreSQL-style SQL errors while Docker keeps this workload running; no database is hosted."""
    for index in range(60):
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
    Path("/tmp/ready").touch()
    while True:
        time.sleep(1)


def main() -> None:
    """Run one explicit workload without contacting the host or any external network."""
    mode = sys.argv[1]
    if mode == "dependency":
        dependency()
    elif mode == "oom":
        oom()
    elif mode == "logs":
        logs()
    elif mode == "database-logs":
        database_logs()
    elif mode == "crash":
        print("ConfigurationError: REQUIRED_SETTING is missing; initialization aborted")
        raise SystemExit(1)
    elif mode == "unknown":
        print("Worker ended without recording the reason for termination")
        raise SystemExit(137)
    else:
        raise ValueError("Unknown fixture workload")


if __name__ == "__main__":
    main()
