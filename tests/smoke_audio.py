"""Offline smoke test: VAD segmentation, ASR, TTS, Opus round-trip. No network."""
import sys
import time
import wave
from pathlib import Path

import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from audio import Asr, OpusCodec, build_vad, pop_segments, resample  # noqa: E402
from tts import build_tts  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def read_wav(path: str):
    with wave.open(path) as w:
        rate, ch = w.getframerate(), w.getnchannels()
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    if ch > 1:
        pcm = pcm.reshape(-1, ch).mean(axis=1).astype(np.int16)
    return pcm, rate


def main(wav_path: str | None):
    cfg = yaml.safe_load(open(ROOT / "config.yaml"))
    codec = OpusCodec(16000, 60)

    if wav_path:
        pcm, rate = read_wav(wav_path)
        pcm = resample(pcm, rate, 16000)
        # A real device never stops streaming; pad so the VAD can close.
        pcm = np.concatenate([pcm, np.zeros(16000, dtype=np.int16)])
        vad = build_vad(cfg["vad"]["model"], cfg["vad"]["min_silence"],
                        cfg["vad"]["min_speech"], cfg["vad"]["max_speech"])
        t0 = time.perf_counter()
        segs = []
        for off in range(0, len(pcm), 960):  # feed per frame, not whole file
            vad.accept_waveform(pcm[off:off + 960].astype(np.float32) / 32768.0)
            segs += pop_segments(vad)
        print(f"vad: {len(segs)} segs in {time.perf_counter()-t0:.2f}s "
              f"{[round(len(s)/16000,2) for s in segs]}")
        asr = Asr(cfg["asr"]["model_dir"])
        for seg in segs:
            t1 = time.perf_counter()
            text = asr.transcribe(seg, 16000)
            print(f"asr {time.perf_counter()-t1:.2f}s: {text}")

        # Opus round-trip on the same audio
        frames = list(codec.frames(pcm))
        back = np.concatenate([codec.decode(f) for f in frames])
        print(f"opus: {len(frames)} frames, {len(back)} samples back "
              f"(in {len(pcm)})")

    tts = build_tts(cfg["tts"])
    t0 = time.perf_counter()
    audio, rate = __import__("asyncio").run(tts.synth("这是一次桌面语音助手的测试。"))
    print(f"tts: {time.perf_counter()-t0:.2f}s rate={rate} "
          f"{len(audio)/rate:.2f}s audio")
    pcm16 = resample(audio, rate, 16000)
    print(f"tts frames at 16k: {len(list(codec.frames(pcm16)))}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
