"""微信发送：固定动作白名单，纯键盘 + 剪贴板。

语音请求「给 X 发微信，说 Y」落到这里，变量只有两个：收件人、正文。
步骤严格按 skill `apple/wechat-desktop-messaging` 执行：

    1 open -b com.tencent.xinWeChat   打开并前置
    2 ⌘F → ⌘A → Delete               聚焦并清空搜索框
    3 ⌘V 粘收件人 → 回车             打开对话
    4 Esc → ⌘A → Delete              退出搜索、清空输入框
    5 ⌘V 粘正文 → ⌘A ⌘C 读回校验     必须等于正文
    6 回车 → ⌘A ⌘C 读回             必须为空 = 已发出

不截图、不看图、不读 AX、不问确认。微信 4.x 不暴露窗口内部结构，
所以收件人无法用快捷键校验，只能靠搜索框粘的是用户原话。
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
PREPARE = SCRIPTS / "wechat-prepare.applescript"
SEND_KEY = SCRIPTS / "wechat-send-key.applescript"

# 发消息意图：出现「微信」且带发送动词；「打开微信」不算
_SEND_WORDS = ("发", "说", "告诉", "打个招呼", "留言")
_NO_SEND = ("打开微信", "关掉微信", "退出微信")

_BOX_RE = re.compile(r"box=\[(.*)\]$", re.S)
_AFTER_RE = re.compile(r"found=(yes|no)")


def wants_send(text: str) -> bool:
    """这句话是不是「用微信给某人发点什么」。"""
    t = (text or "").strip()
    if "微信" not in t and "wechat" not in t.lower():
        return False
    if any(w in t for w in _NO_SEND):
        return False
    return any(w in t for w in _SEND_WORDS)


def parse_request(text: str) -> tuple[str | None, str | None]:
    """从口语句子里抽（收件人, 正文）。抽不到就返回 None，由调用方追问。"""
    t = (text or "").strip()
    who = None
    for pat in (
        r"(?:给|跟|向)\s*(.+?)\s*(?:发送|发)(?:一?条|一?个|个)?微信",
        r"发微信(?:给|到)\s*([^，,。；;]+)",
        r"发给\s*([^，,。；;]+?)\s*[，,。：:]",
    ):
        m = re.search(pat, t)
        if m:
            who = m.group(1).strip()
            break
    if who:
        who = re.split(r"[，,。；;：:]|说|打", who)[0].strip()
    if not who or len(who) > 20:
        return None, None

    body = None
    m = re.search(r"(?:内容是|内容|说|告诉(?:他|她|ta)?)\s*[：:,，]?\s*(.+)$", t)
    if m:
        body = m.group(1).strip().strip("。！!，,")
    if not body or body in ("打个招呼", "打招呼", "问个好"):
        body = "你好"
    return who, body


async def _osascript(script: Path, *args: str, timeout: float = 40.0) -> str:
    proc = await asyncio.create_subprocess_exec(
        "/usr/bin/osascript", str(script), *args,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    text = out.decode("utf-8", "replace").strip()
    if proc.returncode != 0:
        raise RuntimeError((err.decode("utf-8", "replace") or text)[:200])
    return text


async def send_message(who: str, body: str | None, log=None) -> dict:
    """发一条。返回 {ok, stage, chat, box}；stage 指出停在哪一步。"""
    say = log or (lambda *a, **k: None)
    body = (body or "").strip() or "你好"
    who = (who or "").strip()
    if not who:
        return {"ok": False, "stage": "no_recipient", "chat": "", "box": ""}

    # 步骤 1~5：搜索、打开、粘正文、读回校验（不一致重来一次，最多两次）
    box = ""
    for attempt in range(2):
        out = await _osascript(PREPARE, who, body)
        m = _BOX_RE.search(out)
        box = (m.group(1) if m else "")
        say("[wechat] prepare", attempt + 1, repr(box[:30]))
        if box.strip() == body:
            break
    if box.strip() != body:
        return {"ok": False, "stage": "type_mismatch", "chat": who, "box": box}

    # 步骤 6：回车发送，然后在会话里回读，确认这条真的进去了
    out2 = await _osascript(SEND_KEY, body)
    m2 = _AFTER_RE.search(out2)
    found = (m2.group(1) if m2 else "no")
    say("[wechat] after-send", found)
    if found != "yes":
        return {"ok": False, "stage": "not_sent", "chat": who, "box": ""}
    return {"ok": True, "stage": "sent", "chat": who, "box": ""}
