"""Proactive v0: four whitelisted triggers, gate chain, face before voice.

Standard library only (no aiohttp, no models), so the decision logic imports
offline and every gate is unit-testable with an injected clock.

What may start an utterance -- nothing else is allowed:
    TASK_DONE        an async task / tool result finished
    SCHEDULED        a reminder the user explicitly set for a time
    ANSWER_READY     something we promised ("我查一下") now has an answer
    CONFIRM_TIMEOUT  a confirm-pending action expired unanswered

The B1 mute switch adds one gate at the very front (`Gate.MUTE`): while it is on
there is no face push, no speech and no quota consumption; `tick()` is a no-op
and queues keep their items for the unmute catch-up.

The board has no websocket session while it is fully idle, so a proactive event
may find no channel. That is recorded as `outcome="no_session"` and dropped: no
exception, no retry, no queue. When a gate rejects the event, the face is still
pushed (face-only feedback) but nothing is spoken; that is counted too.

`evaluate()` is pure and takes `now` through `Env`, so tests never depend on the
wall clock. The controller owns the mutable counters and the async executor.
"""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time as dt_time, timedelta
from enum import StrEnum

from persona import EMOTIONS


# How many recent decisions /debug/proactive/status keeps for review.
# Step 3 is judged over thirty minutes of ordinary use, so five was too few.
RECENT_KEEP = 20

# A queued announcement is heard minutes later with no context, so it says where it
# came from: a cut-off answer is being continued, a late reply answers something the
# person asked before the socket dropped. Kinds without an entry speak verbatim.
PENDING_PREFIX = {
    "task_done": "接着刚才说：",
    "answer_ready": "刚才你问的那件事：",
}


class TriggerKind(StrEnum):
    TASK_DONE = "task_done"
    SCHEDULED = "scheduled"
    ANSWER_READY = "answer_ready"
    CONFIRM_TIMEOUT = "confirm_timeout"


class Gate(StrEnum):
    MUTE = "muted"
    NO_SESSION = "no_session"
    IDLE_QUIET = "idle_quiet"
    HUMAN_SILENCE = "human_silence"
    NIGHT = "night"
    TOPIC_COOLDOWN = "topic_cooldown"
    HOURLY_LIMIT = "hourly_limit"
    MANUAL_MUTE = "manual_mute"


# Only this phrase family mutes proactive speech; it is deliberately narrow.
DONT_SPEAK = "别说了"


@dataclass(frozen=True)
class Trigger:
    kind: TriggerKind
    topic: str
    text: str
    emotion: str = "neutral"
    request_id: str = ""

    def __post_init__(self):
        if not isinstance(self.kind, TriggerKind):
            object.__setattr__(self, "kind", TriggerKind(self.kind))
        if self.emotion not in EMOTIONS:
            raise ValueError(f"unknown emotion {self.emotion!r}")


@dataclass(frozen=True)
class ProactiveConfig:
    enabled: bool = True
    dry_run: bool = True
    night_start: dt_time = dt_time(23, 0)
    night_end: dt_time = dt_time(8, 0)
    hourly_limit: int = 2
    topic_cooldown_min: int = 30
    mute_minutes: int = 30
    emotion_lead_ms: int = 600
    human_silence_seconds: float = 10.0
    pending_ttl_min: int = 30
    pending_max: int = 5
    pending_retry_seconds: int = 30
    # B1 catch-up after the mute switch is turned off: only items whose due time
    # is inside this window are spoken, at most `catchup_max_items` of them,
    # merged into one sentence. Older items are counted `missed_muted`, never
    # spoken. Read from the `mute:` block (also accepted under `proactive:`).
    catchup_window_min: float = 10.0
    catchup_max_items: int = 2

    def __post_init__(self) -> None:
        """Clamp values that would break the gates or the queue arithmetic.

        `pending_max = 0` used to make `enqueue_pending` loop on an empty list
        (IndexError), and a negative TTL/mute/lead silently inverted its gate.
        Clamping here covers both `from_cfg()` and hand-built configs (tests).
        """
        minimums = {
            "hourly_limit": 0,
            "topic_cooldown_min": 0,
            "mute_minutes": 0,
            "human_silence_seconds": 0.0,
            "emotion_lead_ms": 600,
            "pending_ttl_min": 1,
            "pending_max": 1,
            "pending_retry_seconds": 0,
            "catchup_window_min": 0.0,
            "catchup_max_items": 0,
        }
        for name, minimum in minimums.items():
            value = getattr(self, name)
            if value < minimum:
                print(f"[proactive] config {name}={value} < {minimum}, "
                      f"clamped to {minimum}", flush=True)
                object.__setattr__(self, name, minimum)

    @classmethod
    def from_cfg(cls, cfg: dict | None) -> "ProactiveConfig":
        """Parse the `proactive:` block; a typo must never break startup.

        Every value falls back to its default independently, so one bad key
        cannot cost the whole app its HTTP route or its voice pipeline.
        """
        block = (cfg or {}).get("proactive") or {}
        mute_block = (cfg or {}).get("mute") or {}
        return cls(
            enabled=_coerce_bool(block.get("enabled"), True),
            dry_run=_coerce_bool(block.get("dry_run"), True),
            night_start=_parse_hhmm(block.get("night_start"), dt_time(23, 0)),
            night_end=_parse_hhmm(block.get("night_end"), dt_time(8, 0)),
            hourly_limit=_coerce_int(block.get("hourly_limit"), 2),
            topic_cooldown_min=_coerce_int(block.get("topic_cooldown_min"), 30),
            mute_minutes=_coerce_int(block.get("mute_minutes"), 30),
            emotion_lead_ms=_coerce_int(block.get("emotion_lead_ms"), 600),
            human_silence_seconds=_coerce_float(
                block.get("human_silence_seconds"), 10.0),
            pending_ttl_min=_coerce_int(block.get("pending_ttl_min"), 30),
            pending_max=_coerce_int(block.get("pending_max"), 5),
            pending_retry_seconds=_coerce_int(
                block.get("pending_retry_seconds"), 30),
            catchup_window_min=_coerce_float(
                mute_block.get("catchup_window_min",
                               block.get("catchup_window_min")), 10.0),
            catchup_max_items=_coerce_int(
                mute_block.get("catchup_max_items",
                               block.get("catchup_max_items")), 2),
        )


def _coerce_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_bool(value, default: bool) -> bool:
    """Accept real bools plus the obvious strings; anything else -> default."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "yes", "on", "1"):
            return True
        if lowered in ("false", "no", "off", "0"):
            return False
    return default


def _parse_hhmm(value, default: dt_time) -> dt_time:
    if isinstance(value, str) and ":" in value:
        try:
            hour, minute = value.split(":", 1)
            return dt_time(int(hour), int(minute))
        except (TypeError, ValueError):
            return default
    return default


# ---------------- reminder text parsing (trigger A) ----------------

_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9}
_CN_NUMERALS = "零一二两三四五六七八九十"


def _parse_cn_number(text: str) -> int | None:
    """Parse 1-99 written as Chinese numerals ("三", "十五", "二十")."""
    if not text or any(ch not in _CN_NUMERALS for ch in text):
        return None
    if "十" not in text:
        return _CN_DIGITS.get(text) if len(text) == 1 else None
    head, _, tail = text.partition("十")
    tens = _CN_DIGITS.get(head, 1) if head else 1
    ones = _CN_DIGITS.get(tail, 0) if tail else 0
    return tens * 10 + ones


def _parse_int_word(text: str) -> int | None:
    return int(text) if text.isdigit() else _parse_cn_number(text)


# Request words, longest first: 「提醒我」 must win over 「提醒」 or the content
# would start with the leftover 「我」 ("提醒你我" read aloud).
_REMINDER_REQUEST_WORDS = ("提醒我", "叫我", "提醒", "别忘", "记得")


def _reminder_content(text: str, time_expr: str = "") -> str:
    """What to remind about: drop the time phrase, then the request words.

    Order matters: the time expression is removed first, so 「提醒我三分钟后
    喝水」 yields 喝水 rather than 三分钟后喝水 (which would make the read-back
    repeat the time). An empty result is legitimate — 「9:30 提醒我」 means "just
    remind me at 9:30" and is announced as 「好，09:30 提醒你。」.
    """
    content = text
    if time_expr:
        content = content.replace(time_expr, "", 1)
    for word in _REMINDER_REQUEST_WORDS:
        content = content.replace(word, "")
    return content.strip("，,。.！!？?、 ").lstrip("了")[:60]


def _next_occurrence(now: datetime, hour: int, minute: int,
                     tomorrow: bool = False) -> datetime | None:
    """Clock time today, rolling to tomorrow when it already passed."""
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if tomorrow:
        target += timedelta(days=1)
    elif target <= now:
        target += timedelta(days=1)
    return target


# 九点 / 九点半 / 九点三十分 / 9:30 / 明天九点 / 下午三点 / 今晚十点
# Up to two prefix tokens (in any order): a day word and/or a half-day word.
_DAY_WORDS = ("明天", "后天", "今天", "今日")
_HALF_DAY_WORDS = ("凌晨", "早上", "上午", "中午", "下午", "傍晚",
                   "晚上", "夜里", "今晚", "今夜")
# Only the abbreviations people actually say; everything else stays unsupported
# and is caught by the residue guard below instead of becoming a wrong time.
_PREFIX_ALIASES = {
    "明晚": ("明天", "晚上"),
    "后晚": ("后天", "晚上"),
    "明早": ("明天", "早上"),
    "半夜": ("", "晚上"),
    "午夜": ("", "晚上"),
}
_PREFIX_TOKENS = ("明晚|后晚|明早|半夜|午夜|凌晨|早上|上午|中午|下午|傍晚"
                  "|晚上|夜里|今晚|今夜|明天|后天|今天|今日")
_ABS_TIME_RE = re.compile(
    rf"((?:{_PREFIX_TOKENS})\s*)?"
    rf"((?:{_PREFIX_TOKENS})\s*)?"
    r"([零一二两三四五六七八九十\d]{1,3})(?:点|[:：])"
    r"(半|一刻|三刻|[零一二两三四五六七八九十\d]{1,3})?分?")

# A time expression must be preceded by non-time words only. 「今早七点」 would
# otherwise match 七点 and ring at 07:00, silently ignoring 今早 (right or wrong
# by accident). Unparsed time words before the match always mean the utterance
# is not something we understand, so: no reminder, no read-back.
#
# Two probes, because single characters are too blunt for Chinese:
# - day/night *fragments* anywhere in the prefix (明儿/今早/昨晚/前天/...) are
#   unambiguous, so they invalidate the match wherever they appear;
# - a bare fragment (大/昨/前) only counts when it sits right before the match
#   (「大后天八点」 -> prefix 大). A whole-word probe would reject ordinary
#   sentences like 「删除文件后提醒我九点」 (后 is content there) and
#   「我有个会三分钟后提醒我」 (个 is content there).
_TIME_RESIDUE_FRAGMENT_RE = re.compile(
    r"(?:明|后|今|昨|前|大)(?:天|晚|早|儿|日|个)")
_TIME_RESIDUE_TAIL_RE = re.compile(r"[晚早夜午半明后今昨前大儿天晨凌]")
_TIME_RESIDUE_TAIL_CHARS = 2
# Unsupported date contexts ("周末", "月底", "十月", "下个月", "10月8号"): we have
# not understood *when* the user means, so scheduling any clock time would be a
# guess. Returning None keeps 「没完全理解就不排提醒」 true for every such input
# instead of covering them one by one.
_TIME_RESIDUE_DATE_RE = re.compile(
    r"(?:周末|这周|本周|下周|上周|月底|月初|年中|年底|年初|下个月|下月|这个月|上个月"
    r"|[一二三四五六七八九十百\d]{1,3}月"
    r"|[一二三四五六七八九十百\d]{1,3}[号日]"
    r"|假期|过年|春节|国庆"
    r"|下周[一二三四五六日天]|周[一二三四五六日天])")


def _has_time_residue(text: str, position: int) -> bool:
    prefix = text[:position]
    if _TIME_RESIDUE_FRAGMENT_RE.search(prefix):
        return True
    if _TIME_RESIDUE_DATE_RE.search(prefix):
        return True
    return bool(_TIME_RESIDUE_TAIL_RE.search(prefix[-_TIME_RESIDUE_TAIL_CHARS:]))


def _apply_half_day(word: str, hour: int) -> tuple[int, int] | None:
    """Half-day word -> `(hour, day_offset)`; None when the pair is nonsense.

    The table is deliberately small and explicit. Being wrong by twelve hours is
    worse than not understanding at all (both are silent, but the wrong one rings
    at a time the user never asked for), so impossible pairs return None.
    """
    if word == "凌晨":
        if hour == 12:
            return 0, 0
        if hour < 12:
            return hour, 0
        return None
    if word in ("早上", "上午"):
        return (hour, 0) if hour <= 12 else None
    if word == "中午":
        if hour in (11, 12):
            return hour, 0
        if hour in (1, 2):
            return hour + 12, 0
        return None
    if word in ("下午", "傍晚"):
        if hour < 12:
            return hour + 12, 0
        if hour == 12:
            return 12, 0
        return hour, 0
    if word in ("晚上", "夜里", "今晚", "今夜"):
        # 「晚上零点/一点」 are the small hours (00:00/01:00), not 12:00/13:00;
        # only 5–11 shift by twelve hours. 「晚上十三点」 is not something anyone
        # says, so it returns None (unlike 「下午十三点」, which is ordinary 24h).
        if hour <= 4:
            return hour, 0
        if hour <= 11:
            return hour + 12, 0
        if hour == 12:                  # 「晚上十二点」 = midnight, next day
            return 0, 1
        return None
    return None


def _parse_absolute_time(match: "re.Match", now: datetime) -> datetime | None:
    raw_hour, raw_minute = match.group(3), match.group(4)
    tokens = [token.strip() for token in match.groups()[:2] if token and token.strip()]
    expanded: list[str] = []
    for token in tokens:
        if token in _PREFIX_ALIASES:
            day, half = _PREFIX_ALIASES[token]
            expanded.extend(part for part in (day, half) if part)
        else:
            expanded.append(token)
    day_words = [token for token in expanded if token in _DAY_WORDS]
    half_days = [token for token in expanded if token in _HALF_DAY_WORDS]
    if len(day_words) > 1 or len(half_days) > 1:
        return None                     # 「明天后天九点」 etc: do not guess
    day_word = day_words[0] if day_words else ""
    half_day = half_days[0] if half_days else ""

    hour = _parse_int_word(raw_hour)
    if raw_minute == "半":
        minute = 30
    elif raw_minute in ("一刻", "三刻"):
        # 「九点一刻」 must not fall through as 九点一 (09:01).
        minute = 15 if raw_minute == "一刻" else 45
    elif raw_minute:
        minute = _parse_int_word(raw_minute)
    else:
        minute = 0
    if hour is None or minute is None:
        return None

    day_offset = 0
    evening_small_hour = (half_day in ("晚上", "夜里", "今晚", "今夜")
                          and hour <= 4)
    if half_day:
        normalized = _apply_half_day(half_day, hour)
        if normalized is None:
            return None
        hour, day_offset = normalized
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None

    if day_word:
        base = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        # The half-day offset is part of the answer: 「明天晚上十二点」 is the
        # midnight *after* tomorrow (base +1 day +1 day), not tomorrow 00:00.
        day_offset += {"今天": 0, "今日": 0, "明天": 1, "后天": 2}[day_word]
        if evening_small_hour:
            # 「今天晚上零点」 is the midnight that ends today, i.e. tomorrow
            # 00:00 — not today 00:00, which is already gone and would be
            # dropped by the TTL without ever ringing.
            day_offset += 1
        # 今天/今日 are literal, even when the time has already passed (it then
        # expires through the TTL, which is honest).
        return base + timedelta(days=day_offset)

    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    target += timedelta(days=day_offset)
    if target <= now:
        target += timedelta(days=1)
    return target


# A bare time expression is not a reminder: 「我三分钟后出门」 must not schedule
# one. The user has to say they want to be reminded (relative and absolute both).
REMINDER_INTENT_WORDS = ("提醒", "叫我", "别忘", "记得")
# Cancel detection is a whitelist, not a guess: the request word must sit at the
# start of the utterance ("取消提醒…", "别提醒了"). 「特别/分别/告别/个别」 only look
# like a cancel request because of one shared character, and deleting a reminder
# the user wanted is worse than missing a cancel, so those block it outright.
_REMINDER_CANCEL_PREFIX_RE = re.compile(
    r"^(取消|不用再?|不要(?:再)?|不再|停止|别)(提醒|再提醒)")
# Verb + optional demonstrator + 「提醒」, all adjacent: 「删除刚才那个提醒」 works,
# 「删除文件后提醒我」 does not (no arbitrary gap is allowed, so nothing that merely
# mentions deletion *and* a reminder later in the sentence can delete one).
_REMINDER_CANCEL_PHRASE_RE = re.compile(
    r"(?:取消|删掉|删除)"
    r"(?:刚才那个|刚刚那个|刚才|刚刚|上一个|上个|那个|这个)?"
    r"(?:的)?提醒")
_REMINDER_CANCEL_BLOCKERS = ("特别", "分别", "告别", "个别", "再提醒我一次")
# Negation in front of the cancel verb flips the meaning: never delete on these.
_REMINDER_CANCEL_NEGATION_RE = re.compile(
    r"(?:不要|不用|不必|不想|无需|别|不)\s*(?:再)?\s*(?:删除|删掉|取消)")


def has_reminder_intent(text: str) -> bool:
    compact = "".join((text or "").split())
    return any(word in compact for word in REMINDER_INTENT_WORDS)


def is_reminder_cancel(text: str) -> bool:
    compact = "".join((text or "").split())
    # One global guard for the whole negation family: 「不要删除提醒」「别删掉提醒」
    # 「不用取消提醒」 all contain a cancel phrase, and deleting the reminder the
    # user just told us not to delete is the worst possible outcome here.
    if _REMINDER_CANCEL_NEGATION_RE.search(compact):
        return False
    if any(word in compact for word in _REMINDER_CANCEL_BLOCKERS):
        return False
    return bool(_REMINDER_CANCEL_PREFIX_RE.match(compact)
                or _REMINDER_CANCEL_PHRASE_RE.search(compact))


def parse_reminder(text: str, now: datetime | None = None):
    """Parse a reminder request into `(when, content)`; None when not a reminder.

    Supported shapes (the card's four classes):
        3 分钟后提醒我喝水 / 五分钟后叫我 / 半小时后提醒我
        明天 9 点提醒我开会 / 明天9点半
        9:30 提醒我 / 15:30 叫我
    Times are local wall-clock (same timezone as the rest of the server).
    A time expression alone is not enough: the text must also carry an explicit
    reminder intent (`REMINDER_INTENT_WORDS`), otherwise 「我三分钟后出门」 would
    schedule a reminder the user never asked for. Anything else is left to the
    normal conversation: returning None here must never change what the
    assistant answers.
    """
    if not text or not has_reminder_intent(text):
        return None
    now = now or datetime.now()
    compact = "".join(text.split())

    # relative: N 分钟后 / N 个小时后 / 半小时后 / 一个半小时后
    match = re.search(r"(半|\d+|[零一二两三四五六七八九十]+)个?(半)?"
                      r"(小时|钟头|分钟|分)后", compact)
    if match:
        if _has_time_residue(compact, match.start()):
            return None
        amount = 0.5 if match.group(1) == "半" else _parse_int_word(match.group(1))
        if amount is None:
            return None
        if match.group(2):              # 一个半小时 -> +0.5 hour
            amount = float(amount) + 0.5
        unit = match.group(3)
        minutes = amount * 60 if unit in ("小时", "钟头") else amount
        if minutes <= 0 or minutes > 60 * 24 * 7:
            return None
        return (now + timedelta(minutes=minutes),
                _reminder_content(compact, match.group(0)))

    # absolute: 九点 / 九点半 / 九点三十分 / 9:30, with 明天 / 后天 / 今天 / 今日
    match = _ABS_TIME_RE.search(compact)
    if match:
        if _has_time_residue(compact, match.start()):
            return None
        when = _parse_absolute_time(match, now)
        if when is None:
            return None
        return when, _reminder_content(compact, match.group(0))
    return None


def note_pending_task(text: str, turn_id: str) -> bool:
    """Trigger B: queue a tool result the user never heard (<=60 chars)."""
    controller = get_controller()
    if controller is None or not text:
        return False
    return controller.enqueue_pending(
        TriggerKind.TASK_DONE, topic=f"task:{turn_id}",
        text="".join(text.split())[:60], turn_id=turn_id, emotion="happy")


def note_pending_answer(text: str, turn_id: str) -> bool:
    """Trigger C: queue a reply that arrived when nobody was listening."""
    controller = get_controller()
    if controller is None or not text:
        return False
    compact = "".join(text.split())
    if len(compact) < 8 or all(ch in "，,。.！!？?、…~ " for ch in compact):
        return False
    return controller.enqueue_pending(
        TriggerKind.ANSWER_READY, topic=f"answer:{turn_id}",
        text=compact[:60], turn_id=turn_id, emotion="neutral")


def maybe_schedule_from_text(text: str, now: datetime | None = None) -> dict | None:
    """Production hook for trigger A: schedule when the user asked for it."""
    controller = get_controller()
    if controller is None:
        return None
    return controller.schedule_from_text(text, now)


def maybe_cancel_reminder(text: str) -> dict | None:
    """Production hook: 「取消提醒」 drops the newest reminder, if any."""
    controller = get_controller()
    if controller is None or not is_reminder_cancel(text):
        return None
    return controller.cancel_latest_reminder()


@dataclass(frozen=True)
class Env:
    """Snapshot of the board environment for one decision."""

    now: datetime
    socket_alive: bool = True
    device_idle: bool = True
    playing: bool = False
    muted: bool = False


@dataclass
class ProactiveState:
    last_human_speech_at: datetime | None = None
    last_emotion_sent_at: datetime | None = None
    last_spoke_at: datetime | None = None
    last_slot_at: datetime | None = None
    last_tick_at: datetime | None = None
    topic_last_at: dict[str, datetime] = field(default_factory=dict)
    spoke_at: list[datetime] = field(default_factory=list)
    muted_until: datetime | None = None
    scheduled: list[tuple[datetime, Trigger]] = field(default_factory=list)
    reminders: dict[str, dict] = field(default_factory=dict)
    reminder_seq: int = 0
    pending: list[dict] = field(default_factory=list)
    pending_expired: int = 0
    pending_dropped: int = 0
    reminder_expired: int = 0
    # B1 mute catch-up accounting (runtime only; not persisted).
    catchup_missed: int = 0
    catchup_spoken: int = 0
    catchup_last_at: datetime | None = None
    confirm_deadline: datetime | None = None
    confirm_topic: str = ""
    confirm_fired: bool = False
    day: date | None = None
    attempts: int = 0
    spoke_total: int = 0
    dry_run_total: int = 0
    face_only_total: int = 0
    no_session_total: int = 0
    rejected: dict[str, int] = field(default_factory=dict)
    recent: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class GateResult:
    allowed: bool
    rejected_by: Gate | None
    detail: str


def _is_night(now: dt_time, start: dt_time, end: dt_time) -> bool:
    """True inside [start, end), wrapping midnight; start == end disables it."""
    if start == end:
        return False
    if start < end:
        return start <= now < end
    return now >= start or now < end


def is_dont_speak(text: str) -> bool:
    """The narrow mute phrase from the task card ("别说了"), punctuation-tolerant."""
    compact = "".join(ch for ch in (text or "") if ch not in "，,。.！!？?、 \t\n")
    return DONT_SPEAK in compact


def evaluate(trigger: Trigger, env: Env, state: ProactiveState,
             cfg: ProactiveConfig) -> GateResult:
    """Return the first failing gate; pure apart from reading the state.

    Gate order is fixed (Lead-approved) so the logged `rejected_by` is stable:
    MUTE -> NO_SESSION -> IDLE_QUIET -> HUMAN_SILENCE -> NIGHT -> TOPIC_COOLDOWN
    -> HOURLY_LIMIT -> MANUAL_MUTE. The mute switch is checked first: while it
    is on there is no face push and no speech at all. A disabled controller is
    not a gate.
    """
    if not cfg.enabled:
        return GateResult(False, None, "proactive disabled")
    if env.muted:
        return GateResult(False, Gate.MUTE,
                          "mute switch on: server drops all uplink audio")
    if not env.socket_alive:
        return GateResult(False, Gate.NO_SESSION, "no live websocket session")
    if not env.device_idle or env.playing:
        return GateResult(False, Gate.IDLE_QUIET, "device busy or playing")
    if state.last_human_speech_at is not None:
        quiet = (env.now - state.last_human_speech_at).total_seconds()
        if quiet < cfg.human_silence_seconds:
            return GateResult(False, Gate.HUMAN_SILENCE,
                              f"human_silence: {quiet:.1f}s < "
                              f"{cfg.human_silence_seconds:g}s")
    if _is_night(env.now.time(), cfg.night_start, cfg.night_end):
        return GateResult(False, Gate.NIGHT,
                          f"night: {env.now.strftime('%H:%M')} in "
                          f"{cfg.night_start.strftime('%H:%M')}-"
                          f"{cfg.night_end.strftime('%H:%M')}")
    last = state.topic_last_at.get(trigger.topic)
    if last is not None:
        age = (env.now - last).total_seconds() / 60.0
        if age < cfg.topic_cooldown_min:
            return GateResult(False, Gate.TOPIC_COOLDOWN,
                              f"topic: {age:.1f}min < "
                              f"{cfg.topic_cooldown_min}min ({trigger.topic})")
    used = sum(1 for at in state.spoke_at
               if env.now - at < timedelta(hours=1))
    if used >= cfg.hourly_limit:
        return GateResult(False, Gate.HOURLY_LIMIT,
                          f"hourly: {used}/{cfg.hourly_limit}")
    if state.muted_until is not None and env.now < state.muted_until:
        return GateResult(False, Gate.MANUAL_MUTE,
                          f"muted_until: {state.muted_until.strftime('%H:%M')}")
    return GateResult(True, None, "ok")


def _iso(value: datetime | None) -> str | None:
    return value.isoformat(timespec="seconds") if value else None


class ProactiveController:
    """The executor: gates -> face -> (>= lead ms) -> speech, plus counters."""

    def __init__(self, sessions, cfg: dict | ProactiveConfig | None = None,
                 clock=None, sleep=None, log=None, mute=None):
        self._sessions = sessions
        self.cfg = (cfg if isinstance(cfg, ProactiveConfig)
                    else ProactiveConfig.from_cfg(cfg))
        self.state = ProactiveState()
        self._clock = clock or datetime.now
        self._sleep = sleep or asyncio.sleep
        self._log = log or (lambda line: print(line, flush=True))
        # Injected by server.main via vision.make_router (same instance as the
        # 4410 Session gate). None = mute feature not wired.
        self._mute = mute
        # Set by the HTTP app's startup hook; None when no ticker is running.
        self.worker_task: asyncio.Task | None = None
        # B1 unmute catch-up: one background task at a time, plus the last
        # result for /debug/mute (GET reports running/last_result).
        self._catchup_task: asyncio.Task | None = None
        self._catchup_last_result: dict | None = None

    def _muted(self) -> bool:
        return bool(self._mute is not None
                    and getattr(self._mute, "muted", False))

    # ---------------- time / accounting ----------------

    def _now(self) -> datetime:
        return self._clock()

    def _reset_day(self, now: datetime) -> None:
        if self.state.day == now.date():
            return
        self.state.day = now.date()
        self.state.attempts = 0
        self.state.spoke_total = 0
        self.state.face_only_total = 0
        self.state.no_session_total = 0
        self.state.rejected = {}
        self.state.recent = []

    def _env(self, now: datetime, live) -> Env:
        playing = any(getattr(sess, "speaking", False) for sess in live)
        busy_turn = any(getattr(sess, "turn", None) is not None
                        and not sess.turn.done() for sess in live)
        return Env(now=now,
                   socket_alive=bool(live),
                   device_idle=not playing and not busy_turn,
                   playing=playing,
                   muted=self._muted())

    # ---------------- inputs from the rest of the server ----------------

    def note_human_speech(self, now: datetime | None = None) -> None:
        self.state.last_human_speech_at = now or self._now()

    def note_user_text(self, text: str, now: datetime | None = None) -> bool:
        """Mute proactive speech for `mute_minutes` when the user says 别说了."""
        if not is_dont_speak(text):
            return False
        now = now or self._now()
        self.state.muted_until = now + timedelta(minutes=self.cfg.mute_minutes)
        self._log(f"[proactive] muted for {self.cfg.mute_minutes} min by user text")
        return True

    def note_confirm_pending(self, topic: str, expires_in: float,
                             now: datetime | None = None) -> None:
        now = now or self._now()
        self.state.confirm_deadline = now + timedelta(seconds=float(expires_in))
        self.state.confirm_topic = topic
        self.state.confirm_fired = False

    def clear_confirm(self) -> None:
        self.state.confirm_deadline = None
        self.state.confirm_topic = ""
        self.state.confirm_fired = False

    # ---------------- trigger A: reminders ----------------

    def schedule_from_text(self, text: str, now: datetime | None = None) -> dict | None:
        """Parse a reminder request from user text; None when it is not one."""
        now = now or self._now()
        parsed = parse_reminder(text, now)
        if parsed is None:
            return None
        when, content = parsed
        return self.add_reminder(content, when, now)

    def add_reminder(self, text: str, when: datetime,
                     now: datetime | None = None) -> dict:
        # Whole-second resolution on purpose: `at` is written to the log/HTTP
        # echo AND is the instant `tick()` compares against (`now >= _at`).
        # Parsers start from `datetime.now()`, so without this the echoed `at`
        # (truncated to seconds) and the real fire instant could differ by up to
        # 1 s: curl says 15:05:00 while the reminder actually fires at 15:05:00.6.
        # Truncating keeps echo == stored == comparison, i.e. fire at the second.
        when = when.replace(microsecond=0)
        now = now or self._now()
        self.state.reminder_seq += 1
        rid = f"r{self.state.reminder_seq}"
        item = {
            "id": rid,
            "text": text[:60],
            "at": when.isoformat(timespec="seconds"),
            "created_at": now.isoformat(timespec="seconds"),
            "_at": when,
        }
        self.state.reminders[rid] = item
        self._log(f"[proactive] reminder {rid} at {item['at']}: {item['text']}")
        return {key: value for key, value in item.items() if not key.startswith("_")}

    def list_reminders(self, now: datetime | None = None) -> list[dict]:
        now = now or self._now()
        out = []
        for item in self.state.reminders.values():
            out.append({
                "id": item["id"],
                "text": item["text"],
                "at": item["at"],
                "created_at": item["created_at"],
                # Whole seconds: `_at` is truncated in add_reminder, `now` is not,
                # so a raw float here would read 179.4 for a "3 minutes" reminder.
                "in_seconds": round((item["_at"] - now).total_seconds()),
            })
        return sorted(out, key=lambda entry: entry["at"])

    def delete_reminder(self, reminder_id: str) -> bool:
        return self.state.reminders.pop(str(reminder_id), None) is not None

    def cancel_latest_reminder(self) -> dict | None:
        """Drop the newest reminder (spoken 「取消提醒」); None when there is none."""
        if not self.state.reminders:
            return None
        latest = max(self.state.reminders.values(),
                     key=lambda item: int(item["id"][1:]))
        del self.state.reminders[latest["id"]]
        self._log(f"[proactive] reminder {latest['id']} cancelled by user")
        return {key: value for key, value in latest.items()
                if not key.startswith("_")}

    def _due_reminder_items(self, now: datetime) -> list[dict]:
        """Reminders whose time has come, oldest first. Pure: no removal.

        A reminder is a request the user made on purpose, so it is deleted only
        after it was actually spoken (or consumed by dry_run); `no_session` and
        gate rejections keep it for a retry instead of losing it.
        """
        return sorted((item for item in self.state.reminders.values()
                       if item["_at"] <= now),
                      key=lambda entry: entry["_at"])

    def _expire_reminders(self, now: datetime) -> None:
        if self._muted():
            # B1: a reminder that came due while muted must not silently age
            # out; it either gets the catch-up window or is counted missed when
            # the switch is turned off.
            return
        ttl = timedelta(minutes=self.cfg.pending_ttl_min)
        for reminder_id, item in list(self.state.reminders.items()):
            if now - item["_at"] > ttl:
                del self.state.reminders[reminder_id]
                self.state.reminder_expired += 1
                self._log(f"[proactive] expired reminder {reminder_id} "
                          f"({item['at']})")

    async def _flush_due_reminders(self, now: datetime) -> list[dict]:
        """Fire due reminders that can actually be spoken, keep the rest.

        Same rules as the pending queue: no live session -> keep without
        spending an attempt or an hourly slot; a rejected reminder is retried
        after `pending_retry_seconds`; it is dropped (counted `expired`) only
        after `pending_ttl_min` past its scheduled time.
        """
        if self._muted():
            return []
        self._expire_reminders(now)
        due = self._due_reminder_items(now)
        if not due:
            return []
        live = [sess for sess in (self._sessions() or [])
                if getattr(sess, "alive", True)]
        if not live:
            return []
        records: list[dict] = []
        for item in due:
            last_try = item.get("last_try_at")
            if last_try is not None and (now - last_try).total_seconds() \
                    < self.cfg.pending_retry_seconds:
                continue
            item["last_try_at"] = now
            body = (item["text"] or "").strip()
            record = await self.fire(Trigger(
                TriggerKind.SCHEDULED, topic=f"reminder:{item['id']}",
                # Say what it is: the reminder may have been set hours ago, so a
                # bare 「喝水」 out of nowhere reads as a non sequitur. Without any
                # content (「9:30 提醒我」) say that time has come rather than
                # synthesizing an empty sentence.
                text=f"提醒你{body}" if body else "提醒时间到了",
                emotion="happy"), now)
            records.append(record)
            if record["outcome"] in ("spoke", "dry_run"):
                self.state.reminders.pop(item["id"], None)
        return records

    # ---------------- triggers B/C: deferred announcements ----------------

    def enqueue_pending(self, kind: TriggerKind, topic: str, text: str,
                        turn_id: str, now: datetime | None = None,
                        emotion: str = "neutral") -> bool:
        """Queue a result the user did not hear. Deduped by turn_id.

        One turn can qualify as both task-done and answer-ready; the turn id
        keeps it to a single announcement ("同一件事补两遍最糟糕").
        """
        kind = TriggerKind(kind)
        now = now or self._now()
        self._expire_pending(now)
        for item in self.state.pending:
            if item["turn_id"] == turn_id:
                return False
        # Never drop an item that is being spoken right now: another turn can
        # enqueue during the 600 ms face->voice window.
        while len(self.state.pending) >= self.cfg.pending_max:
            victim = next((item for item in self.state.pending
                           if not item.get("in_flight")), None)
            if victim is None:
                # Everything is in flight; refuse the newcomer instead.
                self.state.pending_dropped += 1
                self._log("[proactive] pending queue full (all in flight), dropped new")
                return False
            self.state.pending.remove(victim)
            self.state.pending_dropped += 1
            self._log("[proactive] pending queue full, dropped oldest")
        self.state.pending.append({
            "kind": kind.value,
            "topic": topic,
            "text": text[:60],
            "emotion": emotion,
            "turn_id": turn_id,
            "created_at": now,
            "created_at_iso": now.isoformat(timespec="seconds"),
            "session_seen_at": now.isoformat(timespec="seconds"),
        })
        self._log(f"[proactive] queued {kind.value} turn={turn_id}: {text[:40]}")
        return True

    def _expire_pending(self, now: datetime) -> None:
        if self._muted():
            return
        ttl = timedelta(minutes=self.cfg.pending_ttl_min)
        keep = []
        for item in self.state.pending:
            if now - item["created_at"] > ttl:
                self.state.pending_expired += 1
                self._log(f"[proactive] expired {item['kind']} "
                          f"turn={item['turn_id']}")
            else:
                keep.append(item)
        self.state.pending = keep

    def pending_status(self, now: datetime | None = None) -> dict:
        now = now or self._now()
        self._expire_pending(now)
        by_kind: dict[str, int] = {}
        for item in self.state.pending:
            by_kind[item["kind"]] = by_kind.get(item["kind"], 0) + 1
        oldest = min((item["created_at"] for item in self.state.pending),
                     default=None)
        return {
            "count": len(self.state.pending),
            "by_kind": by_kind,
            "oldest_age_s": (round((now - oldest).total_seconds(), 1)
                             if oldest else 0),
            "expired": self.state.pending_expired,
            "dropped": self.state.pending_dropped,
        }

    async def _flush_pending(self, now: datetime) -> dict | None:
        """Speak at most one queued announcement, only with a live session.

        No session means the board is idle: keep the item until it expires and
        do not spend a gate attempt or an hourly slot on it.
        """
        if self._muted():
            return None
        self._expire_pending(now)
        if not self.state.pending:
            return None
        live = [sess for sess in (self._sessions() or [])
                if getattr(sess, "alive", True)]
        if not live:
            return None
        item = next((entry for entry in self.state.pending
                     if not entry.get("in_flight")), None)
        if item is None:
            return None
        last_try = item.get("last_try_at")
        if last_try is not None and (now - last_try).total_seconds() \
                < self.cfg.pending_retry_seconds:
            return None
        item["in_flight"] = True
        item["last_try_at"] = now
        body = item["text"]
        prefix = PENDING_PREFIX.get(item["kind"], "")
        trigger = Trigger(TriggerKind(item["kind"]), topic=item["topic"],
                          text=f"{prefix}{body}" if prefix else body,
                          emotion=item["emotion"])
        try:
            record = await self.fire(trigger, now)
        finally:
            item["in_flight"] = False
        if record["outcome"] in ("spoke", "dry_run"):
            # Identity removal: the queue may have shifted during the await.
            self.state.pending = [entry for entry in self.state.pending
                                  if entry is not item]
        return record

    def schedule(self, trigger: Trigger, at: datetime) -> None:
        self.state.scheduled.append((at, trigger))

    # ---------------- executor ----------------

    async def fire(self, trigger: Trigger, now: datetime | None = None) -> dict:
        now = now or self._now()
        self._reset_day(now)
        record = {
            "at": now.isoformat(timespec="seconds"),
            "kind": str(trigger.kind),
            "topic": trigger.topic,
            "allowed": False,
            "rejected_by": None,
            "detail": "",
            "emotion": trigger.emotion,
            "emotion_sent": False,
            "spoke": False,
            "outcome": "rejected",
        }

        if self._muted():
            # The switch is checked before `attempts += 1` on purpose: a muted
            # period must not consume hourly/cooldown/attempts quotas, and no
            # face is pushed either (the board is meant to sit quiet).
            record["detail"] = "mute switch on: no face, no speech"
            record["outcome"] = "muted"
            return self._finish(record)

        self.state.attempts += 1

        if not self.cfg.enabled:
            record["outcome"] = "disabled"
            return self._finish(record)

        live = [sess for sess in (self._sessions() or [])
                if getattr(sess, "alive", True)]
        if not live:
            # The board has no session while fully idle. Record it and drop the
            # event: no exception, no retry, nothing to speak to.
            record["detail"] = "no live session (board idle)"
            record["outcome"] = "no_session"
            self.state.no_session_total += 1
            return self._finish(record)

        result = evaluate(trigger, self._env(now, live), self.state, self.cfg)
        record["allowed"] = result.allowed
        record["rejected_by"] = result.rejected_by.value if result.rejected_by else None
        record["detail"] = result.detail
        # A face is pushed even when rejected (that is the "look but stay quiet"
        # behaviour), with one exception: if the reason we are staying quiet is that
        # the board is busy or already talking, showing a new face fights the face
        # that turn is using - the answer would visibly change expression mid-sentence.
        push_face = result.allowed or result.rejected_by is not Gate.IDLE_QUIET
        record["emotion_sent"] = (await self._push_emotion(live, trigger.emotion)
                                  if push_face else False)

        if not result.allowed:
            if result.rejected_by is not None:
                key = result.rejected_by.value
                self.state.rejected[key] = self.state.rejected.get(key, 0) + 1
            record["outcome"] = "face_only" if record["emotion_sent"] else "rejected"
            if record["emotion_sent"]:
                self.state.face_only_total += 1
            return self._finish(record)

        # Face first, then speech: the display needs >= emotion_lead_ms to
        # change before the board speaks (first sound lands ~600 ms later).
        await self._sleep(self.cfg.emotion_lead_ms / 1000.0)

        if self.cfg.dry_run:
            # Same path as production (gates -> face -> lead) but the utterance
            # is dropped right before speech. It still occupies the hourly and
            # topic windows so a dry run cannot hide a rate-limit problem.
            self._count_utterance(trigger, now)
            self.state.dry_run_total += 1
            record["outcome"] = "dry_run"
        else:
            record["spoke"] = await self._speak(live, trigger.text)
            if record["spoke"]:
                self._count_utterance(trigger, now)
                self.state.last_spoke_at = now
                self.state.spoke_total += 1
                record["outcome"] = "spoke"
            else:
                self.state.face_only_total += 1
                record["outcome"] = "face_only"
        return self._finish(record)

    def _count_utterance(self, trigger: Trigger, now: datetime) -> None:
        """Reserve a rate-limit slot in the hourly and topic windows.

        `last_spoke_at` is only updated when speech actually happened, so a dry
        run does not pretend it spoke; the slot time goes to `last_slot_at`.
        """
        self.state.spoke_at.append(now)
        self.state.topic_last_at[trigger.topic] = now
        self.state.last_slot_at = now
        self._prune_slots(now)

    def _prune_slots(self, now: datetime) -> None:
        """Drop rate-limit slots older than the rolling hour window."""
        cutoff = now - timedelta(hours=1)
        self.state.spoke_at = [at for at in self.state.spoke_at if at >= cutoff]

    async def _push_emotion(self, live, emotion: str) -> bool:
        sent = False
        for sess in live:
            try:
                await sess.push_emotion(emotion)
                sent = True
            except Exception as exc:  # cosmetic; never block a trigger
                self._log(f"[proactive] emotion error {type(exc).__name__}: {exc}")
        if sent:
            self.state.last_emotion_sent_at = self._now()
        return sent

    async def _speak(self, live, text: str) -> bool:
        for sess in live:                     # single board: first live session
            try:
                await sess.speak_announcement(text)
                return True
            except Exception as exc:
                self._log(f"[proactive] speech error {type(exc).__name__}: {exc}")
        return False

    def _finish(self, record: dict) -> dict:
        self.state.recent.append(record)
        # Keep enough history to review a whole acceptance window from
        # /debug/proactive/status: five entries covered minutes, while Step 3 is
        # judged over thirty minutes of ordinary use.
        del self.state.recent[:-RECENT_KEEP]
        self._log("[proactive] " + json.dumps(record, ensure_ascii=False))
        return record

    # ---------------- B1 mute catch-up ----------------

    def catchup_status(self) -> dict:
        """Queue depth plus the mute catch-up counters for /debug/mute."""
        return {
            "pending": len(self.state.reminders) + len(self.state.pending),
            "missed": self.state.catchup_missed,
            "missed_muted": self.state.catchup_missed,
            "spoken": self.state.catchup_spoken,
            "last_at": _iso(self.state.catchup_last_at),
            "window_min": self.cfg.catchup_window_min,
            "max_items": self.cfg.catchup_max_items,
            "running": (self._catchup_task is not None
                        and not self._catchup_task.done()),
            "last_result": self._catchup_last_result,
        }

    @staticmethod
    def _catchup_text(item: dict) -> str:
        raw = item["raw"]
        if item["queue"] == "reminder":
            body = (raw.get("text") or "").strip()
            return f"提醒你{body}" if body else "提醒时间到了"
        prefix = PENDING_PREFIX.get(raw.get("kind"), "")
        return f"{prefix}{raw.get('text', '')}"

    def _drop_catchup_item(self, item: dict) -> bool:
        raw = item["raw"]
        if item["queue"] == "reminder":
            return self.state.reminders.pop(raw["id"], None) is not None
        before = len(self.state.pending)
        self.state.pending = [entry for entry in self.state.pending
                              if entry is not raw]
        return len(self.state.pending) != before

    def _restore_catchup_item(self, item: dict) -> None:
        raw = item["raw"]
        if item["queue"] == "reminder":
            self.state.reminders[raw["id"]] = raw
        else:
            self.state.pending.append(raw)

    async def resume_from_mute(self, now: datetime | None = None) -> dict:
        """Speak what came due during the mute, once, on unmute.

        Only items whose due time is inside `catchup_window_min` are eligible,
        and only if they are already due: a future reminder stays queued and is
        spoken by its normal tick, never early. The newest `catchup_max_items`
        of the due items become one sentence; everything older (or beyond the
        cap) is dropped and counted `missed_muted` — a three-hour-old reminder
        must not ambush the person after unmute. Repeating this call finds the
        queues empty, so on/off cycles cannot repeat an announcement.
        """
        now = now or self._now()
        if self._muted():
            return {"spoken": False, "items": 0, "missed": 0,
                    "reason": "still muted"}
        window = timedelta(minutes=self.cfg.catchup_window_min)
        candidates: list[dict] = []
        for reminder in self.state.reminders.values():
            candidates.append({"queue": "reminder", "due": reminder["_at"],
                               "raw": reminder})
        for pending in self.state.pending:
            candidates.append({"queue": "pending", "due": pending["created_at"],
                               "raw": pending})
        if not candidates:
            return {"spoken": False, "items": 0, "missed": 0,
                    "reason": "empty"}

        # Future items (due > now) are not catch-up candidates: leave them in
        # their queues untouched, do not count them missed, and do not let them
        # occupy one of the two catch-up slots.
        due = [entry for entry in candidates if entry["due"] <= now]
        # Newest first: when more than the cap is due, the most recent items are
        # the ones a person still remembers, and the older ones are the "missed".
        due.sort(key=lambda entry: entry["due"], reverse=True)
        recent = [entry for entry in due if now - entry["due"] <= window]
        missed = ([entry for entry in due if now - entry["due"] > window]
                  + recent[max(0, self.cfg.catchup_max_items):])
        chosen = recent[:max(0, self.cfg.catchup_max_items)]
        chosen.reverse()                       # chronological in the sentence

        for entry in missed:
            self._drop_catchup_item(entry)
            self.state.catchup_missed += 1
            age_min = (now - entry["due"]).total_seconds() / 60.0
            kind = entry["raw"].get("kind") or entry["raw"].get("id") or "?"
            self._log(f"[mute] catchup missed_muted {entry['queue']}:{kind} "
                      f"due {age_min:.1f} min ago (not replayed)")

        reached = len(self.state.reminders) + len(self.state.pending)
        if not chosen:
            self._log(f"[mute] catchup nothing to speak, missed="
                      f"{len(missed)} pending={reached}")
            return {"spoken": False, "items": 0, "missed": len(missed),
                    "reason": "nothing_recent"}

        live = [sess for sess in (self._sessions() or [])
                if getattr(sess, "alive", True)]
        if not live:
            # Keep them queued: without a channel this is not a miss, the normal
            # path will deliver them when the board reconnects.
            self._log(f"[mute] catchup held: no live session "
                      f"items={len(chosen)} missed={len(missed)}")
            return {"spoken": False, "items": 0, "missed": len(missed),
                    "reason": "no_session"}

        line = "；".join(self._catchup_text(entry) for entry in chosen)
        removed = [entry for entry in chosen if self._drop_catchup_item(entry)]
        spoke = False
        try:
            for sess in live:              # single board: first live session
                spoke = await sess.speak_announcement(line)
                break
        except Exception as exc:  # noqa: BLE001 - restore and keep the service up
            self._log(f"[mute] catchup speech error "
                      f"{type(exc).__name__}: {exc}")
            spoke = False
        if not spoke:
            for entry in removed:
                self._restore_catchup_item(entry)
            self._log(f"[mute] catchup speech failed; items kept "
                      f"({len(removed)})")
            return {"spoken": False, "items": 0, "missed": len(missed),
                    "reason": "speech_failed"}

        self.state.catchup_spoken += len(removed)
        self.state.catchup_last_at = now
        self._log(f"[mute] catchup spoke items={len(removed)} "
                  f"missed={len(missed)}: {line[:60]}")
        return {"spoken": True, "items": len(removed), "missed": len(missed),
                "text": line}

    def start_catchup(self, now: datetime | None = None) -> bool:
        """Run `resume_from_mute` in the background; True when a task started.

        `/debug/mute` calls this after the switch was persisted so its POST can
        answer immediately even when TTS is slow. Only one task may exist at a
        time, which also makes a repeated/concurrent `off` idempotent. Failures
        are logged and stored in `catchup_status()["last_result"]`.
        """
        task = self._catchup_task
        if task is not None and not task.done():
            self._log("[mute] catchup already running; not started again")
            return False
        self._catchup_task = asyncio.create_task(
            self._run_catchup(now), name="mute-catchup")
        return True

    async def _run_catchup(self, now: datetime | None = None) -> dict:
        try:
            result = await self.resume_from_mute(now)
        except Exception as exc:  # noqa: BLE001 - task must never kill the loop
            result = {"spoken": False, "items": 0, "missed": 0,
                      "reason": f"error: {type(exc).__name__}"}
            self._log(f"[mute] catchup task error "
                      f"{type(exc).__name__}: {exc}")
        self._catchup_last_result = result
        return result

    # ---------------- scheduler ----------------

    async def tick(self, now: datetime | None = None) -> list[dict]:
        """Fire due reminders and one confirm-timeout reminder, if any."""
        now = now or self._now()
        self._reset_day(now)
        if self._muted():
            # No flush, no catch-up, no expiry while the switch is on. Keeping
            # `scheduled` untouched is what lets the first tick after unmute
            # decide what is still inside the catch-up window.
            self.state.last_tick_at = now
            return []
        self._prune_slots(now)
        self.state.last_tick_at = now
        fired: list[dict] = []
        due = [(at, trigger) for at, trigger in self.state.scheduled if at <= now]
        self.state.scheduled = [(at, trigger) for at, trigger in self.state.scheduled
                                if at > now]
        for _, trigger in due:
            fired.append(await self.fire(trigger, now))
        fired.extend(await self._flush_due_reminders(now))
        flushed = await self._flush_pending(now)
        if flushed is not None:
            fired.append(flushed)
        if (self.state.confirm_deadline is not None
                and not self.state.confirm_fired
                and now >= self.state.confirm_deadline):
            self.state.confirm_fired = True
            topic = self.state.confirm_topic or "confirm"
            fired.append(await self.fire(Trigger(
                TriggerKind.CONFIRM_TIMEOUT, topic=f"confirm:{topic}",
                text="刚才那个操作还在等你确认，要我继续吗？", emotion="confused",
            ), now))
        return fired

    async def run_forever(self, interval: float = 1.0) -> None:
        """Tick forever; a failing tick is logged, never fatal.

        Without this, one bad trigger (or a session raising mid-push) would end
        the worker silently and proactive would be dead until a restart.
        """
        if self.worker_task is None:
            # Manual starts (tests, a future keepalive path) still show up in
            # `status()["worker_alive"]`; the HTTP hook assigns the task it
            # created, which is the same object.
            self.worker_task = asyncio.current_task()
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._log(f"[proactive] tick error {type(exc).__name__}: {exc}")
            await self._sleep(interval)

    # ---------------- observability ----------------

    def status(self, now: datetime | None = None) -> dict:
        now = now or self._now()
        self._reset_day(now)
        self._prune_slots(now)
        # Same visibility as `pending_status`: a reminder past its TTL must not
        # keep showing up as "active" between two ticks.
        self._expire_reminders(now)
        used = len(self.state.spoke_at)
        live = [sess for sess in (self._sessions() or [])
                if getattr(sess, "alive", True)]
        return {
            "enabled": self.cfg.enabled,
            "dry_run": self.cfg.dry_run,
            "muted": self._muted(),
            "socket_alive": bool(live),
            "now": now.isoformat(timespec="seconds"),
            "night": f"{self.cfg.night_start.strftime('%H:%M')}-"
                     f"{self.cfg.night_end.strftime('%H:%M')}",
            "today": {
                "attempts": self.state.attempts,
                "spoke": self.state.spoke_total,
                "face_only": self.state.face_only_total,
                "no_session": self.state.no_session_total,
                "dry_run": self.state.dry_run_total,
                "rejected": dict(self.state.rejected),
            },
            "hourly": {"used": used, "limit": self.cfg.hourly_limit},
            "pending": self.pending_status(now),
            "catchup": self.catchup_status(),
            "reminders": {"count": len(self.state.reminders),
                          "expired": self.state.reminder_expired},
            "muted_until": (self.state.muted_until.isoformat(timespec="seconds")
                            if self.state.muted_until else None),
            "last_human_speech_at": _iso(self.state.last_human_speech_at),
            "last_emotion_sent_at": _iso(self.state.last_emotion_sent_at),
            "last_spoke_at": _iso(self.state.last_spoke_at),
            "last_slot_at": _iso(self.state.last_slot_at),
            "worker_alive": self.worker_task is not None
                            and not self.worker_task.done(),
            "last_tick_at": _iso(self.state.last_tick_at),
            "recent": list(self.state.recent),
        }


_CONTROLLER: ProactiveController | None = None


def configure(cfg: dict | None, sessions,
              mute=None) -> ProactiveController:
    """Create (or replace) the process-wide controller; called by the router."""
    global _CONTROLLER
    _CONTROLLER = ProactiveController(sessions, cfg, mute=mute)
    return _CONTROLLER


def get_controller() -> ProactiveController | None:
    return _CONTROLLER
