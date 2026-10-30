# ESP32 Voice Entry

[English](#english) | [中文](#中文)

A compact ESP32-S3 desk terminal that gives an agent **ears, eyes, and a voice**:
wake word, streaming ASR, LLM, streaming TTS, barge-in, camera vision, MCP device
tools, and a small paper-and-ink UI. The firmware is built from the open-source
XiaoZhi ESP32 project with a board configuration and persona UI; the intelligence
lives in a thin WebSocket server in this repository.

---

## English

### What it does

- **Voice loop**: wake word → VAD → streaming ASR → LLM → sentence-streamed TTS,
  with barge-in and a spoken confirmation gate for risky tools.
- **Device as an MCP server**: the board exposes photo, volume, brightness, theme,
  status, and screen tools over MCP.
- **Vision**: camera frames are posted to the local server and described by a
  local vision model.
- **UI**: six expression states, A/B/C information views, an idle dino strip, and
  a 480×320 dino game view.
- **Media**: agent-generated images and desktop screenshots can be shown
  full-screen on the device and dismissed by tap or timeout.
- **OTA**: the device discovers the local WebSocket endpoint through OTA.

### Repository layout

```text
src/protocol.py   Xiaozhi WS message shapes + MCP envelopes
src/audio.py      Opus codec, VAD, ASR wrappers
src/tts.py        local or cloud TTS backends
src/llm.py        OpenAI-compatible / Hermes client with streaming
src/session.py    per-connection pipeline, turn state machine, MCP calls
src/ota.py        OTA endpoint + aiohttp app
src/vision.py     camera sink, vision description, debug hooks
src/server.py     entrypoint
scripts/          fake device, MCP bridge, flashing and acceptance helpers
docs/             protocol, hardware, operations and handoff notes
```

### Quick start

```bash
cp config.example.yaml config.local.yaml   # fill local endpoints and keys
python3.13 -m venv .venv313
.venv313/bin/pip install -r requirements.txt
cd src && ../.venv313/bin/python server.py --config ../config.local.yaml
```

Default ports: `4410` for the voice WebSocket, `4411` for OTA, vision, and debug
endpoints. Device-facing paths are documented in `docs/device-capabilities.md`.

### Firmware

The firmware lives in a **separate repository** (the XiaoZhi fork) and must be
built there — `scripts/build.py` does not exist in this repo:

```bash
# run in the firmware repository, not here
source <esp-idf>/export.sh                        # ESP-IDF release/v6.1
export XIAOZHI_OTA_BASE=http://<server-ip>:4411   # injected at build time
python3 scripts/build.py chd/chd-esp32s3-box \
  --name chd-esp32s3-box-lcd35 --language zh-CN
```

Release assets differ by tag: **`v2.5.3-persona.4` is app-only** (`xiaozhi.bin`,
flashed at `0x20000`, plus a SHA-256 manifest); **`v2.5.3-persona.2`/`persona.3`
also ship `merged-binary.bin`** (full image at `0x0`, which erases NVS/Wi-Fi)
and `generated_assets.bin`. For an existing board, flash the app only; for a new
board use the merged image or build once from source. Step-by-step:
[`docs/quickstart-single-board.md`](docs/quickstart-single-board.md).

### Known limitations

- Validated on one ESP32-S3 board and 2.4 GHz Wi-Fi.
- The dino game view measures about 25 fps; the 30 fps target is not reached.
- Desktop capture requires the host's screen-recording permission.
- The project is a desk device, not a far-field speaker.

### Acknowledgements

This project stands on open-source work:

- [78/xiaozhi-esp32](https://github.com/78/xiaozhi-esp32) — firmware base,
  board framework, protocol and MCP foundations.
- [ESP-IDF](https://github.com/espressif/esp-idf), [LVGL](https://lvgl.io/),
  [ESP-SR](https://github.com/espressif/esp-sr) — embedded runtime, UI and
  wake-word engine.
- [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) and
  [Opus](https://opus-codec.org/) — local speech recognition and audio codec.
- The XiaoZhi community and the open-source projects that documented the
  protocol, MCP patterns and device workflows.

Thanks to the maintainers and contributors of these projects.

### License

MIT — see [LICENSE](LICENSE). Copyright belongs to the esp32-voice-entry
contributors. Upstream components retain their own licenses and attribution.

---

## 中文

### 项目简介

一个桌面级 ESP32-S3 语音终端：唤醒词、流式 ASR、LLM、流式 TTS、打断、摄像头
视觉、MCP 设备工具，以及一套纸墨风格的小屏 UI。固件基于开源的小智 ESP32
项目，加上板级配置和人格化界面；真正的智能逻辑在本仓库的轻量 WebSocket
服务端。

### 主要能力

- **语音闭环**：唤醒 → VAD → 流式 ASR → LLM → 按句流式 TTS，支持打断；
  高风险工具调用前有语音确认。
- **设备即 MCP 服务**：拍照、音量、亮度、主题、状态、屏幕等工具通过 MCP 暴露。
- **视觉**：摄像头画面上传到本机服务，由本地视觉模型描述。
- **界面**：六种表情状态、A/B/C 信息视图、空闲恐龙条、480×320 恐龙游戏视图。
- **媒体**：Agent 生成的图片和桌面截图可在设备上全屏显示，点击或超时关闭。
- **OTA**：设备通过 OTA 获取本机 WebSocket 地址。

### 快速开始

```bash
cp config.example.yaml config.local.yaml   # 填写本机端点与密钥
python3.13 -m venv .venv313
.venv313/bin/pip install -r requirements.txt
cd src && ../.venv313/bin/python server.py --config ../config.local.yaml
```

默认端口：`4410` 语音 WebSocket，`4411` OTA、视觉和调试接口。设备侧接口见
`docs/device-capabilities.md`。

### 固件

固件在**另一个仓库**（小智 ESP32 的 fork）里，必须到那边构建——本仓库没有
`scripts/build.py`：

```bash
# 在固件仓库执行，不是本仓库
source <esp-idf>/export.sh                        # ESP-IDF release/v6.1
export XIAOZHI_OTA_BASE=http://<server-ip>:4411   # 构建期注入 OTA 地址
python3 scripts/build.py chd/chd-esp32s3-box \
  --name chd-esp32s3-box-lcd35 --language zh-CN
```

发布资产按 tag 不同：**`v2.5.3-persona.4` 是 app-only**（只有 `xiaozhi.bin`，烧
`0x20000`，附 SHA-256 清单）；**`v2.5.3-persona.2`/`persona.3` 还带
`merged-binary.bin`**（整包，烧 `0x0`，会清 NVS/Wi-Fi）与 `generated_assets.bin`。
已有同款板升级只烧 app；新板可用整包或从源码构建一次。完整步骤见
[`docs/quickstart-single-board.md`](docs/quickstart-single-board.md)。

### 已知限制

- 目前只在一块 ESP32-S3 板和 2.4 GHz Wi-Fi 上验证。
- 恐龙游戏视图约 25 fps，尚未达到 30 fps。
- 桌面截图需要宿主系统授予屏幕录制权限。
- 定位是桌面设备，不是远场音箱。

### 致谢

本项目建立在以下开源工作之上：

- [78/xiaozhi-esp32](https://github.com/78/xiaozhi-esp32)：固件基础、板级框架、
  协议与 MCP 基础。
- [ESP-IDF](https://github.com/espressif/esp-idf)、[LVGL](https://lvgl.io/)、
  [ESP-SR](https://github.com/espressif/esp-sr)：嵌入式运行时、UI 与唤醒词引擎。
- [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx)、
  [Opus](https://opus-codec.org/)：本地语音识别与音频编解码。
- 小智社区，以及记录协议、MCP 模式和设备工作流的开源项目。

感谢这些项目的维护者和贡献者。

### 许可证

MIT，见 [LICENSE](LICENSE)。版权归 esp32-voice-entry 贡献者所有；上游组件保留
各自的许可证与署名。
