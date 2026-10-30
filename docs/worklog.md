# Worklog

## 2026-10-21 - server MVP verified without hardware

Built the thin server (`src/`) and validated the whole pipeline with
`scripts/fake_device.py` over loopback. No board was touched.

Verified:

- hello handshake, 60 ms Opus frames both directions
- silero VAD segmenting a real 1.25 s question
- SenseVoice ASR 0.04-0.06 s
- DeepSeek flash reply 0.5-1.0 s
- matcha TTS 0.14 s for 2.5 s of audio
- multi-turn context in one connection ("那昨天呢" resolved against the
  previous answer)
- abort: mid-sentence `wake_word_detected` cancelled the turn after 19 frames
  instead of the full 50

Fixed during the session:

1. Clock injection per turn. Without it the model invented "下午三点四十二分"
   when the real time was 17:44.
2. Reply length capped at 120 chars on sentence boundaries (first attempt
   produced 113 frames / 6.8 s of speech).
3. `opuslib`'s `.bitrate` setter raises "invalid argument" on this build;
   leave the default VoIP bitrate.
4. Fake device must keep streaming silence. Stopping the stream stalls the
   server VAD forever, which looks like a 6 s server hang.
5. Port 4399 is the LX06 service on this host; this server binds 4410.

## 2026-10-21 (later) - firmware built and pointed at us

ESP-IDF 6.1 installed at `~/AI_Workspace/05_Tools/esp-idf-6.1`
(`~/.espressif` holds 8.5 GB of toolchains). Wrapper: `05_Tools/esp-idf-env.sh`
sources export.sh with `IDF_PYTHON_ENV_PATH` pinned - this Mac has Hermes'
3.14 and the system 3.9 ahead of the 3.12 venv the installer created, and
export.sh picks the wrong one otherwise.

Firmware built and verified:

```
python3 scripts/build.py chd/chd-esp32s3-box --name chd-esp32s3-box-lcd35 \
        --language zh-CN --wake-word nihaoxiaozhi
```

Confirmed in sdkconfig: `BOARD_TYPE_CHD_ESP32S3_BOX`, `CHD_ESP32S3_BOX_LCD_35`,
`USE_DEVICE_AEC`, `LANGUAGE_ZH_CN`, `SR_WN_WN9_NIHAOXIAOZHI_TTS`, 16 MB flash.
Artifact `merged-binary.bin` = 9.7 MB, whole-image, flash at 0x0.

The firmware's default OTA URL is `https://api.tenclass.net/xiaozhi/ota/`, so a
stock flash would have talked to the public XiaoZhi cloud and bypassed this
server entirely. Fixed two ways:

1. `src/ota.py` - answers the device's OTA POST on port 4411 with
   `{"websocket": {"url": "ws://<mac-lan-ip>:4410"}}` plus server time.
2. `CONFIG_OTA_URL` in sdkconfig rewritten to
   `http://<mac-lan-ip>:4411/xiaozhi/ota/`, rebuilt.

Verified in the binary: our URL present, `api.tenclass.net` count = 0.
Archived copy: `~/AI_Workspace/02_Archive/esp32-voice-firmware/chd-esp32s3-box-lcd35-20261021.bin`.

`idf.py` must be invoked as `python3 "$IDF_PATH/tools/idf.py"`; calling it
through the `idf.py` shim fails with a python-vs-python3 project mismatch.

Not done yet: tool layer (weather/news/HA), Hermes API Server, streaming TTS.

## 2026-10-26 - first hardware smoke (M1 done)

Board on the desk, one flash, zero parameter tuning. Wake word, ASR, LLM, TTS,
wake-word stripping, device volume over MCP and a real camera photo all work.
Detail and numbers: `docs/m1-smoke.md`.

Fixed during the session:

1. Homebrew Python 3.15 processes receive **no LAN inbound** on this Mac (TCP
   connects, HTTP hangs, loopback fine, ALF reports permitted). Use the uv 3.13
   env: `uv venv --python 3.13 .venv313`.
2. `opuslib` needs `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib` under 3.13.
3. `python -m src.server` cannot work (flat imports); run `cd src && python server.py`.
4. Old process holds 4411 for a few seconds after SIGTERM; wait 3-5 s before restart.
5. Wake word lands in ASR text (`你好，小志。`); strip prefix server-side, and a
   wake-only segment must not open a turn.
6. Device volume defaults low; set it with MCP `self.audio_speaker.set_volume`
   on handshake (persists in NVS).
7. The WS closes when the device goes idle, so out-of-band commands cannot reach
   it later - tools must be driven inside a turn (M2/M5).

Added: MCP initialize with `capabilities.vision.url`, `src/vision.py` camera sink
+ local Qwen3-VL description, `/debug/mcp` for bench testing, session registry.

## 2026-10-27 - M6 c/e/f/g, and a night lost to the wrong build command

**Shipped and measured on hardware**

- **Streaming TTS (c).** The model's sentences are synthesized and pushed as they
  complete. Four-sentence answer: audio starts at 2.96 / 4.69 / 10.5 s while the
  model is still generating; before, the whole reply had to arrive first (4.25 s
  then a 10 s block). DeepSeek is excluded from this path because it can emit
  `tool_calls` mid-text.
- **Dual channel (g).** Small talk → `deepseek-flash`, work → Hermes.
  `[route] fast` turn: LLM 0.51 s, first audio 0.94 s. `[route] agent` turn with
  an HA tool: 13.35 s, filler at 1.8 s. Router = task-word list + length + a
  pending confirmation always forces the agent.
- **Spoken confirmation (f).** The gate lives in `call_device_tool`, so it covers
  both the function-tool path and Hermes' MCP path. It asks out loud, stores the
  pending call for 120 s, executes only after 「确认」, and says so afterwards.
  Verified by temporarily adding `set_brightness` to `safety.confirm_tools`.

**Why notifications cannot be pushed over WebSocket (e)**

The firmware does implement `notify` (server pushes an Ogg Opus file, played while
idle, mic stays closed). It is unusable on this transport: after `tts stop` the
device returns to `Listening`, not `Idle` (`main/application.cc:642-650`), and
`notify` is only accepted in `Idle`. So while the audio channel is open every push
is dropped, which is why the official path uses MQTT. Shipped the honest fallback:
notifications queue and are spoken on the next connection (verified: push while
offline → wake → it says the queued line).

**Self-built firmware that boots but never wakes (root cause)**

Symptom: our own image loaded WakeNet (`detector: WakeNet`), logged the right model,
and still ignored the wake word; the vendor image on the same board woke instantly.

Cause: the image was built with a raw `idf.py build`, which never injects the board's
`sdkconfig_append`. The AFE came up with **1 channel and no AEC stage** instead of
2 channels and `AEC(FD_LOW_COST)`, so it was reading misaligned 4-slot TDM data.

```
BAD : AFE: Input PCM Config: total 1 channels(1 microphone, 0 playback)
GOOD: total 2 channels(1 microphone, 1 playback)
      |AEC(FD_LOW_COST, NLP_VERY_AGGRESSIVE)| -> |VAD| -> |WakeNet(wn9_nihaoxiaozhi_tts,)|
      I2S_IF: TDM: RX … total_slot: 4, slot_mask: 0x3
```

Fix: build with `python3 scripts/build.py chd/chd-esp32s3-box --name
chd-esp32s3-box-lcd35 --language zh-CN --wake-word nihaoxiaozhi`, with the board's
config.json carrying `CONFIG_USE_DEVICE_AEC`, `CONFIG_CHD_ESP32S3_BOX_LCD_35` and our
own `CONFIG_OTA_URL`. `build.py` needs the board **path** (`chd/chd-esp32s3-box`),
not the bare name, and its output flashes best with
`cd build && python3 -m esptool … write-flash "@flash_args"` (the `idf.py` shim
aborts on a python-vs-python3 mismatch after build.py configured the project).

**Screen experiment, rejected**

Built a glyph-rain overlay (canvas, dirty-cell invalidation, status band) and a
server-side renderer as a fallback. Two rendering bugs cost time and are worth
remembering: a canvas on `lv_layer_top()` is invisible to `lv_snapshot` (verification
showed the stock UI), and the panel port runs `swap_bytes=1`, so canvas pixels must
be byte-swapped or the rain renders magenta. It worked, and 9哥 rejected it on sight:
the 480x320 panel is too small for it. Reverted to the stock interface; the overlay
stays in the xiaozhi branch `feat/matrix-ui` and the server renderer stays unused.

**Also learned**

- Opening the serial port asserts DTR/RTS and **resets the board** — several
  "spontaneous reboots" were self-inflicted. Verify flash state by hashing the
  partition back (`read-flash`), not by watching the screen.
- `idf.py flash` rewrites the assets partition at 0x800000, so any hand-flashed
  assets (e.g. a factory bundle with the wake model) are wiped by the next flash.
- Screenshots come back as JPEG via MCP `self.screen.snapshot`; that is the only
  remote way to see the panel, and it only shows the active screen layer.
