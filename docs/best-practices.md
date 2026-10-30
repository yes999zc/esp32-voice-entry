# 业界调研对标（M2）

目的：把「别人已经解过的问题」变成设计输入，而不是事后对照。
方法：每项只回答三问——解决什么问题、代价是什么、我们抄不抄。
**只记录读过源码或读过官方文档的结论**，没读过的写成「待查」，不猜。

调研时间：2026-10-26。上游版本：`78/xiaozhi-esp32` @ main（本地克隆），
社区后端 `xinnan-tech/xiaozhi-esp32-server` @ main（3,880 commits, 11.0k stars）。

---

## 1. 上游固件 `78/xiaozhi-esp32`

### 1.1 全双工不是服务端能力，是硬件 AEC 决定的

**事实**（源码，非推测）：

- `main/application.cc:1270`：
  `GetDefaultListeningMode()` 返回 `aec_mode_ == kAecOff ? kListeningModeAutoStop : kListeningModeRealtime`
  —— 也就是**只要设备端 AEC 开着，默认就是 realtime 监听模式**。
- `main/application.cc:1062`：进入 `kDeviceStateSpeaking` 时，
  只有 `listening_mode_ != kListeningModeRealtime` 才 `EnableVoiceProcessing(false)`。
  换句话说 **realtime 模式下，它说话时麦克风不关**。
- `main/audio/engines/afe_audio_engine.cc:134`：AFE 配置写死
  `afe_config->aec_mode = AEC_MODE_FD_LOW_COST`（全双工低成本模式）。

**结论**：我们这块板（ES7210 + 参考通道 + device AEC）在协议层**本来就是全双工的**，
设备一直在推麦音频。而我们的服务端 `session._on_audio` 里写着
`if self.speaking: return` —— 是我们自己把全双工关掉了。

**抄什么**：立刻把「播放时丢帧」改成「播放时继续收，用判据决定是否打断」。
**抄谁的判据**：抄我们自己在 LX06 上的实现（见 §5），不重新发明。
**不抄什么**：不要去实现服务端 AEC。

### 1.2 能力协商字段

`docs/websocket.md`：设备 hello 里带 `features: {mcp, aec, glyph_push}` 与 `text_font`。
其中 `aec: true` 表示 **`CONFIG_USE_SERVER_AEC`**（服务端 AEC），不是「设备有 AEC」。
另有 `glyph_push`（动态文本推送扩展，`docs/glyph-push.md`）与三种二进制帧版本：
v1 裸 Opus、v2 带 timestamp（给服务端 AEC 用）、v3 轻量头。

**影响 M3**：盘点时要记录这块板 hello 实际发来的 `features`，别假设。
`glyph_push` 若可用，是「屏上显示 agent 状态/审批」的现成通道（M5/M6 用得上）。

### 1.3 上游也支持端到端 Realtime 语音模型

`README_zh.md` 原文：*「采用 Opus 音频流，既支持传统的流式 ASR + LLM + TTS 方案，也支持
Realtime 端到端语音模型；具备 AEC 的硬件可实现实时全双工交互」*。

**抄不抄**：**不抄（本阶段）**。端到端模型体验更顺，但它把 agent 的工具链、记忆、
审批全绕过去了——我们要的是「Hermes 的嘴和眼睛」，不是另一个语音模型。
留在 M6 之后作为可选通道评估。

### 1.4 MCP 通道

`docs/mcp-protocol.md`：后端是 MCP client，设备是 MCP server；
`initialize` 的 `capabilities.vision.url` 决定拍照往哪推（我们已按此实现）；
`tools/list` 可枚举工具。IoT 旧协议 `type:"iot"` 已废弃，全部走 MCP。

**结论**：我们的做法与上游一致，`docs/device-capabilities.md` 的形态可以直接对上游文档。

---

## 2. 社区后端 `xinnan-tech/xiaozhi-esp32-server`

**它是什么**：11k stars 的小智自建后端，Python/Java/Vue，支持 MQTT+UDP 与 WebSocket
两种传输、MCP 接入点、声纹识别、知识库、管理控制台。工程完整度远超我们这套薄服务端。

**抄什么**

- 多传输并存（WS + MQTT/UDP）的抽象——我们暂时不需要，但「设备层抽象」的思路值得在 M5 前想清楚。
- 「MCP 接入点」的做法：把后端能力反向暴露给设备侧 agent，和我们 M5 的「板子给 agent 当嘴」是同一个问题的两面。

**不抄什么**

- 整套管理台、知识库、声纹：与「个人 agent 的桥」无关，只会拖慢迭代。
- **服务端 AEC**：见下。

**反面证据（很重要）**：issue #3453「开启 Server-Side AEC 后，喇叭播放声音依然被录入
（自我打断）」，配置项自己标着 `(Unstable)`，单麦板上会自打断。
→ **服务端做 AEC 不可靠，回声消除必须留在设备（我们的板子有 ES7210 参考通道 + AFE）。**

---

## 3. `Seeed-Projects/espclaw`（板载 agent）

**它是什么**：把 agent 直接放进 ESP32（工具注册表、cron、memory、GPIO 工具、
Telegram/Discord/飞书等出口通道，provider 支持 Anthropic/OpenAI 兼容）。
61 stars，最后一次提交 2026-03。

**路线差异**：它把 agent 放在板上；我们把板当终端、agent 留在 Mac/NAS。
两者目标重叠（都能对话 + 控硬件），但维护成本完全不同：板上跑 LLM 逻辑意味着
每次改工具都要重刷固件。

**抄什么**

- `builtin_tools.def` 的 X-macro 工具表 + `tool_registry` 分发：我们 `src/tools.py`
  已经是「声明式清单 + 名字映射」，方向一致，可以借它的分层（工具表 / 分发 / 安全护栏）。
- **危险工具护栏**：它对 GPIO 有 safety guardrails；我们已经在 `tools.py` 里
  把 `reboot/upgrade_firmware/set_download_url/reconfigure_wifi` 挡在语音之外，思路相同。

**不抄什么**：板上跑推理与 cron（S3 资源有限，而且我们已经有 Hermes）。

---

## 4. `OHF-Voice/wyoming`（Home Assistant 语音栈的传输协议）

**它是什么**：设备/服务解耦的点对点语音协议，事件分阶段：
`audio-start/chunk/stop`、`transcript`、`handled-start/chunk/stop`、`played`。

**抄什么**：**分阶段事件 + 明确结束信号** 的设计。我们的 TTS 现在是
「一次性合成整段 → 连续推帧 → tts_stop」，首帧 4 s 就是这么来的；
Wyoming 的 `handled-start → handled-chunk… → handled-stop` 正好对应
「先出第一句、边合成边推、明确收尾」，是 M6 流式 TTS 的现成骨架。

**不抄什么**：不实现 Wyoming 协议本身（我们不需要兼容 HA 生态），只借事件模型。

---

## 5. 自家两个项目：LX06（已归档）与 Rui（继任内核）

**两者已经差得很大，参照的东西不一样：LX06 给的是实测声学数字，Rui 给的是架构与契约。**

### 5.1 LX06 / `xiaoai-voice-entry`（legacy，已归档）

`yes999zc/xiaoai-voice-entry` 现在是 private + archived，只作只读参考。它留下的价值是
**实机测出来的声学与打断数据**：

- 打断只有一个检测点：`frames()` 里 AEC 之后的同一路音频；
  早期 `BARGE_FE` / `BARGE_AEC` 双实现已删——**两套判据就是「有时能打断有时不能」的来源**。
- AEC 参数：speexdsp MDF、4096 taps（256 ms）；修好参考通道量程后实机 ERLE
  **23.4 / 30.2 dB**，80% 音量整段 21.8–32.0 dB。
- 双讲判据：短时残差 > **35%** 短时麦能量 → 判定为人声，停止自适应。
- 唤醒前 0.5 s 靠 preroll 回放补回句头；KWS 命中本身晚约 0.5 s。
- 回声门：回复结束后 0.7 s + 设备缓冲 0.3 s ≈ 1.0 s，门内帧进 1.2 s 回放缓冲。

**抄什么**：进 M6 时逐条搬（单点检测、双讲阈值、preroll、回声门）。
**不抄什么**：LX06 的 8 通道/移位 12/16 参数——那块板是 6 麦 + 2 参考；虫洞板是
ES7210 TDM 4 slot、设备内 AFE 已做 AEC，链路不同。

### 5.2 Rui（原 house-ear，现任内核）

`yes999zc/rui`（public, MIT），本地 `~/AI_Workspace/01_Code/projects/house-ear`。
定位：**设备无关的语音内核**——控制面（FastAPI）+ 独立音频面（AEC/KWS/VAD/播放仲裁）
+ Vue 控制台 + 插件体系，NAS 一条 Docker 起。

关键事实（读 `docs/architecture.md` 与 `docs/adapter-contract.md`）：

- **加一台音箱 = 写一个 adapter + 注册一行**，这是它整个设计的验收标准；
  内核里没有厂商名。
- 设备契约 `DeviceAdapter`：`probe()` / `open()` / `close()` / `frames()` /
  `play(pcm, sample_rate, channels)` / `stop_playback(fade_ms)` / `set_volume()` / `set_led()`。
- 能力是**声明**不是假设：`mic_array` / `reference` / `playback` / `led` / `keys` /
  `volume` / `native_kws`；缺 `reference` 就没有播歌时打断，控制台直说缺什么。
- 传输分 `inbound`（设备拨入，LX06 就是这样，`ws://<server>:<listen_port>`）与
  `outbound`（我们拨设备）。我们这块板天然是 **inbound**。
- 已有两个 out-of-tree 卫星：`rui-xiaoai-bridge`（LX06）、`rui-dot2-bridge`（Echo Dot 2），
  都**不 fork 内核**，用 `plugin.yaml`（`rui-plugin/v0`）+ `rui-device/v1` 清单挂进去。

**对 M5 的影响（2026-10-27 修正）**：Rui 的插件模型证明了「设备无关 + 能力声明」
这条路可行，但**按角色定义，这块板不做 Rui 的卫星**——卫星已经够多，它要的是
「我和 Hermes 之间的通道」。所以：借 Rui 的 **adapter 契约与能力降级思路**，
保持本仓库的独立通道；不引入 Rui 的回合编排与多房间层。

**抄什么**：`DeviceAdapter` 的接口形状、能力降级（不假装支持）、
`stop_playback()` 的语义（**听众听不到**，不是「停止发送」：本地淡出 + 清队列 + 让设备丢弃缓冲）、
断线重连退避、以及「一个 mock adapter 集成测试 + 一次真机手测」。

**不抄什么 / 硬约束**：

- **不改 Rui 源码**（9 哥 明确要求）。要做就做成 out-of-tree 插件，像两个 bridge 那样。
- 不把 Rui 的音频面搬过来：这块板的 AEC 在设备里（AFE `AEC_MODE_FD_LOW_COST`），
  再在服务端做一遍 AEC 就是 §2 里那个自打断的坑。

---

## 6. 对后续里程碑的具体影响（至少各一条）

**M3（能力盘点）**

1. 记录 hello 里真实的 `features`（`aec` 是服务端 AEC 标志，别误读）。
2. 盘 `self.AEC.set_mode` 与 listening mode 的联动：切 AEC 模式会改变设备是
   realtime 还是 auto-stop，直接决定能不能打断——这条排进 M3 优先级第一。
3. 盘 `glyph_push` 是否可用（顶栏/字幕/审批提示的现成通道）。

**M4（接 Hermes）**

1. 保持 OpenAI 兼容的 chat completions 通道，不接 Realtime 模型（会绕开工具链）。
2. 设备工具仍由我们这层执行（MCP），Hermes 只看到「工具定义 + 结果」。

**M5（适配性研究）**

1. 三态表加一列「上游是否已有通道」：已经有通道的（拍照、音量、屏、AEC 模式）
   标「直接可用」，别重复造。
2. 审批确认的候选落地：`glyph_push` 或屏幕 + 触摸（FT6336），不是新增硬件。
3. **架构（已定）**：不做 Rui 的卫星、不做多房间——角色是「9 哥 与 Hermes 的通道」。
   借 Rui 的 adapter 契约与能力降级思路，保持独立栈。延迟基准是「打字路径」，
   不是固定秒数。

**M6（全双工）**

1. 第一刀：删掉 `if self.speaking: return`，改成「播放中继续收 + 与播放波形对齐后判定」，
   按 LX06 的单点检测实现，目标 ≤300 ms。
2. 第二刀：TTS 改流式，按 Wyoming 的分阶段事件（句为单位 start/chunk/stop），首帧目标 <1 s。
3. 明确不做：服务端 AEC（社区 issue #3453 已证明不稳）。

---

## 参考

- `78/xiaozhi-esp32`：`main/application.cc`（1270、1062 行）、`main/audio/engines/afe_audio_engine.cc`、
  `docs/websocket.md`、`docs/mcp-protocol.md`、`docs/glyph-push.md`、`README_zh.md`
- `xinnan-tech/xiaozhi-esp32-server`：README、issue #3453（Server-Side AEC 自打断）
- `Seeed-Projects/espclaw`：README、`tool/`、`PLAN.md`
- `OHF-Voice/wyoming`：README（事件流程）
- `yes999zc/rui`（原 house-ear）：`docs/architecture.md`、`docs/adapter-contract.md`；
  `yes999zc/rui-xiaoai-bridge`：`plugin.yaml`、adapter 实现（out-of-tree 的样板）
- `yes999zc/xiaoai-voice-entry`（archived）：`docs/design-and-measurements.md`（LX06 实测）

## 2026-10-27 补记：三条花时间才拿到的结论

### 1. 自编译固件唤不醒，先看 AFE 的两行日志

```
BAD : AFE: Input PCM Config: total 1 channels(1 microphone, 0 playback)
GOOD: total 2 channels(1 microphone, 1 playback)
      AFE Pipeline: [input] -> |AEC(FD_LOW_COST, NLP_VERY_AGGRESSIVE)| -> |VAD| -> |WakeNet(...)|
```

单通道、没有 AEC 段 = 板级 `sdkconfig_append` 没注入。用裸 `idf.py` 编译就会这样：
`CONFIG_USE_DEVICE_AEC` / `CONFIG_CHD_ESP32S3_BOX_LCD_35` 只在
`scripts/build.py` 里写进 `build/xiaozhi-build.sdkconfig.defaults`。AFE 拿到错位的
4-slot TDM 数据，模型照样加载、照样打印 `detector: WakeNet`，但永远不触发。

- board 参数要用**路径**：`chd/chd-esp32s3-box`（build.py 拿它跟 CMakeLists 里的
  `set(BOARD_DIR ...)` 比对，写裸名会 `[ERROR] board_type … not found`）。
- 想让 OTA 指向自建服务器，把 `CONFIG_OTA_URL` 写进**板级 config.json 的
  `sdkconfig_append`**，不要手改 sdkconfig——下次 build.py 会重新生成。
- 刷 build.py 的产物：`cd build && python3 -m esptool … write-flash "@flash_args"`。
- `idf.py flash` 会重写 0x800000 的 assets 分区，手工塞进去的带唤醒模型的分区会被冲掉。

### 2. `notify` 在 WS 传输下不可用

固件支持服务端推 Ogg Opus（空闲时播、不开麦），但 tts stop 之后设备回到
`Listening` 而不是 `Idle`，而 `notify` 只在 `Idle` 接受 → 音频通道开着时推送全被丢弃。
官方推送走 MQTT。WS 下只能做「排队，下次连上就播」。

### 3. 480x320 上全屏动画的预算是负的

307 KB/帧，SPI 80 MHz 实测约 24 fps 上限，本机显示配置把 flush 切成 16 段，单帧
60–75 ms。任何「每帧整屏 invalidate」的效果都会饿死音频任务（表现为唤醒彻底失效）。
要做效果只能：脏格/脏区失效、每帧只改少量像素；并把 `LV_INV_BUF_SIZE` 从默认 32
提到 128（超了 LVGL 会静默塌成全屏重绘）。另有两个坑：画布挂在 `lv_layer_top()` 上
`lv_snapshot` 拍不到（验证时只看到原生 UI）；面板端口 `swap_bytes=1`，写画布缓冲要
自己做字节交换，否则颜色跑到红通道。
