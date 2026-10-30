"""LLM client. Streaming text, one interface for DeepSeek and Hermes."""
import asyncio
import json
import os
import time
from pathlib import Path

import aiohttp


def _env(name: str) -> str:
    val = os.environ.get(name)
    if val:
        return val
    env_file = Path.home() / ".hermes" / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError(f"{name} not set")


def _hermes_key() -> str:
    """Hermes API server bearer. One secret, two names: the gateway reads
    API_SERVER_KEY, our client historically looked for HERMES_API_KEY."""
    for name in ("HERMES_API_KEY", "API_SERVER_KEY"):
        try:
            return _env(name)
        except RuntimeError:
            continue
    raise RuntimeError("neither HERMES_API_KEY nor API_SERVER_KEY is set")


_ENDERS = "。！？!?\n"


def _sentence_cut(text: str) -> int | None:
    """Index just past the first sentence end, or None while it is still growing.

    Sentences shorter than 4 characters stay together so "好。" does not become
    its own TTS request.
    """
    for i, ch in enumerate(text):
        if ch in _ENDERS and i >= 3:
            return i + 1
    return None


class LlmReply:
    """One assistant turn: either text, or tool calls (or both)."""

    def __init__(self, content: str = "", tool_calls: list[dict] | None = None,
                 latency: float = 0.0):
        self.content = content
        self.tool_calls = tool_calls or []
        self.latency = latency

    def __repr__(self):
        return (f"LlmReply(text={self.content[:40]!r}, "
                f"calls={[c['name'] for c in self.tool_calls]})")


class Llm:
    """Returns an LlmReply; sets .last_latency for logging."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.provider = cfg.get("provider", "deepseek")
        if self.provider == "hermes":
            base = cfg["hermes"]["base_url"].rstrip("/")
            self.url = base + "/chat/completions"
            # Hermes API Server uses its own bearer; the key stays server-side and
            # is the same value the gateway reads from API_SERVER_KEY.
            self.key = _hermes_key()
            self.model = cfg["hermes"]["model"]
        else:
            self.url = "https://api.deepseek.com/chat/completions"
            self.key = _env("DEEPSEEK_API_KEY")
            self.model = cfg.get("model", "deepseek-flash")
        self.max_tokens = int(cfg.get("max_tokens", 400))
        self.last_latency = 0.0

    def _payload(self, messages, tools=None):
        body = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "temperature": 0.6,
            "max_tokens": self.max_tokens,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        if self.provider == "deepseek":
            body["thinking"] = {"type": "disabled"}
        return body

    async def hermes_info(self) -> dict:
        """Return backend identity/version without leaking the bearer."""
        if self.provider != "hermes":
            return {"ok": True, "provider": self.provider, "backend": self.provider}
        root = self.url.split("/v1/", 1)[0].rstrip("/")
        info = {"ok": True, "provider": "hermes", "backend": "hermes-agent",
                "model": self.model, "models": [], "version": None, "platform": None}
        try:
            async with aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=3)) as sess:
                async with sess.get(f"{root}/health",
                                    headers={"Authorization": f"Bearer {self.key}"}) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        info["version"] = data.get("version")
                        info["platform"] = data.get("platform")
                async with sess.get(f"{root}/v1/models",
                                    headers={"Authorization": f"Bearer {self.key}"}) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        info["models"] = [m.get("id") for m in data.get("data", [])
                                          if isinstance(m, dict) and m.get("id")]
                        if info["models"]:
                            info["model"] = info["models"][0]
        except Exception as exc:
            info["error"] = type(exc).__name__
        return info

    async def chat(self, messages, session_id: str, tools=None,
                   on_sentence=None) -> LlmReply:
        headers = {"Authorization": f"Bearer {self.key}",
                   "Content-Type": "application/json"}
        if self.provider == "hermes":
            headers["X-Hermes-Session-Id"] = session_id
        t0 = time.perf_counter()
        parts: list[str] = []
        pending = ""
        calls: dict[int, dict] = {}
        timeout = aiohttp.ClientTimeout(total=90, sock_read=45)
        async with aiohttp.ClientSession(timeout=timeout) as sess:
            async with sess.post(self.url, json=self._payload(messages, tools),
                                 headers=headers) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"llm {resp.status}: {await resp.text()}")
                async for raw in resp.content:
                    line = raw.decode("utf-8", "ignore").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        delta = json.loads(data)["choices"][0]["delta"]
                    except (KeyError, IndexError, json.JSONDecodeError):
                        continue
                    if piece := delta.get("content"):
                        parts.append(piece)
                        if on_sentence is not None:
                            pending += piece
                            while True:
                                cut = _sentence_cut(pending)
                                if cut is None:
                                    break
                                sentence, pending = pending[:cut], pending[cut:]
                                if sentence.strip():
                                    await on_sentence(sentence.strip())
                    for tc in delta.get("tool_calls") or []:
                        idx = int(tc.get("index", 0))
                        slot = calls.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["name"] += fn["name"]
                        if fn.get("arguments"):
                            slot["arguments"] += fn["arguments"]
        out: list[dict] = []
        for idx in sorted(calls):
            slot = calls[idx]
            try:
                args = json.loads(slot["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            out.append({"id": slot["id"] or f"call_{idx}", "name": slot["name"],
                        "arguments": args})
        if on_sentence is not None and pending.strip():
            await on_sentence(pending.strip())
            pending = ""
        self.last_latency = time.perf_counter() - t0
        return LlmReply("".join(parts).strip(), out, self.last_latency)
