"""Process-wide mute switch (B1, mode A: the server drops the uplink frames).

One `MuteState` is created by `server.main()` before the WebSocket server starts
and injected into both the 4410 `Session` and the 4411 control handlers, so the
voice path and `/debug/mute` always read the same truth. The state is persisted
to `~/.esp32-voice/mute.json` (0600, atomic replace) and reloaded on the next
start.

Mode A means the board keeps its microphone on and keeps uploading: the server
throws every frame away *before* Opus decode. Only the firmware (B2) can stop
the capture itself, so both `/debug/mute` and the CLI say so explicitly.

This module deliberately has no dependency on the audio stack or the firmware:
it is importable offline and unit-testable with an injected clock.
"""
from __future__ import annotations

import datetime
import json
import os
import tempfile
import threading
import time
from pathlib import Path

DEFAULT_PATH = "~/.esp32-voice/mute.json"
DEFAULT_LOG_INTERVAL_S = 60.0

MODE = "A"
# Shown by GET /debug/mute and the CLI. The wording is an acceptance item:
# a muted board is *not* a board with the microphone switched off.
MODE_NOTE = "服务端丢帧；设备仍在采集并上传，B2 后才是设备停采"

_STATE: "MuteState | None" = None


def _iso(value: datetime.datetime | None) -> str | None:
    return value.isoformat(timespec="seconds") if value else None


def _parse_iso(value) -> datetime.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.datetime.fromisoformat(value)
    except ValueError:
        return None


class MuteState:
    """The switch plus its per-cycle frame counters.

    `muted` is the only value the gates read. Counters are diagnostics: they are
    zeroed when a mute cycle starts and the previous cycle is kept in
    `previous`, so `/debug/mute` can show what the just-ended silence dropped.

    The `[mute] frames_in=...` heartbeat is emitted from `note_frame()`, i.e.
    only when a frame actually arrives. That is deliberate: in mode A the board
    keeps streaming, so real uplink is the useful signal; a wall-clock timer
    would print zero lines for an offline device and pretend the gate is
    working. No frames -> no heartbeat line.
    """

    def __init__(self, path=None, *, log_interval_s: float = DEFAULT_LOG_INTERVAL_S,
                 clock=None, monotonic=None, log=None):
        self.path = Path(path or DEFAULT_PATH).expanduser()
        self.log_interval_s = float(log_interval_s)
        self._clock = clock or datetime.datetime.now
        self._monotonic = monotonic or time.monotonic
        self._log = log or (lambda line: print(line, flush=True))
        self._lock = threading.RLock()

        self.muted = False
        self.since: datetime.datetime | None = None
        self.changed_by: str | None = None
        self.updated_at: datetime.datetime | None = None

        self.frames_in = 0
        self.frames_dropped = 0
        self.frames_accepted = 0
        self.turns = 0
        self.last_frame_at: datetime.datetime | None = None
        self._previous: dict | None = None
        self._last_report = self._monotonic()

    # ---------------- persistence ----------------

    def load(self) -> bool:
        """Read the persisted state. Missing file means "not muted".

        A corrupt file must not take the server down or silently mute the
        board: log ERROR, keep the safe default (unmuted) and leave the file for
        an operator to inspect.
        """
        with self._lock:
            try:
                raw = self.path.read_text(encoding="utf-8")
            except FileNotFoundError:
                self._log(f"[mute] no state file at {self.path}; default unmuted")
                return False
            except OSError as exc:
                self._log(f"[mute] ERROR cannot read {self.path} "
                          f"({type(exc).__name__}: {exc}); default unmuted")
                return False
            try:
                data = json.loads(raw)
            except (TypeError, ValueError) as exc:
                self._log(f"[mute] ERROR bad JSON in {self.path} "
                          f"({type(exc).__name__}: {exc}); default unmuted")
                return False
            if not isinstance(data, dict):
                self._log(f"[mute] ERROR {self.path} is not a JSON object; "
                          "default unmuted")
                return False
            self.muted = data.get("muted") is True
            self.since = _parse_iso(data.get("since"))
            self.updated_at = _parse_iso(data.get("updated_at"))
            changed_by = data.get("changed_by")
            self.changed_by = str(changed_by) if changed_by else None
            if self.muted and self.since is None:
                self.since = self.updated_at or self._clock()
            self._last_report = self._monotonic()
            self._log(f"[mute] loaded muted={self.muted} from {self.path}")
            return True

    def save(self) -> bool:
        """Persist the current state; False (and ERROR) when the write fails."""
        with self._lock:
            try:
                self._write_payload(self._payload())
            except Exception as exc:  # noqa: BLE001 - persistence must be loud
                self._log(f"[mute] ERROR cannot write {self.path} "
                          f"({type(exc).__name__}: {exc}); state unchanged")
                return False
            return True

    def _payload(self) -> dict:
        return {
            "muted": bool(self.muted),
            "since": _iso(self.since),
            "changed_by": self.changed_by,
            "updated_at": _iso(self.updated_at),
        }

    def _write_payload(self, payload: dict) -> None:
        """Atomic 0600 write: tmp file in the same dir, fsync, os.replace."""
        parent = self.path.parent
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            os.chmod(parent, 0o700)
        except OSError:
            pass
        fd, tmp = tempfile.mkstemp(dir=str(parent), prefix=".mute-", suffix=".tmp")
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
            os.chmod(self.path, 0o600)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    # ---------------- switching ----------------

    def set_muted(self, muted: bool, changed_by: str = "http") -> tuple[bool, str | None]:
        """Flip the switch and persist it. Returns `(ok, error)`.

        Memory changes only after the file was replaced, so a failed write is
        reported as HTTP 500 instead of leaving the server muted while the next
        restart would not be. Repeating the same value is a no-op (no write, no
        log line, no catch-up).
        """
        muted = bool(muted)
        with self._lock:
            if muted == self.muted:
                return True, None
            now = self._clock()
            payload = {
                "muted": muted,
                "since": _iso(now) if muted else None,
                "changed_by": changed_by,
                "updated_at": _iso(now),
            }
            try:
                self._write_payload(payload)
            except Exception as exc:  # noqa: BLE001
                self._log(f"[mute] ERROR cannot write {self.path} "
                          f"({type(exc).__name__}: {exc}); state unchanged")
                return False, "persist failed"

            self.muted = muted
            self.since = now if muted else None
            self.changed_by = changed_by
            self.updated_at = now
            if muted:
                # Fresh cycle; keep the counters of the interval that just ended.
                self._previous = {
                    "frames_in": self.frames_in,
                    "frames_dropped": self.frames_dropped,
                    "frames_accepted": self.frames_accepted,
                    "turns": self.turns,
                    "ended_at": _iso(now),
                }
                self.frames_in = 0
                self.frames_dropped = 0
                self.frames_accepted = 0
                self.turns = 0
                self.last_frame_at = None
                self._last_report = self._monotonic()
                self._log(f"[mute] ON by={changed_by} since={_iso(now)} "
                          f"mode={MODE} (server drops frames; device keeps uploading)")
            else:
                self._log(f"[mute] OFF by={changed_by} at={_iso(now)}")
            return True, None

    def toggle(self, changed_by: str = "http") -> tuple[bool, str | None]:
        return self.set_muted(not self.muted, changed_by)

    # ---------------- 4410 counters ----------------

    def note_frame(self) -> None:
        """One uplink frame arrived. Called by Session._on_audio before decode."""
        with self._lock:
            self.frames_in += 1
            self.last_frame_at = self._clock()
            if self.muted:
                self.frames_dropped += 1
                self._maybe_report()
            else:
                self.frames_accepted += 1

    def note_turn(self) -> None:
        """A turn was started from accepted audio (never while muted)."""
        with self._lock:
            if not self.muted:
                self.turns += 1

    def _maybe_report(self) -> None:
        if self.log_interval_s <= 0:
            return
        now = self._monotonic()
        if now - self._last_report < self.log_interval_s:
            return
        self._last_report = now
        self._log(f"[mute] frames_in={self.frames_in} "
                  f"dropped={self.frames_dropped} "
                  f"accepted={self.frames_accepted} turns={self.turns}")

    # ---------------- observability ----------------

    def status(self) -> dict:
        with self._lock:
            return {
                "muted": self.muted,
                "since": _iso(self.since),
                "changed_by": self.changed_by,
                "updated_at": _iso(self.updated_at),
                "mode": MODE,
                "mode_note": MODE_NOTE,
                "counters": {
                    "frames_in": self.frames_in,
                    "frames_dropped": self.frames_dropped,
                    "frames_accepted": self.frames_accepted,
                    "turns": self.turns,
                },
                "last_frame_at": _iso(self.last_frame_at),
                "previous": dict(self._previous) if self._previous else None,
                "persisted_path": str(self.path),
            }


# ---------------- process-wide instance (injected by server.main) ----------------

def configure(path=None, *, log_interval_s: float = DEFAULT_LOG_INTERVAL_S,
              clock=None, monotonic=None, log=None) -> MuteState:
    """Create, load and install the process-wide switch; returns the instance."""
    global _STATE
    state = MuteState(path, log_interval_s=log_interval_s, clock=clock,
                      monotonic=monotonic, log=log)
    state.load()
    _STATE = state
    return state


def get_state() -> "MuteState | None":
    return _STATE
