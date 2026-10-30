"""Spoken confirmation parsing for destructive device actions.

Deliberately free of aiohttp/numpy/model imports so the decision rule can be
unit-tested offline. `session.Session._resolve_confirm` is the only caller.

Two-step confirmation (C2/C3): the first step restates the pending action and
asks; only a later, explicit 「确认」/「确定」 (optionally with a filler suffix)
approves it. Weak agreement (「好吧」「可以吧」「没问题了」「就行」...) is
None: the caller keeps the pending action and asks again.

The pipeline is order-sensitive and deliberately asymmetric: a wrong "no" or
None only skips the action, a wrong "yes" runs reboot / firmware flash. So every
hedge, doubt, question or postponed answer is caught before any yes word.
"""
import re

# Negation always wins: one negative word turns the whole utterance into a
# refusal, so "别急着确认，先看看" can never be read as approval.
_NO_WORDS = ("不确认", "不确定", "不要", "不用", "不行", "不是", "不好", "不对",
             "取消", "算了", "先别", "停", "别", "否")

# "我不太确定", "我不建议执行", "我还没说可以": a negator within 3 chars of any
# yes word makes the whole sentence a refusal. Targets cover every explicit yes
# word plus the single-character ones, because "不可以" used to hit the explicit
# tier and really ran call_device_tool(confirmed=True).
# Known acceptable overreach (safe direction): "不好意思，确认" and "差不多可以"
# become no, since 不 is within reach of 好 / 可以.
_NEGATED_CONFIRM_RE = re.compile(
    r"(不|没|未|别|无法|不能)[^，。]{0,3}"
    r"(确认|确定|可以|执行|干吧|来吧|行吧|好的|没问题|好|是|对|行|来|干)")

# Step 4: yes word followed by rejection, "执行不了" / "确认个啥" /
# "可以个鬼". `你?` is a safety extension over the spec regex so "确认你个头"
# (listed by the reviewer) is caught too instead of falling through to the
# explicit yes tier.
_REJECTED_CONFIRM_RE = re.compile(
    r"(确认|确定|可以|执行|干吧|来吧|行吧|好的|没问题)你?"
    r"(不了|个屁|个头|个毛|才怪|个啥|个什么|个鬼|个锤子|个鸟)")

# Step 5: rhetorical question about the need to act at all.
# "这也要确认", "这还用执行", "还要执行", "那得执行".
_RHETORICAL_NEED_RE = re.compile(
    r"(这|那|还|也)[^，。]{0,4}(要|用|需要|得|让)[^，。]{0,2}"
    r"(确认|确定|执行)")

# Step 6: concessive stalling: "可以是可以", "行倒是行", "好是好".
_CONCESSIVE_RE = re.compile(r"(可以|行|好)倒?是")

# Step 7: hedge prefix before a yes word. The list is a closed set on purpose:
# hedge vocabulary is open-ended, so steps 8-10 add structural guards instead
# of trying to enumerate every Chinese hedge.
_HEDGED_YES_RE = re.compile(
    r"(好像|似乎|应该|大概|可能|也许|估计|恐怕|八成|兴许|或许|说不定|差不多|基本上)"
    r"[^，。]{0,3}"
    r"(确认|确定|可以|执行|干吧|来吧|行吧|好的|没问题)")

# Step 8: a sentence that opens with a question word is a question.
_LEADING_QUESTION_RE = re.compile(
    r"^(为什么|为啥|怎么|怎样|凭什么|何时|什么时候|是否|可否|能否|哪儿|哪里|谁|哪"
    r"|问一下|请教|请示)")

# Step 9: echo / rhetorical rejection: "谁让你确认的", "我什么时候说确认了",
# "确认什么确认", "确认啥", "执行啥". The second branch is a safety extension
# for the "确认什么确认" shape, which the spec's negator-first regex cannot
# match (什么 followed by 确认, not by 让/说/要/叫).
_ECHO_REBUTTAL_RE = re.compile(
    r"(谁|什么时候|哪|啥|什么)[^，。]{0,6}(让|说|要|叫)[^，。]{0,3}"
    r"(确认|确定|可以|执行)"
    r"|(确认|确定|可以|执行|没问题|好的)(什么|啥)")

# Step 9: postponing / sequencing — "等我确认", "改天确认", "晚一点执行",
# "确认无误后执行", "检查后执行". Semantics: not now, so keep pending. This list
# stays a guard (defence in depth); the template matcher in step 11 already
# refuses any such sentence because it is not exactly a yes word.
_POSTPONE_YES_RE = re.compile(
    r"(等|待|稍|晚|回头|改天|改日|明天|后天|今天|明早|明儿|下周|下个月"
    r"|以后|之后|过后|一会|过会|抽空|有空)"
    r"[^，。]{0,6}(确认|确定|可以|执行|干吧|来吧|行吧|好的|没问题)")
_AFTER_CONFIRM_RE = re.compile(
    r"(确认|确定|检查|核实)[^，。]{0,5}(后|再)[^，。]{0,5}(确认|确定|执行)")
_FIRST_THEN_RE = re.compile(r"(先|再)[^，。]{0,2}(确认|确定|执行)")

# Shared trailing-particle class. The template strips any number of these, so
# every guard below must allow them in any quantity too; otherwise "行了嘛呀"
# slips through with one particle and "我觉得行了" slips through with a prefix.
# 了 is included because the template also strips it: "对了了啊" would otherwise
# reduce to 对. 吧 is handled by the softer agreement guards.
_PARTICLES = "啊呀哦哈啦喽哟嘛咧了"

# Step 10: "那就好" / "这样行" / "这样好" are evaluations, not answers, and the
# template would strip the demonstrative away and approve them. At least one of
# 样/就 must be present, otherwise real agreements like 那好 / 那行 / 这好 (which
# the verifier requires to stay yes) would be blocked too.
# (样|就) is repeatable so "这样就行" / "这样就好" are covered too, and the tail
# tolerates the whole particle class (plus 的/吧) because the template strips
# them: without that, "那就好哦" / "这样行的" / "那就好的吧" still approve.
_DEMONSTRATIVE_EVAL_RE = re.compile(
    rf"^(这|那)(样|就)+(好|行|可以)[{_PARTICLES}的吧]*$")

# Step 10: trailing question markers and soft agreement. "吗"/"么" is the usual
# question tail; "能执行不" / "确认不" use a bare 不; "是吧" / "对吧" is a tag
# question without a question mark; "都可以" / "都行" is indifferent agreement.
_QUESTION_TAIL = ("吗", "么")
_QUESTION_MARKS = ("?", "？")
_A_NOT_QUESTION_RE = re.compile(r"(确认|确定|可以|执行|行|好|是|对)不$")
_SOFT_AGREEMENT_TAIL_RE = re.compile(r"(是|对)的?吧[啊呀]?$")
_ALL_FINE_RE = re.compile(r"(都|全都)[^，。]{0,2}(可以|行)$")
# "行了吧" / "确认了吧" / "对了吧": impatient or seeking-reassurance shape. The
# 了 is required; plain "行吧" / "好吧" no longer approve either (weak
# agreement, see _YES_WORDS), but the guard keeps this shape from being
# mistaken for consent if a yes word is ever added back.
_LE_BA_RE = re.compile(
    rf"(确认|确定|可以|执行|干吧|来吧|行吧|好的|没问题|是|好|行|对)了吧"
    rf"[{_PARTICLES}]*$")
# Fixed idioms: "对了" changes topic and "行了/好了/可以了/是了" ends the
# discussion. Anchored at the END only and tolerant of any leading context and
# any number of trailing particles, because the template strips prefixes and
# suffixes without limit ("我觉得行了", "哦对了", "那是了", "行了嘛呀").
_IDIOM_RE = re.compile(rf"(对了|行了|好了|可以了|是了)[{_PARTICLES}]*$")

# Step 10: a short yes word plus a call-off particle ("行啦", "好喽", "对哟",
# "行嘛", "那就行嘛") is someone ending the conversation, not agreeing to a
# destructive action. Unanchored on purpose: the template peels prefixes.
_CALLOFF_PARTICLE_RE = re.compile(
    rf"(行|好|可以|对|是)(啦|喽|哈|哟|咧|嘛)[{_PARTICLES}]*$")

# Thinking out loud / postponing: keep asking instead of acting.
_HEDGE_WORDS = ("让我", "我先", "我再", "等一下", "等等", "先看看", "再说",
                "不过", "但是", "可是", "我想想")
_CONFIRM_HEDGE_RE = re.compile(r"(确认|确定)一下")

# Yes words used by the guards above (regex targets). Kept separate from the
# template below: guards need to spot these words anywhere in a sentence.
_EXPLICIT_YES_WORDS = ("确认", "确定", "可以", "执行", "干吧", "来吧", "行吧",
                       "好的", "没问题")

# Step 11: the ONLY path to "yes" — whole-utterance template matching. Chinese
# hedges, deferrals and rhetorical questions are an open set, so no blacklist can
# keep up. Instead a sentence approves only when it is exactly an explicit yes
# word after stripping a closed set of fillers ("那就确认吧" -> 确认,
# "我觉得确定" -> 确定).
#
# C2/C3 (2026-10-28): yes is deliberately limited to 确认 / 确定. Weak agreement
# ("没问题了", "好吧", "可以吧", "就行", "好的", "行", "对", "可以", "执行",
# "没问题", "好", ...) is NOT consent to a destructive action: it is a None
# (keep pending, ask again), never a yes. The guards below still spot those
# words inside longer sentences so a hedge or a rejection keeps its "no"/None
# classification.
_YES_WORDS = ("确认", "确定")
_FILLER_PREFIXES = ("嗯", "哦", "啊", "呀", "那", "就", "这", "我", "觉得",
                    "我看", "当然", "肯定", "这样", "这么着", "这么")
# 啦/喽/哈 are deliberately NOT strippable: "行啦" / "行喽" is a call-off, not
# an affirmation, so they must never reduce to "行".
_FILLER_SUFFIXES = ("吧", "啊", "呀", "了", "的", "嘛", "哦")
# Question marks are NOT trimmed: "确认？" must stay a question (see step 10).
_PUNCT = "。，．.!！~～、"

# "嗯" is not in any table: a filler grunt alone is never an answer.


def _longest_match(text: str, words: tuple[str, ...]) -> str | None:
    """Longest keyword from `words` present in `text`, or None."""
    best = None
    for word in words:
        if word in text and (best is None or len(word) > len(best)):
            best = word
    return best


def _strip_fillers(text: str) -> set[str]:
    """All forms of `text` reachable by repeatedly stripping filler affixes.

    Breadth-first over single prefix/suffix removals, so both orders are seen
    ("那就干吧" -> 就干吧 -> 干吧, and 那就干 -> 就干).
    """
    seen = {text}
    queue = [text]
    while queue:
        current = queue.pop()
        for prefix in _FILLER_PREFIXES:
            if current.startswith(prefix) and len(current) > len(prefix):
                next_text = current[len(prefix):]
                if next_text not in seen:
                    seen.add(next_text)
                    queue.append(next_text)
        for suffix in _FILLER_SUFFIXES:
            if current.endswith(suffix) and len(current) > len(suffix):
                next_text = current[:-len(suffix)]
                if next_text not in seen:
                    seen.add(next_text)
                    queue.append(next_text)
    return seen


def _template_matches_yes(text: str) -> bool:
    """True only when the whole utterance reduces to a single yes word."""
    return any(candidate in _YES_WORDS for candidate in _strip_fillers(text))


# Weak-agreement words that used to approve before C2/C3. They are NOT consent,
# but they are confirm-shaped: an ASR result of one of them immediately after the
# prompt's TTS ends is the board's own voice (echo), not the user.
_WEAK_AGREEMENT_WORDS = ("可以", "执行", "干吧", "来吧", "行吧", "好的",
                         "没问题", "是", "好", "行", "对")


def is_weak_agreement(text: str) -> bool:
    """True when the utterance is weak agreement ("好吧"/"没问题了"/"好的").

    Used by `Session._resolve_confirm` only to recognise an echo-shaped
    utterance inside the TTS echo guard window; it never approves anything.
    """
    normalized = "".join(text.split()).strip(_PUNCT)
    return any(candidate in _WEAK_AGREEMENT_WORDS
               for candidate in _strip_fillers(normalized))


def classify_confirm(text: str) -> str | None:
    """Classify an utterance as "yes", "no", or None when it is unrelated.

    None means "this was not an answer to the confirmation question": the
    caller must keep the pending action and handle the text as a normal turn.
    """
    # The raw text is kept because a question mark anywhere makes the sentence a
    # question, and ASR may attach it to a phrase that is otherwise a yes word.
    raw = text
    # 1. ASR sometimes inserts spaces inside a word ("不 是"); trim edge
    #    punctuation so "确认！" reads like "确认" (question marks excluded).
    text = "".join(text.split()).strip(_PUNCT)
    # 2. Plain negation.
    if _longest_match(text, _NO_WORDS) is not None:
        return "no"
    # 3. Negated yes word ("不可以", "我不建议执行", "我还没说可以").
    if _NEGATED_CONFIRM_RE.search(text):
        return "no"
    # 4. Yes word followed by rejection ("执行不了", "可以个屁", "确认个啥").
    if _REJECTED_CONFIRM_RE.search(text):
        return "no"
    # 5. Rhetorical need ("这也要确认", "这还用执行", "那得执行") and
    #    concessive stalling ("可以是可以", "行倒是行", "好是好").
    if _RHETORICAL_NEED_RE.search(text) or _CONCESSIVE_RE.search(text):
        return None
    # 6. Hedged approval ("这好像可以吧", "估计可以", "恐怕没问题").
    if _HEDGED_YES_RE.search(text):
        return None
    # 7. A sentence that opens with a question word ("为什么执行", "怎么确认").
    if _LEADING_QUESTION_RE.search(text):
        return None
    # 8. Echo / rhetorical rejection ("谁让你确认的", "确认什么确认", "确认啥").
    if _ECHO_REBUTTAL_RE.search(text):
        return None
    # 9. Postponing / sequencing ("改天确认", "确认无误后执行", "检查后执行",
    #    "先确认", "再执行"): not now, keep pending.
    if (_POSTPONE_YES_RE.search(text) or _AFTER_CONFIRM_RE.search(text)
            or _FIRST_THEN_RE.search(text)):
        return None
    # 10. Questions ("可以吗", "能执行不", "确认不"), soft agreement ("是吧",
    #     "都可以") and thinking out loud ("让我确认一下", "不过我想想").
    if (any(mark in raw for mark in _QUESTION_MARKS)
            or text.endswith(_QUESTION_TAIL)
            or _A_NOT_QUESTION_RE.search(text)
            or _SOFT_AGREEMENT_TAIL_RE.search(text)
            or _ALL_FINE_RE.search(text)
            or _LE_BA_RE.search(text)
            or _IDIOM_RE.search(text)
            or _CALLOFF_PARTICLE_RE.search(text)
            or _DEMONSTRATIVE_EVAL_RE.search(text)
            or any(word in text for word in _HEDGE_WORDS)
            or _CONFIRM_HEDGE_RE.search(text)):
        return None
    # 11. The only path to "yes": whole-utterance template matching. Strip the
    #     closed set of fillers from both ends; the remainder must be exactly one
    #     yes word ("那就执行吧" -> 执行, "改天确认" -> not a yes word -> None).
    if _template_matches_yes(text):
        return "yes"
    # 12. No substring matching: a yes word buried anywhere in a sentence no
    #     longer approves it.
    # 13. Anything else is not an answer ("嗯" alone lands here too).
    return None
