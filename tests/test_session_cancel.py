"""task-1: a turn has a hard ceiling, and a disconnect really lets go upstream.

2026-11-02 incident: the board was powered off mid-request, our server logged
`[turn] cancelled`, but the upstream agent kept working because (a) nothing
bounded how long one turn could take and (b) cancelling the task without
awaiting it left the HTTP stream to be torn down whenever the loop got to it.

Rules under test:
  * a turn that never answers is closed by `turn_timeout_s` and the board is
    left in a clean state instead of being reported as a normal answer;
  * cancelling the turn waits for it to unwind, so the upstream connection is
    released before the session forgets the task;
  * a second turn cannot start while one is in flight (no stacked upstream
    requests from the bench hook).
"""

import asyncio
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

sys.modules.setdefault("opuslib", types.ModuleType("opuslib"))

import session as voice_session  # noqa: E402

Session = voice_session.Session


def _bare_session(**overrides):
    """A Session with only the attributes these three paths touch.

    The real constructor needs a websocket, codec, ASR, LLM and TTS; the turn
    ceiling and the cancel path are pure control flow, so they are exercised
    without any of that.
    """
    sess = Session.__new__(Session)
    sess.log_prefix = "[test]"
    sess.turn = None
    sess.turn_timeout_s = 1.0
    sess.speaking = False
    sess._reply_ready = True
    sess.timeouts = []
    sess._reply_ready = True

    async def _record_timeout():
        sess.timeouts.append(True)

    sess._abort_after_timeout = _record_timeout
    for key, value in overrides.items():
        setattr(sess, key, value)
    return sess


async def test_turn_timeout_fires_and_cleans_up():
    sess = _bare_session()
    loop = asyncio.get_running_loop()
    started = loop.time()

    async def never_answers():
        await asyncio.sleep(30)

    finished = await sess._guard_turn(never_answers(), started)

    assert finished is False
    assert loop.time() - started < 3, "the ceiling must fire near turn_timeout_s"
    assert sess.timeouts == [True], "a timed-out turn must clean the board state"


async def test_cancel_turn_waits_for_upstream_to_close():
    sess = _bare_session()
    closed = []
    leaked = []

    async def upstream():
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            closed.append("closed")   # stands in for aiohttp releasing the socket
            raise

    sess.turn = asyncio.create_task(upstream())
    await asyncio.sleep(0)            # let the task reach its await

    try:
        await sess._cancel_turn()
    except Exception as exc:          # pragma: no cover - the helper must swallow
        leaked.append(exc)

    assert closed == ["closed"], "the upstream coroutine never saw the cancellation"
    assert leaked == [], f"cancelling leaked {leaked!r}"
    assert sess.turn.done(), "the turn stayed alive after the disconnect path"


async def test_start_text_turn_refuses_while_a_turn_is_in_flight():
    sess = _bare_session()

    async def never_answers():
        await asyncio.sleep(30)

    sess.turn = asyncio.create_task(never_answers())
    try:
        assert sess.start_text_turn("现在几点") is None
    finally:
        await sess._cancel_turn()


def test_turn_timeout_is_clamped():
    assert voice_session._turn_timeout_from_cfg({}) == 90.0
    assert voice_session._turn_timeout_from_cfg({"session": {"turn_timeout_s": 0.1}}) == 5.0
    assert voice_session._turn_timeout_from_cfg({"session": {"turn_timeout_s": 999}}) == 300.0
    assert voice_session._turn_timeout_from_cfg({"session": {"turn_timeout_s": "45"}}) == 45.0
    assert voice_session._turn_timeout_from_cfg({"session": {"turn_timeout_s": "bad"}}) == 90.0
