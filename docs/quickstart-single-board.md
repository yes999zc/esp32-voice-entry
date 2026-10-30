# 新人单板部署（chd-esp32s3-box）

> 目标读者：第一次拿到这块板、手上只有一台局域网主机的人。
> 范围：**一块 `chd-esp32s3-box`（480×320）+ 本仓库服务端**，从零到「能唤醒、能一问一答、能打断」。
> 编写日期：2026-10-30。文中标注 `[已核]` 的路径/命令/键都已在仓库里核对；`[未验证]` 表示没有仓库证据或在真机上未验证。

本仓库只包含**服务端**。固件在另一个仓库：小智 ESP32 的 fork，本文用
`<xiaozhi-repo>` 代指（本机布局是 `05_Tools/xiaozhi-esp32/`）。

---

## 1. 板子：这块 3.5" 480×320 屏只有一种配好的板型

`[已核]` 固件仓里唯一为这块 3.5" 屏配好的板型是 **`chd/chd-esp32s3-box`**，
它的 480×320 变体名是 **`chd-esp32s3-box-lcd35`**：

- 板级目录：`<xiaozhi-repo>/main/boards/chd/chd-esp32s3-box/`（`config.json` + 板级 `.cc`）
- 变体声明：`<xiaozhi-repo>/main/boards/chd/chd-esp32s3-box/config.json:13`
- 列出所有板型/变体（只读命令）：
  ```bash
  cd <xiaozhi-repo>
  python3 scripts/build.py --list-boards          # 应能看到 chd/chd-esp32s3-box
  ```

### 怎么确认你手上是同款

`[已核]` 同时满足这三条即可按本文走：

1. 屏幕是 **3.5" ST7796、480×320**（`docs/device-capabilities.md:99`，来自 `self.screen.get_info`）。
2. 触摸是 **FT6336**（`docs/device-capabilities.md:100`）。
3. 设备启动后 MCP `serverInfo.name` 报 **`chd-esp32s3-box-lcd35`**（设备 `MCP: initialize` 回执；串口日志里也能看到）。

```bash
# 可选：设备在线时读一次屏幕分辨率（需要 control token，首次启动会自动生成）
TOK=$(cat ~/.esp32-voice/control.token)
curl -s -H "Authorization: Bearer $TOK" -H 'Content-Type: application/json' \
  -d '{"name":"self.screen.get_info","arguments":{}}' http://<server-ip>:4411/debug/mcp
```

### 不是这块板怎么办（先查列表，别急着新建）

`[已核]` 固件仓已带**不少 ESP32-S3 现成板**（`python3 scripts/build.py --list-boards` 实测；
例：`quandong/esp32-s3-spi-4.0` = ST7796S 320×480 + FT6336U，另有
`quandong/esp32-s3-spi-2.8`、`quandong/esp32-s3-qspi-3.5`、`bread-compact-esp32*`、
`alientek/atk-dnesp32s3*` 等）：

1. 先跑 `--list-boards`；**列表里已有的，直接用对应 board 名**（必要时用 `--name` 选变体）。
2. 只有列表里**没有**你的屏/触摸组合时，才新建 `main/boards/<manufacturer>/<type>/` 目录，
   写 `config.json` 声明 `target`/`builds`/`sdkconfig_append`，并按屏/触摸/音频/摄像头实现或
   复用板级类——**不是改参数**。入口和示例都在 `<xiaozhi-repo>/main/boards/`；教程不在本文范围。

---

## 2. 固件：新板烧整包（`0x0`），老板只烧 app（`0x20000`）

### 为什么不能直接用 release 的 `xiaozhi.bin`

`[已核]`（`gh release view -R yes999zc/xiaozhi-esp32` 实测）：

| release | 资产 | 用法 |
|---|---|---|
| `v2.5.3-persona.4`（最新） | **`merged-binary.bin` 10164189 B（2026-10-30 追加，`0x0` 整包）+ `xiaozhi.bin` 2921264 B（10-28 的 app-only，未改）+ `SHA256SUMS.txt`（两行）** | 新板烧 `0x0` 整包；已有同款板只升级 app 烧 `0x20000` |
| `v2.5.3-persona.2` | `merged-binary.bin` 10164189 B（整包）、`generated_assets.bin` 1775581 B、`xiaozhi.bin` **2920928 B**、`SHA256SUMS` | 已有同款板升级只烧 app；**新板可直接整包**（或从源码构建） |
| `v2.5.3-persona.3` | 同布局：`merged-binary.bin`（整包）、`generated_assets.bin`、`xiaozhi.bin` **2921072 B**、`SHA256SUMS` | 同上 |

- `[已核]` 整包由 `<xiaozhi-repo>/scripts/build.py` 的 `merge_bin()`（`:81-83`）生成（本地
  `build/merged-binary.bin` 头部 `E9 03 …`，即 bootloader image，可 `0x0` 整包烧）。
  **它会清 NVS/Wi-Fi**：整包覆盖 `0x0`–`0x9B17DD`，其中 NVS 分区 `0x9000`–`0xD000` 全是 `0xFF`
  （`[已核]` 实测该区间 16384 字节里非 `0xFF` 的字节数为 **0**），烧完设备要重新配网。
- `[已核]` 只烧 app 时，新板仍缺 bootloader（`0x0`）、分区表（`0x8000`）、字体/表情资源分区
  （`<xiaozhi-repo>/build/bootloader/bootloader.bin`、`build/partition_table/partition-table.bin`、
  `build/generated_assets.bin`）→ **只烧 app 不会启动**；只适合「已经跑着同款固件、只换 app」。

`[已核]` **镜像里的 OTA 地址**（两个资产不一样，别混）：

- 整包 `merged-binary.bin` 编进去的是占位域名 `http://rui-ota.invalid:4411/xiaozhi/ota/`
  （`strings -a` 命中 1 次；无任何内网 IP，也无未展开的 `${XIAOZHI_OTA_BASE}` 字面量）。
- app-only `xiaozhi.bin`（10-28 的旧构建，本次没动）编进去的是**未展开的字面量**
  `${XIAOZHI_OTA_BASE}/xiaozhi/ota/`（`strings -a` 命中 1 次）——只烧它 OTA 一定失败。

要指向你自己的服务端，三条路都**不用改源码**：①烧整包后用 NVS/配网高级页覆盖 `ota_url`；
②重编时给 `XIAOZHI_OTA_BASE`（注意本分支 `scripts/build.py` 的构建路径不展开该占位，需按
`docs/firmware-release.md` 的 factory 一节操作）；③用 `scripts/make_nvs_ota.py` 生成 NVS 镜像刷
`0x9000`。设备运行期优先读 NVS `wifi/ota_url`（`main/ota.cc:56-62`），所以①③对两种镜像都有效。

### 第一次上板：三种烧写方式

`idf.py flash` 的**前提**（`[已核]`）：必须在**这个变体**配好的仓库/`build` 目录下——即已经用
`python3 scripts/build.py chd/chd-esp32s3-box --name chd-esp32s3-box-lcd35` 配过
`IDF_TARGET=esp32s3` 与 `BOARD_NAME`；否则 `build/flash_args` 指向别的板子/别的 app。先自检：

```bash
cd <xiaozhi-repo>
grep -E '^CONFIG_IDF_TARGET=|^CONFIG_CHD_ESP32S3_BOX_LCD_35=y' sdkconfig   # 期望 esp32s3 / =y
cat build/flash_args                                                      # 期望含 0x20000 xiaozhi.bin
```

**A. 新板/救砖（推荐默认）：`0x0` 一次烧整包（会清 NVS）**

```bash
# 用 release 资产（无需本地构建）
curl -LO https://github.com/yes999zc/xiaozhi-esp32/releases/download/v2.5.3-persona.4/merged-binary.bin
shasum -a 256 merged-binary.bin    # 对比 SHA256SUMS.txt 第一行
python -m esptool --chip esp32s3 -p <serial-port> -b 460800 write-flash 0x0 merged-binary.bin
```

**B. 已有同款板：只换 app（`0x20000`，不动 NVS/Wi-Fi）—— 不是默认推荐**

```bash
python -m esptool --chip esp32s3 -p <serial-port> -b 460800 write-flash 0x20000 xiaozhi.bin
# 或者本地构建后：cd <xiaozhi-repo> && idf.py -p <serial-port> flash   （按 build/flash_args 全量写）
```

> ⚠️ `[已核]` 线上这个 app 资产（`xiaozhi.bin` 2921264 B，sha256 `63c9f7e5…4728de4`）里编的是**未展开的
> 字面量** `${XIAOZHI_OTA_BASE}/xiaozhi/ota/`：只烧它、且设备 NVS 里没有 `ota_url` 时 **OTA 必失败**
> （设备会拿这个坏 URL 去请求）。只有两种正确用法：先按下面 **C** 写好 NVS `ota_url`，或烧你自己
> 重编的 app（见本节末尾「构建命令」）。**B 是「换 app」的手段，不是省事的默认路径。**

**C. 只改 OTA 地址：写 NVS 分区 `0x9000`（会清 NVS，需重新配网）**

```bash
# 在服务端仓库执行；需要已 source ESP-IDF（读 IDF_PATH）
python3 scripts/make_nvs_ota.py --url http://<server-ip>:4411 --out /tmp/nvs-ota.bin
python -m esptool --chip esp32s3 -p <serial-port> -b 460800 write-flash 0x9000 /tmp/nvs-ota.bin
# 刷完进配网（§3.5）重连 Wi-Fi；ota_url 已在 NVS 里，重启后生效
```

`[已核]` 固件把 NVS 里的值**当作完整 URL 直接用**（`main/ota.cc:56-62` 原样返回、不拼路径），
而服务端只注册了 `/xiaozhi/ota/`（`src/ota.py:180-181`），所以脚本会**规范化**：
给 base（无 path 或只有 `/`）→ 补成 `<base>/xiaozhi/ota/`；给完整端点 → 原样存。
实测两次输入 `--url http://<server-ip>:4411` 与 `--url http://<server-ip>:4411/xiaozhi/ota/`
生成的镜像**字节相同**（sha256 一致）。

### 构建命令（在固件仓库执行，不在本仓库）

`[已核]` 依赖 **ESP-IDF `release/v6.1`（最低 v6.0.1）**（`<xiaozhi-repo>/README.md:28`）；
`scripts/build.py` 的参数以 `--help` 为准（`board` 位置参数 + `--name/--language/--wake-word` 等）。

> ⚠️ **动手前先读这条**（`[已核]`）：在 `9b22121` 上 `export XIAOZHI_OTA_BASE=…` **不生效**——
> `scripts/build.py` 的 `_expand_ota_base()`（`:412-415`）只在 `--list-boards`/option 定义路径
> （`:509`、`:977`）被调用，真正构建用的是未展开的 `sdkconfig_append`（`:1577-1596`）；
> ESP-IDF Kconfig 也不展开 `${...}`（实测：带环境变量 reconfigure 后 `sdkconfig` 仍是字面量）。
> **下面的命令块只负责「装环境 + 配好板型 + 编出 app」，编出来的 `CONFIG_OTA_URL` 是字面量占位。**
> 要让镜像带上你自己的地址，二选一：
>
> - **① 重编（要改镜像）**：按 `docs/firmware-release.md`「如何产出 factory 镜像（0x0 一次烧）」的
>   fragment 展开法 —— 跑完下面命令后改 `build/xiaozhi-build.sdkconfig.defaults` 里的 `CONFIG_OTA_URL` 行 →
>   `rm sdkconfig` → `reconfigure` + `build` + `merge-bin`，并用那里给的 `grep`/`strings` 断言确认。
> - **② 不重编（改设备 NVS）**：镜像保持原样，用上面 **C**（`scripts/make_nvs_ota.py` 刷 `0x9000`）
>   或配网高级页 `/advanced` 写 `wifi/ota_url`；运行期优先读 NVS（`main/ota.cc:56-62`）。

```bash
# 0) 环境（一次性）
#    ESP-IDF v6.1：安装后每个新 shell 先 source 它的 export.sh
source <esp-idf>/export.sh

# 1) 进入"固件仓库"（不是本仓库）
cd <xiaozhi-repo>

# 2) 构建 480×320 变体（zh-CN，唤醒词默认 nihaoxiaozhi）
python3 scripts/build.py chd/chd-esp32s3-box \
  --name chd-esp32s3-box-lcd35 --language zh-CN

# 产物：build/xiaozhi.bin（app），同目录还有 bootloader / partition-table / generated_assets
# 注意：这一份的 CONFIG_OTA_URL 是未展开占位；要自己的地址请看上面的 ① / ②
```

`[已核：本机 IDF 6.1]` 用分支 `9b22121` 跑上面的命令 → exit 0，产出 `build/xiaozhi.bin`（app）与
`build/merged-binary.bin` 10164189 B；但镜像里是**字面量** `${XIAOZHI_OTA_BASE}/xiaozhi/ota/`。
上文提到的 2921280 B / 命中 `rui-ota.invalid` 的那份 A 版，是**再做了一步 fragment 展开**才得到的
（不是这条命令的直接产物）；把它当成「①②之后的产物」看。

---

## 3. 服务端：复制示例配置并逐项改

### 3.1 环境与启动

`[已核]` Python **3.13**（`README.md:48`）；依赖含 `sherpa-onnx`（`requirements.txt`）。

```bash
cd <repo>
python3.13 -m venv .venv313
.venv313/bin/pip install -r requirements.txt
cp config.example.yaml config.local.yaml
# 编辑 config.local.yaml（见 3.2）
cd src && ../.venv313/bin/python server.py --config ../config.local.yaml
```

`[已核]` 默认端口：**4410** 语音 WebSocket、**4411** OTA/视觉/调试（`config.example.yaml:3-4`）。

### 3.2 `config.local.yaml` 必改项

| 键（`config.example.yaml` 行号） | 新人要改成 | 说明 |
|---|---|---|
| `server.ws_url`（:5） | `ws://<server-ip>:4410` | 设备连的 WS 地址 |
| `server.vision_url`（:6） | `http://<server-ip>:4411/xiaozhi/vision` | 拍照上传地址（不用视觉可留空） |
| `security.control_token_file`（:18） | 保持默认 | 首次启动自动生成 32 字节 token（0600） |
| `vad.model`（:44） | `<user-home>/AI_Workspace/03_Data/Models/sherpa-onnx/silero_vad.onnx` | **绝对路径**；文件见下 |
| `asr.model_dir`（:58） | `<user-home>/AI_Workspace/03_Data/Models/sherpa-onnx/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17` | **绝对路径**；目录见下 |
| `llm.provider` / `llm.model`（:82-83） | `deepseek` / `deepseek-flash` | 默认 `hermes` 指向 `127.0.0.1:8642`，新人没有 |
| `tts.provider`（:61） | `volc` 或 `matcha` | 二选一，见 3.4 |
| `conversation.barge_in`（:120） | `true`（默认） | 验收第 5 条要它 |

### 3.3 模型从哪下、放哪

**ASR（SenseVoice）** `[已核]` 走 hf-mirror：

```bash
# 仓库：csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17
# 已核 hf-mirror 可访问（API 200），目录含 model.int8.onnx / tokens.txt 等
HF_ENDPOINT=https://hf-mirror.com \
  hf download csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17 \
  --local-dir <user-home>/AI_Workspace/03_Data/Models/sherpa-onnx/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17
```

- `[未验证]` `hf` CLI（`huggingface_hub`）本身的可用性；备选：`git clone https://hf-mirror.com/<repo>` 后把目录放到同一路径。
- `[已核]` 目录名必须与 `asr.model_dir` 完全一致；本地已有该目录时可直接用。

**VAD（Silero）** `[未验证]`：

- 需要单个文件 `silero_vad.onnx`。`[已核]` hf-mirror 上**没有**与 sherpa-onnx 完全对应的
  官方仓库（`csukuangfj/sherpa-onnx-vad` 返回 401；`onnx-community/silero-vad` 提供的是
  `onnx/model.onnx`，未验证与 sherpa-onnx VAD 的输入/输出兼容）。
- 可靠来源是 sherpa-onnx 的 GitHub `asr-models` release 里的 `silero_vad.onnx`（本机文件
  643854 B 即此文件），下载后放到 `<user-home>/AI_Workspace/03_Data/Models/sherpa-onnx/silero_vad.onnx`。
- 若你已能访问 HuggingFace 镜像，也可自行转存该文件；**不要把 `onnx-community` 的
  `model.onnx` 直接改名当成 `silero_vad.onnx`**，除非你验证过它能被 sherpa-onnx 加载。

### 3.4 LLM 与 TTS

**LLM** `[已核]`：

```yaml
llm:
  provider: deepseek
  model: deepseek-flash
```

```bash
export DEEPSEEK_API_KEY=<your-key>    # src/llm.py:77-79 读取
```

**TTS 二选一** `[已核]`：

- 云端 volc：`tts.provider: volc` + `export VOLC_API_KEY=<your-key>`（`config.example.yaml:61,71`）。
- 本地 matcha：`tts.provider: matcha`，并准备
  `tts.matcha.model_dir`（`.../tts/matcha-icefall-zh-baker`）与
  `tts.matcha.vocoder`（`.../tts/vocos-22khz-univ.onnx`）（`config.example.yaml:74-76`）。
- `[已核]` volc 的 key 缺失或请求失败会**自动回落到本地 matcha**，不会让设备静音（缺 key 回落 `src/tts.py:213-225`；运行期失败回落 `:195-205`）。

### 3.5 配网：SoftAP 热点 + 网页（不是 BLE）

`[已核]` 这块板实际走的是 **SoftAP 热点**配网，不是 BLE：

- 编译配置选的是热点 —— `main/Kconfig.projbuild:1077-1079`（`USE_HOTSPOT_WIFI_PROVISIONING`，
  `default y`）；构建产物 `sdkconfig:1169` 为 `=y`、`:1171` 为
  `# CONFIG_USE_ESP_BLUFI_WIFI_PROVISIONING is not set`。
- 运行期分支 —— `main/boards/common/wifi_board.cc:174` 的
  `#ifdef CONFIG_USE_HOTSPOT_WIFI_PROVISIONING` → `:177` `wifi_manager.StartConfigAp()`。
- 源码里确有 BLE BluFi 分支（`wifi_board.cc:188-192` → `blufi.init()`，实现文件
  `main/boards/common/blufi.cpp`），但**当前编译配置没有启用**；要 BLE 配网必须自己开
  `CONFIG_USE_ESP_BLUFI_WIFI_PROVISIONING` 并重编。

操作步骤：

1. **什么时候进配网**：设备没有保存的 Wi-Fi，或连接超时
   （`wifi_board.cc:162-167`：`OnWifiConnectTimeout` → `StartWifiConfigMode`）。
   进配网后屏幕会显示热点名和访问地址（提示串在 `wifi_board.cc:179-186`）。
2. **用手机或电脑连设备开的 SoftAP**：SSID 形如 **`Xiaozhi-0F64`**，即
   `Xiaozhi` ＋ `-` ＋ **设备 STA MAC 末两字节**（前缀 `wifi_board.cc:57`，
   `"%s-%02X%02X"` 在 `managed_components/78__esp-wifi-connect/wifi_configuration_ap.cc:125`）。
   热点是**开放网络、无密码**（`wifi_configuration_ap.cc:166` `WIFI_AUTH_OPEN`）。
3. **打开配置页 `http://192.168.4.1/`**（`wifi_configuration_ap.cc:129-134` 返回该 URL，
   `:146-149` 把 AP 自身 ip/gw 设为 `192.168.4.1`）。设备自带 DNS + captive portal
   （常见探测域名统一 302 到首页，`:477-507`），多数手机会自动弹窗；不弹就手输这个地址。
   注意 `192.168.4.1` 是**设备热点自己的地址**，与你的路由器网段无关。
4. **提交**：在首页填你家 Wi-Fi 的 SSID/密码，表单 `POST /submit`（`wifi_configuration_ap.cc:359`）。
   设备连上后会去服务端 `/xiaozhi/ota/` 拿 `ws_url`，再连 4410。
5. **失败与重试**：连不上会在超时后自动回到配网模式（同 1）；配置页可以再提交一次，不必重启。
   若浏览器缓存/运营商页面拦着，用无痕窗口或直接敲 `http://192.168.4.1/submit`。
6. **顺手填 OTA 地址（可选，省一次重编）**：配网页的高级页
   `http://192.168.4.1/advanced`（路由 `:515` `/advanced/config`、`:558` `/advanced/submit`；
   板级已开 `show_ota_config`，`main/boards/common/wifi_board.cc:59`）可以填 `ota_url`，
   提交时写进设备 NVS 的 `wifi/ota_url`（`wifi_configuration_ap.cc:599-610`，
   `nvs_open("wifi")` + `nvs_set_str("ota_url", ...)`）。运行期优先于编译进镜像的
   `CONFIG_OTA_URL`（`main/ota.cc:56-62`）。`[源码已核 / 真机端到端未验证]`（本卡不刷机）；
   等价且可离线准备的做法是 `scripts/make_nvs_ota.py`（见 `docs/firmware-release.md`）。

---

## 4. 验收：5 条可自证

| # | 验收 | 怎么自证 |
|---|---|---|
| 1 | 服务起在 4410/4411 | `lsof -nP -iTCP:4410 -iTCP:4411 -sTCP:LISTEN` 能看到两个 LISTEN；`[已核]` 端口来自 `config.example.yaml:3-4` |
| 2 | 设备配网后拿到 IP | 路由器 DHCP 列表出现设备 MAC；或串口日志 `esp_netif_handlers: sta ip: ...`（串口见 `<serial-port>`，115200） |
| 3 | 能唤醒 | 说「你好小智」→ 屏幕进入 listening；服务端日志出现 `[listen]`（唤醒词默认 `nihaoxiaozhi`，`build.py --help`） |
| 4 | 能一问一答 | 问一句 → 服务端依次出现 `[asr]` / `[llm]` / `[tts]`，设备出声 |
| 5 | 能打断 | TTS 播放中说话 → 服务端出现打断日志且 TTS 停（`conversation.barge_in: true`，`config.example.yaml:120`） |

> 排查顺序：先看 4410 是否有连接（`[conn]`），再看 OTA 请求是否打进来、设备是否拿到正确
> `ws_url`，最后才看 ASR/LLM/TTS。

---

## 已知缺口（本卡不做）

- **factory 镜像已补（`persona.4` 2026-10-30 追加 `merged-binary.bin`）**：新板可 `0x0` 一次烧；
  但它是**整包、会清 NVS/Wi-Fi**，且编的是占位 OTA 域名（`http://rui-ota.invalid:4411`）。
  因此还缺一份「不清 NVS、自带你自己的 OTA 地址、跨版本通用」的出厂镜像——那需要按
  `XIAOZHI_OTA_BASE` 重编并妥善保管（自用版不入库、不上传）。
- `idf.py flash` 全量烧写路径未在真机验证（`[未验证]`）。
- 配网高级页写 `ota_url`（§3.5 第 6 条）源码已核，真机端到端未验证（`[未验证]`）。
- VAD 的 hf-mirror 下载路径未验证（见 §3.3）。
- 本文只覆盖这块 3.5" 480×320 屏（`chd-esp32s3-box`）；其他屏/触摸组合先按 §1 查 `--list-boards`，列表里没有再自建板级。
