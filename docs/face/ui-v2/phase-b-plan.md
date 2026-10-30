# UI v2 Phase B 设计与数据源盘点（A + B + C）

- 日期：2026-10-28
- 结论：9哥 选版 **A + B + C**（A 默认、B 可切、C 调试；D 不做）
- 性质：**设计文档**。本卡不改固件、不刷机、不 commit 固件；实现拆到 B1/B2。
- 目标设备：CHD ESP32-S3-BOX，480×320，`chd-esp32s3-box-lcd35`（kawaii 脸 + B2 静音 + C1 六状态表情已在 HEAD）

---

## 1. 真实数据源盘点（只列设备端真有的）

固件里没有“统一日志 API”，只有 `ESP_LOGx` 的串口输出；下表是 Phase B 日志环可以**真实拿到**的事件源。
“无”表示设备端没有该事件，UI 不得伪造。

### 1.1 对话 / 协议事件

| UI 需要显示 | 设备端是否有 | 来源（file:line） | 回调/触发点 | 备注 |
|---|---|---|---|---|
| ASR 文本（服务器 `stt`） | **有** | `main/application.cc:774-787` | `Protocol::OnIncomingJson` 的 `type=="stt"` 分支；`text` 字段 | 已 `display->SetChatMessage("user", ...)`；串口打 `Application: >> %s`（`application.cc:782`；783 是 `Schedule(...)`，不是日志） |
| TTS 开始 | **有** | `main/application.cc:743-747` | `type=="tts" && state=="start"` → `SetDeviceState(kDeviceStateSpeaking)` | |
| TTS 结束 | **有** | `main/application.cc:748-757` | `type=="tts" && state=="stop"` → Listening/Idle | 正常播完与打断都会到；不能单独当 barge |
| TTS 逐句文本 | **有** | `main/application.cc:758-772` | `type=="tts" && state=="sentence_start"`，`text` | 可作字幕/日志（assistant 句子） |
| 服务器 emotion（含 thinking/confirm/barge 的替身） | **有** | `main/application.cc:789-795` | `type=="llm"` 的 `emotion` → `display->SetEmotion` | 设备**没有** thinking/confirm 状态；只能显示/记录 `llm:emotion=<name>`，不得写成 `state=thinking` |
| MCP 消息 | **有** | `main/application.cc:796-800` | `type=="mcp"` → `McpServer::ParseMessage` | 可记 `mcp:<method>`（若需要，需在 MCP 解析处加 hook） |
| system 命令（reboot 等） | **有** | `main/application.cc:801-811` | `type=="system"`，`command` | |
| alert | **有** | `main/application.cc:812-822` | `type=="alert"` | |

### 1.2 状态机 / 打断

| UI 需要显示 | 设备端是否有 | 来源（file:line） | 说明 |
|---|---|---|---|
| listening / speaking / idle | **有** | `main/device_state.h:4-16` 枚举；`main/device_state_machine.cc:113-135` `TransitionTo()`；`main/application.cc:1436` `HandleStateChangedEvent()` | 状态名映射在 `application.cc:38-49`；这是设备真实状态，可直接记录 |
| thinking | **无（设备状态）** | 服务器 `src/persona.py:127`、`src/session.py:540` 推 `thinking` → 设备收到 `llm.emotion=confused` | UI 若需要“思考中”，只能由 `llm:emotion=confused` + TTS 未开始推导；日志里写 `llm:emotion`，不写 `state=thinking` |
| confirm-pending / tool-running | **无（设备状态）** | 服务器 `persona.py:128-131`；设备只收到 `llm.emotion=shocked/angry` | 同上，按 emotion 记录 |
| barge（打断） | **无（设备事件）** | 检测在服务器：`src/session.py:589` 调 `_barge_watch()`（:609-676），日志 `[barge] rms`（`session.py:659-661`）/ `[barge] face`（`:669-670`）、推 `barge-in` 表情（`:668` 调用 `_push_state_face("barge-in")`）；`:1371/1390` 是通用 `_push_state_face`/`push_emotion`，不是 barge 检测点；发 `tts_stop`（`:674`） | 设备端只能看到 `llm:emotion=shocked` 和 `tts:stop`；**没有**独立 barge 事件。UI 可用 `tts:stop` 作为“播放结束”事件，不可声称 barge |
| VAD（用户说话） | **有** | `main/audio/audio_service.cc:92-93` `callbacks_.on_vad_change`（`OnVadStateChange` 内）；`Application` 置位 `MAIN_EVENT_VAD_CHANGE`（`application.cc:135`），主循环处理（`:335`） | 只有 speaking 布尔，无音量 |
| 唤醒词 | **有** | `audio_service.cc:98-99` `callbacks_.on_wake_word_detected`；`Application::HandleWakeWordDetectedEvent`（`application.cc:1325`） | 可记 `wake:<word>` |

### 1.3 静音 / 音频 / 系统

| UI 需要显示 | 设备端是否有 | 来源（file:line） | 说明 |
|---|---|---|---|
| 静音状态（服务端 last-confirmed） | **有** | `main/mute/mute_controller.h:30-41`（`MuteSyncState`/`MuteStatus`）；`MuteController::status()` :83；实现 `main/mute/mute_controller.cc:224-227`（`:230` 是 `PublishState()` 里的局部 `MuteStatus status;`，不是 getter） | `MuteStatus{muted, state, has_result}`；`kFailed` = 同步失败 |
| mute hold（真正停采停传） | **有** | `main/audio/audio_service.h:144` `SetMuteHold()`、`:145` `IsMuteHeld()`；实现 `audio_service.cc:760` | UI 显示“HOLD”即可 |
| 音量 | **有** | `main/audio/audio_codec.h:47` `output_volume()`；`audio_codec.cc:40-45` `SetOutputVolume`；MCP 工具 `mcp_server.cc:52-58` | 通过 `Board::GetAudioCodec()` 读 |
| WiFi RSSI | **有（底层）** | `managed_components/78__esp-wifi-connect/include/wifi_manager.h:88` `WifiManager::GetRssi()`；`main/boards/common/wifi_board.cc:256/273/337` 已使用 | 目前 `Board`/`NetworkInterface` **没有**通用 RSSI getter；B1 需在 WiFi 板加一个只读接口（或 UI 条件编译直接取 singleton），CHD 为 WiFi 板 |
| free SRAM | **有** | `main/system_info.cc:31-33` `SystemInfo::GetFreeHeapSize()`；内部 SRAM 直接 `heap_caps_get_free_size(MALLOC_CAP_INTERNAL)`（`system_info.cc:151` 已这样用） | 没有公开的 “free internal SRAM” getter；B1 加 `SystemInfo::GetFreeSramSize()` 或 UI 直接调用 |
| 音频上行帧数（mic→opus） | **部分有** | `main/audio/audio_service.h:146-151` `GetInputFrameCount()`/`GetEncodedFrameCount()`；计数在 `audio_service.cc:234/520` | 只有 input/encode 两个 getter |
| 音频下行帧数（server→decode） | **计数有、getter 无** | `main/audio/audio_service.h:110-115` `decode_count/playback_count`；`audio_service.cc:360/461` | B1 需补 `GetDecodedFrameCount()`/`GetPlaybackFrameCount()` |
| 实际 WebSocket 上行帧数 | **无公开计数** | `Application::Run` 发送循环（`application.cc:238` 起，`:318` `SendAudio`）只给 `mute_tx_frames_since_log_` 私有计数 | B1 加只读 `tx_frames_total`（发送成功才 +1） |
| OTA/网络事件 | **有** | `NetworkEvent` + `Board::SetNetworkEventCallback`（`main/application.cc:172`） | 可记 connected/disconnected/IP/RSSI（RSSI 同上） |
| 电池/温度 | **有** | `Board::GetBatteryLevel` / `GetTemperature`（`board.h`） | Phase B 未要求，可留空 |
| 设备端 ASR/LLM “假日志” | **无** | — | 不得用样张里的 `asr:`/`llm:` 文本；ASR 只能来自服务器 `stt`，LLM 只能说 `llm:emotion` |

> 结论：A/B/C 的日志环核心事件 = `stt`、`tts start/stop/sentence`、`state`、`llm:emotion`、`wake`、
> `vad`、`mute:status/hold`、`net`、`mute sync fail`、音量/RSSI/SRAM/帧计数。设备端没有 barge/thinking
> 独立事件，UI 必须如实标注来源（如 `llm:emotion=confused`、`tts:stop`）。

---

## 2. 日志环形缓冲（UiLog）

### 2.1 容量与字段

- 容量：**10 行固定环**（A 7 / B 5 / C 8 可见；C 多出的 2 行仅作合并/快照余量，不提供历史）。A 渲染最新 7 行、B 最新 5 行、C 最新 8 行；
  **不做滚动、不做历史页、日志区不可点**（设计选择②：环容量贴近可见行数，旧行不可达是明确取舍，不保留“可滚动/可回溯”的模糊表述）。
- 每行结构（固定大小，无 `std::string`）：
  ```c
  struct UiLogLine {
      uint32_t uptime_ms;     // esp_timer_get_time()/1000，4 B
      uint16_t seq;           // 环形序号，用于判断新行，2 B
      uint8_t  level;         // I/W/E，1 B
      uint8_t  source;        // enum: STT/TTS/STATE/LLM/WAKE/VAD/MUTE/NET/SYS/AUDIO
      char     tag[8];        // "stt","tts","state","llm","mute","net","audio"
      char     text[96];      // UTF-8：snprintf 后向前回退到合法码点边界，最后一个字节写 '\0'，不拆汉字
  };                          // ≈ 112 B/行
  ```
- 10 行 ≈ **1.1 KB 静态 SRAM**；另加快照缓冲（UI 线程用，最多 10 行）≈ 1.1 KB，总计 **~2.2 KB**，
  全部 `static`/成员数组，无堆分配。
- 时间显示：`mm:ss.mmm` 由 `uptime_ms` 在 UI 层格式化；不依赖 RTC（`has_server_time` 只在 OTA 后有效）。

### 2.2 线程/任务安全

- 写入者：主循环（state/mute/stt/tts）、WebSocket 接收任务（JSON 回调）、音频任务（VAD/wake）、
  MuteController 任务（sync fail/hold）。全部通过唯一入口 `UiLog::Add(level, source, tag, fmt, ...)`。
- 用一把 **`std::mutex`**（或 `portMUX_TYPE`）保护 `head/seq/lines`；写入只做 `snprintf` 到本地栈
  buffer（≤96 B）后加锁复制，临界区 < 50 µs。
- UI 侧（LVGL timer，250 ms）在同一把锁下把“自上次读取后的新行”复制到快照（最多 10 行，只拷新增），
  解锁后再更新 label；**不在锁内调用 LVGL**。
- 不在 ISR 中写；音频回调只记录 VAD 边沿（非每帧），避免高频。

### 2.3 溢出 / 限流 / 持久化

- 溢出：环形覆盖最旧行；维护 `dropped_total` 与 `overwritten_total`，UI 在日志区右上角显示 `+N`。
  可见行就是环里最新 7/5/8 行；更旧的已覆盖，**没有历史入口**（见 2.1）。
- 限流：同一 `tag` 连续相同文本合并为 `xN`（只更新计数，不新增行）；每 tag 最多 5 行/s；
  高频事件（如 `audio frames`）**不进日志环**，只进卡片/浮层的数值字段。
- 持久化：**不落 NVS**（日志是运行态观测；NVS 写放大/磨损/敏感信息都不合适）。重启清空，
  首行固定 `boot: ui v2 phase B`。

### 2.4 事件接入点（B1 实现）

在以下现有代码处调用 `UiLog::Add`（不改协议/状态机）：
- `application.cc:774`（stt）、`:758`（sentence_start）、`:743/:748`（tts start/stop）、`:789`（llm emotion）
- `application.cc:1436`（state changed，记录旧→新）
- `application.cc:1325`（wake word）
- `application.cc:135` 置位 / `:335` 处理（VAD change，边沿）
- `mute_controller` 状态回调（`application.cc:149` 的 lambda，记录 status/state 变化）
- `HandleNetworkConnectedEvent`（`application.cc:381`）与 network event callback（`:172`）
- 音频计数/音量/RSSI/SRAM 由 UI timer 直接读 getter，不逐帧写日志。

---

## 3. A/B/C 切换 UX

### 3.1 推荐：顶栏右侧「视图」按钮（视觉 24×24 / 命中 ≥44×44）

- 视觉：24×24 圆角 6，material symbols `grid_view` + 14 px 字母 `A/B/C`。
- **命中区：44×44 透明容器**（visual 24×24 居中，四周各 10 px 透明 padding），满足 ≥40×40 触摸目标。
- 坐标（480×320）：
  - `view_hit_` 44×44 @ `(x=428, y=0)`（视觉 `view_btn_` 24×24 @ `(438, 10)`）；
  - `mute_hit_` 44×44 @ `(x=376, y=0)`（视觉 `mute_icon_` 24×24 @ `(386, 10)`）；
  - 两个命中区间隔 **8 px**（428-420），不会互相误触；都落在顶栏 44 px 高区域内（状态条视觉仍按 24 px 画）。
- 交互：单击 `A → B → C → A`；切换时只重建当前页的对象显隐（不重建 LVGL 树），
  打 `CHD_UI: view=A|B|C`。
- 防误触（写清作用范围）：
  - **3 s 开机 guard 覆盖所有触摸**（含顶栏两个按钮）：`s_touch_ready_ms < kTapBootGuardMs` 时 view/mute 均不响应
    （`chd_esp32s3_box_board.cc:396-397`，现 ScreenClickCb/FaceClickCb 同源）；
  - **400 ms 手势 guard 同样保留给顶栏按钮**：`last_gesture_ms_`（`:477`）在 view/mute 的 CLICKED 处理里也检查，
    滑动后 400 ms 内不切换视图、不切静音；两个 guard 都是“保留”而非移除；
  - 点击是 `LV_EVENT_CLICKED`，不上浮到 screen/container，不触发 `ScreenClickCb`（`target==current_target` 保护，`:463-475`）；
  - **真机必须验**“从顶栏起手的上下滑”是否仍被 screen 手势接收：若被按钮吞掉，给 `view_hit_/mute_hit_` 关闭
    `LV_OBJ_FLAG_GESTURE_BUBBLE` 或在 `gesture_event_cb` 里排除 y<44 区域，再复测；不允许为了按钮牺牲上下滑。
- NVS：**不记住**。每次开机回到 **A**（A 是产品默认；C 是调试，不能让设备重启后停在调试页）。
  若 9哥 要求“记住上次”，再单独加 `Settings("ui").SetInt("view_mode")`，默认 A，但本设计不推荐。
- 备选方案：
  1. 长按顶栏 1.5 s 循环（不占按钮，但与未来“长按设置”冲突）；
  2. 顶栏三击（误触率高）；
  3. MCP `self.screen.set_view(mode)`（无触摸依赖，适合自动化/验证，但 9哥 手动不便）。
  **推荐：按钮 + MCP 只读/设置 fallback**（MCP 用现有工具框架新增一个 UI 工具，不改协议）。

### 3.2 与 mute / 滑动 / tap 的冲突

- mute 按钮当前 `(8,160)` 56×56（B2）；Phase B 日志页会覆盖该区域 → B1 把 mute 迁到顶栏
  `mute_hit_` 44×44 @ `(376,0)`（视觉 24×24 @ `(386,10)`，见 3.1），语义不变（仍走 `ToggleMute` 事件）。
- **静音必须常驻中文文字**（图标仅辅助；A/C 顶栏、B 的静音卡都显示）：
  - `kSynced && muted` → **“已静音 · 点顶栏解除”**；
  - `kSynced && !muted` → “未静音”；
  - `kFailed` → **“同步失败”**（灰/警示色，不显示“已静音”）；
  - `kNoEndpoint` → **“待同步”**；
  - `kSyncing/kToggling` → “同步中…” / “切换中…”。
- 点击反馈保留 B2 的 **200 ms 语义**：先落“切换中…” + `lv_refr_now()`，等服务端 POST/GET 确认后才落
  “已静音/解除”；失败落“同步失败”，**不得先伪装已静音**。
- 屏幕/控制台/HTTP 三处一致：UI 只读 `MuteController::status()`（`mute_controller.cc:224-227`），
  `MuteController` 仍是唯一真相；B2 的 228 overlay 在 A/B/C 不显示，但状态文字必须常驻。
- 静音 overlay（228×228）在 A/B/C 不显示；状态用顶栏文字 + 图标 + B 卡表示。
- 顶栏是 `container_/top_bar_` 的子对象；现有屏幕 tap/gesture 回调不会因按钮被误触发；
  但需要在真机确认“从顶栏开始的上下滑”是否仍被 screen 手势接收（LVGL gesture bubble 行为），
  若冲突则给按钮加 `LV_OBJ_FLAG_GESTURE_BUBBLE` 关闭/或在 gesture cb 里排除顶栏区域。

---

## 4. 480×320 布局与对象清单

现布局（HEAD）：脸 panel 480×228 @y=46（实际脸 228×228 居中，左右各 ~126 px 空白），
字幕条 464×84 @y=228，静音按钮 56×56 @(8,160)，顶栏 `top_bar_` 全宽、内容高度（`lcd_display.cc:420-432`）。
Phase B 三个视图**都隐藏 kawaii 脸**（`face_panel_` 加 HIDDEN，不删对象，便于回退/Phase C），
字幕统一 **60 px** 高；表情状态改用文字/小图标（顶栏 chip + B 卡）。

> **尺寸现实（避免布局数学对不上）**：当前 `top_bar_` 是 `LV_HOR_RES × LV_SIZE_CONTENT`（`lcd_display.cc:421`），
> `subtitle_bar_` 是 `464 × LV_SIZE_CONTENT`（`chd_esp32s3_box_board.cc:968`），**都不是固定的 84/24**。
> Phase B 不新建第二套 bar：沿用对象并显式固定高度——`lv_obj_set_height(top_bar_, 44)`（容纳 44×44 hit 容器）、
> `lv_obj_set_height(subtitle_bar_, 60)`，同时移除 `LV_SIZE_CONTENT`；字幕 y=260..320、日志区 y=44..260 的
> 数学都按这两个固定值算。若 CHD 自定义 UI 与 base `top_bar_` 冲突，则在 CHD 侧重建同名对象并保持 44 px，不并行两套。

### A（默认）：7 行日志 + 窄状态条

```
y   0.. 44  顶栏 480×44：常驻静音文字 | mute hit 44 | RSSI | SRAM | view hit 44
            （视觉仍按 24 px 画文字/图标，44 px 是触摸高度）
y  44..254  日志区 480×210：7 行 × 30 px = 210 px（20 px 字体，line_height 24）
y 254..260  6 px 留白
y 260..320  字幕条 464×60（x8，r10）
```

新增/替换对象：
- **复用 `top_bar_`（不建 `view_bar_`）**，固定 44 px、两行布局：
  第一行 y0..24：`state_chip_`(20px) + `mute_text_`(20px，完整中文)；第二行 y24..44：`rssi_label_`(14px) + `sram_label_`(14px)。
  右端 x376..472 固定 `mute_hit_`/`view_hit_`（44×44）；左端 0..368 给文字。宽度预算：mute_text 200 px + state 100 px = 300 < 368，
  静音时若仍超宽则隐藏 state chip，**优先保证“已静音 · 点顶栏解除”完整不截断**。
- `log_list_`（新，480×210）：7 个 `log_label_[7]`（或一个 `lv_label` 多行 + 手动换行），
  每行 `mm:ss tag text`，20 px 字体；超长省略。
- 复用 `subtitle_bar_`，高度改 60、y=260；`subtitle_label_` 保留 20 px。
- 隐藏 `face_panel_`、`mute_overlay_`、旧 `mute_button_`（迁移到顶栏）。

### B：6 卡 + 5 行（MVP 字体限制）

```
y   0.. 44  顶栏（同 A，常驻静音文字）
y  44..120  6 卡：3 列 × 2 行，卡 152×35，gap 3/6（顶栏 44 + 两行卡 70 + gap 6 + 日志 140 + 字幕 60 = 320，卡高 35 正好闭合）
            ①状态 ②静音 ③音量 ④RSSI ⑤SRAM ⑥音频帧(tx/rx)
y 120..260  日志 5 行 × 28 px = 140（common_20，line_height 24）
y 260..320  字幕 464×60
```

对象：`card_[6]`（**单行 `标签: 值`**，common_20，35 px 高；不设 11px 中文标题），`log_label_[5]` 用 **common_20**；A 的 `log_list_` 复用。MVP 受字体限制比样张少 2 行，字体版恢复 7 行。卡内静音值用短词 **已静音/同步失败/待同步**（152 px 放不下完整解除提示），完整“已静音 · 点顶栏解除”只在顶栏。
每 250 ms 只刷新变化的 value label；卡数值来自 §1 的 getter。

### C：8 行 + 浮层（MVP 字体限制）

```
y   0.. 44  顶栏（同 A，常驻静音文字 + dropped 计数）
y  44..244  日志 8 行 × 25 px = 200（common_20；line_height 24，25 px 行距不裁字）
y 244..254  10 px 留白
y 254..314  字幕 464×60
y 314..320  6 px 底边
浮层 240×132 @(232,48)：uptime / heap free/min / tx/rx frames / mute state / rssi
```

对象：`log_label_[8]`、`debug_overlay_`（半透明黑 70%，`LV_OBJ_FLAG_FLOATING` 或 `lv_layer_top()`），
overlay 内 5 行 ×20 px 数值（line_height 24）；默认常显，**不提供长按隐藏**（避免与单击 A→B→C 冲突）。
overlay **non-clickable**（`LV_OBJ_FLAG_CLICKABLE` 关闭，事件穿透到下层）；起点 y=48，不盖顶栏 0..44 和 mute/view hit 区；遮挡日志上部若干行；字幕固定在 y=254..314。

### 与 kawaii/静音/字幕关系

- **kawaii 脸 + 静音灰化（需 9哥 拍板）**：A/B/C 全部隐藏脸；不做删除、不动 `face_animation_init/SetEmotion` 代码。
  **这是产品决策**：Phase B 用信息屏替代脸，因此 **B2 的“静音脸灰化”也失效**，同时 C1 的六张不同表情在默认 UI 不可见；
  不等于 B2/C1 作废（切回/后续表情页仍可用），但**必须 9哥 明确同意** text-only 替代“脸灰化 + 六表情”，
  不能悄悄绕过 B2/C1 验收。若不同意：保留一个 64×64 灰度脸/表情缩略图在 B 卡或顶栏。
- **静音**：B2 的 56×56 按钮与 228 overlay 在 A/B/C 隐藏；顶栏改为 **常驻中文文字**
  （`已静音 · 点顶栏解除` / `同步失败` / `待同步`）+ 44×44 hitbox 图标（visual 24×24），B 卡同步显示同一文字；
  逻辑仍由 `Application::ToggleMute()`/`MuteController` 驱动，服务端唯一真相不变。
- **字幕**：统一 60 px；A/B 固定在底部 y=260；C 为浮层下方/上层，仍由 `subtitle_bar_` 重定位，
  不新造字幕逻辑。
- **手势/触摸**：脸隐藏后空白区域仍走 `ScreenClickCb`（tap 开/关对话）；日志区不接收点击（`LV_OBJ_FLAG_CLICKABLE` 去掉），
  避免吞掉屏幕单击；A/B/C 切换按钮独立命中。

---

## 5. 字体 MVP 策略

- 事实：lcd35 的 `BUILTIN_TEXT_FONT` 链接 **`font_noto_sans_basic_20_4`**（`main/CMakeLists.txt:116`）；
  runtime 另有 assets 里的 `font_noto_sans_common_20_4`（~1.29 MB cbin，6845 字，覆盖任意 ASR/TTS 中文）。
  Phase B **只用 common_20**，不引入任何新字体。
- MVP（Phase B）：
  - A 主文本/状态/卡片值：**runtime common_20**（已加载，零新增体积）；
  - **统一用 common_20**（零新增字体/flash）：
    A 7 行×30=210；B 5 行×28=140；C 8 行×25=200。line_height 用 `lv_font_get_line_height()` 实测（≈24）；
    **MVP 受字体限制，B/C 行数比样张少（5/8 vs 7/10），字体版再恢复**，不裁字、不硬塞。
  - 小标签（RSSI/SRAM/tag）：用 **`lv_font_montserrat_14`（LVGL 内置，零新增）** 或 runtime common_20。
- 字体替换单独一版（不在 Phase B 引入 basic_16/common_16/common_30）：
  - MiSans（中文常用子集，20 px，估 0.8–1.2 MB）+ JetBrains Mono（ASCII 子集，14/16 px，30–60 KB）；
  - 子集化后加进 `assets` 分区（8 MB，当前余量需在 B1 实测 `idf.py size`/assets 生成日志确认）。
- 字体切换只影响 `LvglTheme::text_font()`（`lvgl_theme.h:31`）与相关 label；Phase B 的结构验证不依赖字体，
  MVP 用现有字体即可评审布局。

---

## 6. 拆分、风险、人日

### B1：数据源 + 日志环 + A 布局（约 2 人日）

- 新增 `main/ui/ui_log.{h,cc}`（10 行环、mutex、快照、限流；无历史/无滚动）；
- 补只读 getter：`MuteController::status()`（`mute_controller.cc:224-227`）已有；`AudioService` 补 decode/playback getter；
  `Application` 补 tx 帧计数/静音状态；`SystemInfo::GetFreeSramSize()`；`WifiBoard::GetRssi()`（或 UI 侧条件读取）；
- A 视图对象（顶栏、7 行日志、60 px 字幕、隐藏脸/旧 mute 按钮）；
- 事件 hook 接入 §2.4；
- 验收：build lcd35、reviewer/verifier、刷机看 A 默认、7 行实时更新、mute 图标与服务器一致、长按不再假 click。

### B2：B/C 布局 + 切换（约 2 人日）

- B 6 卡（5 行日志）、C 8 行 + 浮层（MVP 字体限制，字体版恢复 7/10）；
- view 按钮 A→B→C，MCP fallback；不落 NVS（开机 A）；
- 触摸冲突测试（顶栏手势、mute 图标、face 隐藏后的 tap）；
- 验收：三视图切换无闪烁、卡片数值/浮层正确、重启回 A、无堆增长、reviewer/verifier + 刷机。

### 字体版（另开卡，约 0.5–1 人日）

- MiSans/JetBrains 子集化、assets 体积核算、替换 runtime font、真机字宽/行高校准。

### 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| LVGL 每帧刷新导致闪烁/CPU | 日志滚动卡顿 | 250 ms timer；只更新变化 label；不整屏 `lv_refr_now`；切换时一次性重建 |
| 日志环锁竞争 | 音频/WS 任务延迟 | 临界区 <50 µs；只在事件边沿写；快照在 UI timer |
| 内存 | PSRAM/LVGL 对象增长 | 固定数组 **2.2 KB SRAM**（10 行 1.1 + 快照 1.1）；对象复用；B1 实测 heap |
| 触摸冲突 | 误切换/误 mute | 3 s 开机 guard + 400 ms 手势 guard；按钮独立命中；脸隐藏但 tap 逻辑不动 |
| 字体 tofu/字宽 | 中文显示不全 | MVP 只用 common_20，B/C 行数降为 **5/8**；字体版恢复 B7/C10 |
| 事件缺失 | “thinking/barge”显示不实 | UI 标 `llm:emotion` / `tts:stop`，不伪造 ASR/LLM 行 |
| NVS 写磨损 | 切换频繁写 | 不落 NVS（开机 A） |
| 一次刷机混入非 UI 改动 | 回归风险 | 每步 build/review/verify/flash；diff 只含 UI/数据 getter 文件 |

---

## 7. 验收（Phase B）

1. 开机默认 **A**；7 行日志随 stt/tts/state/wake/mute 事件更新，时间戳递增。
2. 顶栏 view 按钮 A→B→C→A；B 6 卡（状态/静音/音量/RSSI/SRAM/帧）数值正确；B 5 行、C 8 行日志 + 浮层计数正确（字体版再恢复 7/10）。
3. 重启后回 A（不落 NVS）；C 不会意外成为默认。
4. mute 图标切换仍以服务器为准；静音 hold/`kFailed` 在 A 日志/B 卡正确显示；长按 5 s 无假 toggle（D1/D2 已修）。
5. 脸隐藏后，空白区 tap 仍 toggle 对话；上/下滑手势不回退；无触摸死区。
6. build exit 0、0 新增 warning；reviewer-firmware PASS；verifier-firmware VERIFIED；刷机前后报类别/bin md5。

## 8. 不做

- 不做 D 版；不做 Live2D/新角色形象；不改协议/鉴权/服务端；不在本卡改固件或刷机。
- 不伪造设备端没有的 ASR/LLM/barge 日志；不用样张文本冒充真机数据。
