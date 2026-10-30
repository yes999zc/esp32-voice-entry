# M7 Step 4 · 传输层评估（WS / HTTP / MQTT）

## 0. 9哥 拍板结论（2026-10-27 22:08，当时已定）

> **⚠️ 2026-10-28 更新（状态校正）：本节第 1 条「主动开口 v1 = 单向播报（notify）」已被 §5 取代 ——
> v1 = 现有 TTS 路径，notify 不做（commit `fd22391`，task-24 关单）。本节第 2/3/4 条（不改固件状态机 / 先测功耗 / 公网离线搁置）仍然有效。**

| # | 决定 | 落地含义 |
|---|---|---|
| 1 | **主动开口 v1 = 单向播报**（`notify`：不开音频通道、不能 barge、只能唤醒词停、播完回 Idle） | 走 **F**：Step 0（`dry_run=false` + 一次 1 分钟提醒，判定=听到声音 + `[tts] first frame` + status 出现 `spoke`）→ Step 1（**纯服务端**：记录 listen start/stop 与自己发出的 tts/notify，推断 `unknown/idle/listening`；idle 走 `notify`、其余走 `tts`，用 `[notify] device fetched` 当送达回执）。**预算 0.5–1.5 人日、零固件**；够用就停，**不升级到 E/A** |
| 2 | **暂不接受改固件状态机** | 只有 Step 1 的推断被实测证明不稳定时，才允许 B′（约 20 行状态上报）；**动手前必须先报他** |
| 3 | **常驻 WS 功耗：批准先测**（约 2 小时） | 要的是**数字**：常驻 WS + 上行语音处理关闭（唤醒词保持）的待机电流。测完先报数，**不得顺手改板子行为** |
| 4 | **公网 / 离线 / 多设备：明确搁置** | 不启动 D（8–15 人日）；**Step 4 到此结案**，以后不在 Step 4 里反复评估 |

字幕：**先 20px 全量字库**（不缺字、已刷）；30px 需 2.6 MB 字库进 assets 分区，另开卡，不进本轮。


> 2026-10-27。只出结论：**不写代码、不改配置、不刷机、不重启服务**。
> 路径口径：服务端相对本仓库；固件相对 `05_Tools/xiaozhi-esp32`（本仓库只有 `firmware/matrix-ui.patch`，不含固件源码）。
> 「估算」= 人日/延迟估值；「未核实」= 没有真机证据的推断。

## 0. 结论

**预计不换传输**（关键验证「无 turn 的 TTS」与「15 min soak」尚未做；下方 §4 的 Step 0 一旦通过即可定案）。现有 WS 的协议层已经能承载「服务端主动出声」：固件 `tts start` handler 本身不检查状态（`application.cc:700-707`），但 `SetDeviceState` 仍走状态机校验（`application.cc:95-104`）——**Idle/Listening → Speaking 合法；Notifying 等会被拒绝**（`device_state_machine.cc:72-99`）。真正缺的是三件事：

1. **设备状态可见性**——服务端只把 `listen start/stop` 打进日志（`src/session.py:603-604`），不知道设备此刻是 Idle 还是 Listening；
2. **送达确认**——`_safe_send` 吞掉发送异常（`src/session.py:637-642`），`send_notify` 发完即返回 True（`src/session.py:1065-1072`）；
3. **「不开麦的播报」与「回 Idle」**——`notify` 只在 Idle 接受（`main/application.cc:1261-1264`），而一轮 TTS 结束后设备回到 Listening（`main/application.cc:707-716`），所以会话开着且设备在 Listening 时 `notify` 收不到（`ROADMAP.md:219-224` 已记录）。

建议按 **F → E/A（A 的最小版）** 分两期，D（MQTT/UDP）只在公网/多设备/离线推送进入范围时再做。

## 1. 现状盘点

### 1.1 两条通道各自承担什么

| | 4410 语音 WS | 4411 HTTP 控制面 |
|---|---|---|
| 实现 | `websockets.asyncio.server.serve`（`src/server.py:9,64`） | aiohttp `web.Application`（`src/ota.py:23,141-156`） |
| 承担 | hello、双向 Opus 音频、`listen`、`abort`、`stt/tts/llm`、双向 MCP、`notify`（`system`：固件支持 `application.cc:760`、**服务端未使用**）| OTA 配置、拍照 POST、`/debug/*`（MCP/tool/turn/emotion/notify/reminder）、照片/截图/播报音频文件 |
| 鉴权 | 无（`config.yaml:9` 的 `device_token` 未被任何代码读取；HANDOFF「未关闭风险」） | Bearer，除 **四条**匿名路由：`POST /xiaozhi/ota/`、**`POST /debug/upload`**、`GET /notify/*`、`GET /screen/*`（`ota.py:31-43`，注释也写 "these four calls"）（`src/ota.py:31-43,96-112`） |
| 谁发起 | 设备连上后长期保持；服务端可随时下发 | 只有设备主动请求（开机 OTA、拍照、取播报音频） |
| 单板约束 | 当前按**单板**使用；代码**不强制**单会话（`_SESSIONS` 是集合、`active_sessions` 会返回多个，`src/session.py:163,181-182`），同一时刻一个 turn（`src/session.py:483-486`） | 按请求处理，不持有设备会话 |

> 修正任务卡摘要：4410 不是 aiohttp，是 `websockets` 库；4411 才是 aiohttp。两端口同进程（`src/server.py:60-67`），本机当前 PID 26738 在听（`lsof -nP -iTCP:4410/4411`，2026-10-27 13:2x）。

### 1.2 瓶颈在哪

- **会话即生命周期**：`Session.run()` 在 WS 关闭时才把 `alive=False`（`src/session.py:443-462`）；没有连接 = 没有可推送对象。
- **服务端没有设备状态机**：`listen` 只打印（`src/session.py:603-604`）；proactive 的 `device_idle` 是「没在说话且没有 turn」的代理（`src/proactive.py:657-666`），不是设备真实状态。
- **没有送达语义**：TTS 帧走 `_safe_send`（吞错），`notify` 被设备静默忽略（`main/application.cc:1262-1267`），服务端都不知道。
- **120 s 只是设备侧新鲜度**：`IsTimeout()` 120 s（`main/protocols/protocol.cc:108-123`）只让 `IsAudioChannelOpened()` 变 false；`last_incoming_time_` 只在收到数据帧时刷新（`main/protocols/websocket_protocol.cc:166`），服务端 20 s 的 WS ping（`websockets` 默认，`.venv313/.../websockets/asyncio/server.py:513`）不算。F1 已让「要不要新开连接」改判 `IsSocketConnected()`（`main/protocols/websocket_protocol.cc:74-79`；`main/application.cc:888,920,955,1040,1060`）。
- **功耗大头不是 socket**：板子 `PowerSaveTimer(-1, 180, -1)`（`main/boards/chd/chd-esp32s3-box/chd_esp32s3_box_board.cc:790-800`），180 s 只关屏/降背光，不关麦、不进 light sleep；真正贵的是「播完开麦」（见 3.6）。

## 2. 四条既有事实核实

| # | 任务卡说法 | 核实结果 | 证据 |
|---|---|---|---|
| 1 | Idle 不关 WS；120 s `IsTimeout` 让 `IsAudioChannelOpened()` 变 false；已加 `IsSocketConnected()` 让唤醒词复用长连接 | **成立（有保留）** | `protocol.cc:108-123`、`websocket_protocol.cc:70-79`、`application.cc:334-341,1384-1387`、HANDOFF「task-10 F1 保活改动」。~~保留：15 min soak 未做~~ → ✅ **已完成（2026-10-27 22:09–22:24）**：16 次采样全部 `established=1 sent=1`（HANDOFF §「真机验收结果（2026-10-27 22:24）」）。当时唯一正证据是 `/debug/emotion` 返回 `sent:1`（HANDOFF「F1 保活」），它只证明「收到 JSON」，不证明「能出声」——这条保留意见至今有效 |
| 2 | 服务端在设备 Idle 时无法主动开口；TTS 只能在一轮 turn 里发；表情任何状态放行 | **需修正**：协议层并非做不到 | `tts start` handler 不查状态（`application.cc:700-707`），但**仅 Idle/Listening→Speaking 合法**；Notifying 等会被状态机拒绝（`device_state_machine.cc:72-99`）；`speak_announcement` 已存在（`session.py:371-386`）且 `_speak` 无 turn 守卫（`session.py:927-969`）。真正的卡点是 3.2-3.7，不是「只能 turn 里发」。表情任何状态放行成立（`application.cc:748-753`） |
| 3 | 打断靠播放期 20 ms 子帧 RMS，`barge_rms=0.008`；回声≈0.0017、真人 0.0348、响应 0.192 s | **成立**；数字来自 HANDOFF 记录，本次未复测 | 代码 `session.py:489-548`；配置 `config.yaml:84-95`；测量 HANDOFF「task-13 barge 阈值校准」。注意 0.192 s 是墙钟 onset→stop，判据是 240 ms 音频 |
| 4 | 主动播报 4 类触发 + 6 道闸门 + dry_run | **成立，但闸门口径要统一** | `TriggerKind` 4 个（`proactive.py:32-37`）；`Gate` 7 个、`evaluate` 按 7 个判（`proactive.py:39-46,579-620`）；config 注释写「six gates」却列了 7 个名字（`config.yaml:145-151`）；`dry_run: true`（`config.yaml:156`），worker 在 4411 启动时拉起（`vision.py:455-471`） |

## 3. 「主动开口」到底卡在哪

### 3.1 协议层：不卡

- 固件收到 `{"type":"tts","state":"start"}` 就 `SetDeviceState(kDeviceStateSpeaking)`，不检查当前状态（`application.cc:700-707`）；`Idle/Listening → Speaking` 都是合法迁移（`device_state_machine.cc:72-95`）。
- 二进制音频只在 `Speaking` 时进解码队列（`application.cc:623-627`），所以顺序必须是 `tts start` 先到。

### 3.2 卡点 1：会话是否存在

- 服务端只有 `Session` 存活才能发（`session.py:443-462`）。F1 让 socket 活过 120 s，但只验证到「能收 JSON」（`/debug/emotion sent:1`，HANDOFF「F1 保活：已刷机 + 首个正证据」），没验证 15 min soak，也没验证「无 turn 时 TTS 能否出声」。
- 设备离线/断电时，提醒只保留到 `pending_ttl_min=30` 分钟（`config.yaml:168`；`proactive.py:766-800`），过期即丢。

### 3.3 卡点 2：`notify` 与设备状态互斥

- `notify`（不向服务端开音频通道、播完回 Idle）只在 `kDeviceStateIdle` 接受（`application.cc:1261-1264`；服务端注释 `protocol.py:75-82`）。
- 任何一轮 TTS 的 `stop` 都把设备送回 `Listening`（`application.cc:707-716`，除非 `listening_mode_ == ManualStop`），而本板 AEC 开启、默认 `Realtime`（`application.cc:60-66,1350-1353`，`sdkconfig:1153`）→ **会话开着时设备基本不在 Idle，`notify` 永远被忽略**。ROADMAP:219-224 已记录这一点。

### 3.4 卡点 3：服务端不知道设备状态

- `_on_json` 对 `listen` 只打日志（`session.py:603-604`）；没有状态变量。
- proactive 的「idle」是 `not speaking && no turn`（`proactive.py:657-666`），设备可能实际在 Listening，也可能刚播完还没回 Idle。
- 后果：服务端无法在 `tts`（会开麦）和 `notify`（只在 Idle）之间做正确选择。

### 3.5 卡点 4：没有送达确认

- `_safe_send` 捕获异常只打印（`session.py:637-642`）；`send_notify` 发完即 `True`（`session.py:1065-1072`）。
- 设备对 `notify` 的拒绝只打 `ESP_LOGW("Ignoring notify message while device is busy")`（`application.cc:1262-1267`），不回任何消息。
- 唯一可用的隐式 ack：设备真的来取 Ogg 时 4411 会打印 `[notify] device fetched`（`vision.py:451-455`）。

### 3.6 卡点 5：从 Idle 播完会开麦，且回不去

- Idle 处理器关闭**上行语音处理**（`EnableVoiceProcessing(false)`，`application.cc:1108-1109`），**唤醒词仍开**——麦克风硬件没关（`application.cc:1101-1111`）；`tts stop` 后进入 Listening，会 `SendStartListening` + 开麦（`application.cc:707-716` → `1119-1135` → `1239`）。
- 协议里没有「服务端让设备回 Idle」的消息（服务端只会发 hello/stt/tts/llm/mcp/notify，**从不发 `system`**；`src/protocol.py`）。
- 结果：一次「从 Idle 主动开口」= 麦克风常开 + 可能被环境噪声切出一个空 turn；功耗和隐私都变差。

### 3.7 卡点 6：首帧竞态（未核实）

- `tts start` 经 `Schedule()` 到主任务（`application.cc:703-706`），二进制帧在接收任务里按 `state == Speaking` 过滤（`application.cc:623-627`）；服务端 `_speak` 发完 `tts start` 立刻发第一帧（`session.py:951-957`）。理论上会丢开头 1-2 帧（≤120 ms），**没有真机证据**。
- 另外 `speak_announcement` 是整段合成后再发（`session.py:376-385`），文本越长首帧越晚；按句流式只用于 turn（`session.py:819-831`）。

### 3.8 当前「不出声」的直接原因

`proactive.dry_run: true`（`config.yaml:156`）：`fire()` 在 `_speak` 之前返回 `dry_run`（`proactive.py:969-978`）。这不是能力缺失，是刻意演练。

## 4. 候选方案对比

> 人日/延迟均为**估算**；延迟从「服务端决定说话」到「设备第一声」，不含 ASR/LLM。现有参照：fast 路由首帧 1.14-1.18 s、agent 2.43-2.66 s（HANDOFF「9哥 亲耳验收」「两个已确认的关键数字」），单句 TTS 合成 0.14-0.15 s（HANDOFF「两个已确认的关键数字」），表情前置 600 ms（`config.yaml:163`）。

| 方案 | 做法 | 代价（人日） | 固件改动 | 延迟 | 功耗 | 断线恢复 | 风险 |
|---|---|---|---|---|---|---|---|
| **A. WS + 服务端发起 turn** | 新增 `announce`/`turn` 消息；设备在 Idle/Listening 接受，播完回原状态 | 3-5（固件 2-4、服务端 1） | 状态机 + 新消息 + 记录 prev state + 构建/刷机 | TTS 路径：≈0.3-0.8 s 合成 + 0.6 s 表情 ≈ **0.9-1.4 s**（估算） | 从 Idle 播完会开麦（3.6） | 依赖 WS；pending/提醒 TTL 30 min | 改状态机；首帧竞态；回 Idle 语义要新写 |
| **B. 长活 WS + 设备轮询** | 设备每 N 秒问「有话说吗」，服务端出队 | 2-3 | 定时器 + 一条消息 | 轮询间隔（1-5 s）+ TTS 路径 | 周期唤醒，N 越小越耗电 | 天然自愈 | 延迟/功耗；仍要解决「播完回哪」 |
| **B′. 长活 WS + 状态上报** | 状态变化时发 `state`，不轮询 | 1-2 | ~20 行，无状态机改动 | ≈ A（无轮询延迟） | 仅状态变化时一帧 | 重连后重报 | 要改固件（但很小）；状态仍可能丢 |
| **C. 第二条控制通道**（HTTP 长轮询/SSE） | HTTP 唤醒，会话仍走 WS | 3-6 | HTTP client 任务 + 鉴权 + 重连/退避 | 长轮询≈0 + TTS 路径 | 长连接保持 WiFi 活跃，和 WS 同级 | 要自己写重连 | 与 WS 冗余；两通道状态同步；`notify` 仍需 Idle |
| **D. 换 MQTT+UDP** | 控制走 MQTT、音频走 UDP | 8-15 | 已有 `mqtt_protocol.cc`（`main/CMakeLists.txt:35`），但要 broker/UDP/AES/OTA 契约 | 与 A 同量级（未实测） | MQTT keepalive + UDP，未实测 | MQTT 自动重连（`docs/mqtt-udp.md:19`） | 服务端要新建 broker/UDP/AES；收益只在公网/多设备/离线 |
| **E. 放宽 `notify` 到 Listening** | 复用现有 Ogg/HTTP 播报；允许 `Listening→Notifying` | 1-2 | 状态机加一条边 + `StartNotification` 门 | TTS + ffmpeg + HTTP 下载（未实测，估 +0.3-1 s） | 不开麦，最低 | 依赖 WS；有 HTTP fetch 作隐式 ack | Ogg/ffmpeg 路径未在真机验证；`ReleaseWakeWordResources()` 后唤醒词要重建；只能唤醒词打断，不能「等一下」 |
| **F. 零固件：状态推断 + 分路** | 服务端用 `listen start/stop` + 自己的发送推断状态；idle→`notify`，listening→现有 TTS | 0.5-1.5（纯服务端） | **0** | idle: notify 路径；listening: 现有 TTS | notify 不开麦；TTS 不新增开麦（本来就在 Listening） | 依赖 WS；重连后状态置 unknown→按 idle 保守处理 | 推断漂移；`notify` 静默丢（3.5）；首帧竞态仍在 |

## 5. 推荐

**先做 F（0.5-1.5 人日，零固件），用一次真机实验判定；不够再做 E 或 A 的最小版；D 搁置。**

理由：

1. **F 直接回答「要不要换传输」**：如果 F 能让提醒/任务结果在设备空闲时出声，就说明 WS 足够，D 的 8-15 人日没有对应收益。
2. **F 的成本几乎全在服务端**，失败也不欠固件债；`notify` 的 Ogg/HTTP 链路服务端已经完整（`vision.py:265-300`、`session.py:1065`、`ota.py:31-43`），设备端 `notify_player` 也已存在（`application.cc:1261-1305`）。
3. **E/A 的增量价值是「可打断」和「从 Idle 直接出声」**：E 只解决前者的一半（唤醒词可停），A 才能像正常一轮那样用 `barge_rms` 打断（`session.py:489-548`）。这属于体验升级，不是传输问题。
4. **D 的收益只在公网/多设备/离线推送**；设备断电/断网时任何传输都推不到，MQTT 也只能「上线后补发」。当前是单板 LAN，先不付这个复杂度。

建议的验证顺序（都需要 9哥 批，本文档不执行）：

1. **Step 0（0.5 人日，改配置+重启）**：`proactive.dry_run=false`，造一次 1 分钟提醒；判定 = 听到声音 + `[tts] first frame` + `/debug/proactive/status` 出现 `spoke`。同时做 15 min soak（9哥 唤醒一次后不动），确认 `lsof` 仍 ESTABLISHED。
2. **Step 1（0.5-1 人日，纯服务端）**：记录 `listen start/stop` 与自己发出的 `tts/notify`，得到 `unknown/idle/listening`；idle 走 `notify`，其余走 `tts`；用 `[notify] device fetched` 当送达回执。
3. **Step 2（1.5-2.5 人日，可选，固件）**：只有当 Step 1 的推断不稳定，或 9哥 要求「从 Idle 出声 + 可打断」时，才做 A 的最小版（`announce` + 恢复 prev state + 状态上报）。

**不换的体验损失**（写清楚，供拍板）：

- 设备离线/断电时，提醒最多等 30 分钟（从原定时刻起算，`config.yaml:168`）后丢弃；没有离线推送。
- 若 F 的状态推断错，`notify` 会被静默忽略（3.5），表现为「它没说话」，服务端日志里看不到失败。
- 不能做到「用户不在房间也能收到」——这需要公网 + 推送通道，不是换个传输协议就自动有。

## 6. 需要 9哥 拍板 —— ✅ 四项已于 2026-10-27 22:08 拍完（答案见 §0）

> **2026-10-28 状态校正**：本节是**提问原文**，不是待办。第 1 条（主动开口语义）**已被 §5 取代**
> —— 现行结论是 **v1 = 现有 TTS 路径，notify 不做**；第 2/3/4 条按 §0 执行。不要再据本节判断未决事项。

> 口径说明：『常驻 WS 功耗』目前**没有实测数据**（功耗测法见 §1.2 末条与 §3.6）。若你要的是数字而不是判断，请把该拍板项改成『批准先测（约 2 小时）』。

1. **主动开口的语义**：接受「单向播报」（`notify`：不向服务端开音频通道、不能像 barge 那样被打断，只能唤醒词；播完回 Idle）作为 v1；还是要「能被打断的完整说话」（A/E，需改固件状态机）？
2. **是否接受改固件**：B′ 状态上报约 20 行；E/A 还需加 1-3 条状态机边。若都不接受，只能走 F 的推断，接受 `notify` 静默丢的风险。
3. **是否接受常驻 WS 的功耗**：F1 已经是常驻；板子 180 s 只关屏、不进 light sleep（`main/boards/chd/chd-esp32s3-box/chd_esp32s3_box_board.cc:790-800`）；实测功耗没做过。若在意，需先测「常驻 WS + **上行语音处理关闭（唤醒词保持）**」的待机电流。
4. **范围**：公网/离线/多设备是否进入近期路线图？是 → 启动 D 的调研（8-15 人日）；否 → 明确搁置，不再在 Step 4 反复评估。

## 7. 不实施

本文档只出结论。未改代码、未改 `config.yaml`、未构建/刷机、未重启 4410/4411、未向设备发任何真实调用（板子可能不在线）。

## 8. 已知限制 / 未核实

- **未核实**：F1 的 15 min soak；「无 turn 时 TTS 能否真的出声」；首帧竞态实际丢几帧；`notify` Ogg 路径在本板的端到端延迟/成功率；MQTT+UDP 在本板的本机延迟；常驻 WS 的功耗。
- **未核实**：固件工作树与设备镜像是否一致（写稿时 `05_Tools/xiaozhi-esp32` 为 clean，但 `build/` 是否就是刷进板子的镜像没有核对；HANDOFF 记录过「build 目录必须与镜像一致」）。
- **口径**：任务卡说「6 道闸门」，代码 `Gate` 是 7 个（含 `NO_SESSION`）；`config.yaml:145-151` 的注释也列了 7 个名字。建议统一为「7 道（含无会话）」或「6 道 + 会话前置」。
- **已知限制**：4410 无鉴权（LAN 内可连）；当前按单板使用（代码不强制单会话）；`notify` 无应用层 ack；`_speak` 的 `spoke` 只代表「帧发完」，不代表「设备播完」（`session.py:927-969` 返回于发送结束）。
- **测量口径**：HANDOFF 的 0.192 s 是墙钟，判据是 240 ms 音频；0.0017/0.0348 是 20 ms 峰值 RMS，不是 dBFS。

## 附：与 Step 5 的时序约束

Step 5 的 P0（删临时插桩）**必须排在本文档 Step 0 的 15 min 保活 soak 之后**——`application.cc:333-341`(idle-heartbeat) 与 `:659-662`(rx-while-idle) 正是 soak 的判读依据，先删就失去证据。

## 1b. Idle 主动开口实验：**今晚未能判定**（2026-10-27 22:56–23:09）

按 9哥 给的判定树跑了一次，结论是**实验条件不成立**，不是方案失败：

| 时刻 | 事件 |
|---|---|
| 22:56:34 | 会话在（`sent:1`），`POST /debug/reminder {"text":"喝水","when":"+120s"}` → 到点 22:58:34 |
| ~22:57 | 该会话 `ConnectionClosedError no close frame` → closed |
| ~22:58 | 两次 `[conn]` → 每次都在数十秒内以同样方式掉线 |
| 22:58:34 | **到点，但此刻没有会话** → `_flush_due_reminders` 按设计跳过（`attempts=0`，提醒保留，`in_seconds=-28`） |
| 22:59–23:09 | **连续 10 分钟 `established=0`、`sent=0`**：完全没有会话，也没有自动重连 |

判定树的三条分支**都没触发**：既没有出声，也没有 `GET /notify/…`，也没有 `device fetched`——因为那时根本没有活会话。

### 两个叠加原因
1. **设备静置后不自动重连**：重连只由本地事件触发（点屏/唤醒词）。22:58 那两次是 9哥 点屏产生的。
2. **23:00 后夜间闸门生效**（`night 23:00-08:00`）→ 即使有会话，主动播报也会被拒成 `face_only`。

### 与 15 分钟 soak 的矛盾（重要，别混）
22:09–22:24 的 soak 全程 `established=1`，而今晚 22:57 之后 2 分钟就掉。差别是**设备状态**：
soak 那次是刚被唤醒、处于活跃态；这次是回答结束回到静息、Wi-Fi 进深省电（静置时 ping RTT 实测 **789 ms**，正常 5–10 ms）。
**所以"保活 PASS"只在"刚交互过"的窗口内成立，长时间真静置仍需再测**；这条要写进 task-25 的口径里。

### 重测条件（明天白天）
会话在 + 不在夜间窗口 + 设 +120s 提醒 → 记录出声 / notify 取件 / `device fetched`。
提醒已手工删除（`DELETE /debug/reminder/r1`），避免明天一早它以"逾期"状态干扰判定。

## 1c. Idle 主动开口：**已成立（TTS 路径）**，2026-10-28 09:22–09:38 实测

### 结论
**零固件改动即可在 Idle 主动开口**，前提是长活 WS 能活下来——而这件事的根因今天找到了（见下）。

| 环节 | 证据 |
|---|---|
| 连接存活 | 09:22:22 → 09:37:47 **15 分钟 est=1、零变化**（此前数十秒就掉） |
| Idle 闸门通过 | `recent`: `{"kind":"scheduled","allowed":true,"rejected_by":null,"emotion_sent":true,"outcome":"dry_run"}` @ 09:24:21 |
| 到点送达 | `emotion_sent: true` —— 静置 2 分钟后 socket 仍能推表情 |
| 真出声 | 2026-10-27 22:35 Step 0 实测（`dry_run=false`，9哥 听到「提醒你喝水」） |

### 根因：不是省电，是**服务端心跳太紧**
板子 modem sleep 时 ping RTT 实测 **789–840 ms**，而 `websockets` 库默认 `ping_interval=20 / ping_timeout=20`；
设备间歇性答不上，连接被判死（`no close frame received or sent`）→ 推送全部落空、日志表现为"设备自己消失"。
已排除：不是重启循环（60 秒 0 次 OTA）、不是固件挂死。

**修法（纯服务端，零固件）**：`src/server.py` 改 `ping_interval=30, ping_timeout=90`（提交 `66df4bb`）。
修好之后：连接存活 15 分钟不掉，且 **ping RTT 从 840 ms 降到 4.8 ms** ——
设备因为保持长活 WS 而不再进 modem sleep，形成正反馈。

### 由此得到的取舍（写进功耗卡）
**长连接 ⇄ 省电 互斥**：维持"可被主动触达"，代价是不能进 modem sleep。
没有电流表无法量化成 mA，这已写进 task-25 的「无仪表·间接指标」口径。

### 9哥 决定（2026-10-28）：**v1 就用 TTS 现状**，notify 不做
理由（记录在案）：TTS 在 Idle 与 Listening 都能送达（今天与 22:35 实测），播放期间 barge 仍生效——
"可以被打断"比严格的单向播报更好用，因此**不需要**再实现 notify 发送端与 `device fetched` 回执。
连带结论：task-24（状态推断 + notify/tts 选路）**不再必要**，已关单。

### notify 路径：未实现，也不在 v1 范围内（口径说清）

**现状（2026-10-28 起，唯一现行口径）**：**notify 未实现**，v1 已定 **TTS 路径**（见上一节，commit `fd22391`）；
若将来要严格「不可打断的单向播报」，**另开卡**。当前 proactive 实现走的是**会话内 TTS**：
今天 `GET /notify` 与 `device fetched` 计数为 0 —— **因为根本没发 notify**，不是取件失败，
所以 9哥 判定树的后两支（"有取件无出声"/"连取件都没有"）**不适用**。

> **历史（2026-10-27 口径，已被 2026-10-28 决定取代）**：~~`v1 = 单向播报（notify）` 这条决定里，notify 是"不开音频通道、
> 不可打断"的那条路…两条路的选择留给他：TTS 已被证明能出声（且播放期间 barge 仍生效，实际可被打断）；
> 要严格"不可打断的单向播报"才需要实现 notify 发送 + 真机验取件。~~

