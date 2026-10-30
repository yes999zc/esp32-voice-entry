"""Fake ESP32: handshake, stream wavs as Opus frames, record what comes back.

Usage:
    python scripts/fake_device.py --wav q1.wav [--wav q2.wav ...] [--save reply.wav]
    python scripts/fake_device.py --wav q1.wav --abort-after 1.0

--abort-after N sends an abort N seconds after the first TTS start, to check
that playback and the turn are actually cancelled.
"""
import argparse
import asyncio
import time
import json
import sys
import wave
from pathlib import Path

import numpy as np
import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from audio import OpusCodec, resample  # noqa: E402

SILENCE_BETWEEN = 1.5  # seconds; long enough for the server VAD to close a segment


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path)) as w:
        rate = w.getframerate()
        channels = w.getnchannels()
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    if channels > 1:
        pcm = pcm.reshape(-1, channels).mean(axis=1).astype(np.int16)
    return pcm, rate


async def run(args):
    codec = OpusCodec(16000, 60)
    buffers: list[np.ndarray] = []
    for path in args.wav:
        pcm, rate = read_wav(Path(path))
        buffers.append(resample(pcm, rate, 16000))

    reply_frames: list[bytes] = []
    speaking = asyncio.Event()
    finished = asyncio.Event()

    async with websockets.connect(args.url, max_size=1 << 20) as ws:
        await ws.send(json.dumps({
            "type": "hello", "version": 1, "features": {"mcp": False},
            "transport": "websocket",
            "audio_params": {"format": "opus", "sample_rate": 16000,
                             "channels": 1, "frame_duration": 60},
        }))
        hello = json.loads(await asyncio.wait_for(ws.recv(), 10))
        T0 = time.time()
        print(f"{time.time()-T0:6.2f} [hello]", hello.get("session_id", "?")[:8], flush=True)
        session_id = hello.get("session_id", "")

        async def wait_reply_done():
            """Wait for TTS to start (<=6 s) and then stop, like a quiet room."""
            for _ in range(60):
                if speaking.is_set():
                    break
                await asyncio.sleep(0.1)
            while speaking.is_set():
                await asyncio.sleep(0.1)
            await asyncio.sleep(0.3)

        async def push_silence(seconds: float):
            """A real device never stops streaming: VAD can only close on frames."""
            frames = int(seconds / 0.06)
            silence = codec.encode(np.zeros(960, dtype=np.int16))
            for _ in range(frames):
                await ws.send(silence)
                await asyncio.sleep(0.06)

        async def push():
            await ws.send(json.dumps({"session_id": session_id, "type": "listen",
                                      "state": "start", "mode": "auto"}))
            for i, pcm in enumerate(buffers):
                if i:
                    # Half-duplex like a real device, but keep streaming silence:
                    # without frames the server VAD can never close the segment.
                    await push_silence(args.gap)
                for frame in codec.frames(pcm):
                    await ws.send(frame)
                    await asyncio.sleep(0.06)
                print(f"{time.time()-T0:6.2f} [sent] turn {i+1}", flush=True)
            # keep streaming silence like a real device until the last reply ends
            for _ in range(int(args.timeout / 0.06)):
                if finished.is_set():
                    return
                for frame in codec.frames(np.zeros(960, dtype=np.int16)):
                    await ws.send(frame)
                await asyncio.sleep(0.06)

        async def pull():
            deadline = asyncio.get_running_loop().time() + args.timeout
            aborted = False
            replies = 0
            while True:
                left = deadline - asyncio.get_running_loop().time()
                if left <= 0:
                    return
                try:
                    msg = await asyncio.wait_for(ws.recv(), left)
                except asyncio.TimeoutError:
                    return
                if isinstance(msg, bytes):
                    reply_frames.append(msg)
                    continue
                data = json.loads(msg)
                kind = data.get("type")
                if kind == "stt":
                    print(f"{time.time()-T0:6.2f} [stt]", data.get("text"), flush=True)
                elif kind == "tts":
                    print(f"{time.time()-T0:6.2f} [tts]", data.get("state"), data.get("text", ""), flush=True)
                    if data.get("state") == "start":
                        speaking.set()
                        if args.abort_after and not aborted:
                            aborted = True
                            asyncio.create_task(abort_later(ws, session_id, args.abort_after))
                    if data.get("state") == "stop":
                        speaking.clear()
                        replies += 1
                        if replies >= len(buffers):
                            finished.set()
                            return

        await asyncio.gather(push(), pull())

    print(f"[done] reply frames={len(reply_frames)}", flush=True)
    if args.save and reply_frames:
        out = np.concatenate([codec.decode(f) for f in reply_frames])
        with wave.open(args.save, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(out.tobytes())
        print("[saved]", args.save, round(len(out) / 16000, 2), "s", flush=True)


async def abort_later(ws, session_id: str, delay: float):
    await asyncio.sleep(delay)
    print(f"[abort] after {delay}s", flush=True)
    await ws.send(json.dumps({"session_id": session_id, "type": "abort",
                              "reason": "wake_word_detected"}))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--wav", action="append", required=True)
    ap.add_argument("--url", default="ws://127.0.0.1:4410")
    ap.add_argument("--timeout", type=float, default=40)
    ap.add_argument("--gap", type=float, default=5.0)
    ap.add_argument("--abort-after", type=float, default=0)
    ap.add_argument("--save")
    asyncio.run(run(ap.parse_args()))
