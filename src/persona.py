"""Server-side expression channel for the board's face (M7 persona layer).

Standard library only, on purpose: this module imports offline (no aiohttp, no
models, no Opus dynamic library), so the state vocabulary and the mapping can be
unit-tested and reused by the dialogue layer without dragging in the audio stack.

Step 2 splits responsibility with the firmware (application.cc):

- firmware owns the neutral baseline: Idle (:1101-1110), Connecting (:1116)
  and Listening (:1121) all call SetEmotion("neutral");
- firmware does NOT touch the face in ``kDeviceStateSpeaking`` (:1138-1147,
  SetStatus only) - the server owns ``speaking``;
- C2/C3 (2026-10-28) the server pushes all six conversation states:
  ``listening`` (session ready / listen start), ``thinking`` (ASR done, before
  the LLM call), ``speaking`` (before tts_start, i.e. face first, then voice),
  ``tool-running`` (around a device tool call), ``confirm-pending`` (while an
  action waits for a spoken yes) and ``idle`` (turn end / answer / cancel /
  timeout). Unknown states normalise to ``idle``.
- C1a (2026-10-28, task-12) each of the six states maps to its own emotion name
  so the C1 firmware can route six different EAFs: ``idle`` -> ``idle``
  (firmware-native idle -> neutral.eaf), ``listening`` -> ``happy``,
  ``thinking`` -> ``confused``, ``speaking`` -> ``speaking`` (C1 aliases the
  name to firmware ``neutral``; emote.json maps neutral -> winking.eaf),
  ``tool-running``/``working`` -> ``angry``, ``confirm-pending`` -> ``shocked``.
  ``speaking`` must NOT map to ``winking``: native ``winking`` already resolves
  to neutral.eaf, i.e. the same frame as native ``idle``.
- `barge-in` is an event look (not one of the six states): the startle is
  ``shocked``, pushed the moment the user talks over an answer.

The six state -> emotion names are now distinct on purpose; the earlier design
reused ``thinking`` for tool work and ``confused`` for confirm-pending, which
made the two states indistinguishable to the firmware.

State vocabulary
----------------
Copied from rui's ``LED_STATES`` so both projects name the same states
(``off listening thinking speaking wake error music music_paused muted``).
rui is MIT licensed; the vocabulary lives in this local checkout:

    01_Code/projects/house-ear/src/rui/config/schema.py:128  ("LED_STATES")

    MIT License

    Copyright (c) 2026 rui contributors

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in
    all copies or substantial portions of the Software.

Expression names
----------------
The stock display resolves a name through the Noto emoji table (firmware 2.5.3,
``managed_components/78__xiaozhi-fonts/include/noto_emoji.h:10-30``), then falls
back to Material Symbols, then logs a warning and ignores the name.

C1a switched the state map to six distinct names (``idle``, ``happy``,
``confused``, ``speaking``, ``angry``, ``shocked``) so the C1 firmware can show
six different EAFs. ``idle`` is not a Noto name: C1's ``SetEmotion`` override
maps it to neutral.eaf, while stock 2.5.3 ignores it. ``speaking`` is alias
resolved by C1 to firmware ``neutral`` (emote.json: neutral -> winking.eaf);
mapping it to native ``winking`` would collide with ``idle`` (native winking ->
neutral.eaf). ``listening`` remains in ``EMOTIONS`` for compatibility with the
pre-C1a contract but is no longer emitted by the state map.
"""
from enum import StrEnum

# rui LED_STATES (see the module docstring for the exact source and licence).
STATES = (
    "off", "listening", "thinking", "speaking", "wake", "error",
    "music", "music_paused", "muted",
)


class EMOTIONS(StrEnum):
    """Expression names the board's display understands (see module docstring)."""

    NEUTRAL = "neutral"
    # C1a: native idle look (C1 firmware maps it to neutral.eaf); NOT neutral:
    # the stock display's ``neutral`` is winking.eaf, which is not the idle face.
    IDLE = "idle"
    HAPPY = "happy"
    LAUGHING = "laughing"
    FUNNY = "funny"
    SAD = "sad"
    ANGRY = "angry"
    CRYING = "crying"
    LOVING = "loving"
    EMBARRASSED = "embarrassed"
    SURPRISED = "surprised"
    SHOCKED = "shocked"
    THINKING = "thinking"
    WINKING = "winking"
    COOL = "cool"
    RELAXED = "relaxed"
    DELICIOUS = "delicious"
    KISSY = "kissy"
    CONFIDENT = "confident"
    SLEEPY = "sleepy"
    SILLY = "silly"
    CONFUSED = "confused"
    # Persona looks: LISTENING kept for compatibility (not emitted by the state
    # map); SPEAKING IS emitted by C1a and C1 aliases it to firmware neutral.
    LISTENING = "listening"
    SPEAKING = "speaking"


EMOTION_NAMES = frozenset(emotion.value for emotion in EMOTIONS)

# Step 2 product states (ROADMAP: idle / listening / thinking / speaking /
# tool-running / confirm-pending), plus the rui vocabulary aliases kept from
# Step 1 and one event look (barge-in). This is the single definition of
# "state -> expression".
#
# C1a (task-12): the six conversation states map to six DISTINCT emotion names
# so the C1 firmware can route six different EAFs. Do not reuse a name across
# states ("working looks like thinking") - that is exactly what C1a fixes.
STATE_TO_EMOTION = {
    # --- the six Step 2 states (six distinct looks) -----------------------
    "idle": EMOTIONS.IDLE,               # C1: neutral.eaf
    "listening": EMOTIONS.HAPPY,         # Happy.eaf
    "thinking": EMOTIONS.CONFUSED,       # confused.eaf
    "speaking": EMOTIONS.SPEAKING,       # C1 alias -> neutral (winking.eaf)
    "tool-running": EMOTIONS.ANGRY,      # angry.eaf: focused execution
    "working": EMOTIONS.ANGRY,           # readable alias for tool-running
    "confirm-pending": EMOTIONS.SHOCKED, # shocked.eaf: "are you sure?"
    # --- event look (not a conversation state) ----------------------------
    # Barge-in startle: pushed the moment the user talks over an answer.
    "barge-in": EMOTIONS.SHOCKED,
    # --- rui vocabulary aliases (kept for compatibility) ------------------
    "off": EMOTIONS.NEUTRAL,
    "wake": EMOTIONS.NEUTRAL,
    "error": EMOTIONS.NEUTRAL,
    "music": EMOTIONS.NEUTRAL,
    "music_paused": EMOTIONS.NEUTRAL,
    "muted": EMOTIONS.NEUTRAL,
}

# Unknown states normalise to `idle` (C3): the face returns to the resting look
# instead of inventing an expression. `DEFAULT_EMOTION` is derived from it so
# there is still exactly one state -> emotion table.
DEFAULT_STATE = "idle"
DEFAULT_EMOTION = STATE_TO_EMOTION[DEFAULT_STATE]


def is_emotion(name: str) -> bool:
    """True when `name` is a known expression (used to validate /debug/emotion)."""
    return isinstance(name, str) and name in EMOTION_NAMES


def normalize_state(state: str) -> str:
    """Canonical state name: case/space tolerant, unknown states -> `idle`."""
    key = (state or "").strip().lower()
    return key if key in STATE_TO_EMOTION else DEFAULT_STATE


def map_state_to_emotion(state: str) -> str:
    """Map a state name to an expression name; unknown states -> idle's look.

    Pure function: case/space tolerant, no I/O. The six Step 2 states are
    ``idle`` / ``listening`` / ``thinking`` / ``speaking`` / ``tool-running`` /
    ``confirm-pending`` and map to six distinct names (``idle`` / ``happy`` /
    ``confused`` / ``speaking`` / ``angry`` / ``shocked``); ``barge-in`` is an
    event look mapped to ``shocked``.
    """
    return STATE_TO_EMOTION[normalize_state(state)].value
