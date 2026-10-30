"""TTS providers. Each returns (int16 pcm, sample_rate) for one reply."""
import asyncio
import base64
import io
import json
import os
import time
import wave
from pathlib import Path

import aiohttp
import numpy as np
import sherpa_onnx

SF_URL = "https://api.siliconflow.cn/v1/audio/speech"

# ByteDance Volcano Engine / 豆包语音合成 2.0 (HTTP streaming, JSON lines of
# base64 PCM). Reference: house-ear src/rui/providers/volc_tts.py (MIT), read
# only - this repo keeps its own implementation instead of importing it.
VOLC_URL = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
VOLC_DEFAULT_VOICE = "zh_female_xiaohe_uranus_bigtts"   # 小荷 2.0
VOLC_DEFAULT_RESOURCE = "seed-tts-2.0"


def _env(name: str) -> str:
    """Env var first, then ~/.hermes/.env; an empty value counts as missing."""
    val = (os.environ.get(name) or "").strip()
    if val:
        return val
    env_file = Path.home() / ".hermes" / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith(name + "="):
                value = line.split("=", 1)[1].strip().strip('"').strip("'").strip()
                if value:
                    return value
    raise RuntimeError(f"{name} not set")


class MatchaTts:
    """Local, no network. 22.05 kHz output; caller resamples."""

    def __init__(self, model_dir: str, vocoder: str, speed: float = 1.05):
        d = Path(model_dir).expanduser()
        self.speed = speed
        self._tts = sherpa_onnx.OfflineTts(sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                matcha=sherpa_onnx.OfflineTtsMatchaModelConfig(
                    acoustic_model=str(d / "model-steps-3.onnx"),
                    vocoder=str(Path(vocoder).expanduser()),
                    lexicon=str(d / "lexicon.txt"),
                    tokens=str(d / "tokens.txt"),
                    dict_dir=str(d / "dict")),
                num_threads=2, provider="cpu"),
            rule_fsts=",".join(str(d / f) for f in ("phone.fst", "date.fst", "number.fst")),
            max_num_sentences=1))

    def _run(self, text: str):
        audio = self._tts.generate(text, sid=0, speed=self.speed)
        pcm = np.asarray(audio.samples, dtype=np.float32)
        return np.clip(pcm * 32767, -32768, 32767).astype(np.int16), audio.sample_rate

    async def synth(self, text: str):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._run, text)


class SiliconFlowTts:
    """CosyVoice2 over HTTP. 24 kHz wav."""

    def __init__(self, voice: str, model: str):
        self.voice = voice
        self.model = model
        self._key = _env("SILICONFLOW_API_KEY")

    async def synth(self, text: str):
        payload = {"model": self.model, "voice": self.voice, "input": text,
                   "response_format": "wav", "sample_rate": 24000}
        headers = {"Authorization": f"Bearer {self._key}"}
        async with aiohttp.ClientSession() as sess:
            async with sess.post(SF_URL, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"siliconflow {resp.status}: {await resp.text()}")
                raw = await resp.read()
        with wave.open(io.BytesIO(raw)) as w:
            rate = w.getframerate()
            pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        return pcm, rate


class VolcTts:
    """豆包语音合成 2.0 over the HTTP streaming endpoint.

    The endpoint answers with JSON lines; each frame carries base64 PCM at the
    requested rate. `synth()` collects the whole reply (the session then does
    its own sentence-level streaming), so it pays the full synthesis time
    before returning - unlike a chunk-by-chunk caller, which can start playing
    at ~0.6 s (rui measured 22 chars -> ttfb 0.58 s / 2.38 s audio).
    """

    def __init__(self, cfg: dict, api_key: str | None = None):
        volc = cfg.get("volc") or {}
        self.url = volc.get("base_url") or VOLC_URL
        self.voice = volc.get("voice") or VOLC_DEFAULT_VOICE
        self.resource_id = volc.get("resource_id") or VOLC_DEFAULT_RESOURCE
        self.sample_rate = int(volc.get("sample_rate", 16000))
        self.timeout = float(volc.get("timeout", 30))
        self.uid = str(volc.get("uid", "esp32-voice-entry"))
        self._api_key = api_key or _env(volc.get("api_key_env", "VOLC_API_KEY"))

    def _payload(self, text: str) -> dict:
        return {
            "user": {"uid": self.uid},
            "req_params": {
                "text": text,
                "speaker": self.voice,
                "audio_params": {"format": "pcm", "sample_rate": self.sample_rate},
            },
        }

    async def synth(self, text: str):
        headers = {
            "X-Api-Key": self._api_key,
            "X-Api-Resource-Id": self.resource_id,
            "Content-Type": "application/json",
        }
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        chunks = bytearray()
        done = False
        async with aiohttp.ClientSession(timeout=timeout) as sess:
            async with sess.post(self.url, json=self._payload(text),
                                 headers=headers) as resp:
                if resp.status != 200:
                    body = (await resp.read()).decode("utf-8", "replace")[:300]
                    raise RuntimeError(f"volc tts HTTP {resp.status}: {body}")
                while True:
                    raw = await resp.content.readline()
                    if not raw:
                        break
                    line = raw.decode("utf-8", "ignore").strip()
                    if not line:
                        continue
                    try:
                        frame = json.loads(line)
                    except ValueError:
                        continue
                    code = frame.get("code", 0)
                    if code == 20000000:
                        # Completion marker: keep its data (if any), then stop.
                        # A stream that closes without this marker is truncated
                        # - raise so FallbackTts re-synthesises the whole reply
                        # instead of playing half a sentence.
                        data = frame.get("data")
                        if data:
                            chunks.extend(base64.b64decode(data))
                        done = True
                        break
                    if code != 0:
                        raise RuntimeError(
                            f"volc tts code={code} message={frame.get('message')}")
                    data = frame.get("data")
                    if not data:
                        continue                    # heartbeat / empty frame
                    chunk = base64.b64decode(data)
                    if chunk:
                        chunks.extend(chunk)
        if not done:
            raise RuntimeError("volc tts stream ended before completion")
        if not chunks:
            raise RuntimeError("volc tts returned no audio")
        pcm = np.frombuffer(bytes(chunks), dtype=np.int16).copy()
        return pcm, self.sample_rate


class FallbackTts:
    """Run `primary`; on any failure/timeout run `fallback` instead.

    A dead TTS provider must never leave a turn silent: the fallback is built
    eagerly at startup (matcha is local), so switching costs no model-load time.

    After the first primary failure the primary is skipped for `cooldown_s`
    seconds: a streaming turn synthesises sentence by sentence, and 4 x a 9 s
    timeout + 4 WARN lines is worse than just using matcha for the rest of the
    turn. The cooldown also retries the cloud path later without a restart.
    """

    def __init__(self, primary, fallback, primary_name: str = "volc",
                 cooldown_s: float = 60.0):
        self.primary = primary
        self.fallback = fallback
        self.primary_name = primary_name
        self.cooldown_s = float(cooldown_s)
        self._broken_until = 0.0

    async def synth(self, text: str):
        if time.monotonic() < self._broken_until:
            return await self.fallback.synth(text)
        try:
            return await self.primary.synth(text)
        except Exception as exc:  # noqa: BLE001 - silence is worse than matcha
            self._broken_until = time.monotonic() + self.cooldown_s
            print(f"[tts] WARN {self.primary_name} failed "
                  f"({type(exc).__name__}: {exc}); falling back to matcha",
                  flush=True)
            return await self.fallback.synth(text)


def _build_matcha(cfg: dict) -> MatchaTts:
    m = cfg["matcha"]
    return MatchaTts(m["model_dir"], m["vocoder"], cfg.get("speed", 1.0))


def build_tts(cfg: dict):
    provider = cfg.get("provider", "matcha")
    if provider == "siliconflow":
        sf = cfg["siliconflow"]
        return SiliconFlowTts(sf["voice"], sf["model"])
    if provider == "volc":
        try:
            volc = VolcTts(cfg)
        except Exception as exc:  # noqa: BLE001 - missing key must not mute us
            print(f"[tts] WARN volc unavailable ({type(exc).__name__}: {exc}); "
                  f"falling back to matcha", flush=True)
            return _build_matcha(cfg)
        return FallbackTts(volc, _build_matcha(cfg))
    return _build_matcha(cfg)
