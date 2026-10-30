"""Single-instance guard: a taken port must end the process with one line.

2026-10-30: two instances fought over 4411, the loser wrote an aiohttp
traceback, launchd KeepAlive restarted it and the board reconnected every few
seconds. These tests hold a real port and run the real entrypoint in a
subprocess, because the property is about exit status and stderr - not about a
mock.

Ports are picked dynamically: the house service may be running on 4410/4411 and
a test must never seize it.
"""
import errno
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import netguard  # noqa: E402


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def hold(port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", port))
    sock.listen(1)
    return sock


def write_config(tmp_path: Path, ws_port: int, ota_port: int) -> Path:
    path = tmp_path / "cfg.yaml"
    path.write_text(
        "server:\n"
        "  host: 127.0.0.1\n"
        f"  port: {ws_port}\n"
        f"  ota_port: {ota_port}\n",
        encoding="utf-8",
    )
    return path


# The entrypoint imports the audio stack, whose Opus library is not loadable on
# this Mac. The guard runs before any of it is touched, so a stub is enough.
ENTRY = """
import asyncio, sys, types
sys.modules.setdefault("opuslib", types.ModuleType("opuslib"))
import server
asyncio.run(server.main(__import__("pathlib").Path(sys.argv[1])))
"""


def run_startup(cfg_path: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    return subprocess.run([sys.executable, "-c", ENTRY, str(cfg_path)],
                          capture_output=True, text=True, env=env, timeout=180)


# ---------------- probe primitives ----------------

def test_port_is_free_while_nothing_listens():
    port = free_port()
    assert netguard.port_is_free("127.0.0.1", port) is True


def test_port_is_free_false_while_held():
    port = free_port()
    with hold(port):
        assert netguard.port_is_free("127.0.0.1", port) is False
        assert netguard.first_busy_port("127.0.0.1", (free_port(), port)) == port


def test_handle_bind_error_reports_the_busy_port(capsys):
    port = free_port()
    with hold(port):
        with pytest.raises(SystemExit) as exc:
            netguard.handle_bind_error(
                OSError(errno.EADDRINUSE, "address in use"), "127.0.0.1", (port,))
    assert exc.value.code == 1
    assert netguard.FATAL_TEMPLATE.format(port=port) in capsys.readouterr().out


def test_handle_bind_error_reraises_unrelated_oserror():
    with pytest.raises(OSError) as exc:
        netguard.handle_bind_error(
            OSError(errno.EACCES, "permission denied"), "127.0.0.1", (free_port(),))
    assert exc.value.errno == errno.EACCES


# ---------------- the real entrypoint ----------------

def test_startup_exits_when_ota_port_is_taken(tmp_path):
    ota_port = free_port()
    ws_port = free_port()
    cfg = write_config(tmp_path, ws_port, ota_port)
    with hold(ota_port):
        proc = run_startup(cfg)
    output = proc.stdout + proc.stderr
    assert proc.returncode == 1, output[-400:]
    assert f"[fatal] port {ota_port} already in use" in proc.stdout
    assert "Traceback" not in output
    assert "[exit]" not in proc.stdout


def test_startup_exits_when_ws_port_is_taken(tmp_path):
    ws_port = free_port()
    ota_port = free_port()
    cfg = write_config(tmp_path, ws_port, ota_port)
    with hold(ws_port):
        proc = run_startup(cfg)
    output = proc.stdout + proc.stderr
    assert proc.returncode == 1, output[-400:]
    assert f"[fatal] port {ws_port} already in use" in proc.stdout
    assert "Traceback" not in output
    assert "[exit]" not in proc.stdout
