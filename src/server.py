"""WebSocket entrypoint for the ESP32 desktop terminal."""
import argparse
import asyncio
import signal
import time
from pathlib import Path

import yaml
from websockets.asyncio.server import serve

from audio import Asr, OpusCodec, resample
from llm import Llm
from session import Session, active_sessions
from tts import build_tts
import mute
import ota
import vision

ROOT = Path(__file__).resolve().parent.parent


def load_config(path: Path) -> dict:
    with open(path) as fh:
        return yaml.safe_load(fh)


async def main(config_path: Path):
    cfg = load_config(config_path)
    # The single mute truth: loaded before the first session can connect, then
    # injected into both the 4410 pipeline and the 4411 control handlers.
    mute_cfg = cfg.get("mute") or {}
    mute_state = mute.configure(
        path=mute_cfg.get("path"),
        log_interval_s=mute_cfg.get("log_interval_s", mute.DEFAULT_LOG_INTERVAL_S))
    t0 = time.perf_counter()
    codec = OpusCodec(cfg["audio"]["sample_rate"], cfg["audio"]["frame_ms"],
                      cfg["audio"]["channels"])
    asr = Asr(cfg["asr"]["model_dir"])
    tts = build_tts(cfg["tts"])
    llm = Llm(cfg["llm"])
    try:
        info = await llm.hermes_info()
        cfg["llm"]["hermes_version"] = info.get("version") or "unknown"
        cfg["llm"]["hermes_model"] = info.get("model") or cfg["llm"].get("model", "unknown")
    except Exception:
        cfg["llm"].setdefault("hermes_version", "unknown")
        cfg["llm"].setdefault("hermes_model", cfg["llm"].get("model", "unknown"))
    print(f"[init] backend version={cfg['llm']['hermes_version']}", flush=True)
    print(f"[init] models {time.perf_counter() - t0:.1f}s, "
          f"tts={cfg['tts']['provider']} llm={cfg['llm']['provider']}", flush=True)

    filler_cache = {}
    for phrase in cfg["conversation"].get("filler_phrases") or []:
        pcm, rate = await tts.synth(phrase)
        filler_cache[phrase] = resample(pcm, rate, cfg["audio"]["sample_rate"])
    if filler_cache:
        print(f"[init] filler ready: {list(filler_cache)}", flush=True)

    async def handler(ws):
        session = Session(ws, cfg, codec, tts, asr, llm, filler_cache=filler_cache,
                          mute=mute_state)
        print(f"[conn] {ws.remote_address}", flush=True)
        await session.run()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    control_token = ota.resolve_control_token(cfg)
    # The device expects the camera token on POST /xiaozhi/vision; empty config
    # means "reuse the control token" so no extra secret has to be managed.
    cfg["server"]["vision_token"] = ota.effective_vision_token(cfg, control_token)

    host, port = cfg["server"]["host"], cfg["server"]["port"]
    ota_runner = await ota.start(cfg,
                                extras=(vision.make_router(cfg, active_sessions, tts=tts,
                                                           resample=resample,
                                                           mute_state=mute_state),),
                                control_token=control_token)
    # The board spends most of its life in Wi-Fi modem sleep and answers a ping
    # hundreds of milliseconds late (measured 789-840 ms round trip against 5-10 ms
    # awake). The library defaults are 20 s / 20 s, which is fine for a laptop but
    # turns a sleepy device into a flapping connection; be generous instead.
    async with serve(handler, host, port, max_size=1 << 20,
                     ping_interval=30, ping_timeout=90):
        print(f"[ready] ws://{host}:{port}", flush=True)
        await stop.wait()
    await ota_runner.cleanup()
    print("[exit]", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    local_cfg = ROOT / "config.local.yaml"
    default_cfg = local_cfg if local_cfg.exists() else ROOT / "config.example.yaml"
    ap.add_argument("--config", default=str(default_cfg))
    args = ap.parse_args()
    asyncio.run(main(Path(args.config)))
