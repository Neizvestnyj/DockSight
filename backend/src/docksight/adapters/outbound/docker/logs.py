from collections.abc import Iterator
from contextlib import suppress
from socket import SHUT_RDWR
from threading import Timer
from time import monotonic
from typing import Protocol, cast

from docker.errors import DockerException, NotFound
from paramiko import Channel
from requests import Response
from requests.exceptions import Timeout

from docksight.domain.errors import DockSightError, ErrorKind


class LogAPI(Protocol):
    """Describe the SDK internals needed for a finite, cancellable log response."""

    def _url(self, pathfmt: str, *args: str) -> str:
        """Build an API-versioned URL using the configured Docker transport."""
        ...

    def _get(self, url: str, *, params: dict[str, int], stream: bool, timeout: float) -> Response:
        """Open an HTTP response with a bounded wait for its headers."""
        ...

    def _get_raw_response_socket(self, response: Response) -> object:
        """Resolve the transport-specific socket after validating the HTTP status."""
        ...


class _Socket(Protocol):
    """Describe cancellation shared by local sockets, SSH channels, and named pipes."""

    def shutdown(self, how: int) -> None:
        """Interrupt an outstanding read so the owning worker can close its response."""
        ...


def _remaining(deadline: float) -> float:
    """Reject expired reads instead of presenting the bytes collected so far as a complete tail."""
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise DockSightError("runtime_timeout", "Docker log read timed out", ErrorKind.TIMEOUT)
    return remaining


def read_logs(client: LogAPI, container_id: str, tty: bool, lines: int, deadline: float, scan_limit: int) -> bytes:
    """Preserve HTTP read timeouts and abort finite log bodies at an absolute deadline."""
    params = {"stdout": 1, "stderr": 1, "timestamps": 1, "follow": 0, "tail": lines}
    # The SDK exposes transport-aware response access only through these protected methods.
    url = client._url("/containers/{0}/logs", container_id)  # pyright: ignore[reportPrivateUsage]
    try:
        response = client._get(  # pyright: ignore[reportPrivateUsage]
            url, params=params, stream=True, timeout=_remaining(deadline)
        )
    except Timeout as exc:
        raise DockSightError("runtime_timeout", "Docker log read timed out", ErrorKind.TIMEOUT) from exc
    with response:
        if response.status_code == 404:
            raise NotFound("Container not found")
        response.raise_for_status()
        raw = client._get_raw_response_socket(response)  # pyright: ignore[reportPrivateUsage]
        transport = cast(_Socket, getattr(raw, "_sock", raw))

        def abort() -> None:
            """Unblock HTTP reads without closing a buffered response from a competing thread."""
            if isinstance(transport, Channel):
                # Paramiko shutdown only marks EOF. Close buffers locally; the worker owns client shutdown.
                transport.in_buffer.close()
                transport.in_stderr_buffer.close()
                return
            with suppress(OSError):
                transport.shutdown(SHUT_RDWR)

        timer = Timer(_remaining(deadline), abort)
        timer.daemon = True
        timer.start()
        try:
            return _read_body(response, tty, deadline, scan_limit)
        finally:
            timer.cancel()
            timer.join()


def _read_body(response: Response, tty: bool, deadline: float, scan_limit: int) -> bytes:
    """Keep transport failures explicit and distinguish deadline cancellation from a complete response."""
    try:
        chunks = response.iter_content(16384) if tty else _frames(response, deadline, scan_limit)
        result = bytearray()
        for chunk in chunks:
            _remaining(deadline)
            if len(result) + len(chunk) > scan_limit:
                raise DockSightError(
                    "log_read_limit",
                    "Docker log tail exceeded the bounded read limit; latest output is unknown",
                    ErrorKind.DEPENDENCY,
                )
            result.extend(chunk)
        _remaining(deadline)
        return bytes(result)
    except DockSightError:
        raise
    except Exception as exc:
        if monotonic() >= deadline:
            raise DockSightError("runtime_timeout", "Docker log read timed out", ErrorKind.TIMEOUT) from exc
        raise DockerException("Docker log stream failed") from exc


def _frames(response: Response, deadline: float, scan_limit: int) -> Iterator[bytes]:
    """Decode finite Docker frames while retaining the HTTP read timeout and limiting allocations."""
    scanned = 0
    while True:
        _remaining(deadline)
        header = cast(bytes, response.raw.read(8))
        if not header:
            return
        if len(header) != 8:
            raise DockerException("Incomplete Docker log frame header")
        length = int.from_bytes(header[4:], "big")
        if length > scan_limit - scanned:
            raise DockSightError(
                "log_read_limit",
                "Docker log tail exceeded the bounded read limit; latest output is unknown",
                ErrorKind.DEPENDENCY,
            )
        data = cast(bytes, response.raw.read(length))
        if len(data) != length:
            raise DockerException("Incomplete Docker log frame payload")
        scanned += length
        yield data
