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

### Getting started (about 15 minutes)

One board from "nothing installed" to "wake it and ask the time". Everything in
angle brackets is **yours to fill in**; the first table lists each value.

#### 1. The values only you can supply

No working address, key or credential is stored in this repository. Every one of
these is a placeholder you replace:

| Placeholder | What it is | Where it goes |
|---|---|---|
| `<server-ip>` | LAN address of the machine running this server (the file spells it `<mac-lan-ip>`) | `config.local.yaml` → `server.ws_url` = `ws://<server-ip>:4410`, `server.vision_url` = `http://<server-ip>:4411/xiaozhi/vision`; also the OTA base you build or provision into the device |
| `<serial-port>` | the board's USB serial device | `python -m esptool -p <serial-port>`, `idf.py -p <serial-port>` |
| Wi-Fi SSID + password | **your 2.4 GHz** network | typed into the board's provisioning page (step 4); never committed |
| `DEEPSEEK_API_KEY` | LLM API key | exported in the shell that starts the server |
| `VOLC_API_KEY` | cloud TTS key, only when `tts.provider: volc` | exported in the same shell |
| `llm.provider` | which brain answers | `config.local.yaml`; the default `hermes` expects a local gateway at `http://127.0.0.1:8642/v1` and needs `HERMES_API_KEY` (or `API_SERVER_KEY`). Set `provider: deepseek` to use `DEEPSEEK_API_KEY` instead |
| `tts.matcha.model_dir` + `tts.matcha.vocoder` | local fallback TTS model and vocoder | `config.local.yaml`; **both files must exist even when `tts.provider: volc`**, because the fallback is constructed at startup |
| vision endpoint (optional) | local vision server for `take_photo` | `config.local.yaml` → `vision.base_url` (default `http://127.0.0.1:9981/v1`), `vision.model`, and `OMLX_API_KEY` or `~/.hermes/keys/omlx.key`; skip it if you do not use the camera |
| `vad.model`, `asr.model_dir` | absolute paths to the local models | `config.local.yaml` |
| control token | generated on first start at `~/.esp32-voice/control.token` | keep it; `/debug/*` and the vision endpoint require it as a bearer token |

Download commands for all three model sets (ASR, VAD, TTS matcha + vocoder) are in
[`docs/quickstart-single-board.md`](docs/quickstart-single-board.md) §3.3.

#### 2. Start the server

```bash
python3.13 -m venv .venv313
.venv313/bin/pip install -r requirements.txt
cp config.example.yaml config.local.yaml        # apply the table above
export DEEPSEEK_API_KEY=<your-key>
cd src && ../.venv313/bin/python server.py --config ../config.local.yaml
```

The minimum edits in `config.local.yaml` — the defaults do **not** start on their
own, because `llm.provider` defaults to a local Hermes gateway:

```yaml
server:
  ws_url: ws://<server-ip>:4410
  vision_url: http://<server-ip>:4411/xiaozhi/vision
llm:
  provider: deepseek          # default "hermes" needs a gateway on 127.0.0.1:8642
tts:
  provider: volc              # or "matcha"; the matcha files must exist either way
```

Expected first lines: `[ota] listening on http://0.0.0.0:4411/xiaozhi/ota/` and
`[ready] ws://0.0.0.0:4410`. Ports are **4410** (voice WebSocket) and **4411**
(OTA / vision / debug). Starting a second instance prints a single
`[fatal] port … already in use` line and exits instead of crash-looping.

#### 3. Put the firmware on the board

`esptool` ships with ESP-IDF, not with this repository's virtualenv, so load the
toolchain first in the shell that flashes:

```bash
source <esp-idf>/export.sh
```

`v2.5.3-persona.5` publishes `merged-binary.bin`, `xiaozhi.bin` and
`SHA256SUMS.txt`. Pick the row that matches your board:

| Situation | Command | What it changes |
|---|---|---|
| New or bricked board | `write-flash 0x0 merged-binary.bin` | full image; **erases NVS**, so Wi-Fi must be configured again |
| Board already running this firmware | `write-flash 0x20000 xiaozhi.bin` | app only; keeps NVS, Wi-Fi and the saved OTA URL |
| Only change the OTA server | `write-flash 0x9000 nvs-ota.bin` | NVS only; also erases the saved Wi-Fi credentials |

Prepend `python -m esptool --chip esp32s3 -p <serial-port> -b 460800` to each.
The public image bakes the placeholder `http://rui-ota.invalid:4411/xiaozhi/ota/`
(an RFC 2606 domain that never resolves), so no one's LAN address leaks — point
the device at your own server with step 5.

#### 4. Provision Wi-Fi

A board without credentials opens an open SoftAP named `Xiaozhi-XXXX` (the last
two MAC bytes). Join it and open `http://192.168.4.1/` — that is the access
point's own fixed address, independent of your LAN — then pick your 2.4 GHz
network and submit. If the connection times out, the board returns to this mode;
re-submitting is enough, no reboot needed.

The same page has an **Advanced** tab (`POST /advanced/submit`) where you can
set the OTA URL; it writes the NVS key `wifi/ota_url`. Use it **before**
submitting Wi-Fi: a successful submit posts `/exit`, the board leaves config
mode and the page is gone. There is no `/advanced` route of its own — open
`http://192.168.4.1/` and switch to the tab.

#### 5. Point the device at your server (choose one)

- the **Advanced** tab above, set before submitting Wi-Fi, or
- generate a 16 KB NVS image and flash it:

  ```bash
  source <esp-idf>/export.sh                       # provides IDF_PATH
  python3 scripts/make_nvs_ota.py --url http://<server-ip>:4411 --out nvs-ota.bin
  python -m esptool --chip esp32s3 -p <serial-port> -b 460800 write-flash 0x9000 nvs-ota.bin
  ```

  The script stores the complete endpoint (`/xiaozhi/ota/` is appended for you).
  Flashing `0x9000` erases NVS, so re-provision Wi-Fi afterwards.
- or build the firmware yourself with your own base (see *Firmware* below).

#### 6. Talk to it and check it is alive

Say the wake word (default `nihaoxiaozhi`, 「你好小智」). The board connects to
4410; the server log shows `[conn]`, `[asr]`, `[llm]`, `[tts]`.

```bash
lsof -nP -iTCP:4410 -iTCP:4411 -sTCP:LISTEN          # two listeners, one pid
TOK=$(cat ~/.esp32-voice/control.token)
curl -H "Authorization: Bearer $TOK" http://127.0.0.1:4411/debug/mute
```

If the board never connects, look for the `[ota]` line: a bare base without
`/xiaozhi/ota/` gets a 404 and the device retries. Wake-word and audio details are
in [`docs/quickstart-single-board.md`](docs/quickstart-single-board.md).

### Firmware

The firmware lives in a **separate repository** (the XiaoZhi fork) and must be
built there — `scripts/build.py` does not exist in this repo:

```bash
# run in the firmware repository, not here
source <esp-idf>/export.sh                        # ESP-IDF release/v6.1
python3 scripts/build.py chd/chd-esp32s3-box \
  --name chd-esp32s3-box-lcd35 --language zh-CN
```

**`XIAOZHI_OTA_BASE` is not expanded by this firmware tree**, even though
`main/boards/chd/chd-esp32s3-box/config.json` contains
`CONFIG_OTA_URL="${XIAOZHI_OTA_BASE}/xiaozhi/ota/"`: the build path passes the
string through untouched, so a plain build bakes the literal placeholder. Set
your address by rewriting the generated fragment **after** the last `build.py`
run and rebuilding from a clean configure — `build.py` regenerates that file on
every invocation, and `fullclean` deletes it, so the order matters:

```bash
python3 scripts/build.py chd/chd-esp32s3-box --name chd-esp32s3-box-lcd35 --language zh-CN
cp build/xiaozhi-build.sdkconfig.defaults /tmp/frag        # keep the generated options
idf.py fullclean
mkdir -p build
sed 's#${XIAOZHI_OTA_BASE}#http://<server-ip>:4411#' /tmp/frag > build/xiaozhi-build.sdkconfig.defaults
rm -f sdkconfig
idf.py -DIDF_TARGET=esp32s3 \
  -DSDKCONFIG_DEFAULTS="sdkconfig.defaults;build/xiaozhi-build.sdkconfig.defaults" \
  -DBOARD_NAME=chd-esp32s3-box-lcd35 reconfigure
idf.py build && idf.py merge-bin
strings -a build/xiaozhi.bin | grep -c 'XIAOZHI_OTA_BASE'      # must print 0
```

Or leave the image alone and write the NVS key `wifi/ota_url` (step 5). The full
recipe and partition table are in
[`docs/firmware-release.md`](docs/firmware-release.md).

Release assets: **`v2.5.3-persona.5` ships both `merged-binary.bin`** (full image
at `0x0`, erases NVS) **and `xiaozhi.bin`** (app at `0x20000`), plus a SHA-256
manifest. Older tags are gone — the repository history was rebuilt on
2026-10-30. For an existing board flash the app only; for a new board use the
merged image or build once from source. Step-by-step:
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

### 使用指导书（约 15 分钟）

从"什么都没装"到"唤醒它并问一句时间"。尖括号里的内容**都要你自己填**，
第一张表就是清单。

#### 1. 只有你能提供的信息

仓库里没有任何可用的地址、密钥或凭据；下面每一项都是占位符，需要你替换：

| 占位符 | 是什么 | 填在哪里 |
|---|---|---|
| `<server-ip>` | 跑本服务端那台机器的**局域网**地址（配置文件里写的是 `<mac-lan-ip>`） | `config.local.yaml` → `server.ws_url` = `ws://<server-ip>:4410`、`server.vision_url` = `http://<server-ip>:4411/xiaozhi/vision`；以及你给设备编入/写入的 OTA 基址 |
| `<serial-port>` | 板子的 USB 串口 | `python -m esptool -p <serial-port>`、`idf.py -p <serial-port>` |
| Wi-Fi 名称 + 密码 | **你家 2.4 GHz** 网络 | 在设备配网页输入（第 4 步）；**不要**写进仓库任何文件 |
| `DEEPSEEK_API_KEY` | 大模型 API Key | 启动服务端的那个 shell 里 `export` |
| `VOLC_API_KEY` | 云端 TTS Key，仅当 `tts.provider: volc` | 同一个 shell 里 `export` |
| `llm.provider` | 用哪个大脑回答 | `config.local.yaml`；默认 `hermes` 需要本地网关 `http://127.0.0.1:8642/v1` 和 `HERMES_API_KEY`（或 `API_SERVER_KEY`）。改成 `provider: deepseek` 则只需 `DEEPSEEK_API_KEY` |
| `tts.matcha.model_dir` + `tts.matcha.vocoder` | 本地兜底 TTS 模型与声码器 | `config.local.yaml`；**即使 `tts.provider: volc` 也必须存在**，因为兜底在启动时就会构建 |
| 视觉服务（可选） | 给 `take_photo` 做本地识图 | `config.local.yaml` → `vision.base_url`（默认 `http://127.0.0.1:9981/v1`）、`vision.model`，密钥 `OMLX_API_KEY` 或 `~/.hermes/keys/omlx.key`；不用摄像头可忽略 |
| `vad.model`、`asr.model_dir` | 本地模型的**绝对路径** | `config.local.yaml` |
| 控制 token | 首次启动自动生成在 `~/.esp32-voice/control.token` | 留着；`/debug/*` 与视觉接口要用它做 Bearer |

三套模型（ASR、VAD、TTS 的 matcha + 声码器）的下载命令都在
[`docs/quickstart-single-board.md`](docs/quickstart-single-board.md) §3.3。

#### 2. 启动服务端

```bash
python3.13 -m venv .venv313
.venv313/bin/pip install -r requirements.txt
cp config.example.yaml config.local.yaml        # 按上表逐项改
export DEEPSEEK_API_KEY=<your-key>
cd src && ../.venv313/bin/python server.py --config ../config.local.yaml
```

`config.local.yaml` 里**至少**要改这几项——默认配置不能直接跑，因为 `llm.provider`
默认指向本地 Hermes 网关：

```yaml
server:
  ws_url: ws://<server-ip>:4410
  vision_url: http://<server-ip>:4411/xiaozhi/vision
llm:
  provider: deepseek          # 默认的 hermes 需要 127.0.0.1:8642 上的网关
tts:
  provider: volc              # 或 matcha；两条 matcha 模型路径都必须存在
```

启动后应看到 `[ota] listening on http://0.0.0.0:4411/xiaozhi/ota/` 与
`[ready] ws://0.0.0.0:4410`。端口：**4410** 语音 WebSocket、**4411**
OTA / 视觉 / 调试。再起第二个实例只会打印一行
`[fatal] port … already in use` 然后退出，不会再刷 Traceback。

#### 3. 把固件刷到板上

`esptool` 随 ESP-IDF 提供，本仓库的虚拟环境里没有，所以刷机前先在同一个 shell 里加载工具链：

```bash
source <esp-idf>/export.sh
```

`v2.5.3-persona.5` 提供 `merged-binary.bin`、`xiaozhi.bin` 与 `SHA256SUMS.txt`。
按下表选一行：

| 情况 | 命令 | 影响 |
|---|---|---|
| 新板 / 救砖 | `write-flash 0x0 merged-binary.bin` | 整包；**清 NVS**，Wi-Fi 需重新配 |
| 板上已有同版本 | `write-flash 0x20000 xiaozhi.bin` | 只换 app；保留 NVS、Wi-Fi 与已存的 OTA 地址 |
| 只想改 OTA 服务器 | `write-flash 0x9000 nvs-ota.bin` | 只写 NVS；同样会清掉 Wi-Fi 凭据 |

每条前面加 `python -m esptool --chip esp32s3 -p <serial-port> -b 460800`。
公开镜像里编的是占位地址 `http://rui-ota.invalid:4411/xiaozhi/ota/`（RFC 2606
保留域名，永不解析），所以不会泄漏任何人的内网地址——用它自己的服务器请走第 5 步。

#### 4. 配网

没有保存 Wi-Fi 的板子会开一个**开放**热点，名为 `Xiaozhi-XXXX`（X 为 MAC 末两字节）。
连上后打开 `http://192.168.4.1/`（这是热点自己的固定地址，与你的局域网网段无关），
选你家 2.4 GHz 网络并提交。连接超时会自动回到这个模式，重新提交即可，不用重启。

同一个页面上有个 **Advanced** 标签（表单 `POST /advanced/submit`），可以填 OTA 地址，
会写进 NVS 的 `wifi/ota_url`。**一定要在提交 Wi-Fi 之前填**：提交成功后页面会 `POST /exit`、
设备退出配网模式，这个页面就没了。并不存在 `/advanced` 这个独立地址——打开
`http://192.168.4.1/` 再切到标签页。

#### 5. 让设备指向你的服务器（三选一）

- 配网页的 **Advanced** 标签（要在提交 Wi-Fi 之前填）；
- 生成 16 KB 的 NVS 镜像再刷：

  ```bash
  source <esp-idf>/export.sh                       # 提供 IDF_PATH
  python3 scripts/make_nvs_ota.py --url http://<server-ip>:4411 --out nvs-ota.bin
  python -m esptool --chip esp32s3 -p <serial-port> -b 460800 write-flash 0x9000 nvs-ota.bin
  ```

  脚本会自动补成完整端点（`/xiaozhi/ota/`）；刷 `0x9000` 会清 NVS，刷完要重新配网；
- 或者自己重编固件、把自己的地址编进去（见下面「固件」）。

#### 6. 跟它说话并确认链路

说唤醒词（默认 `nihaoxiaozhi`，即「你好小智」）。板子会连上 4410，服务端日志依次出现
`[conn]`、`[asr]`、`[llm]`、`[tts]`。

```bash
lsof -nP -iTCP:4410 -iTCP:4411 -sTCP:LISTEN          # 两个监听，同一个 pid
TOK=$(cat ~/.esp32-voice/control.token)
curl -H "Authorization: Bearer $TOK" http://127.0.0.1:4411/debug/mute
```

如果设备始终不连：先看 `[ota]` 那行——只写了基址、缺 `/xiaozhi/ota/` 会 404 并让设备
一直重试。唤醒词与音频细节见
[`docs/quickstart-single-board.md`](docs/quickstart-single-board.md)。

### 固件

固件在**另一个仓库**（小智 ESP32 的 fork）里，必须到那边构建——本仓库没有
`scripts/build.py`：

```bash
# 在固件仓库执行，不是本仓库
source <esp-idf>/export.sh                        # ESP-IDF release/v6.1
python3 scripts/build.py chd/chd-esp32s3-box \
  --name chd-esp32s3-box-lcd35 --language zh-CN
```

**这棵固件树不会展开 `XIAOZHI_OTA_BASE`**：虽然
`main/boards/chd/chd-esp32s3-box/config.json` 里写着
`CONFIG_OTA_URL="${XIAOZHI_OTA_BASE}/xiaozhi/ota/"`，构建路径是原样透传的，
直接编出来就是字面占位符。要改地址，必须在**最后一次 `build.py` 之后**重写生成的 fragment、再从干净配置重编——
`build.py` 每次运行都会重写这个文件，而 `fullclean` 又会把它删掉，所以顺序不能错：

```bash
python3 scripts/build.py chd/chd-esp32s3-box --name chd-esp32s3-box-lcd35 --language zh-CN
cp build/xiaozhi-build.sdkconfig.defaults /tmp/frag        # 先保存生成的选项
idf.py fullclean
mkdir -p build
sed 's#${XIAOZHI_OTA_BASE}#http://<server-ip>:4411#' /tmp/frag > build/xiaozhi-build.sdkconfig.defaults
rm -f sdkconfig
idf.py -DIDF_TARGET=esp32s3 \
  -DSDKCONFIG_DEFAULTS="sdkconfig.defaults;build/xiaozhi-build.sdkconfig.defaults" \
  -DBOARD_NAME=chd-esp32s3-box-lcd35 reconfigure
idf.py build && idf.py merge-bin
strings -a build/xiaozhi.bin | grep -c 'XIAOZHI_OTA_BASE'      # 必须是 0
```

或者不动镜像，改写 NVS 的 `wifi/ota_url`（第 5 步）。完整配方与分区表见
[`docs/firmware-release.md`](docs/firmware-release.md)。

发布资产：**`v2.5.3-persona.5` 同时提供 `merged-binary.bin`**（整包，烧 `0x0`，
会清 NVS）**与 `xiaozhi.bin`**（app，烧 `0x20000`），外加 SHA-256 清单。更早的
tag 已不存在——仓库历史在 2026-10-30 重建过。已有同款板升级只烧 app；新板用整包
或从源码构建一次。完整步骤见
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
