"""Per-connection pipeline: hello -> VAD -> ASR -> LLM -> TTS -> Opus frames."""
import asyncio
import difflib
import json
import random
import re
import time
import unicodedata
import uuid
import shutil
import subprocess
from pathlib import Path

import numpy as np

import persona
import protocol
import proactive
from dialogue import classify_confirm
from llm import Llm
import tools as devtools
from audio import (build_segment_recorder, build_vad, is_noise_segment,
                   pop_segments, resample)

MIN_SEGMENT_SECONDS = 0.3
SPEECH_FRAME_SECONDS = 0.06

# Filler ("I heard you, I'm working") used to be a whole TTS sentence. A 160 ms
# locally generated chime acknowledges the turn without pushing the real answer
# back and without spending a TTS request at all. rui makes the same call with a
# 160 ms chime (house-ear src/rui/audio/chime.py, MIT). Hard ceiling: the filler
# must never sound like a full sentence.
FILLER_CHIME_MS = 160
# The delay mask is visual by default: after the segment closes, switch the face
# to "thinking". Empty string disables the cue entirely. 9哥 2026-10-27: the
# screen already shows state/subtitles, so a sound only steals attention.
THINKING_FACE_DEFAULT = "thinking"
FILLER_CHIME_MIN_MS = 20          # shorter than the 8 ms fades is not a sound
FILLER_CHIME_MAX_MS = 300

# The chime has to lead the answer, not follow the old spoken-filler delay. Fired
# this long after the segment closes; skipped when the real answer is already
# queued. 400 ms is the acceptance ceiling (log time for the chime must be <=400).
PROACTIVE_CHIME_LEAD_MS = 300
PROACTIVE_CHIME_LEAD_MAX_MS = 400


def _chime_pcm(sample_rate: int, ms: int = FILLER_CHIME_MS) -> np.ndarray:
    """Short soft beep, mono int16, with fade in/out so it does not click."""
    if not FILLER_CHIME_MIN_MS <= ms <= FILLER_CHIME_MAX_MS:
        raise ValueError(f"filler chime must be {FILLER_CHIME_MIN_MS}-"
                         f"{FILLER_CHIME_MAX_MS} ms, got {ms}")
    n = int(sample_rate * ms / 1000)
    t = np.arange(n, dtype=np.float32) / float(sample_rate)
    tone = np.sin(2 * np.pi * 880.0 * t)
    fade = max(1, int(sample_rate * 0.008))
    envelope = np.ones(n, dtype=np.float32)
    envelope[:fade] = np.linspace(0.0, 1.0, fade, dtype=np.float32)
    envelope[-fade:] = np.linspace(1.0, 0.0, fade, dtype=np.float32)
    return (0.12 * tone * envelope * 32767).astype(np.int16)


def filler_chime_ms_for(conversation_cfg: dict) -> int:
    """Configured chime length, sanitised so a bad value cannot mute the device.

    Any typo must not abort `Session.__init__` (that would take the whole
    connection down): a non-number falls back to 160 ms, an oversized value is
    clamped to 300 ms, and anything in (0, 20) ms is disabled (too short to be
    an audible filler). The warning is per connection because this runs from
    `Session.__init__`; no global state is kept on purpose.
    """
    configured = conversation_cfg.get("filler_chime_ms", FILLER_CHIME_MS)
    try:
        raw = int(configured or 0)
    except (TypeError, ValueError):
        print(f"[filler] warning: filler_chime_ms={configured!r} is not a "
              f"number, using {FILLER_CHIME_MS} ms", flush=True)
        return FILLER_CHIME_MS
    if raw > FILLER_CHIME_MAX_MS:
        print(f"[filler] warning: filler_chime_ms={raw} clamped to "
              f"{FILLER_CHIME_MAX_MS} ms", flush=True)
        return FILLER_CHIME_MAX_MS
    if 0 < raw < FILLER_CHIME_MIN_MS:
        print(f"[filler] warning: filler_chime_ms={raw} is shorter than "
              f"{FILLER_CHIME_MIN_MS} ms, filler disabled", flush=True)
        return 0
    return max(0, raw)


def proactive_chime_lead_ms_for(conversation_cfg: dict) -> int:
    """How long after segment close the chime fires (0-400 ms, default 300).

    Same sanitise rule as the chime length: a typo must never crash
    `Session.__init__` or push the chime past the 400 ms acceptance ceiling.
    """
    configured = conversation_cfg.get("proactive_chime_lead_ms",
                                      PROACTIVE_CHIME_LEAD_MS)
    try:
        raw = int(configured or 0)
    except (TypeError, ValueError):
        print(f"[filler] warning: proactive_chime_lead_ms={configured!r} is "
              f"not a number, using {PROACTIVE_CHIME_LEAD_MS} ms", flush=True)
        return PROACTIVE_CHIME_LEAD_MS
    if raw > PROACTIVE_CHIME_LEAD_MAX_MS:
        print(f"[filler] warning: proactive_chime_lead_ms={raw} clamped to "
              f"{PROACTIVE_CHIME_LEAD_MAX_MS} ms", flush=True)
        return PROACTIVE_CHIME_LEAD_MAX_MS
    return max(0, raw)


def should_stream_sentences(stream_tts: bool, provider: str, route: str) -> bool:
    """Whether to speak sentences while the model is still generating.

    DeepSeek may return tool_calls in the middle of the text, so it is only safe
    when no tools are offered - which is exactly the fast (small-talk) route.
    Streaming the fast route is what removes the full-reply TTS synth (1.2 s on
    a 18 s answer) from the first-frame path.
    """
    return bool(stream_tts) and (provider != "deepseek" or route == "fast")

# The firmware's own wake word ("你好小智") often ends up in the ASR text because
# the device keeps streaming a moment after it fires. Strip a leading wake word
# so the model does not answer it as a question; a segment that is *only* the
# wake word must not open a turn at all.
WAKE_WORDS = (
    "你好，小智", "你好小智", "你好，小志", "你好小志",
    "你好，晓智", "你好晓智", "小智小智", "嗨，小智", "嗨小智",
)
_LEAD_PUNCT = "，,。.！!？?、 \t\n"
_URL_RE = re.compile(r"https?://\S+")


def strip_wake(text: str) -> str:
    """Remove a leading wake word and any punctuation glued to it."""
    out = text.lstrip(_LEAD_PUNCT)
    changed = True
    while changed:
        changed = False
        for word in WAKE_WORDS:
            if out.startswith(word):
                out = out[len(word):].lstrip(_LEAD_PUNCT)
                changed = True
    return out


# Same wake word, as SenseVoice actually hears it on this board (2026-10-30):
# 小智 -> 小志 / 小石 / 小日 / 晓智, and the leading 你 sometimes disappears.
# These must be rejected as "wake only" for the same reason as WAKE_WORDS: the
# board keeps streaming for ~1 s after it fires, so the segment carries the wake
# word alone, and sending that to the model produced answers to a question
# nobody asked (``[asr] 你好，小石。`` -> LLM).
WAKE_VARIANTS = (
    "你好小石", "你好小日", "好小日", "好小智", "好小志",
    "小智", "小志", "晓智", "小石", "小日",
)
def normalize_wake_text(text: str) -> str:
    """Fold an ASR line to the form the wake table is written in.

    NFKC makes full-width forms (Ｈｉ / ０) equal to ASCII, lower-casing makes the
    English wake spellings case-insensitive, and dropping every non-alphanumeric
    character removes the punctuation/space variants ASR sprinkles in
    (``你好，小智。`` -> ``你好小智``).
    """
    folded = unicodedata.normalize("NFKC", text or "").lower()
    return "".join(ch for ch in folded if ch.isalnum())


_WAKE_KEYS = tuple(dict.fromkeys(
    normalize_wake_text(word) for word in WAKE_WORDS + WAKE_VARIANTS
))

# SenseVoice also swaps homophones inside the wake word: 你 is heard as 郝/好/
# 高, and 智 as 志/石/日/时/识/纸. A 2-4 character line made only of an optional
# leading homophone plus 小/晓/笑/校 + one of those tails is the wake word, not
# a question ("郝小智", "好小时", "高小日" were all observed on this board on
# 2026-10-30 while the table above only had the 小志/小石/小日 spellings).
_WAKE_TAIL_RE = re.compile(
    r"^(?:你|尼|泥|郝|好|号|高|搞)?(?:小|晓|笑|校)[智志石时识日纸只制子治]$"
)


def _is_wake_tail(normalized: str) -> bool:
    return bool(_WAKE_TAIL_RE.match(normalized))



def match_wake_prefix(text: str) -> str | None:
    """Return the text after a leading wake word, or None when there is none.

    Longest match first so ``小智小智`` is consumed as two wake words rather than
    leaving ``小智`` behind as a "command".
    """
    normalized = normalize_wake_text(text)
    for key in sorted(_WAKE_KEYS, key=len, reverse=True):
        if normalized.startswith(key):
            return normalized[len(key):]
    return None


def _wake_similarity(text: str) -> float:
    normalized = normalize_wake_text(text)
    if not normalized:
        return 0.0
    return max(difflib.SequenceMatcher(None, normalized, key).ratio()
               for key in _WAKE_KEYS)


# A segment shorter than this cannot hold a question after the wake word: the
# board fires on "你好小智" and the same ~0.8 s segment reaches ASR. Anything
# longer gets the benefit of the doubt, because a real one-word command
# ("停"/"别说了") can be short too - those match a wake word poorly anyway.
WAKE_ONLY_MAX_SECONDS = 0.8
# 0.60 catches the heard-on-this-board variants (``好小日`` vs ``你好小日`` =
# 0.857, ``你好小石`` = 0.75) while loose greetings stay out: ``你好`` (0.667)
# and ``你好吗`` (0.571) are real things to answer, not a wake word. The 3-char
# floor removes the 2-char case outright, and 0.60 the 3-char one.
WAKE_ONLY_MIN_SIMILARITY = 0.60
WAKE_ONLY_MIN_CHARS = 3
WAKE_ONLY_MAX_CHARS = 6


def is_wake_only(text: str, duration_s: float | None = None) -> bool:
    """True when the segment is the wake word (or a misheard variant of it).

    Exact wake prefixes (``你好，小智。``) are always wake-only regardless of
    length. Fuzzy matching is deliberately narrow - short segment AND high
    character overlap with a wake key - so real short commands keep working.
    """
    normalized = normalize_wake_text(text)
    if not normalized:
        return True
    remainder = match_wake_prefix(normalized)
    if remainder is not None:
        return remainder == ""
    if _is_wake_tail(normalized):
        # A pure homophone of the wake word: length is irrelevant, the board
        # streams ~1 s after firing and that segment must never open a turn.
        return True
    if duration_s is None or duration_s >= WAKE_ONLY_MAX_SECONDS:
        return False
    if not WAKE_ONLY_MIN_CHARS <= len(normalized) <= WAKE_ONLY_MAX_CHARS:
        return False
    return _wake_similarity(normalized) >= WAKE_ONLY_MIN_SIMILARITY


# One-character utterances are usually silence fillers ("啊"/"好"), which the
# noise gate must keep rejecting. A stop command is the exception: losing it
# makes the board look deaf exactly when the user wants it to stop.
_SHORT_COMMANDS = frozenset({"停"})



# SenseVoice/Whisper silence hallucinations that look like plausible text. They
# must be rejected after ASR, because the (now looser) energy gate cannot tell
# them apart from quiet speech. Matched on alphanumeric-normalised text, so
# punctuation/spacing variations are covered.
_HALLUCINATION_MARKERS = (
    "谢谢观看", "感谢观看", "谢谢大家观看",
    "字幕", "请不吝点赞", "点赞订阅", "订阅转发", "打赏支持",
    "明镜与点点",
)


def _valid_text(text: str) -> bool:
    """Reject noise segments: too short, punctuation-only, or a known hallucination."""
    stripped = "".join(ch for ch in text if ch.isalnum())
    if len(stripped) < 2 and stripped not in _SHORT_COMMANDS:
        return False
    normalized = "".join(ch for ch in text.lower() if ch.isalnum())
    return not any(marker in normalized for marker in _HALLUCINATION_MARKERS)


def speech_text(reply: str) -> str:
    """Turn an agent reply into something worth saying out loud.

    The agent writes for a chat window: MEDIA: paths, URLs, markdown and code
    fences. None of that should be read aloud — the earlier run pronounced a
    /Users/... path character by character.
    """
    lines = [ln for ln in reply.splitlines() if not ln.strip().startswith("MEDIA:")]
    text = " ".join(lines)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)   # markdown links -> label
    text = _URL_RE.sub("", text)
    text = text.replace("`", "").replace("**", "").replace("__", "")
    text = re.sub(r"(?m)^\s*[#>\-*]\s+", "", text)
    return " ".join(text.split())


_MEDIA_RE = re.compile(r"(?m)^\s*MEDIA:\s*(\S+)\s*$")


def _media_paths(reply: str) -> list[str]:
    return [m.group(1) for m in _MEDIA_RE.finditer(reply or "")]


def _strip_media(reply: str) -> str:
    return _MEDIA_RE.sub("", reply or "")


# Live sessions, so a local debug endpoint (and later the tool layer) can talk
# to the device without owning the websocket.
_SESSIONS: set["Session"] = set()

# Voice notifications produced while the board is offline. The WS transport only
# accepts `notify` while the device is Idle, and an open audio channel keeps it in
# Listening, so the honest fallback is: speak it the next time it connects.
_PENDING_NOTIFY: list[str] = []


def queue_notification(text: str) -> int:
    _PENDING_NOTIFY.append(text)
    return len(_PENDING_NOTIFY)


def take_notifications() -> list[str]:
    global _PENDING_NOTIFY
    out, _PENDING_NOTIFY = _PENDING_NOTIFY, []
    return out


def active_sessions() -> list["Session"]:
    return [s for s in _SESSIONS if s.alive]


# ---------------- proactive v0 hooks ----------------
# The controller is process-wide and may not exist (tests, proactive disabled):
# every hook is a no-op without it, and none of them can raise into the loop.

def _note_human_speech() -> None:
    """Feed gate 2: the user just spoke, so stay quiet for a few seconds."""
    controller = proactive.get_controller()
    if controller is not None:
        controller.note_human_speech()


def _note_speech_in_progress(vad) -> None:
    """Feed gate 2 while the person is still talking.

    `_note_human_speech()` only fires when a segment closes, which is up to
    `human_silence_seconds` too late for a long sentence: the server would think the
    room went quiet mid-sentence and could start speaking over the person. The VAD
    knows speech is happening before it knows the sentence ended.
    """
    probe = getattr(vad, "is_speech_detected", None)
    if probe is None:
        return
    try:
        if probe():
            _note_human_speech()
    except Exception:
        pass


def _note_user_text(text: str) -> None:
    """Feed gate 6: 「别说了」 mutes proactive speech for mute_minutes."""
    controller = proactive.get_controller()
    if controller is not None and controller.note_user_text(text):
        print("[proactive] muted by user text", flush=True)


def _note_confirm_pending(topic: str, timeout: float) -> None:
    """Feed trigger 4: remind once when a destructive confirm goes unanswered."""
    controller = proactive.get_controller()
    if controller is not None:
        controller.note_confirm_pending(topic, timeout)


def _clear_confirm() -> None:
    """The pending action was answered (or expired): no reminder is due."""
    controller = proactive.get_controller()
    if controller is not None:
        controller.clear_confirm()



def _mcp_result_text(result) -> str:
    """Flatten an MCP tool result into text the LLM can read.

    Firmware shapes seen: {"content":[{"type":"text","text":"…"}],"isError":false},
    a bare string, or an arbitrary JSON object.
    """
    if isinstance(result, dict):
        content = result.get("content")
        if isinstance(content, list):
            parts = [c.get("text", "") for c in content if isinstance(c, dict)]
            text = "\n".join(p for p in parts if p)
            if text:
                return text
        return json.dumps(result, ensure_ascii=False)
    if isinstance(result, str):
        return result
    return json.dumps(result, ensure_ascii=False)



class Session:
    def __init__(self, ws, cfg: dict, codec, tts, asr, llm, filler_cache=None,
                 mute=None):
        self.ws = ws
        self.cfg = cfg
        self.codec = codec
        self.tts = tts
        self.asr = asr
        self.llm = llm
        # Process-wide mute switch (src/mute.py), injected by server.main so the
        # 4410 pipeline and 4411 /debug/mute read the same instance. None means
        # "feature not wired" (tests, minimal deployments) and disables the gate.
        self.mute = mute
        # Dual channel: small talk goes to the fast model, anything that looks like
        # work goes to the agent (which has memory, tools and the device).
        route = cfg["llm"].get("routing") or {}
        self.fast_llm = None
        if route.get("enabled") and llm.provider == "hermes":
            fast_cfg = dict(cfg["llm"])
            fast_cfg["provider"] = "deepseek"
            fast_cfg["model"] = route.get("model", "deepseek-flash")
            self.fast_llm = Llm(fast_cfg)
        self.route_max_chars = int(route.get("max_chars", 20))
        # Dangerous device actions need a spoken yes before they run. They are
        # never executed straight from the model's tool call.
        self.confirm_tools = set(cfg.get("safety", {}).get("confirm_tools", []))
        self.pending_confirm: dict | None = None
        # C2/C3 echo guard: when the last confirmation prompt finished playing.
        # A yes/no/weak-agreement utterance whose speech segment *started* within
        # `safety.confirm_echo_guard_ms` of this instant is the board hearing its
        # own TTS through the microphone, not consent (2026-10-28 reboot incident).
        self._confirm_prompt_end_at: float | None = None
        guard_ms = self.cfg.get("safety", {}).get("confirm_echo_guard_ms", 400)
        try:
            self.confirm_echo_guard_ms = max(0.0, float(guard_ms))
        except (TypeError, ValueError):
            # A typo must not crash Session.__init__; fall back to the default.
            self.confirm_echo_guard_ms = 400.0
        # Timer that discards an unanswered pending action after
        # `safety.confirm_timeout` seconds (C2/C3); None when nothing is pending.
        self._confirm_task: asyncio.Task | None = None
        # Last conversation state the server pushed (persona vocabulary). Used to
        # clear the face once at turn end and to avoid re-sending the same look.
        self._face_state: str | None = None
        self._face_emotion: str | None = None
        self.filler_cache = filler_cache or {}
        # Opt-in, off by default: WAV capture of VAD segments for threshold work
        # (task-26). With capture_segments=false this is None and costs nothing.
        self.segment_recorder = build_segment_recorder(cfg.get("audio") or {})
        chime_ms = filler_chime_ms_for(self.cfg["conversation"])
        self._filler_pcm = (_chime_pcm(self.cfg["audio"]["sample_rate"], chime_ms)
                            if chime_ms > 0 else None)
        face = self.cfg["conversation"].get("thinking_face", THINKING_FACE_DEFAULT)
        self.thinking_face = "" if face is None else str(face).strip()
        restore = self.cfg["conversation"].get("cue_restore_face", "neutral")
        self.cue_restore_face = "" if restore is None else str(restore).strip()
        # True only between a successful thinking cue and its matching restore.
        # Restoring unconditionally would stomp the state-driven face (Step 2).
        self._cue_pushed = False
        self._cue_tasks: set[asyncio.Task] = set()
        # True once this turn actually played answer audio (an `_speak(...,
        # answer=True)` call); the speaking face may then be pushed once and
        # cleared at turn end.
        self._spoke_answer = False
        self._state_tasks: set[asyncio.Task] = set()
        self._speak_lock = asyncio.Lock()
        self._reply_ready = False
        self._first_audio_at = None
        # Echo probe (calibration): `_echo_sub` holds 20 ms sub-frame RMS, the
        # exact statistic _barge_watch compares; `_echo_frame` is 60 ms frame
        # RMS for reference. Empty unless conversation.echo_probe is on.
        self._echo_sub: list[float] = []
        self._echo_frame: list[float] = []
        self._echo_recent: list[float] = []
        self._echo_last_log = 0.0
        self._speak_started_at = 0.0
        self._barge_ms = 0
        self._barge_quiet_ms = 0
        self._barge_onset_at: float | None = None
        self.session_id = uuid.uuid4().hex
        self.history: list[dict] = []
        self.speaking = False
        self.turn: asyncio.Task | None = None
        # True between "a frame arrived while muted" and the first unmuted
        # frame; used to reset the listen window once per mute episode.
        self._muted_seen = False
        self.alive = True
        self._mcp_id = 10
        self._pending: dict[int, asyncio.Future] = {}
        self.max_tool_rounds = int(self.cfg["llm"].get("max_tool_rounds", 2))
        self.enable_device_tools = bool(self.cfg["llm"].get("device_tools", True))
        self.log_prefix = f"[{self.session_id[:6]}]"
        _SESSIONS.add(self)

    def log(self, *parts):
        print(self.log_prefix, *parts, flush=True)

    # ---------------- handshake ----------------

    async def handshake(self) -> bool:
        try:
            first = await asyncio.wait_for(self.ws.recv(), timeout=10)
        except asyncio.TimeoutError:
            self.log("hello timeout")
            return False
        msg = json.loads(first) if isinstance(first, str) else {}
        if msg.get("type") != "hello":
            self.log("expected hello, got", str(first)[:80])
            return False
        params = msg.get("audio_params", {})
        self.log("hello", "sr=", params.get("sample_rate"), "frame=", params.get("frame_duration"))
        await self.ws.send(protocol.hello_reply(
            self.session_id,
            self.cfg["audio"]["sample_rate"],
            self.cfg["audio"]["frame_ms"]))
        await self._send_mcp_initialize()
        volume = int(self.cfg["audio"].get("device_volume", 0) or 0)
        if 1 <= volume <= 100:
            await self._safe_send(protocol.mcp_tool_call(
                "self.audio_speaker.set_volume", {"volume": volume},
                msg_id=self._next_mcp_id()))
            self.log("[mcp] set_volume", volume)
        # The session is ready: the device is in Connecting/Listening. Pushing the
        # listening look here gives the face a defined state before the first turn
        # (the stock display ignores the persona names until the C1 firmware).
        await self._push_state_face("listening")
        asyncio.create_task(self._flush_notifications())
        return True

    async def _flush_notifications(self):
        """Speak anything that was queued while the board was offline."""
        mute = getattr(self, "mute", None)
        if mute is not None and mute.muted:
            # Never take the queue while muted: taking is destructive, and an
            # unspoken line would be lost instead of waiting for the next
            # connection after the switch is turned off.
            self.log("[mute] queued notifications held")
            return
        await asyncio.sleep(1.0)          # let the device settle into listening
        if mute is not None and mute.muted:
            self.log("[mute] queued notifications held")
            return
        pending = take_notifications()
        for text in pending:
            self.log("[notify] delivering queued", text[:40])
            try:
                pcm, rate = await self.tts.synth(text)
                pcm16 = resample(pcm, rate, self.cfg["audio"]["sample_rate"])
                await self._speak(text, pcm16, time.perf_counter(), label="notify")
            except Exception as exc:
                self.log("[notify] failed", type(exc).__name__, exc)

    def _next_mcp_id(self) -> int:
        self._mcp_id += 1
        return self._mcp_id

    async def _send_mcp_initialize(self):
        vision_url = self.cfg["server"].get("vision_url", "")
        caps: dict = {}
        if vision_url:
            caps["vision"] = {"url": vision_url,
                              "token": self.cfg["server"].get("vision_token", "")}
        await self._safe_send(protocol.mcp_initialize(caps, msg_id=self._next_mcp_id()))
        self.log("[mcp] initialize", "vision=" + (vision_url or "off"))

    async def send_tool_call(self, name: str, arguments: dict):
        await self._safe_send(protocol.mcp_tool_call(
            name, arguments, msg_id=self._next_mcp_id()))
        # Never write secrets (Wi-Fi password, tokens) into the server log; the
        # wire payload keeps the real values.
        self.log("[mcp] call", name, devtools.redacted_arguments(arguments))

    async def push_emotion(self, name: str):
        """Show an expression on the face without starting a turn (M7).

        The firmware dispatches `{"type":"llm","emotion":...}` in every device
        state (main/application.cc:683-689), unlike `notify`, which needs Idle.
        A dead socket is only a lost expression, hence `_safe_send`.
        """
        await self._safe_send(protocol.llm_emotion(name, self.session_id))
        self.log("[emotion]", name)

    async def speak_announcement(self, text: str) -> bool:
        """Say one unprompted line (proactive v0): synth, then play it.

        Returns False when the socket is gone or synthesis fails, so the
        controller counts it as face-only instead of pretending it spoke.
        """
        mute = getattr(self, "mute", None)
        if mute is not None and mute.muted:
            self.log("[mute] announcement refused")
            return False
        if not self.alive:
            return False
        try:
            pcm, rate = await self.tts.synth(text)
            pcm16 = resample(pcm, rate, self.cfg["audio"]["sample_rate"])
        except Exception as exc:
            self.log("[proactive] synth failed", type(exc).__name__, exc)
            return False
        await self._speak(text, pcm16, time.perf_counter(), label="proactive")
        return self.alive

    async def _show_screen(self) -> str:
        """Snapshot the device screen, upload it to 4411, then display it back."""
        base = self.cfg["server"]["vision_url"].split("/xiaozhi/", 1)[0].rstrip("/")
        snap = await self.call_device_tool(
            "self.screen.snapshot", {"url": base + "/debug/upload"},
            timeout=20, confirmed=True)
        try:
            path = json.loads(snap).get("path", "")
        except Exception:
            path = ""
        name = path.rsplit("/", 1)[-1] if isinstance(path, str) and path else ""
        if not name:
            # Firmware's snapshot tool returns only "true"; /debug/upload saved
            # the file, so pick the newest snapshot just written.
            photos = Path.home() / ".hermes/cache/scratch/esp32-voice/photos"
            files = sorted(photos.glob("snapshot-*.jpg"), key=lambda p: p.stat().st_mtime)
            if files:
                name = files[-1].name
        if not name:
            return json.dumps({"ok": False, "error": "snapshot failed", "raw": snap[:200]},
                              ensure_ascii=False)
        src = Path.home() / ".hermes/cache/scratch/esp32-voice/photos" / name
        screen_dir = src.parent.parent / "screen"
        screen_dir.mkdir(parents=True, exist_ok=True)
        png_name = name.rsplit(".", 1)[0] + ".png"
        import subprocess
        subprocess.run(["sips", "-s", "format", "png", str(src), "--out", str(screen_dir / png_name)],
                       check=True, capture_output=True, timeout=10)
        preview = await self.call_device_tool(
            "self.screen.preview_image",
            {"url": f"{base}/screen/{png_name}"},
            timeout=20, confirmed=True)
        return json.dumps({"ok": True, "file": name, "preview": preview},
                          ensure_ascii=False)

    async def call_device_tool(self, spec_name: str, arguments: dict,
                               timeout: float | None = None,
                               confirmed: bool = False) -> str:
        """Call a device tool and wait for its MCP result. Returns text for the LLM.

        `spec_name` may be a speech-friendly alias (take_photo) or the raw firmware
        name (self.screen.snapshot) for bench work.
        """
        if spec_name == "hermes_info":
            return json.dumps(await self.llm.hermes_info(), ensure_ascii=False)
        if spec_name == "show_screen":
            return await self._show_screen()
        if spec_name.startswith("self."):
            device_name = spec_name
        else:
            device_name = devtools.DEVICE_NAME.get(spec_name) or ""
        if not device_name:
            return json.dumps({"ok": False, "error": f"unknown tool {spec_name}"})
        if not confirmed and device_name in self.confirm_tools:
            # Step one of C2/C3: restate the action out loud ("我要重启…，确认
            # 吗？") and wait for the next utterance. Nothing runs from the
            # model's tool call, and the pending entry is never trusted to a
            # model-generated sentence.
            timeout = float(self.cfg.get("safety", {}).get("confirm_timeout", 120))
            if getattr(self, "pending_confirm", None) is not None:
                # A second tool call while one action waits replaces it; drop the
                # stale entry and its timer so it cannot expire/fire later.
                self._drop_pending()
            pending = {
                "name": device_name,
                "arguments": arguments,
                "expires": time.perf_counter() + timeout,
            }
            self.pending_confirm = pending
            self._start_confirm_timer(pending, timeout)
            _note_confirm_pending(device_name, timeout)
            self.log("[confirm] asking", device_name,
                     devtools.action_name(device_name),
                     devtools.redacted_arguments(arguments))
            await self._push_state_face("confirm-pending")
            await self._ask_confirm(time.perf_counter(), pending)
            return json.dumps({"ok": False, "needs_confirmation": True,
                               "note": "已向用户口头确认，等待下一句回答，不要重复调用"})
        # The tool really runs now: show "working" first, then hand the face back
        # to thinking while the model consumes the result.
        await self._push_state_face("tool-running")
        msg_id = self._next_mcp_id()
        fut = asyncio.get_running_loop().create_future()
        self._pending[msg_id] = fut
        t0 = time.perf_counter()
        try:
            await self._safe_send(protocol.mcp_tool_call(
                device_name, arguments, msg_id=msg_id))
            self.log("[mcp] call", spec_name,
                     devtools.redacted_arguments(arguments))
            wait = timeout or (devtools.SLOW_TIMEOUT if spec_name in devtools.SLOW_TOOLS
                               else devtools.DEFAULT_TIMEOUT)
            if spec_name in devtools.SESSION_ENDING:
                wait = min(wait, 2.5)
            result = await asyncio.wait_for(fut, timeout=wait)
            self.log("[mcp] done", spec_name, round(time.perf_counter() - t0, 2), "s")
            return result
        except asyncio.TimeoutError:
            if spec_name in devtools.SESSION_ENDING:
                self.log("[mcp] session-ending tool", spec_name, "no reply (expected)")
                return json.dumps({"ok": True,
                                   "note": "已下发；该工具会关闭音频通道，回执丢失属预期"})
            self.log("[mcp] timeout", spec_name)
            return json.dumps({"ok": False, "error": "device did not answer in time"})
        finally:
            self._pending.pop(msg_id, None)
            await self._push_state_face("thinking")

    # ---------------- main loop ----------------
    async def run(self):
        if not await self.handshake():
            await self.ws.close()
            return
        vad_cfg = self.cfg["vad"]
        vad = build_vad(self.cfg["vad"]["model"], vad_cfg["min_silence"],
                        vad_cfg["min_speech"], vad_cfg["max_speech"])
        try:
            async for raw in self.ws:
                if isinstance(raw, bytes):
                    await self._on_audio(raw, vad)
                else:
                    await self._on_json(raw, vad)
        except Exception as exc:  # connection-level; keep the process alive
            self.log("connection error", type(exc).__name__, exc)
        finally:
            if self.turn and not self.turn.done():
                self.turn.cancel()
            # A pending confirmation on a dead socket has nobody to ask: drop it
            # (cancels the 120 s timer and clears the proactive reminder) so no
            # timer/reminder outlives the connection.
            self._drop_pending()
            self.alive = False
            _SESSIONS.discard(self)
            self.log("closed")

    async def _on_audio(self, frame: bytes, vad):
        mute = getattr(self, "mute", None)
        if mute is not None:
            mute.note_frame()
            if mute.muted:
                # B1 mode A: drop the frame here, before Opus decode. VAD, ASR,
                # LLM, TTS, turn start and barge-in are all downstream of this
                # line, so a muted board produces none of them. The websocket
                # stays open and JSON (hello/listen) is unaffected; the device
                # keeps capturing and uploading until B2 changes the firmware.
                self._muted_seen = True
                return
            if getattr(self, "_muted_seen", False):
                # The board drops audio while muted, so VAD/barge counters are
                # frozen at whatever they were when the switch flipped. Start
                # the listen window clean instead of carrying that half-state
                # into the first unmuted segment (2026-10-30 mute toggles).
                self._muted_seen = False
                self._reset_listen_window()
        pcm = self.codec.decode(frame)
        if self.speaking:
            # Device AEC is on. Measured 2026-10-27: our own TTS comes back at
            # 60 ms frame RMS 0.0006-0.0011 (20 ms peaks ~0.0017); a person
            # interrupting measures ~0.0348. barge_rms (0.008, config.yaml) is
            # calibrated against those numbers - do not take it back to 1e-3.
            self._probe_echo(pcm)
            vad.accept_waveform(pcm.astype(np.float32) / 32768.0)
            _note_speech_in_progress(vad)
            if await self._barge_watch(pcm):
                segments = pop_segments(vad)
                if segments:
                    self.turn = asyncio.create_task(self._handle_turn(segments[-1]))
                    if mute is not None:
                        mute.note_turn()
            return
        vad.accept_waveform(pcm.astype(np.float32) / 32768.0)
        _note_speech_in_progress(vad)
        for seg in pop_segments(vad):
            if len(seg) < MIN_SEGMENT_SECONDS * self.cfg["audio"]["sample_rate"]:
                self.log("[seg] too short", round(len(seg) / 16000, 2), "s")
                continue
            if self.turn and not self.turn.done():
                self.log("[seg] dropped, turn in flight")
                continue
            self.turn = asyncio.create_task(self._handle_turn(seg))
            if mute is not None:
                mute.note_turn()

    async def _barge_watch(self, pcm: np.ndarray) -> bool:
        """Return True when the user has spoken over us long enough to interrupt.

        Both clocks are audio time: every 20 ms sub-frame adds 20 ms to the
        sustain counter, and >200 ms of quiet sub-frames resets it. Wall clock
        is only used for the guard and for the printed latency.
        """
        conv = self.cfg["conversation"]
        if not conv.get("barge_in", True):
            return False
        if time.perf_counter() - self._speak_started_at < conv.get("barge_guard_ms", 350) / 1000:
            # Keep the invariant explicit even if a future caller starts
            # playback without going through _speak().
            self._barge_ms = 0
            self._barge_quiet_ms = 0
            self._barge_onset_at = None
            return False
        # 60 ms frames give a coarse decision; walk 20 ms sub-frames so the
        # interrupt lands closer to the moment the person actually started.
        samples = pcm.astype(np.float32) / 32768.0
        step = max(1, int(self.cfg["audio"]["sample_rate"] * 0.02))
        threshold = float(conv.get("barge_rms", 0.008))
        loudest = 0.0
        now = time.perf_counter()
        for start in range(0, max(1, len(samples) - step + 1), step):
            chunk = samples[start:start + step]
            if chunk.size == 0:
                continue
            rms = float(np.sqrt(np.mean(chunk ** 2)))
            loudest = max(loudest, rms)
            if rms >= threshold:
                if self._barge_onset_at is None:
                    self._barge_onset_at = now
                self._barge_ms += 20
                self._barge_quiet_ms = 0
            else:
                self._barge_quiet_ms += 20
                if self._barge_quiet_ms > 200:
                    # short gaps between syllables must not reset the counter, or
                    # a normal phrase takes twice as long to qualify
                    self._barge_ms = 0
                    self._barge_onset_at = None
        rms = loudest
        sustained_ms = self._barge_ms
        if sustained_ms < int(conv.get("barge_min_ms", 240)):
            return False
        latency = (time.perf_counter() - self._barge_onset_at) if self._barge_onset_at else 0.0
        self._barge_ms = 0
        self._barge_quiet_ms = 0
        self._barge_onset_at = None
        self.log("[barge] rms", round(rms, 4), "onset->stop", round(latency, 3), "s after",
                 round(time.perf_counter() - self._speak_started_at, 2), "s of playback",
                 f"(sustained={sustained_ms} ms)")
        self._flush_echo("barge")
        # C3: the startle is the first thing the person sees; measure detect ->
        # pushed frame so the 300 ms acceptance ceiling is auditable in the log.
        # Pushing before cancelling the turn also makes the cancelled turn's
        # finally leave this look alone (`_finish_turn_face`).
        t_detect = time.perf_counter()
        await self._push_state_face("barge-in")
        self.log(f"[barge] face={(time.perf_counter() - t_detect) * 1000:.1f} "
                 "ms since detect")
        if self.turn and not self.turn.done():
            self.turn.cancel()
        self.speaking = False
        await self._safe_send(protocol.tts_stop(self.session_id))
        self.log("[barge] playback stopped")
        return True

    def _probe_echo(self, pcm: np.ndarray):
        """Measure mic level while we are speaking — calibration for barge-in.

        Records the statistic `_barge_watch` compares: 20 ms sub-frame RMS
        (`_echo_sub`; summarised as p50/p90/p99/max in `_flush_echo`). The 60 ms
        frame RMS is kept for reference. Off unless conversation.echo_probe.
        """
        if not self.cfg["conversation"].get("echo_probe", False):
            return
        samples = pcm.astype(np.float32) / 32768.0
        step = max(1, int(self.cfg["audio"]["sample_rate"] * 0.02))
        self._echo_frame.append(float(np.sqrt(np.mean(samples ** 2))))
        self._echo_sub.extend(
            float(np.sqrt(np.mean(samples[i:i + step] ** 2)))
            for i in range(0, max(1, len(samples) - step + 1), step))
        self._echo_recent.append(self._echo_frame[-1])
        now = time.perf_counter()
        if now - self._echo_last_log >= 0.5 and self._echo_recent:
            vals = self._echo_recent
            self.log("[echo] live", f"n={len(vals)} min={min(vals):.4f}",
                     f"avg={sum(vals) / len(vals):.4f} max={max(vals):.4f}")
            self._echo_recent = []
            self._echo_last_log = now

    def _flush_echo(self, label: str):
        """Log the 20 ms sub-frame RMS distribution for one playback/barge."""
        if not self.cfg["conversation"].get("echo_probe", False):
            return
        sub, frame = self._echo_sub, self._echo_frame
        if not sub:
            return
        self._echo_sub, self._echo_frame = [], []
        arr = np.asarray(sub, dtype=np.float32)
        farr = np.asarray(frame, dtype=np.float32)
        p50, p90, p99 = (float(v) for v in np.percentile(arr, [50, 90, 99]))
        buckets = ((0.002, "<2m"), (0.005, "2-5m"), (0.01, "5-10m"),
                   (0.02, "10-20m"), (float("inf"), ">=20m"))
        hist, low = [], 0.0
        for high, name in buckets:
            hist.append(f"{name}:{int(np.count_nonzero((arr >= low) & (arr < high)))}")
            low = high
        self.log("[echo]", label, f"n={len(sub)}",
                 f"sub20 p50={p50:.4f} p90={p90:.4f} p99={p99:.4f} "
                 f"max={float(arr.max()):.4f}",
                 "|", f"frame60 p50={float(np.percentile(farr, 50)):.4f} "
                 f"max={float(farr.max()):.4f}",
                 "|", "hist", " ".join(hist))

    async def _on_json(self, raw: str, vad):
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            self.log("bad json", raw[:80])
            return
        kind = msg.get("type")
        if kind == "listen":
            self.log("[listen]", msg.get("state"), msg.get("mode"))
            # Listening look on the device's listen-start edge, except while a
            # spoken confirmation is pending (the confused face must stay until
            # the answer) or the barge startle is still the current look.
            if (msg.get("state") == "start"
                    and getattr(self, "pending_confirm", None) is None
                    and getattr(self, "_face_state", None) != "barge-in"):
                await self._push_state_face("listening")
        elif kind == "abort":
            if self._abort_is_echo_of_mute():
                # The board emits a burst of aborts around a mute toggle
                # (2026-10-30: 5-24 per toggle). This only covers the muted AND
                # idle case: nothing to stop, so the burst is pure log churn.
                # A turn in flight or TTS playing still goes through
                # `_interrupt()` - that path is deliberately untouched.
                self.log("[abort] ignored while muted and idle:", msg.get("reason"))
                return
            self.log("[abort]", msg.get("reason"))
            await self._interrupt()
        elif kind == "mcp":
            payload = msg.get("payload") or {}
            if isinstance(payload, dict):
                mid = payload.get("id")
                fut = self._pending.get(mid) if isinstance(mid, int) else None
                if fut is not None and not fut.done():
                    if "error" in payload:
                        fut.set_result(json.dumps(
                            {"ok": False, "error": payload["error"]}, ensure_ascii=False))
                    else:
                        fut.set_result(_mcp_result_text(payload.get("result")))
                    return
            if isinstance(payload, dict) and "result" in payload:
                text = _mcp_result_text(payload["result"])
                self.log("[mcp] result", text[:160])
            elif isinstance(payload, dict) and "error" in payload:
                self.log("[mcp] error", json.dumps(payload["error"], ensure_ascii=False)[:160])
            else:
                self.log("[mcp] msg", json.dumps(payload, ensure_ascii=False)[:160])

    def _abort_is_echo_of_mute(self) -> bool:
        """Aborts that merely follow a mute toggle must not touch the pipeline.

        Only when muted AND nothing is running: a real abort during speech or a
        turn still has to stop it. Kept as a predicate so the rule is testable
        without a websocket.
        """
        mute = getattr(self, "mute", None)
        if mute is None or not mute.muted:
            return False
        if self.speaking:
            return False
        return self.turn is None or self.turn.done()

    def _reset_listen_window(self) -> None:
        """Clear the session's half-finished listen/answer counters.

        Scope note: the VAD lives in `run()` as a local and is not touched here.
        It keeps the audio it was fed before the mute, so the first segment after
        unmuting can still span the mute boundary; clearing that would need a VAD
        reset and is out of scope here. What this method does clear is session
        bookkeeping - when the first answer audio started, whether a reply is
        ready, and the barge counters.
        """
        self._first_audio_at = None
        self._reply_ready = False
        if not self.speaking:
            self._barge_ms = 0
            self._barge_quiet_ms = 0
            self._barge_onset_at = None
        self.log("[listen] reset after mute")

    async def _interrupt(self):
        if self.turn and not self.turn.done():
            self.turn.cancel()
        if self.speaking:
            self.speaking = False
            await self._safe_send(protocol.tts_stop(self.session_id))

    async def _safe_send(self, data):
        try:
            await self.ws.send(data)
        except Exception as exc:
            self.log("send failed", type(exc).__name__)

    # ---------------- one turn ----------------

    def _system_prompt(self) -> str:
        import datetime
        now = datetime.datetime.now()
        weekday = "一二三四五六日"[now.weekday()]
        clock = (f"当前时间：{now.year}年{now.month}月{now.day}日 "
                 f"星期{weekday} {now.hour}点{now.minute:02d}分。")
        prompt = self.cfg["llm"]["system_prompt"].strip()
        prompt = prompt.replace("{hermes_version}", str(self.cfg["llm"].get("hermes_version", "unknown")))
        prompt = prompt.replace("{hermes_model}", str(self.cfg["llm"].get("hermes_model", "unknown")))
        prompt += "\n" + clock
        if getattr(self, "pending_confirm", None) is not None:
            # C2/C3 guard: while an action waits for a spoken yes, the model must
            # not narrate it as done (the user has not confirmed anything yet).
            prompt += ("\n当前有动作正在等待用户口头确认：不要声称它已经执行，"
                       "也不要自己重复调用该工具；只请用户明确说「确认」或「取消」。")
        return prompt

    async def _handle_turn(self, seg: np.ndarray):
        t0 = time.perf_counter()
        _note_human_speech()          # gate 2: humans are talking right now
        seg_f = seg.astype(np.float32)
        if seg.dtype == np.int16:
            seg_f = seg_f / 32768.0
        seg_rms = float(np.sqrt(np.mean(seg_f ** 2)))
        seg_seconds = len(seg) / float(self.cfg["audio"]["sample_rate"])
        self.log("[seg]", round(seg_rms, 4), "rms", round(seg_seconds, 2), "s")
        self._cue_pushed = False
        self._spoke_answer = False
        dropped = is_noise_segment(seg, self.cfg["audio"]["sample_rate"])
        if self.segment_recorder is not None:
            path = self.segment_recorder.record(
                seg, self.cfg["audio"]["sample_rate"], dropped=dropped,
                rms=seg_rms)
            if path is not None:
                self.log("[capture]", path.name)
        if dropped:
            # No ASR, no LLM, no turn: sustained low energy is room noise, and
            # SenseVoice would invent a sentence for it.
            self.log("[seg] noise gate: dropped", round(seg_rms, 4), "rms",
                     round(seg_seconds, 2), "s")
            return
        self._reply_ready = False
        self._first_audio_at = None
        filler_task = self._start_filler(t0)
        try:
            text = await asyncio.get_running_loop().run_in_executor(
                None, self.asr.transcribe, seg, self.cfg["audio"]["sample_rate"])
            raw_text = text
            # Wake-word judgement comes first and is punctuation/case folded, so
            # the misheard variants (小志/小石/小日) never reach `_valid_text` as
            # a "command": no stt frame, no model call, no turn, no state left.
            if is_wake_only(raw_text, seg_seconds):
                self.log("[asr] wake-only, no turn:", repr(raw_text))
                await self._restore_cue_face("rejected")
                return
            text = strip_wake(text)
            if not _valid_text(text):
                reason = "wake-only" if raw_text != text else "noise"
                self.log(f"[asr] {reason}, no turn:", repr(raw_text))
                await self._restore_cue_face("rejected")
                return
            if raw_text != text:
                self.log("[asr] wake stripped:", repr(raw_text), "->", repr(text))
            self.log("[asr]", round(time.perf_counter() - t0, 2), "s", text)
            await self._safe_send(protocol.stt(text, self.session_id))
            _note_user_text(text)     # gate 6: 「别说了」 mutes proactive speech
            if await self._resolve_confirm(t0, text, seg_seconds=seg_seconds):
                return
            await self._maybe_confirm_reminder(t0, text)
            # ASR is done and we are about to call the LLM: show the thinking
            # look now instead of waiting for the 300 ms delay cue. The cue
            # stays as a visual mask for a slow ASR, but `_filler_after` skips
            # itself once this state is already on screen.
            await self._push_state_face("thinking")
            await self._run_turn(t0, text)
        except asyncio.CancelledError:
            self.log("[turn] cancelled")
            raise
        except Exception as exc:
            self.log("[turn] error", type(exc).__name__, exc)
        finally:
            if filler_task and not filler_task.done():
                filler_task.cancel()
            self._kick_cue_restore("turn end")
            self._finish_turn_face()

    def start_text_turn(self, text: str, t0: float | None = None):
        """Bench hook: run a full turn from text, no microphone involved.

        Returns None when a turn is already running: starting a second one would
        overwrite `self.turn` and reset the per-turn flags the running turn is still
        using, so a bench injection during a real conversation would interleave two
        answers instead of testing one.
        """
        if self.turn and not self.turn.done():
            self.log("[text] refused, turn in flight")
            return None

        async def runner():
            t = t0 if t0 is not None else time.perf_counter()
            self._reply_ready = False
            self._first_audio_at = None
            self._cue_pushed = False
            self._spoke_answer = False
            filler_task = self._start_filler(t)
            try:
                self.log("[text]", repr(text))
                _note_user_text(text)
                if await self._resolve_confirm(t, text):
                    return
                await self._maybe_confirm_reminder(t, text)
                # Bench text turn: ASR is simulated, thinking starts here.
                await self._push_state_face("thinking")
                await self._run_turn(t, text)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.log("[turn] error", type(exc).__name__, exc)
            finally:
                if filler_task and not filler_task.done():
                    filler_task.cancel()
                self._kick_cue_restore("turn end")
                self._finish_turn_face()
        self.turn = asyncio.create_task(runner())
        return self.turn

    _TASK_WORDS = (
        "帮我", "查", "搜", "找", "打开", "关掉", "关了", "开灯", "设置", "调", "写",
        "发", "提醒", "日程", "安排", "订", "买", "拍照", "看看", "看下", "记一下",
        "灯", "天气", "几点", "部署", "重启", "改", "修", "文件", "邮件", "微信",
        "截屏", "截图", "截个图", "截一张", "截下图", "屏幕", "桌面", "显示",
        "后台", "版本", "模型", "Hermes", "连的",
    )

    def _route(self, text: str) -> str:
        """'fast' for small talk, 'agent' for anything that needs tools or memory."""
        if self.fast_llm is None or self.pending_confirm is not None:
            return "agent"
        if any(word in text for word in self._TASK_WORDS):
            return "agent"
        if len(text) > self.route_max_chars:
            return "agent"
        return "fast"

    # ---------------- two-step spoken confirmation (C2/C3) ----------------

    async def _ask_confirm(self, t0: float, pending: dict) -> None:
        """Step one: restate the pending action out loud, then ask.

        The question is generated from the pending name + arguments, so the user
        hears what will happen (「我要重启这台设备（延迟秒数=0），确认吗？」)
        instead of a generic "should I?".
        """
        sentence = devtools.confirm_question(pending["name"], pending["arguments"])
        self.log("[confirm] ask", sentence)
        await self._say_text(t0, sentence)
        # `_say_text` returns after tts_stop, i.e. once the prompt has finished
        # playing (non-streaming: all frames were sent). Start the echo window
        # only now: a confirm-shaped segment that starts inside it is the board's
        # own TTS tail, not the user.
        self._confirm_prompt_end_at = time.perf_counter()

    def _start_confirm_timer(self, pending: dict, timeout: float) -> None:
        """Discard an unanswered confirmation after `safety.confirm_timeout`."""
        task = asyncio.create_task(self._confirm_expiry(pending, timeout))
        self._confirm_task = task
        task.add_done_callback(self._forget_confirm_task)

    def _forget_confirm_task(self, task) -> None:
        if getattr(self, "_confirm_task", None) is task:
            self._confirm_task = None

    async def _confirm_expiry(self, pending: dict, timeout: float) -> None:
        """Timeout path: clear pending, return the face to idle, log expired.

        The identity check is the idempotency guard: if the action was approved,
        cancelled or re-asked meanwhile, this timer must do nothing.
        """
        try:
            await asyncio.sleep(timeout)
        except asyncio.CancelledError:
            raise
        if getattr(self, "pending_confirm", None) is not pending:
            return
        self.pending_confirm = None
        _clear_confirm()
        self.log("[confirm] expired", pending["name"])
        await self._push_state_face("idle")

    def _drop_pending(self) -> None:
        """Clear the pending action, cancel its timer and the reminder.

        The proactive confirm deadline is process-wide, so it is only cleared
        when this session actually had something pending; a disconnect with no
        pending action must not cancel another session's reminder.
        """
        had_pending = (self.pending_confirm is not None
                       or getattr(self, "_confirm_task", None) is not None)
        self.pending_confirm = None
        if had_pending:
            _clear_confirm()
        task = getattr(self, "_confirm_task", None)
        self._confirm_task = None
        if (task is not None and not task.done()
                and task is not asyncio.current_task()):
            task.cancel()

    def _confirm_echo_onset_dt(self, t0: float,
                               seg_seconds: float) -> float | None:
        """Seconds from prompt end to the (estimated) START of the ASR segment.

        `t0` is when the segment closed (VAD hangover included, ~0.5 s after the
        sound ended). Using t0 alone would let the board's own TTS tail through a
        400 ms guard: the tail is picked up during playback but the segment only
        closes after the hangover. Subtracting the segment length estimates the
        speech onset, which is what the guard must compare.

        Returns None when no prompt has been played in this session (bench text
        turns, unit tests), in which case the guard is inactive.
        """
        prompt_end = getattr(self, "_confirm_prompt_end_at", None)
        if prompt_end is None:
            return None
        return (t0 - prompt_end) - max(0.0, float(seg_seconds or 0.0))

    async def _resolve_confirm(self, t0: float, text: str,
                               seg_seconds: float = 0.0) -> bool:
        """Answer a pending confirmation. Returns True when the text was consumed.

        C2/C3 contract:
        - "yes" is only 确认/确定 (see dialogue.classify_confirm); weak agreement
          ("好吧"/"没问题了"/"可以吧"/"就行") is None: keep pending and ask the
          restated question again.
        - "no" (取消/算了/...) drops the action and says so.
        - approval clears pending BEFORE awaiting the tool, so a duplicate or
          concurrent 确认 can never run the action twice.
        - ECHO GUARD (P0/P0.1, 2026-10-28): any non-empty ASR segment whose
          speech started within `safety.confirm_echo_guard_ms` of the prompt
          finishing is ignored. The board's microphone hears its own TTS, and the
          ASR text is unpredictable: 「确认。」 rebooted the board (P0), while
          「嗯刚是你那声音关了。」/「就是出具体，我这测去呢。」 caused a re-ask
          loop (P0.1). Ignored means: keep pending, do NOT run, do NOT re-ask
          (a re-ask would just feed another echo). `seg_seconds` is the VAD
          segment length (segment close is ~0.5 s after the sound ends).
        """
        pending = self.pending_confirm
        if pending is None:
            return False
        if time.perf_counter() > pending["expires"]:
            self._drop_pending()
            self.log("[confirm] expired", pending["name"])
            await self._push_state_face("idle")
            return False
        echo_dt = self._confirm_echo_onset_dt(t0, seg_seconds)
        if (echo_dt is not None
                and echo_dt < self.confirm_echo_guard_ms / 1000.0
                and text.strip()):
            # Self-echo: the prompt (or the room's reaction to it) came back
            # through the mic. Consume the segment so it cannot reach the LLM,
            # but keep the pending action and do not speak again (that would
            # start an echo/re-ask loop). P0.1: shape is NOT checked - the echo
            # was transcribed as arbitrary sentences, not only 确认/取消.
            self.log(f"[confirm] echo ignored dt={echo_dt * 1000:.0f} ms "
                     f"text={text!r} (any segment)")
            return True
        verdict = classify_confirm(text)
        if verdict == "no":
            self._drop_pending()
            self.log("[confirm] cancelled", pending["name"])
            await self._say_text(t0, "好，不动了。")
            await self._push_state_face("idle")
            return True
        if verdict != "yes":
            # Weak agreement, hedge, question or deferral: not consent. Keep the
            # action pending and repeat the restated question. If something else
            # owns the face by now (a barge-in startle interrupted the question),
            # put the confirm-pending look back before asking again.
            self.log("[confirm] asking again", pending["name"])
            if getattr(self, "_face_state", None) != "confirm-pending":
                await self._push_state_face("confirm-pending")
            await self._ask_confirm(t0, pending)
            return True
        # Claim the action before the first await: this assignment is what makes
        # a second 确认 (or a concurrent one) a no-op.
        self._drop_pending()
        self.log("[confirm] approved", pending["name"],
                 devtools.redacted_arguments(pending["arguments"]))
        try:
            result = await self.call_device_tool(pending["name"], pending["arguments"],
                                                 confirmed=True)
        except Exception as exc:
            await self._say_text(t0, "没执行成功。")
            self.log("[confirm] failed", type(exc).__name__, exc)
            await self._push_state_face("idle")
            return True
        await self._say_text(t0, "好，已经执行。")
        self.log("[confirm] done", result[:120])
        await self._push_state_face("idle")
        return True

    async def _say_text(self, t0: float, sentence: str) -> None:
        pcm, rate = await self.tts.synth(sentence)
        pcm16 = resample(pcm, rate, self.cfg["audio"]["sample_rate"])
        await self._speak(sentence, pcm16, t0, label="tts")

    async def _maybe_confirm_reminder(self, t0: float, text: str) -> None:
        """Trigger A: schedule or cancel a reminder, and read the result back.

        Confirming aloud is deliberate: a mis-parse must be audible immediately,
        not silently fire half an hour later. Cancelling is spoken too, so the
        user knows 「取消提醒」 took effect (there is no other UI to check).
        """
        try:
            cancelled = proactive.maybe_cancel_reminder(text)
            if cancelled is not None:
                self.log("[reminder] cancelled", cancelled["id"])
                await self._say_text(t0, "好，取消了。")
                return
            reminder = proactive.maybe_schedule_from_text(text)
        except Exception as exc:          # parsing must never break a turn
            self.log("[reminder] parse error", type(exc).__name__, exc)
            return
        if reminder is None:
            return
        hhmm = reminder["at"][11:16]
        content = reminder["text"]
        self.log("[reminder]", reminder["id"], reminder["at"], content)
        # 「9:30 提醒我」 has no content: 「好，09:30 提醒你。」 (no dangling 你 + object).
        said = f"好，{hhmm} 提醒你{content}。" if content else f"好，{hhmm} 提醒你。"
        await self._say_text(t0, said)

    async def _refresh_hermes_info(self) -> None:
        if self.llm.provider != "hermes":
            return
        try:
            info = await asyncio.wait_for(self.llm.hermes_info(), timeout=2.0)
            if info.get("version"):
                self.cfg["llm"]["hermes_version"] = info["version"]
            if info.get("model"):
                self.cfg["llm"]["hermes_model"] = info["model"]
        except Exception as exc:
            self.log("[hermes] info refresh failed", type(exc).__name__)

    async def _show_media(self, paths: list[str]) -> None:
        if not paths:
            return
        base = self.cfg["server"]["vision_url"].split("/xiaozhi/", 1)[0].rstrip("/")
        screen_dir = Path.home() / ".hermes/cache/scratch/esp32-voice/screen"
        screen_dir.mkdir(parents=True, exist_ok=True)
        for raw in paths:
            if raw.startswith(("http://", "https://")):
                url = raw
            else:
                src = Path(raw).expanduser()
                if not src.is_file():
                    self.log("[media] missing", str(src))
                    continue
                png = screen_dir / (src.stem[:48] + ".png")
                import subprocess
                subprocess.run(["sips", "-s", "format", "png", "-Z", "480", str(src), "--out", str(png)],
                               check=True, capture_output=True, timeout=15)
                url = f"{base}/screen/{png.name}"
            try:
                result = await self.call_device_tool(
                    "self.screen.preview_image", {"url": url}, timeout=90, confirmed=True)
                self.log("[media] shown", url, result[:80])
            except Exception as exc:
                self.log("[media] failed", url, type(exc).__name__)

    async def _run_turn(self, t0: float, text: str):
        # Deterministic screen self-view: the Hermes model often answers
        # "截好了" without calling the tool, so handle the explicit ask here.
        if any(w in text for w in ("打开浏览器", "打开chrome", "打开 Chrome",
                                    "访问百度", "打开百度", "桌面浏览器")):
            want_google = ("谷歌" in text or "google" in text.lower())
            url = "https://www.google.com" if want_google else "https://www.baidu.com"
            site = "谷歌" if want_google else "百度"
            try:
                subprocess.run(["open", "-a", "/Applications/Google Chrome.app", url], check=True, timeout=10)
                await asyncio.sleep(2)
                path = f"/tmp/desktop-{uuid.uuid4().hex[:8]}.png"
                subprocess.run(["screencapture", "-x", path], check=True, timeout=15)
                await self._show_media([path])
                await self._say_text(t0, f"Chrome 已经打开，{site}页面也加载好了。")
            except Exception as exc:
                self.log("[browser] open failed", type(exc).__name__)
                await self._say_text(t0, "浏览器没打开成功，稍后再试。")
            return
        if any(w in text for w in ("截屏", "截图", "截个屏", "截个图", "截一张", "截下图")) \
                and "设备" not in text and "你的屏幕" not in text:
            path = f"/tmp/desktop-{uuid.uuid4().hex[:8]}.png"
            try:
                subprocess.run(["screencapture", "-x", path], check=True, timeout=15)
                await self._show_media([path])
                await self._say_text(t0, "截好了，这就是你桌面现在的画面。")
            except Exception as exc:
                self.log("[media] desktop capture failed", type(exc).__name__)
                await self._say_text(t0, "桌面截图没成功，稍后再试。")
            return
        if any(k in text for k in ("后台", "模型", "版本", "Hermes", "hermes")):
            await self._refresh_hermes_info()
        if any(w in text for w in ("截屏", "截图", "截个图", "截一张", "截下图")) and any(
                w in text for w in ("显示", "给我看", "看看", "屏幕上")):
            result = json.loads(await self._show_screen())
            if result.get("ok"):
                await self._say_text(t0, "截好了，就是现在这块屏幕。")
            else:
                await self._say_text(t0, "截屏没成功，稍后再试。")
            return
        messages: list[dict] = [{"role": "system", "content": self._system_prompt()}]
        messages += self.history[-self.cfg["llm"]["history_rounds"] * 2:]
        messages.append({"role": "user", "content": text})

        specs = devtools.spec_for() if self.enable_device_tools else None
        reply_text = ""
        spoken: list[str] = []
        route = ""
        turn_id = uuid.uuid4().hex[:8]

        async def speak_sentence(sentence: str):
            """Say one sentence as soon as the model finishes it."""
            say = speech_text(sentence)
            if not say:
                return
            t_synth = time.perf_counter()
            pcm, rate = await self.tts.synth(say)
            self.log("[tts] sentence synth", round(time.perf_counter() - t_synth, 2),
                     "s", repr(say[:24]))
            pcm16 = resample(pcm, rate, self.cfg["audio"]["sample_rate"])
            spoken.append(say)
            await self._speak(say, pcm16, t0, label="tts", answer=True)

        route = self._route(text)
        llm = self.fast_llm if route == "fast" else self.llm
        try:
            self.log("[route]", route, llm.provider, llm.model)
            stream = should_stream_sentences(
                bool(self.cfg["llm"].get("stream_tts", False)), llm.provider, route)
            for round_i in range(self.max_tool_rounds + 1):
                use_tools = specs if round_i < self.max_tool_rounds else None
                turn = await llm.chat(messages, self.session_id,
                                      tools=use_tools if route != "fast" else None,
                                      on_sentence=speak_sentence if stream else None)
                if not turn.tool_calls:
                    reply_text = turn.content
                    self.log("[llm]", round(turn.latency, 2), "s",
                             reply_text[:60] if reply_text else "(empty)")
                    break
                self.log("[llm] tool_calls", round(turn.latency, 2), "s",
                         [c["name"] for c in turn.tool_calls])
                messages.append({
                    "role": "assistant",
                    "content": turn.content or None,
                    "tool_calls": [{
                        "id": c["id"], "type": "function",
                        "function": {"name": c["name"],
                                     "arguments": json.dumps(c["arguments"],
                                                             ensure_ascii=False)},
                    } for c in turn.tool_calls],
                })
                for call in turn.tool_calls:
                    t_call = time.perf_counter()
                    result = await self.call_device_tool(call["name"], call["arguments"])
                    self.log("[tool]", call["name"],
                             round(time.perf_counter() - t_call, 2), "s",
                             result[:120])
                    messages.append({"role": "tool", "tool_call_id": call["id"],
                                     "content": result})
            if not reply_text:
                self.log("[llm] empty reply")
                return
            self._reply_ready = True
            media = _media_paths(reply_text)
            reply = _strip_media(reply_text).strip()
            limit = int(self.cfg["conversation"].get("max_reply_chars", 300))
            if len(reply) > limit:
                cut = reply[:limit]
                for sep in "。！？!?":
                    idx = cut.rfind(sep)
                    if idx > limit * 0.6:
                        cut = cut[:idx + 1]
                        break
                reply = cut
            self.history += [{"role": "user", "content": text},
                             {"role": "assistant", "content": reply}]
            await self._show_media(media)

            if not self.alive:
                # C: the reply arrived after the socket went away (user left).
                # Only queue when nothing was heard at all: with streamed TTS a
                # part of the answer may already have played, and repeating the
                # whole reply to someone who heard its beginning is worse than
                # silence. Same rule as B (`_first_audio_at is None`).
                if self._first_audio_at is None and not spoken:
                    proactive.note_pending_answer(reply_text, turn_id)
                    self.log("[proactive] queued late answer turn=" + turn_id)
                else:
                    self.log("[proactive] late answer not queued "
                             "(partially spoken)")
                return

            if spoken:
                self.log("[tts] streamed", len(spoken), "sentence(s)")
                self._reply_ready = True
                self.log("[turn] done", round(time.perf_counter() - t0, 2), "s")
                return

            speak = speech_text(reply) or reply
            if speak != reply:
                self.log("[tts] sanitized", repr(reply[:60]), "->", repr(speak[:60]))
            t_tts = time.perf_counter()
            pcm, rate = await self.tts.synth(speak)
            pcm16 = resample(pcm, rate, self.cfg["audio"]["sample_rate"])
            self.log("[tts] synth", round(time.perf_counter() - t_tts, 2), "s",
                     round(len(pcm16) / self.cfg["audio"]["sample_rate"], 2), "s audio")
            await self._speak(speak, pcm16, t0, answer=True)
            self.log("[turn] done", round(time.perf_counter() - t0, 2), "s")
        except asyncio.CancelledError:
            # Barge/abort/connection-loss cancelled the turn. Queue only when
            # the user heard nothing at all: `_first_audio_at` is set by the
            # first audio frame in `_speak`, and the thinking-face cue does not
            # touch it (chime is disabled since task-17). Partial playback is
            # deliberately not re-announced.
            if (route == "agent" and reply_text
                    and self._first_audio_at is None):
                proactive.note_pending_task(reply_text, turn_id)
                self.log("[proactive] queued task result turn=" + turn_id)
            raise

    async def _speak(self, text: str, pcm16: np.ndarray, t0: float,
                     label: str = "tts", announce: bool = True,
                     answer: bool = False):
        """Play PCM; `answer=True` marks the main answer playback.

        C2/C3 ordering: the cue restore and the ``speaking`` look are pushed
        BEFORE `tts_start` / the first audio frame, so the face moves first and
        the voice follows. ``announce=False`` keeps the filler chime text out of
        the subtitle bar; only `answer=True` owns the speaking look.
        """
        mute = getattr(self, "mute", None)
        async with self._speak_lock:
            if mute is not None and mute.muted:
                # A turn started before the switch was flipped must not keep
                # streaming answer audio into a muted room.
                self.log(f"[mute] {label} speech blocked")
                return
            if not announce and (self._reply_ready or self._first_audio_at is not None):
                # The answer won the lock race while the chime was waiting; do
                # not play "da" after (or on top of) the real reply.
                self.log("[filler] chime skipped (answer ready)")
                return
            # Peek one frame: the face may only claim "speaking" when audio will
            # actually follow, but an empty buffer still opens/closes playback
            # (the legacy chime tests pin that wire shape).
            frame_iter = iter(self.codec.frames(pcm16))
            frame = next(frame_iter, None)
            has_audio = frame is not None
            self.speaking = True
            self._speak_started_at = time.perf_counter()
            self._barge_ms = 0
            self._barge_quiet_ms = 0
            self._barge_onset_at = None
            self._echo_sub.clear()
            self._echo_frame.clear()
            self._echo_recent.clear()
            first_frame = True
            stopped_by_mute = False
            try:
                # Face first, voice second.
                if announce and has_audio:
                    # Any spoken answer (including a confirm read-back) clears
                    # our cue; the opt-in chime uses announce=False and must not
                    # restore a face it never set.
                    await self._restore_cue_face("first audio")
                if answer and has_audio and not self._spoke_answer:
                    # First answer audio of this turn only: streaming sends one
                    # _speak per sentence, and re-emitting llm/speaking would
                    # restart the face animation.
                    self._spoke_answer = True
                    if (getattr(self, "pending_confirm", None) is None
                            and not self._cue_pushed):
                        # Confirm-pending owns the face while a spoken yes is
                        # awaited; and do not steal a pending cue's frame
                        # (cue_restore_face may be configured to never restore).
                        await self._push_state_face("speaking")
                await self._safe_send(protocol.tts_start(self.session_id))
                if announce:
                    await self._safe_send(
                        protocol.tts_sentence(text[:60], self.session_id))
                while frame is not None:
                    if mute is not None and mute.muted:
                        # Drop the rest of the playback without a tts stop: B1
                        # must not send the device back to Listening (that would
                        # be the B2 stop-capture mechanism, not this task).
                        stopped_by_mute = True
                        self.log(f"[mute] {label} playback dropped")
                        break
                    if not self.speaking:
                        # Barge-in and device aborts stop an answer by cancelling
                        # its turn, but a proactive announcement has no turn: the
                        # loop has to watch the flag or it keeps streaming audio at
                        # someone who just interrupted.
                        self.log(f"[{label}] playback stopped early")
                        break
                    await self._safe_send(frame)
                    if first_frame:
                        first_frame = False
                        if self._first_audio_at is None:
                            self._first_audio_at = time.perf_counter() - t0
                        self.log(f"[{label}] first frame",
                                 round(time.perf_counter() - t0, 2), "s after speech end")
                    frame = next(frame_iter, None)
                    if frame is not None:
                        await asyncio.sleep(SPEECH_FRAME_SECONDS * 0.9)
                if not stopped_by_mute:
                    await self._safe_send(protocol.tts_stop(self.session_id))
            finally:
                self.speaking = False
                self._flush_echo("playback")

    # ---------------- filler ----------------

    async def _push_thinking_face(self, t0: float) -> None:
        """Show the thinking face once; never raise into the turn pipeline."""
        try:
            await self.push_emotion(self.thinking_face)
            self._cue_pushed = True
            self._face_state = "thinking"
            self._face_emotion = self.thinking_face
            self.log("[face] cue thinking at", round(time.perf_counter() - t0, 2), "s")
        except Exception as exc:
            self.log("[face] cue failed", type(exc).__name__, exc)

    async def _restore_cue_face(self, reason: str, *, force: bool = False) -> None:
        """Undo our own thinking cue once; a lost restore is only a log line.

        The firmware only sets an emotion on Idle/Connecting/Listening
        (application.cc:1138-1147); kDeviceStateSpeaking calls SetStatus only.
        So nothing else will clear "thinking" while the answer plays - the cue
        must restore itself.

        A stale cue must not overwrite a newer state look: if the face already
        moved on (speaking / confirm-pending / tool-running / barge startle), the
        restore is skipped. `idle` is allowed for the fire-and-forget kick, which
        marks the resting look before scheduling this coroutine.
        """
        if not self.cue_restore_face:
            return
        if not self._cue_pushed and not force:
            return
        self._cue_pushed = False
        state = getattr(self, "_face_state", None)
        if state not in (None, "thinking", "idle"):
            self.log("[face] cue restore skipped", f"({reason}, state={state})")
            return
        try:
            await self.push_emotion(self.cue_restore_face)
            # The restore is the resting look; record it so a turn-end idle push
            # does not repeat the same frame.
            self._face_state = "idle"
            self._face_emotion = self.cue_restore_face
            self.log("[face] cue restore", f"({reason})")
        except Exception as exc:
            self.log("[face] cue restore failed", type(exc).__name__, exc)

    def _kick_cue_restore(self, reason: str) -> None:
        """Fire-and-forget restore for finally blocks (survives cancellation)."""
        if not self._cue_pushed or not self.cue_restore_face:
            return
        self._cue_pushed = False
        state = getattr(self, "_face_state", None)
        if state not in (None, "thinking"):
            self.log("[face] cue restore skipped", f"({reason}, state={state})")
            return
        # The restore is already on its way; mark the resting look synchronously
        # so `_finish_turn_face` does not queue a second neutral frame.
        self._face_state = "idle"
        self._face_emotion = self.cue_restore_face
        task = asyncio.create_task(self._restore_cue_face(reason, force=True))
        self._cue_tasks.add(task)
        task.add_done_callback(self._cue_tasks.discard)

    async def _push_state_face(self, state: str) -> None:
        """Push the expression for a conversation state; a lost face only logs.

        Single source of truth: `persona.map_state_to_emotion(state)`. A frame is
        sent only when the *emotion* changes: `tool-running` and `thinking` share
        the thinking look, and re-sending the same emotion restarts the firmware
        animation. The state transition is still logged when only the name is
        unchanged (C2/C3 audit trail), but no duplicate frame goes on the wire.
        """
        name = persona.map_state_to_emotion(state)
        last_state = getattr(self, "_face_state", None)
        last_emotion = getattr(self, "_face_emotion", None)
        if state == last_state and name == last_emotion:
            return
        if name == last_emotion:
            self._face_state = state
            self.log("[face] state", state, "->", name, "(unchanged, not resent)")
            return
        try:
            await self.push_emotion(name)
            self._face_state = state
            self._face_emotion = name
            self.log("[face] state", state, "->", name)
        except Exception as exc:
            self.log("[face] state failed", state, type(exc).__name__, exc)

    def _kick_state_face(self, state: str) -> None:
        """Fire-and-forget state expression (turn-end clears survive cancel)."""
        task = asyncio.create_task(self._push_state_face(state))
        self._state_tasks.add(task)
        task.add_done_callback(self._state_tasks.discard)

    def _finish_turn_face(self) -> None:
        """Return the face to the idle look at turn end (C3).

        Skips the push when the current look is already resting (idle/listening),
        when a barge-in startle owns the face (the cancelled turn must not paint
        neutral over the surprised look), or when an action is still waiting for
        a spoken yes (the confused / confirm-pending face must survive until
        yes/no/timeout). Neutral (not relaxed) because the firmware already sets
        neutral itself on Idle (application.cc:1101-1110).
        """
        self._spoke_answer = False
        if getattr(self, "pending_confirm", None) is not None:
            return
        if getattr(self, "_face_state", None) in (None, "idle", "listening",
                                                  "barge-in"):
            return
        self._kick_state_face("idle")

    def _start_filler(self, t0: float) -> asyncio.Task | None:
        """Acknowledge the turn at `proactive_chime_lead_ms` after segment close.

        Default is the visual cue (thinking face), no sound. `filler_chime_ms > 0`
        opts back into the chime; both use the same 300 ms lead and skip rules.
        The legacy spoken filler keeps `filler_after_seconds` and only runs when
        both the face and the chime are disabled.
        """
        if self.thinking_face or self._filler_pcm is not None:
            delay = proactive_chime_lead_ms_for(self.cfg["conversation"]) / 1000.0
        else:
            delay = float(self.cfg["conversation"].get("filler_after_seconds", 0) or 0)
            if not self.filler_cache or delay <= 0:
                return None
        return asyncio.create_task(self._filler_after(t0, delay))

    async def _filler_after(self, t0: float, delay: float):
        try:
            wait = delay - (time.perf_counter() - t0)
            if wait > 0:
                await asyncio.sleep(wait)
            if not self.alive:
                return
            if (getattr(self, "pending_confirm", None) is not None
                    or getattr(self, "_face_state", None) == "thinking"):
                # The face is already where the cue wanted it: either the ASR
                # completed and pushed the thinking state, or a confirmation is
                # pending and the confused face must stay. Re-sending would
                # restart the firmware animation (or steal the confirm face).
                self.log("[face] face cue skipped (state already set)")
                return
            if self._first_audio_at is not None or self._reply_ready:
                # The answer is already on its way: do not flash a face (or
                # chirp) just before the real reply.
                if self.thinking_face:
                    self.log("[face] face cue skipped (answer ready)")
                elif self._filler_pcm is not None:
                    self.log("[filler] chime skipped (answer ready)")
                return
            if self.thinking_face:
                await self._push_thinking_face(t0)
                return
            if self._filler_pcm is not None:
                phrase = f"chime {int(len(self._filler_pcm) * 1000 / self.cfg['audio']['sample_rate'])} ms"
                self.log("[filler]", phrase, "at", round(time.perf_counter() - t0, 2), "s")
                # Server log only: never put this string in the device subtitle.
                await self._speak(phrase, self._filler_pcm, t0, label="filler",
                                  announce=False)
                return
            if not self.filler_cache:
                return
            phrase, pcm16 = random.choice(list(self.filler_cache.items()))
            self.log("[filler]", phrase, "at", round(time.perf_counter() - t0, 2), "s")
            await self._speak(phrase, pcm16, t0, label="filler")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.log("[filler] error", type(exc).__name__, exc)


    async def send_notify(self, audio_url: str, text: str) -> bool:
        """Push a one-way voice notification (device must be idle and connected)."""
        mute = getattr(self, "mute", None)
        if mute is not None and mute.muted:
            self.log("[mute] notification refused")
            return False
        if not self.alive:
            return False
        await self._safe_send(protocol.notify(audio_url, text))
        self.log("[notify] pushed", text[:40], audio_url)
        return True
