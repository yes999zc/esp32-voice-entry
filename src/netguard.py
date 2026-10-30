"""Single-instance guard: refuse to start when a service port is already taken.

2026-10-30 incident: two instances raced for 4411. The loser raised
``OSError: [Errno 48] error while attempting to bind ...`` inside aiohttp, wrote
a traceback, and launchd ``KeepAlive`` restarted it 10 s later - so the log
showed 18 tracebacks while the board kept reconnecting. Nothing ever told the
operator "another instance is running".

The guard binds each port once *before* any service starts, then releases it.
Binding with ``SO_REUSEADDR`` still fails when another socket is listening
(TIME_WAIT alone is ignored), which is the distinction we need: a stale
connection must not block a restart, a live instance must.
"""
import errno
import socket

FATAL_TEMPLATE = "[fatal] port {port} already in use — another instance is running"


def _family(host: str) -> int:
    return socket.AF_INET6 if ":" in host else socket.AF_INET


def port_is_free(host: str, port: int) -> bool:
    """True when this process could bind ``host:port`` right now."""
    with socket.socket(_family(host), socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, int(port)))
        except OSError:
            return False
    return True


def first_busy_port(host: str, ports) -> int | None:
    for port in ports:
        if not port_is_free(host, int(port)):
            return int(port)
    return None


def fatal_port_in_use(port: int):
    """Print the one line an operator needs, then exit non-zero (no traceback)."""
    print(FATAL_TEMPLATE.format(port=int(port)), flush=True)
    raise SystemExit(1)


def ensure_ports_free(host: str, ports) -> None:
    busy = first_busy_port(host, ports)
    if busy is not None:
        fatal_port_in_use(busy)


def handle_bind_error(exc: OSError, host: str, ports) -> None:
    """Convert a lost bind race into the same one-line fatal.

    The pre-flight probe can still lose to a process that binds between the
    probe and the real ``listen()``. Callers pass the ports they were trying to
    open and get the same message (plus no traceback) instead of a crash loop.
    """
    if exc.errno == errno.EADDRINUSE:
        busy = first_busy_port(host, ports)
        fatal_port_in_use(busy if busy is not None else int(ports[0]))
    raise exc
