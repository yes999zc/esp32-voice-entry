"""Spoken confirmation gate, C2/C3: restate first, only 确认/确定 approves.

Two-step contract:
1. `Session.call_device_tool` never runs a `safety.confirm_tools` action from the
   model's call. It stores pending {name, arguments, expires}, pushes the
   confirm-pending face, restates the action out loud
   (「我要重启这台设备（延迟秒数=0），确认吗？」) and returns
   `needs_confirmation` to the LLM.
2. The next utterance is classified by `dialogue.classify_confirm`:
   - 「确认」/「确定」 (optionally with 吧/了/啊/呀) -> run ONCE, then idle;
   - 取消/算了/不确认... -> drop, say 好，不动了。, then idle;
   - weak agreement (没问题了/好吧/可以吧/就行/好的/行/对/可以/...) -> None:
     keep pending and ask the restated question again;
   - 120 s timeout -> drop, idle, `[confirm] expired`.

Layout:
- Judgment table: only `dialogue.classify_confirm` is needed, so it runs with no
  aiohttp, no native libs and no ASR/TTS model loaded.
- `_resolve_confirm` / `call_device_tool` gate tests: `session` is imported
  behind a *simulator* (see `load_session`). It keeps the run offline but also
  means these tests prove nothing about `session`'s real import graph; that is
  covered separately by `test_session_top_level_imports_are_pinned`.
"""
import ast
import asyncio
import json
import subprocess
import sys
import time
import types
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dialogue import classify_confirm  # noqa: E402
import tools as devtools  # noqa: E402

CFG = yaml.safe_load((ROOT / "config.yaml").read_text())

# (a) the only two words that approve a destructive action, plus fillers.
YES_CASES = [
    "确认", "确定", "确认吧", "确定了", "确认了", "确认。", "确认！",
    "确认啊", "确定呀", "嗯确认", "那就确认吧", "我觉得确定",
]
# (b) weak agreement: None (not consent), pending survives and is re-asked.
WEAK_AGREEMENT = [
    "没问题了", "好吧", "可以吧", "就行", "好的", "行", "对", "好", "好啊",
    "可以", "没问题", "行吧", "执行", "干吧", "来吧", "是", "是呀", "行啊",
    "对哦", "好啊啊", "那好", "那行", "这好", "我觉得可以", "那就执行吧",
    "这就执行", "当然可以", "肯定可以", "我看可以",
]
NO_CASES = ["不是", "不确认", "先别", "不要了", "取消", "算了", "不行", "停",
            "别急着确认，先看看", "不确定", "不好", "不对",
            # step 3/4: negated or rejected yes words
            "我不太确定", "我还没确认", "没确认", "我还没确定",
            "确认不了", "确定不了", "确认个屁", "确认你个头",
            "不可以", "不可以。", "不可以！", "不可以执行", "不能执行",
            "无法执行", "执行不了", "先不执行", "暂不执行", "不需要执行",
            "我不建议执行", "不想执行", "不太想执行", "我没说可以",
            "我还没说可以", "可以个屁", "执行个屁", "没问题才怪", "没问题个屁",
            "确认个啥", "确认个什么", "确认个鬼", "确认个锤子", "可以个鬼",
            "问一下能不能执行"]
# Unrelated speech: not an answer, but still not consent.
NONE_CASES = ["你说什么", "今天天气不错", "", "嗯", "这是什么东西",
              "好像是这样吧", "那就这样吧", "对不起", "他说行",
              "让我确认一下", "我先确认一下再答复", "可以吗",
              "这个方案可以吗？", "我可以先问一下吗", "可以是可以，不过我想想",
              "确认一下", "确定一下",
              "谁让你确认的", "我什么时候说确认了", "确认什么确认",
              "这也要确认", "这还用确认", "还要确认", "可以是可以", "行倒是行",
              "好是好", "这好像可以吧", "应该可以吧",
              "这也要执行", "还要执行", "这还用执行", "那得执行",
              "估计可以", "估计没问题", "恐怕可以", "恐怕没问题", "八成可以",
              "兴许可以", "确认啥", "确认啥呀", "执行啥",
              "为什么执行", "怎么确认", "什么时候确认", "凭什么执行",
              "能执行不", "确认不",
              "等我确认", "等会儿确认", "等会确认", "等一会儿确认", "稍等确认",
              "稍后确认", "回头确认", "晚点确认", "明天确认", "待会儿确认",
              "我确认后再执行", "确认了再执行", "确认完再执行",
              "我确认后告诉你", "我确认完告诉你", "先确认", "再执行",
              "都可以", "都行", "是都行", "是吧", "对吧", "是吧啊"]


@pytest.mark.parametrize("text", YES_CASES)
def test_yes(text):
    assert classify_confirm(text) == "yes"


@pytest.mark.parametrize("text", WEAK_AGREEMENT)
def test_weak_agreement_is_not_consent(text):
    """C2/C3 acceptance 1: 没问题了/好吧/可以吧/就行/好的/行/对 are not yes."""
    assert classify_confirm(text) is None


# The filler set is closed, so the same weak word with a particle or a filler
# prefix must also stay None (the old template stripped these back to a yes).
WEAK_VARIANTS = ([word + suffix for word in WEAK_AGREEMENT
                  for suffix in ("吧", "了", "啊", "的", "嘛")]
                 + ["那就" + word for word in WEAK_AGREEMENT]
                 + ["我觉得" + word for word in WEAK_AGREEMENT])


@pytest.mark.parametrize("text", WEAK_VARIANTS)
def test_weak_agreement_variants_are_not_consent(text):
    assert classify_confirm(text) is None, text


@pytest.mark.parametrize("text", NO_CASES)
def test_no(text):
    assert classify_confirm(text) == "no"


@pytest.mark.parametrize("text", NONE_CASES)
def test_unrelated(text):
    assert classify_confirm(text) is None


def test_negative_beats_positive():
    # "不是" contains the positive word "是"; negation must win.
    assert classify_confirm("不是") == "no"
    # Longer negative word is not shadowed by the shorter positive one.
    assert classify_confirm("不要") == "no"


def test_structural_guards_still_hold():
    """The safety guards from the earlier revs must survive the yes narrowing."""
    refusals = ["确认个啥", "确认个什么", "确认个鬼", "确认个锤子", "可以个鬼"]
    for text in refusals:
        assert classify_confirm(text) == "no", text
    not_answers = [
        "确认啥", "确认啥呀", "执行啥",
        "这也要确认", "这也要执行", "还要执行", "这还用执行", "那得执行",
        "可以是可以", "行倒是行", "好是好",
        "这好像可以吧", "估计可以", "估计没问题", "恐怕可以", "恐怕没问题",
        "八成可以", "兴许可以",
        "为什么执行", "怎么确认", "什么时候确认", "凭什么执行",
        "能执行不", "确认不",
    ]
    for text in not_answers:
        assert classify_confirm(text) is None, text
    # The only positives are the explicit pair.
    for text in ["确认", "确认吧", "我觉得确定", "那就确认吧", "确定了"]:
        assert classify_confirm(text) == "yes", text


REV16_PREFIXES = ["", "嗯", "哦", "啊", "呀", "我", "我看", "我觉得", "那",
                  "那就", "这", "这就", "这样", "那这样"]
REV16_IDIOMS = ["对了", "行了", "好了", "可以了", "是了"]
REV16_TAILS = ["", "啊", "呀", "哦", "嘛", "啦", "喽", "哈", "哟", "咧",
               "啊呀", "嘛呀", "了啊"]
REV16_GRID = [prefix + idiom + tail
              for prefix in REV16_PREFIXES
              for idiom in REV16_IDIOMS
              for tail in REV16_TAILS]


@pytest.mark.parametrize("text", REV16_GRID)
def test_idiom_grid_never_yes(text):
    """Every prefix x idiom x tail combination must be None."""
    assert classify_confirm(text) is None, text


def test_idiom_grid_summary(capsys):
    failures = [text for text in REV16_GRID if classify_confirm(text) is not None]
    print(f"idiom grid: {len(REV16_GRID)} combinations, {len(failures)} failures")
    assert len(REV16_GRID) == 14 * 5 * 13
    assert failures == []


REV12_QUESTION_CASES = [
    "确认？", "确定？", "确认吧？", "可以？", "行？", "好？", "没问题？",
    "执行？", "好的？", "对啊？", "可以?", "确认??", "可以？。",
]


def test_question_mark_anywhere_is_none():
    """A question mark anywhere keeps the sentence a question (never consent)."""
    for text in REV12_QUESTION_CASES:
        assert classify_confirm(text) is None, text
    # Non-question edge punctuation is still trimmed.
    assert classify_confirm("确认。") == "yes"
    assert classify_confirm("确认！") == "yes"


def test_known_acceptable_overreach_is_documented():
    """Over-blocking in the safe direction is accepted."""
    assert classify_confirm("不好意思，确认") == "no"
    assert classify_confirm("差不多可以") == "no"


def test_filler_grunt_is_never_yes():
    assert classify_confirm("嗯") is None
    assert classify_confirm("嗯嗯") is None
    assert classify_confirm("嗯嗯嗯") is None


def test_spaces_inside_words():
    # ASR occasionally splits a word with spaces.
    assert classify_confirm("不 是") == "no"
    assert classify_confirm(" 确认 ") == "yes"


def test_pure_function_is_side_effect_free():
    before = classify_confirm("确认")
    assert classify_confirm("确认") == before
    assert classify_confirm("随便说点什么") is None


def test_dialogue_module_imports_offline():
    """Importing the pure module must not pull aiohttp or native audio libs."""
    code = (
        "import sys; sys.path.insert(0, 'src'); import dialogue; "
        "loaded = {'aiohttp', 'opuslib', 'sherpa_onnx', 'numpy'} & set(sys.modules); "
        "assert not loaded, loaded; print('offline ok')"
    )
    proc = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert "offline ok" in proc.stdout


# ---------------- restatement text (src/tools.py) ----------------

def test_restatement_names_the_action_and_arguments():
    question = devtools.confirm_question("self.reboot", {"delay": 0})
    assert "我要重启这台设备" in question
    assert "确认吗？" in question
    assert "延迟秒数=0" in question          # arguments are restated
    assert "self.reboot" not in question     # raw tool name never leaks
    assert "（" in question and "）" in question


@pytest.mark.parametrize("tool,word", [
    ("set_volume", "音量"),
    ("self.audio_speaker.set_volume", "音量"),
    ("set_brightness", "亮度"),
    ("self.screen.set_brightness", "亮度"),
    ("take_photo", "拍照"),
    ("self.camera.take_photo", "拍照"),
    ("self.upgrade_firmware", "升级固件"),
    ("self.system.reconfigure_wifi", "配置 Wi-Fi"),
])
def test_restatement_action_names(tool, word):
    question = devtools.confirm_question(tool, {})
    assert word in question
    assert "self." not in question          # dotted firmware name stays internal


def test_restatement_keeps_unknown_argument_key_in_parentheses():
    """Acceptance allows the English key inside parentheses; the name never leaks."""
    question = devtools.confirm_question("self.upload", {"blob_id": "abc"})
    assert "blob_id=abc" in question
    assert "self.upload" not in question


def test_restatement_without_arguments_has_no_empty_parentheses():
    question = devtools.confirm_question("self.system.reconfigure_wifi", {})
    assert question == "我要重新配置 Wi-Fi，确认吗？"


# ---------------- import graph guard ----------------

# Pinned on purpose: the simulator below hides real import failures, so a new
# top-level import in session.py must fail here and force a conscious decision
# (a heavy module at module scope would break the real server and this suite).
EXPECTED_SESSION_TOP_LEVEL_IMPORTS = {
    "asyncio", "json", "random", "re", "time", "uuid", "pathlib", "shutil",
    "subprocess", "numpy", "protocol", "proactive", "persona", "dialogue", "llm",
    "tools", "audio",
}


def test_session_top_level_imports_are_pinned():
    tree = ast.parse((ROOT / "src" / "session.py").read_text(encoding="utf-8"))
    names = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            names |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    assert names == EXPECTED_SESSION_TOP_LEVEL_IMPORTS


# ---------------- _resolve_confirm gate ----------------

_SESSION = None


def load_session():
    """Import `session` with one simulated dependency, purely for offline runs.

    Only `opuslib` is stubbed: it cannot even be imported on this machine
    (missing libopus), so without the stub `_resolve_confirm` could not be
    executed here at all. `aiohttp` is imported for real (it is installed and
    importing it opens no socket), which keeps the simulation as small as
    possible. `sherpa_onnx` stays real too: `audio.py` names it in annotations
    and importing it loads no model.
    """
    global _SESSION
    if _SESSION is None:
        with pytest.MonkeyPatch.context() as mp:
            mp.setitem(sys.modules, "opuslib", types.ModuleType("opuslib"))
            import session as module
        _SESSION = module
    return _SESSION


def test_session_uses_dialogue_classifier():
    assert load_session().classify_confirm is classify_confirm


class FakeSession:
    """Real Session methods on a hand-built instance; only IO is faked."""

    def __init__(self, expires_in: float = 60.0, tool_error: Exception | None = None,
                 tool_delay: float = 0.0):
        cls = load_session().Session
        self.session = cls.__new__(cls)
        self.spoken: list[str] = []
        self.tool_calls: list[tuple] = []
        self.logs: list[str] = []
        self.faces: list[str] = []
        self.tool_error = tool_error
        self.tool_delay = tool_delay
        self.session.pending_confirm = {
            "name": "self.reboot",
            "arguments": {"delay": 0},
            "expires": time.perf_counter() + expires_in,
        }
        self.session._confirm_task = None
        self.session._face_state = "confirm-pending"
        self.session._face_emotion = "shocked"
        self.session.log_prefix = "[test]"
        self.session.log = lambda *parts: self.logs.append(
            " ".join(str(part) for part in parts))

        async def say_text(t0, sentence):
            self.spoken.append(sentence)

        async def push_emotion(name):
            self.faces.append(name)

        async def call_device_tool(name, arguments, timeout=None, confirmed=False):
            self.tool_calls.append((name, arguments, confirmed))
            if self.tool_delay:
                await asyncio.sleep(self.tool_delay)
            if self.tool_error is not None:
                raise self.tool_error
            return '{"ok": true}'

        self.session._say_text = say_text
        self.session.push_emotion = push_emotion
        self.session.call_device_tool = call_device_tool

    async def resolve(self, text: str) -> bool:
        return await self.session._resolve_confirm(time.perf_counter(), text)


def test_yes_runs_tool_once_and_returns_to_idle():
    fake = FakeSession()
    assert asyncio.run(fake.resolve("确认")) is True
    assert fake.session.pending_confirm is None
    assert fake.tool_calls == [("self.reboot", {"delay": 0}, True)]
    assert fake.spoken == ["好，已经执行。"]
    assert fake.faces == ["idle"]                       # idle after execution
    assert any("[confirm] approved" in line for line in fake.logs)
    assert any("state idle -> idle" in line for line in fake.logs)


@pytest.mark.parametrize("text", ["确认", "确定", "确认吧", "确定了", "确认了"])
def test_yes_variants_execute(text):
    fake = FakeSession()
    assert asyncio.run(fake.resolve(text)) is True
    assert fake.tool_calls == [("self.reboot", {"delay": 0}, True)]
    assert fake.session.pending_confirm is None


def test_repeated_confirm_does_not_run_twice():
    fake = FakeSession()
    assert asyncio.run(fake.resolve("确认")) is True
    assert asyncio.run(fake.resolve("确认")) is False
    assert fake.tool_calls == [("self.reboot", {"delay": 0}, True)]


def test_concurrent_confirm_runs_tool_exactly_once():
    """Two turns racing on the same pending confirm must not double-execute."""
    fake = FakeSession(tool_delay=0.01)

    async def race():
        return await asyncio.gather(fake.resolve("确认"), fake.resolve("确认"))

    results = asyncio.run(race())
    assert sorted(results) == [False, True]
    assert fake.tool_calls == [("self.reboot", {"delay": 0}, True)]


@pytest.mark.parametrize("text", WEAK_AGREEMENT)
def test_weak_agreement_keeps_pending_and_asks_again(text):
    fake = FakeSession()
    assert asyncio.run(fake.resolve(text)) is True
    assert fake.session.pending_confirm is not None         # still waiting
    assert fake.session.pending_confirm["name"] == "self.reboot"
    assert fake.tool_calls == []                            # nothing executed
    assert fake.spoken == ["我要重启这台设备（延迟秒数=0），确认吗？"]
    assert any("[confirm] asking again" in line for line in fake.logs)
    assert fake.faces == []                                 # no idle flash


@pytest.mark.parametrize("text", ["让我确认一下", "可以吗", "等我确认", "确认啥"])
def test_hedge_keeps_pending_and_asks_again(text):
    fake = FakeSession()
    assert asyncio.run(fake.resolve(text)) is True
    assert fake.session.pending_confirm is not None
    assert fake.tool_calls == []
    assert fake.spoken == ["我要重启这台设备（延迟秒数=0），确认吗？"]


def test_cancel_drops_pending_and_returns_to_idle():
    fake = FakeSession()
    assert asyncio.run(fake.resolve("取消")) is True
    assert fake.session.pending_confirm is None
    assert fake.tool_calls == []
    assert fake.spoken == ["好，不动了。"]
    assert fake.faces == ["idle"]
    assert any("[confirm] cancelled" in line for line in fake.logs)


def test_suan_le_is_cancel():
    fake = FakeSession()
    assert asyncio.run(fake.resolve("算了")) is True
    assert fake.session.pending_confirm is None
    assert fake.tool_calls == []


def test_negative_confirm_cancels_without_running_tool():
    """A refusal (not a weak yes) also drops the action and says so."""
    fake = FakeSession()
    assert asyncio.run(fake.resolve("我不太确定")) is True
    assert fake.session.pending_confirm is None
    assert fake.tool_calls == []
    assert fake.spoken == ["好，不动了。"]


def test_expired_pending_is_dropped_and_idles():
    fake = FakeSession(expires_in=-1.0)
    assert asyncio.run(fake.resolve("确认")) is False
    assert fake.session.pending_confirm is None
    assert fake.tool_calls == []
    assert fake.spoken == []
    assert fake.faces == ["idle"]
    assert any("[confirm] expired" in line for line in fake.logs)


def test_tool_failure_still_consumes_the_turn():
    fake = FakeSession(tool_error=RuntimeError("boom"))
    assert asyncio.run(fake.resolve("确认")) is True
    assert fake.session.pending_confirm is None
    assert fake.spoken == ["没执行成功。"]
    assert fake.faces == ["idle"]


def test_no_pending_returns_false():
    fake = FakeSession()
    fake.session.pending_confirm = None
    assert asyncio.run(fake.resolve("确认")) is False
    assert fake.tool_calls == []


def test_route_still_prefers_agent_while_pending():
    fake = FakeSession()
    fake.session.fast_llm = object()
    fake.session.route_max_chars = 1000
    assert fake.session._route("哈哈") == "agent"
    fake.session.pending_confirm = None
    assert fake.session._route("哈哈") == "fast"


# ---------------- the real pending path (call_device_tool) ----------------

class FakeWs:
    def __init__(self):
        self.sent = []

    async def send(self, data):
        self.sent.append(data)

    def emotions(self):
        out = []
        for raw in self.sent:
            if isinstance(raw, bytes):
                continue
            msg = json.loads(raw)
            if msg.get("type") == "llm":
                out.append(msg.get("emotion"))
        return out


def real_pending_session(confirm_timeout: float = 120.0):
    """A Session with the real call_device_tool/_resolve_confirm wiring."""
    cls = load_session().Session
    s = cls.__new__(cls)
    s.ws = FakeWs()
    s.session_id = "test"
    s.log_prefix = "[test]"
    s.cfg = dict(CFG)
    s.cfg["safety"] = dict(CFG["safety"], confirm_timeout=confirm_timeout)
    s.confirm_tools = {"self.reboot"}
    s.pending_confirm = None
    s._confirm_task = None
    s._confirm_prompt_end_at = None
    s.confirm_echo_guard_ms = 400.0
    s._face_state = None
    s._face_emotion = None
    s._state_tasks = set()
    s._cue_tasks = set()
    s._mcp_id = 10
    s._pending = {}
    s._speak_lock = asyncio.Lock()
    s.speaking = False
    s.alive = True
    s.turn = None
    spoken = []

    async def say_text(t0, sentence):
        spoken.append(sentence)

    s._say_text = say_text
    return s, spoken


def test_step_one_restates_action_and_pushes_confirm_pending(capsys):
    s, spoken = real_pending_session()

    async def go():
        result = await s.call_device_tool("self.reboot", {"delay": 0})
        return json.loads(result)

    result = asyncio.run(go())
    try:
        assert result["needs_confirmation"] is True
        assert s.pending_confirm is not None
        assert s.pending_confirm["name"] == "self.reboot"
        assert s.pending_confirm["arguments"] == {"delay": 0}
        assert spoken == ["我要重启这台设备（延迟秒数=0），确认吗？"]
        assert s.ws.emotions() == ["shocked"]            # confirm-pending
        out = capsys.readouterr().out
        assert "[confirm] asking self.reboot" in out
        assert "[face] state confirm-pending -> shocked" in out
        assert "state speaking" not in out               # face, not voice, first
    finally:
        s._drop_pending()


def test_weak_agreement_on_real_pending_asks_again(capsys):
    s, spoken = real_pending_session()

    async def go():
        await s.call_device_tool("self.reboot", {"delay": 0})
        pending = s.pending_confirm
        # A real user answers after the prompt; the echo guard window is over.
        consumed = await s._resolve_confirm(s._confirm_prompt_end_at + 1.0,
                                            "没问题了")
        return pending, consumed

    pending, consumed = asyncio.run(go())
    try:
        assert consumed is True
        assert s.pending_confirm is pending              # kept
        assert spoken == [
            "我要重启这台设备（延迟秒数=0），确认吗？",
            "我要重启这台设备（延迟秒数=0），确认吗？",
        ]
        assert s.ws.emotions() == ["shocked"]            # no idle flash
        assert "[confirm] asking again" in capsys.readouterr().out
    finally:
        s._drop_pending()


def test_pending_timer_expires_and_pushes_idle(capsys):
    s, spoken = real_pending_session(confirm_timeout=0.02)

    async def go():
        await s.call_device_tool("self.reboot", {"delay": 0})
        await asyncio.sleep(0.1)

    asyncio.run(go())
    out = capsys.readouterr().out
    assert s.pending_confirm is None
    assert s.ws.emotions()[-1] == "idle"
    assert "state idle -> idle" in out
    assert "[confirm] expired self.reboot" in out


def test_pending_timer_is_cancelled_by_approval():
    s, spoken = real_pending_session()

    async def go():
        await s.call_device_tool("self.reboot", {"delay": 0})
        task = s._confirm_task
        # Approve with a stubbed tool call so the real MCP round-trip is skipped.
        async def fake_tool(name, arguments, timeout=None, confirmed=False):
            return '{"ok": true}'
        s.call_device_tool = fake_tool
        consumed = await s._resolve_confirm(s._confirm_prompt_end_at + 1.0,
                                            "确认")
        await asyncio.sleep(0.01)
        return task, consumed

    task, consumed = asyncio.run(go())
    assert consumed is True
    assert s.pending_confirm is None
    assert task.cancelled() or task.done()


# ---------------- LLM constraint (C2/C3 item 6) ----------------

def test_config_prompt_forbids_claiming_execution():
    prompt = CFG["llm"]["system_prompt"]
    assert "不要声称已经执行" in prompt
    assert "确认" in prompt and "取消" in prompt


def test_system_prompt_adds_pending_action_constraint():
    s, _ = real_pending_session()
    s.pending_confirm = {
        "name": "self.reboot", "arguments": {},
        "expires": time.perf_counter() + 60,
    }
    prompt = s._system_prompt()
    assert "不要声称它已经执行" in prompt
    assert "不要自己重复调用该工具" in prompt
    s.pending_confirm = None
    assert "不要声称它已经执行" not in s._system_prompt()


# ---------------- reviewer follow-ups (C2/C3 rev2) ----------------

class LoopWs(FakeWs):
    """A websocket that completes the handshake, then closes immediately."""

    def __init__(self):
        super().__init__()
        self.closed = False

    async def recv(self):
        return json.dumps({
            "type": "hello",
            "audio_params": {"sample_rate": 16000, "frame_duration": 60},
        })

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration

    async def close(self):
        self.closed = True


def test_disconnect_drops_pending(monkeypatch):
    """reviewer #1: a dead socket must not leave a pending action/timer behind."""
    session_mod = load_session()
    s, _ = real_pending_session()
    s.ws = LoopWs()
    cleared = []

    async def no_flush():
        return None

    monkeypatch.setattr(s, "_flush_notifications", no_flush)
    monkeypatch.setattr(session_mod, "build_vad", lambda *args, **kwargs: None)
    monkeypatch.setattr(session_mod, "_clear_confirm",
                        lambda: cleared.append(True))

    async def go():
        await s.call_device_tool("self.reboot", {"delay": 0})
        timer = s._confirm_task
        await s.run()
        return timer

    timer = asyncio.run(go())
    assert s.pending_confirm is None
    assert s._confirm_task is None
    assert timer.cancelled() or timer.done()
    assert cleared == [True]                 # proactive confirm deadline cleared
    assert s.alive is False


def test_weak_agreement_repushes_confirm_pending_after_barge():
    """reviewer #3: a barge startle must not survive the re-ask.

    C1a maps barge-in and confirm-pending to the same ``shocked`` look, so the
    frame need not be resent; the state must still be put back to confirm-pending
    (auditable in `_face_state` / the log) before the question is repeated.
    """
    s, spoken = real_pending_session()

    async def go():
        await s.call_device_tool("self.reboot", {"delay": 0})
        await s._push_state_face("barge-in")
        # The user answers after the prompt's echo window, so this is a real
        # (weak) answer and must be re-asked, not ignored as echo.
        return await s._resolve_confirm(s._confirm_prompt_end_at + 1.0,
                                        "没问题了")

    consumed = asyncio.run(go())
    try:
        assert consumed is True
        assert s.pending_confirm is not None
        assert s.ws.emotions() == ["shocked"]        # same look, one frame
        assert s._face_state == "confirm-pending"    # state restored for the re-ask
        assert spoken[-1] == "我要重启这台设备（延迟秒数=0），确认吗？"
    finally:
        s._drop_pending()


@pytest.mark.parametrize("key", [
    "password", "passwd", "pwd", "token", "secret", "api_key", "apikey",
    "api-key", "wifi_password", "access_token", "authorization",
    "密码", "令牌", "api密钥",
])
def test_sensitive_argument_keys_are_masked_when_spoken(key):
    """reviewer #4: credential values are never read out."""
    question = devtools.confirm_question("self.x", {key: "S3CRET"})
    assert "S3CRET" not in question
    assert "***" in question


def test_redacted_arguments_keeps_non_secret_values():
    redacted = devtools.redacted_arguments(
        {"ssid": "home", "password": "p", "volume": 60, "api_key": "k"})
    assert redacted == {"ssid": "home", "password": "***",
                        "volume": 60, "api_key": "***"}


def test_reconfigure_wifi_password_never_spoken_or_logged(capsys):
    """reviewer #4 end to end: the Wi-Fi password is not in the TTS text or logs."""
    s, spoken = real_pending_session()
    s.confirm_tools = {"self.system.reconfigure_wifi"}
    asyncio.run(s.call_device_tool("self.system.reconfigure_wifi",
                                   {"ssid": "home", "password": "hunter2"}))
    try:
        assert "hunter2" not in spoken[0]
        assert "***" in spoken[0] and "home" in spoken[0]
        out = capsys.readouterr().out
        assert "hunter2" not in out
        assert "[confirm] asking" in out and "***" in out
    finally:
        s._drop_pending()


def test_approved_log_redacts_sensitive_arguments():
    fake = FakeSession()
    fake.session.pending_confirm["arguments"] = {"password": "hunter2"}
    assert asyncio.run(fake.resolve("确认")) is True
    joined = " ".join(fake.logs)
    assert "hunter2" not in joined
    assert "***" in joined


def test_send_tool_call_log_redacts_sensitive_arguments(capsys):
    s, _ = real_pending_session()
    asyncio.run(s.send_tool_call("self.system.reconfigure_wifi",
                                 {"password": "hunter2"}))
    out = capsys.readouterr().out
    assert "hunter2" not in out
    assert "[mcp] call" in out and "***" in out


def test_disconnect_without_pending_keeps_other_confirm_deadline(monkeypatch):
    """A disconnecting session with nothing pending must not clear the global
    proactive confirm deadline (it belongs to whichever session asked)."""
    session_mod = load_session()
    s, _ = real_pending_session()
    s.ws = LoopWs()
    cleared = []

    async def no_flush():
        return None

    monkeypatch.setattr(s, "_flush_notifications", no_flush)
    monkeypatch.setattr(session_mod, "build_vad", lambda *args, **kwargs: None)
    monkeypatch.setattr(session_mod, "_clear_confirm",
                        lambda: cleared.append(True))

    asyncio.run(s.run())
    assert s.pending_confirm is None
    assert cleared == []


# ---------------- P0 echo guard (task-13) ----------------
# 2026-10-28: the board's mic heard its own confirm prompt and ASR'd 「确认。」,
# approving a real reboot. A confirm-shaped segment whose speech STARTED within
# `safety.confirm_echo_guard_ms` of the prompt's tts end is echo.

def echo_session():
    """FakeSession with a controlled prompt-end clock and the shipped guard."""
    fake = FakeSession()
    fake.session._confirm_prompt_end_at = 100.0
    fake.session.confirm_echo_guard_ms = 400.0
    return fake


def test_config_has_echo_guard_default():
    assert CFG["safety"]["confirm_echo_guard_ms"] == 400


def test_prompt_end_recorded_after_restatement():
    s, spoken = real_pending_session()

    async def go():
        await s.call_device_tool("self.reboot", {"delay": 0})

    asyncio.run(go())
    try:
        assert s._confirm_prompt_end_at is not None
        assert spoken == ["我要重启这台设备（延迟秒数=0），确认吗？"]
    finally:
        s._drop_pending()


@pytest.mark.parametrize("dt", [0.0, 0.02, 0.399])
def test_echo_confirm_inside_guard_is_ignored(dt):
    """tts_end+20ms 「确认」 is the board's own voice: no run, pending kept."""
    fake = echo_session()
    consumed = asyncio.run(
        fake.session._resolve_confirm(100.0 + dt, "确认。", seg_seconds=0.0))
    assert consumed is True
    assert fake.session.pending_confirm is not None
    assert fake.tool_calls == []
    assert fake.spoken == []                       # no run, no re-ask, no "done"
    line = " ".join(fake.logs)
    assert "[confirm] echo ignored dt=" in line
    assert "确认" in line


def test_echo_guard_boundary_is_400ms():
    """399 ms is echo, 401 ms is consent (config boundary)."""
    ignored = echo_session()
    asyncio.run(ignored.session._resolve_confirm(100.399, "确认",
                                                seg_seconds=0.0))
    assert ignored.tool_calls == []
    assert ignored.session.pending_confirm is not None

    allowed = echo_session()
    asyncio.run(allowed.session._resolve_confirm(100.401, "确认",
                                                seg_seconds=0.0))
    assert allowed.tool_calls == [("self.reboot", {"delay": 0}, True)]
    assert allowed.session.pending_confirm is None


def test_echo_guard_uses_segment_start_not_close_time():
    """Incident shape: segment closes 0.5 s after tts end but started ~50 ms in.

    VAD adds ~0.5 s hangover, so a close-time-only guard would have approved the
    real reboot. The segment length must be subtracted before comparing.
    """
    fake = echo_session()
    asyncio.run(fake.session._resolve_confirm(100.5, "确认。", seg_seconds=0.45))
    assert fake.tool_calls == []
    assert fake.session.pending_confirm is not None
    assert "echo ignored" in " ".join(fake.logs)


def test_real_user_confirm_after_guard_executes_once():
    fake = echo_session()
    consumed = asyncio.run(
        fake.session._resolve_confirm(100.9, "确认", seg_seconds=0.4))
    assert consumed is True
    assert fake.tool_calls == [("self.reboot", {"delay": 0}, True)]
    assert fake.session.pending_confirm is None
    assert fake.spoken == ["好，已经执行。"]


def test_real_user_weak_agreement_after_guard_asks_again():
    fake = echo_session()
    asyncio.run(fake.session._resolve_confirm(100.9, "好吧", seg_seconds=0.4))
    assert fake.session.pending_confirm is not None
    assert fake.tool_calls == []
    assert fake.spoken == ["我要重启这台设备（延迟秒数=0），确认吗？"]
    assert "asking again" in " ".join(fake.logs)


def test_real_user_cancel_after_guard_drops_pending():
    fake = echo_session()
    asyncio.run(fake.session._resolve_confirm(100.9, "取消", seg_seconds=0.4))
    assert fake.session.pending_confirm is None
    assert fake.tool_calls == []
    assert fake.spoken == ["好，不动了。"]


def test_prompt_tail_question_is_also_ignored_as_echo():
    """The prompt itself may come back as 「确认吗」; do not re-ask in the window."""
    fake = echo_session()
    asyncio.run(fake.session._resolve_confirm(100.2, "确认吗？", seg_seconds=0.15))
    assert fake.session.pending_confirm is not None
    assert fake.tool_calls == []
    assert fake.spoken == []
    assert "echo ignored" in " ".join(fake.logs)


def test_any_unrelated_text_inside_guard_is_ignored():
    """P0.1: shape is NOT checked inside the window - any non-empty segment is echo.

    Production transcribed the prompt as 「嗯刚是你那声音关了。」 and
    「就是出具体，我这测去呢。」; the old shape filter missed them and re-asked
    three times.
    """
    for text in ("今天天气不错", "嗯刚是你那声音关了。", "就是出具体，我这测去呢。"):
        fake = echo_session()
        consumed = asyncio.run(
            # Incident shape: segment closes 0.5 s after tts end, 0.45 s long,
            # so the speech started ~50 ms after the prompt.
            fake.session._resolve_confirm(100.5, text, seg_seconds=0.45))
        assert consumed is True
        assert fake.session.pending_confirm is not None
        assert fake.tool_calls == []
        assert fake.spoken == []                   # no re-ask, no "done"
        line = " ".join(fake.logs)
        assert "echo ignored" in line and "(any segment)" in line, line


def test_unrelated_text_after_guard_still_asks_again():
    """P0.1 must not over-block: outside the window the C2 re-ask path stays."""
    fake = echo_session()
    asyncio.run(fake.session._resolve_confirm(100.9, "今天天气不错",
                                             seg_seconds=0.4))
    assert fake.tool_calls == []
    assert fake.session.pending_confirm is not None
    assert fake.spoken == ["我要重启这台设备（延迟秒数=0），确认吗？"]
    assert "asking again" in " ".join(fake.logs)


@pytest.mark.parametrize("text", ["好吧", "取消"])
def test_echo_weak_or_cancel_inside_guard_is_ignored(text):
    """Inside the window even 好吧/取消 is echo: keep pending, do not re-ask."""
    fake = echo_session()
    asyncio.run(fake.session._resolve_confirm(100.5, text, seg_seconds=0.45))
    assert fake.session.pending_confirm is not None
    assert fake.tool_calls == []
    assert fake.spoken == []
    assert "(any segment)" in " ".join(fake.logs)


def test_handle_turn_passes_segment_seconds_to_echo_guard():
    """`_handle_turn` must pass the VAD segment length, not only its close time."""
    tree = ast.parse((ROOT / "src" / "session.py").read_text(encoding="utf-8"))
    calls = [node for node in ast.walk(tree)
             if isinstance(node, ast.Call)
             and getattr(node.func, "attr", "") == "_resolve_confirm"]
    assert calls
    assert any(any(kw.arg == "seg_seconds" for kw in call.keywords)
               for call in calls), "seg_seconds must reach _resolve_confirm"
