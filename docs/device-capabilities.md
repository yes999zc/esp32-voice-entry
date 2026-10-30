# 板子能力矩阵（M3 实测）

固件 `chd-esp32s3-box-lcd35` / xiaozhi 2.5.3，服务端本仓库。
来源：`78/xiaozhi-esp32` 的 `main/mcp_server.cc` + 板级 `InitializeTools()`，
并与本板启动日志的工具列表逐条对齐。
**下表每个「实测」都来自 2026-10-26 23:55–00:05 的真机批量调用**（服务端
`/debug/tool` 逐个下发、等回执），不是从代码推断。

## 通信层：MCP over WebSocket

```jsonc
// 服务端下发
{"type":"mcp","payload":{"jsonrpc":"2.0","id":11,"method":"initialize",
  "params":{"capabilities":{"vision":{"url":"http://…/xiaozhi/vision","token":""}}}}}
{"type":"mcp","payload":{"jsonrpc":"2.0","id":12,"method":"tools/call",
  "params":{"name":"self.audio_speaker.set_volume","arguments":{"volume":90}}}}
```

设备回报同形，成功是 `result`（`{"content":[{"type":"text","text":"…"}],"isError":false}`），
失败是 `error`。不需要先 `initialize` 也能 `tools/call`；但 `capabilities.vision.url`
必须由我们下发，否则 `take_photo` 报 "Image explain URL or token is not set"。

**回执延迟**：普通工具 **4–21 ms**（RPC 级别），拍照 1.3–4.0 s，屏幕快照 0.15–0.33 s。

## 工具矩阵（普通工具，可接语音）

| 工具 | 参数 | 实测结果 | 耗时 | 副作用 / 坑 |
|---|---|---|---|---|
| `self.get_device_status` | — | 返回 `audio_speaker.volume`、`screen.brightness/theme`、`battery.level/charging`、`network.type/ssid/signal` | 5–6 ms | 只读 |
| `self.audio_speaker.set_volume` | `volume` 0–100 | 返回 `true`，随后 status 读到 60 / 90，与设置一致 | 11–12 ms | 写 NVS，跨会话保持 |
| `self.screen.set_brightness` | 0–100 | 返回 `true`；status 的 `brightness` 从 75 变到 90 | 6–10 ms | 与 `power_manager` 的亮度恢复有竞争，连续调用要防抖 |
| `self.screen.set_theme` | `light`/`dark` | 返回 `true` | 20–21 ms | 视觉未逐帧核对（屏幕刷新有延迟） |
| `self.camera.take_photo` | `question` | 设备拍 640×480 → JPEG → POST 到 vision_url → 回传描述 | **1.34 s（热）/ 4.02 s（冷）** | 同步阻塞，期间让出音频线程优先级 |
| `self.camera.set_camera_flipped` | — | 返回 `true`，翻转 hmirror+vflip 并写 NVS `chd_esp_box3/camera-flipped` | 9–13 ms | 是**切换**不是设置，连调两次会还原 |
| `self.AEC.get_mode` | — | `{"success":true,"message":"AEC语音打断模式处于开启状态"}` | 4–7 ms | — |
| `self.AEC.set_mode` | `kAecOff` / 其它（= `kAecOnDeviceSide`） | **会先关闭音频通道再回执 → 回执永远收不到，会话直接断** | 2.5 s 超时 | 见下方「关键发现 2」 |
| `self.screen.set_display_mode` | `0`=横屏 / `1`=竖屏 | 返回 `true`，`get` 立刻读到新值 | 6–9 ms | **重启后生效**；写 NVS |
| `self.screen.get_display_mode` | — | 返回 `0`（当前横屏） | 6–8 ms | — |

## 工具矩阵（用户级工具）

固件标 `user_only`，语义是「人通过 App 手动做」。我们**不注册给 LLM**，但 M3 全部实测过
（危险行动项除外）。

| 工具 | 参数 | 实测结果 | 耗时 | 结论 |
|---|---|---|---|---|
| `self.get_system_info` | — | version/language/flash_size=16 MB/mac/uuid/chip/最小堆 ≈1.05 MB | 9 ms | 只读，可留作自检 |
| `self.screen.get_info` | — | `{"width":480,"height":320,"monochrome":false}` | 12 ms | 只读 |
| `self.screen.snapshot` | `url`, `quality` 1–100 | 设备把屏幕截成 JPEG 用 multipart 上传，我们收到 **8.1 KB / 480×320** | 149–328 ms | 可用作「把屏幕内容发给 agent」 |
| `self.screen.preview_image` | `url` | **PNG 成功（57 ms）**；同一张图转成 JPEG 失败："Downloaded image is invalid" | 34–57 ms | 见「关键发现 3」 |
| `self.reboot` | — | **未执行**（策略：语音入口与自动测试都不重启设备） | — | 不接语音 |
| `self.upgrade_firmware` | url 等 | **未执行** | — | 不接语音 |
| `self.screen.preview_image` / `self.assets.set_download_url` | url | 未执行（后者会改素材来源） | — | 不接语音 |
| `self.system.reconfigure_wifi` | — | **未执行**（会让设备掉线进配网） | — | 不接语音 |

## 关键发现

**1. 监听模式与 AEC 是联动的，且已在真机上验证。**

- `AEC on` 时 hello 之后是 `[listen] start realtime`；
- `AEC off` 时是 `[listen] start auto`。

这条直接决定「能不能在它说话时插话」：realtime 才会在播放时继续送麦
（`application.cc:1062/1270`，见 `docs/best-practices.md`）。
**当前生效状态：AEC on / realtime**（M3 收尾时已确认恢复）。

**2. `AEC.set_mode` 是「会话终结」型工具。**

固件 `Application::SetAecMode()` 最后一句是 `protocol_->CloseAudioChannel()`：
先应用设置、弹通知、然后**主动断开音频通道**，工具回执再也发不出来。
所以：

- 调用方必须按「已下发、回执预期丢失」处理（`tools.py` 里 `SESSION_ENDING`）；
- 不能把它当成普通工具交给 LLM 自由调用（会莫名其妙挂断对话）；
- 真要切模式，流程是「切 → 等重连（或主动唤醒）→ 再确认」。

**3. 屏幕预览只吃 PNG，不吃 JPEG。**

`preview_image` 下载后用 `lv_image_decoder_get_info()` 判断有效性；
本固件编进的解码器是 PNG（`LV_USE_LODEPNG`），没有 JPEG 解码器。
同一张 480×320 图：PNG 41 KB → `true`；JPEG 8 KB → `downloaded image is invalid`。
**要用屏幕显示图，必须先转 PNG**（`sips -s format png in.jpg --out out.png`）。

**4. 拍照耗时取决于「冷热」。** 首拍 4.0 s（传感器出帧 + JPEG 编码线程启动），
第二拍起 1.3 s。视觉链路的体感上限在这里，不在模型。

**5. 音量与显示模式都写 NVS。** 音量跨会话保持（切 60 再切 90，重连后仍是 90）；
显示模式写进去但如果选竖屏，**要重启才生效**。

**6. 有 `set_camera_flipped` 这种「切换型」工具，没有「设为某值」的接口。**
调用前要先知道自己当前是翻/不翻（status 里没这个字段），所以要持久化记录状态，
否则会出现「翻回来时翻错一次」。

## 硬件层（与软件能力相关的部分）

| 项 | 事实 | 来源 |
|---|---|---|
| SoC | ESP32-S3 QFN56 rev0.2，8 MB PSRAM，16 MB flash | esptool / 启动日志 |
| 屏 | 3.5" ST7796 480×320（`screen.get_info` 确认），背光可调 | 工具回执 |
| 触摸 | FT6336 | 启动日志 |
| 音频 | ES8311（DAC）+ ES7210（4 路麦，TDM 4 slot），设备侧 AEC 已开 | 启动日志 |
| 摄像头 | **GC2145**（不是文档写的 OV2640/OV5640），DVP，RGB565 VGA | 启动日志 |
| 引脚复用 | 摄像头 / 扩展 IO / TF 卡共用引脚，二选一 | 厂商 README |
| 电池 | PowerManager + ADC，当前 `level 100 / charging false` | status 回执 |
| 配网 | **SoftAP**：SSID `Xiaozhi-XXXX`（X = STA MAC 末两字节）+ 网页 `http://192.168.4.1/`（表单 `POST /submit`）；源码另有 BLE BluFi 分支，**当前编译配置未启用** | 固件源码（见下） |

配网这条的源码依据（`[已核]`，行号以 `<xiaozhi-repo>` 当前分支为准）：

- 编译配置选的是热点：`main/Kconfig.projbuild:1077-1079`（`USE_HOTSPOT_WIFI_PROVISIONING`，`default y`）；
  构建产物 `sdkconfig:1169` 为 `=y`、`:1171` 为 `# CONFIG_USE_ESP_BLUFI_WIFI_PROVISIONING is not set`。
- 入口分支：`main/boards/common/wifi_board.cc:174` 的 `#ifdef CONFIG_USE_HOTSPOT_WIFI_PROVISIONING` →
  `:177` `wifi_manager.StartConfigAp()`；BluFi 在 `:188` 的 `#elif` 分支（`blufi.cpp` 只是可选实现，没编进去）。
- SSID 规则：前缀 `Xiaozhi`（`main/boards/common/wifi_board.cc:57`），拼装
  `"%s-%02X%02X"`（`managed_components/78__esp-wifi-connect/wifi_configuration_ap.cc:125`，取 STA MAC 末两字节）。
- 固定 `192.168.4.1` 是**SoftAP 自己的地址**（不是局域网 IP）：`wifi_configuration_ap.cc:129-134`
  直接返回 `http://192.168.4.1`，`:146-149` 用 `IP4_ADDR(..., 192, 168, 4, 1)` 设置 AP 的 ip/gw。
- 网页端点：根页 `:238`、提交 `POST /submit` `:359`、高级页 `/advanced/config` `:515` 与
  `POST /advanced/submit` `:558`（高级页可把 `ota_url` 写进 NVS，见 `:599-610`）。
- 真机侧证：串口日志出现过 SSID `Xiaozhi-0F64`（`docs/tasks/abcd-views/evidence/serial-persona2-2210.final.log`），
  与上面的 `%s-%02X%02X` 规则一致。

## 已知坑（更新）

- `take_photo` 的返回值是 **HTTP 响应原文**，固件不解析；我们回 JSON，双方都能读。
- 拍照同步阻塞（`TaskPriorityReset(1)`），连续拍照会掉音频帧。
- RGB565 未做字节交换会颜色异常；先查 `SetSwapBytes`，再考虑翻转。
- `set_theme` / `set_brightness` / `set_display_mode` 都改界面状态，连续调用要防抖。
- `AEC.set_mode` 会断会话（见发现 2）。
- `preview_image` 只吃 PNG（见发现 3）。

## 仍未测（有意为之）

- `reboot` / `upgrade_firmware` / `set_download_url` / `reconfigure_wifi`：
  会中断设备或改变固件/素材来源，策略上不自动执行。
- `set_theme` 的视觉效果（dark/light）只核对了回执，没有逐帧比对屏幕。
- 触摸（FT6336）没有任何 MCP 接口，只能靠固件 UI；要用作审批输入需要改固件。
- 电池电量与真实电量的对照（桌面常供电，`charging=false` 但 level 100，口径待查）。

## 屏幕与推送的边界（2026-10-27 实测）

| 能力 | 结论 |
|---|---|
| `self.screen.snapshot` | 返回 JPEG（multipart，字段 `file`，480x320，~6–12 KB），约 0.2–0.4 s。**只拍 active screen**，挂在 `lv_layer_top()` 上的东西拍不到 |
| `self.screen.preview_image` | 只吃 PNG；显示期间设备进入预览态，`Listening` 时会被状态 UI 盖掉，不能当动画通道用 |
| `notify`（服务端推 Ogg Opus） | 结构上不可用：tts stop 后设备回 `Listening`，而 notify 只认 `Idle`（`application.cc:642-650`）。WS 下只能排队、下次连上再播 |
| `llm` + `emotion`（服务端推表情） | 固件在 `application.cc:683-689` 分发 `display->SetEmotion()`，**任何设备状态都放行**（notify 是唯一被 Idle 门控的）。会话开着（Listening/Speaking）就能推；**设备完全 Idle 时 WS 会话已关闭，推不到** |
| 破坏性工具（`self.reboot` / `self.upgrade_firmware` / `self.assets.set_download_url` / `self.system.reconfigure_wifi`） | 不入语音、不入 MCP 工具表；只登记在 `config.yaml safety.confirm_tools`（固件真名，见 config 注释来源），由服务端语音确认闸拦截 |
| raw 通道 `/debug/mcp` | 对 `safety.confirm_tools` 直接 **403**，不下发；破坏性动作只能走 `/debug/tool`（需活会话 + 口头确认） |
| `POST /debug/emotion`（M7 Step 1，需 Bearer） | 向所有活跃会话（或 `session` 前缀指定的一条）推一句 `{"type":"llm","emotion":"…"}`，返回 `{"sent": n, "emotion": "…"}`；未知名 **400 且不下发**，无活会话 **200 `{"sent": 0}`**。设备完全 Idle 时会话不在，同样只能得到 `sent: 0`。表情名见 `src/persona.py`（Noto 表情表 + M7 换脸新增的 `listening`/`speaking`）；`SetEmotion` 对未知名字只记日志并忽略 |

```bash
# 表情推送（/debug/emotion 走 4411 的 Bearer 中间件，不匿名）
TOKEN=$(cat ~/.esp32-voice/control.token)
curl -s -X POST http://127.0.0.1:4411/debug/emotion \
     -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"emotion":"happy"}'
# 指定一条会话（按 session_id 前缀）：{"emotion":"thinking","session":"3f9a1b"}
```

### 主动性 v0（M7 Step 3）的状态查询端点

`GET /debug/proactive/status`（4411，需 Bearer）返回当前计数器，供真机验收与
「误触发 0 次」核对。字段：`enabled` / `dry_run` / `socket_alive` / `night` /
`hourly{used,limit}` / `muted_until` / `last_human_speech_at` /
`last_emotion_sent_at` / `last_spoke_at` / `today{attempts,spoke,face_only,no_session,dry_run,rejected}` /
`pending{count,by_kind,oldest_age_s,expired,dropped}` / `reminders{count,expired}` / `recent`（最近 5 条结构化记录）。
每次触发另打一行 `[proactive] {...}` 日志。

`pending` 是「用户没听到、等设备回来再补」的队列（任务完成 / 回包迟到两类）：
`count` 当前条数、`by_kind` 按类型计数、`oldest_age_s` 最老一条已等多久、
`expired` 30 min 过期丢弃数、`dropped` 超过上限 5 条丢最旧数
（上限/时长/重试间隔见 `config.yaml proactive.pending_*`）。
`reminders` 是尚未响的定时提醒：`count` 当前条数、`expired` 过期丢弃数（见下）。

```bash
TOKEN=$(cat ~/.esp32-voice/control.token)
curl -s http://127.0.0.1:4411/debug/proactive/status -H "Authorization: Bearer $TOKEN"
```

### 定时提醒端点 `/debug/reminder`（M7 Step 3，task-18）

三条路由都在 4411、都需 Bearer（中间件自动覆盖，无匿名例外）：

| 方法 | 路径 | 语义 |
|---|---|---|
| POST | `/debug/reminder` | 建一条提醒。`when` 接受 **ISO8601 本地时间**（`2026-10-27T15:05:00`）或**相对写法**（`+300s` / `+5m` / `+1h`）；不给 `when` 时按口语句子解析（`3分钟后提醒我喝水` → 文本 `喝水`；口语解析**必须带提醒意图词** `提醒`/`叫我`/`别忘`/`记得`，因为这是显式接口，给了 `when` 时不要求意图词）。返回 `{"ok":true,"now":"…","reminder":{"id","text","at","created_at"},"in_seconds":300}`，**`at` 是解析后的绝对本地时间（整秒）**，手搭场景不必再猜时区；`in_seconds` 四舍五入到整秒；`when` 非法或文本解析不出 → **400** |
| GET | `/debug/reminder` | `{"ok":true,"now":"…","count":n,"reminders":[{"id","text","at","created_at","in_seconds"}]}`，按 `at` 升序，`in_seconds` 同为整秒 |
| DELETE | `/debug/reminder/{id}` | `{"ok":true,"deleted":"r1"}`；未知 id → **404** |

```bash
curl -s -X POST http://127.0.0.1:4411/debug/reminder -H "Authorization: Bearer $TOKEN" \
     -H 'Content-Type: application/json' -d '{"text":"喝水","when":"+300s"}'
```

**口语句子支持的时刻写法**（意图词之外，至少要说中一种，否则不调度）：
- 相对：`三分钟后` / `五分钟后` / `半小时后` / `一个半小时后`（单位支持 `分钟/分/小时/钟头`）；
- 裸钟点：`九点` / `九点半` / `九点一刻` / `九点三刻` / `九点三十分` / `9:30` / `15:00`。
  中文数字按 1–99 的写法（含 `两`，如 `两点`），实际可用范围受时刻约束：小时 `0–23`、分钟 `0–59`；
  超范围（`二十四点`、`六十分`）或暂不支持的写法（`九点零五分`）返回 `None`，**不会**排到错误时刻；
- 半日词归一化（列的是**完整规则表**，`h` 为说出的钟点）：

  | 词 | 规则 | 例 |
  |---|---|---|
  | `凌晨` | `h==12` → 0；`h<12` → h；`h>12` → `None` | `凌晨十二点` → 00:00 |
  | `早上` / `上午` | `h<=12` → h；`h>12` → `None` | `上午十二点` → 12:00 |
  | `中午` | `h∈{11,12}` → h；`h∈{1,2}` → h+12；其余 → `None` | `中午一点` → 13:00；`中午十点` → `None` |
  | `下午` / `傍晚` | `h<12` → h+12；`h==12` → 12；`h>12` → h | `下午三点` → 15:00；`下午十三点` → 13:00 |
  | `晚上` / `夜里` / `今晚` / `今夜` | `h∈0–4` → h（凌晨时段，不偏移）；`h∈5–11` → h+12；`h==12` → 0 **且日期 +1 天**；`h>12` → `None` | `晚上零点` → 00:00；`晚上一点` → 01:00；`晚上五点` → 17:00；`晚上十二点` → 次日 00:00；`晚上十三点` → `None` |

  半日词的「日期 +1 天」与日期词的偏移**相加**：`明天晚上十二点` = 明天 +1 再 +1 =
  **后天 00:00**（`后天晚上十二点` = 大后天 00:00）。无法归一化的组合一律返回 `None`，不猜。
  显式日期词 + `晚上` 族的 0–4 点按「那一夜的凌晨」处理，日期再 +1：`今天晚上零点` = **次日 00:00**
  （不是今天 00:00——那已经过去，只会被 TTL 静默丢掉）。
- 口语缩写别名（只这五个，其余缩写一律不认）：`明晚`=明天+晚上、`后晚`=后天+晚上、
  `明早`=明天+早上、`半夜`/`午夜`=晚上（0 点档）。如 `明晚八点` → 明天 20:00、`半夜十二点` → 次日 00:00。
- **前缀残留守卫**：时间表达式左边的文字里若还留着没解析掉的时间片段（`明儿`/`今早`/`昨天`/
  `大后天` 等），一律返回 `None`（不排提醒、不回读）。我们没解析的写法只可能造成错时刻或脏 content，
  所以「不支持就说不知道」，绝不静默排到一个猜的时刻。普通内容不受影响：
  `提醒我买点水果` / `删除文件后提醒我九点开会` / `我有个会三分钟后提醒我` 都照常工作。
  同一条守卫也覆盖**未支持的日期语境**：`周末` / `月底` / `十月` / `下个月` / `周三` / `10月8号` /
  `假期` / `春节` / `国庆` 等出现在时间表达之前 → 一律返回 `None`（不排提醒、不回读），
  而不是把「周末八点」排成明天 08:00。
- 日期词：可显式带 `明天` / `后天` / `今天` / `今日`，按字面含义；**不带日期词时**，今天这个时刻
  还没到 → 今天，已经过了 → 明天（整点边界：正好等于当前分钟也算「已过」，取明天）。
  注意：显式指定**已经过去**的时刻（如 14:00 说「今天九点提醒我」）按字面保留：距原定时刻
  不足 `pending_ttl_min`（默认 30 min）时下一次 `tick()` 就**立刻播**；超过的则在下一次 tick
  直接计 `expired` 丢弃。这是按字面的正确结果，不是 bug。

到点由 `tick()` 转成 `scheduled` 触发（topic `reminder:<id>`），仍要过**七道**闸门：
到点说的话带自己的语境：有内容 → 「提醒你{内容}」（如「提醒你喝水」），没内容（「9:30 提醒我」）
→ 「提醒时间到了」。**不会**只念一个名词——提醒可能是几小时前设的。
被拒只动脸，无声；`dry_run: true` 时停在出声前。

**`status().recent` 保留最近 20 条决策**（`proactive.RECENT_KEEP`）：Step 3 的验收要在
30 分钟正常使用后判「误触发 0」，5 条会在你看到之前就把窗口截断。每条含 `kind`、
`outcome`（`spoke`/`face_only`/`dry_run`/`no_session`…）与 `rejected_by`。

**主动播报也能被打断**：`_barge_watch` 停「回答」靠取消 `turn`，但主动播报没有 turn，
所以 `_speak` 的送帧循环还检查 `self.speaking`——清掉就停（`[proactive] playback stopped early`），
否则你打断它，`tts_stop` 发了、音频帧还在继续送。

**闸门②「人刚说过话」按「正在说话」计时，不是按「说完」**：`human_silence_seconds`（默认 10 s）
读的是 `last_human_speech_at`，它在音频路径里**每一帧**由 VAD 的 `is_speech_detected()` 刷新
（`session._note_speech_in_progress`），不是只在段结束（`_handle_turn`）时刷新。否则一个人说一句
超过 10 s 的长句，闸门会以为房间安静、正好可以让它在句子中间插嘴——这是桌边同事最不能犯的错。
VAD 没有该探针时（测试里的假 VAD）会安全 no-op。

**提醒不轻易丢**：只有真的播出去（`spoke`）或被 `dry_run` 消费后才删除。没有 live 会话时
**保留**（不消耗 attempts / 每小时额度），被闸门拒也保留，30 s 后重试；只有超过
`pending_ttl_min`（默认 30 min，从原定时刻算）才计 `expired` 丢弃——用户明确要求的提醒，
晚一点比没有好。

**口语取消**（白名单，不是关键词猜测）：
- 前缀：`取消提醒…` / `不用(再)提醒了` / `不要(再)提醒了` / `不再提醒` / `停止提醒…` / `别(再)提醒了`；
- 句中短语：`(取消|删掉|删除)` + 可选指示词（`刚才那个 / 刚刚那个 / 刚才 / 刚刚 / 上一个 / 上个 / 那个 / 这个`）
  + 可选 `的` + `提醒`，**必须紧邻**——`删除刚才那个提醒`、`取消刚才的提醒`、`删除上一个提醒` 会取消；
  `删除文件后提醒我九点开会`（中间夹了「文件后」）**不**取消，正常建提醒；
- 命中后删掉**最近一条**提醒并口头回读「好，取消了。」（没有可删的不打扰）；
- 含 `特别` / `分别` / `告别` / `个别` / `再提醒我一次` 的句子**一律不取消**（宁可漏取消，不可误删）：
  `特别提醒我明天九点开会` 会正常建提醒；
- **否定句一律不取消**：`不要删除提醒` / `别删掉提醒` / `不用取消提醒` / `不删除提醒` 等
  （否定词 + 可选「再」+ `删除/删掉/取消` 前置守卫）——用户说「不要删」时反而删掉是最坏结果。
  注意 `不要提醒了` 仍是取消（否定词后面是「提醒」而不是删除/取消动词）。
  HTTP DELETE 按 id 精确删除。

**时间口径（整秒）**：提醒在建的时候就 `replace(microsecond=0)`，所以日志/接口里的 `at`、
内部比较用的时刻、`tick()` 的 `now >= at` 三者是同一个整秒值——不会出现「回显 15:05:00
却 15:05:00.6 才响」或「早 0.4 秒响」。`+300s` 这类相对写法从请求时刻起算，
截断到整秒，绝对值误差 < 1 s。**为什么是截断而不是 `ceil`/`round`**：截断让误差恒为
「早 0–1 s 且永不晚于请求的整秒边界」，`round` 会把误差变成 ±0.5 s 并可能比用户说的
时刻更晚；换成 `round` 就等于改了语义，不是优化。

**内存态**：提醒与待播报队列只在进程内存里，服务崩溃/重启即丢失（没有落盘，重启后不会补播）。

**无会话时的行为**：设备完全 Idle 时没有 WS 会话，`CONFIRM_TIMEOUT` 仍按老样子记
`today.no_session`（`outcome="no_session"`）后丢弃——它只是「还在等你确认」的提示，重问即可。
task-18 的两类则**保留**：待播报队列（任务完成 / 回包迟到）与定时提醒都留在内存里，
期间每秒被 `tick()` 探测一次，设备一回来有 live 会话就补播/补响，且不消耗 attempts
与每小时额度；超过 `pending_ttl_min` 才计 `expired` 丢弃。

**先动脸再动嘴**：闸门通过后先推 `llm+emotion`，等 `proactive.emotion_lead_ms`
（默认 600 ms）再 TTS；被闸门拒绝时**只动脸不出声**并计入 `face_only`。
**例外**：若拒绝原因是闸门①（设备忙 / 正在放音），**不推表情**——否则会把它正在用的说话脸盖掉，
看起来像说着话突然换了表情。其余拒绝（夜间、冷却、频率）仍只动脸不出声。

`proactive.dry_run: true` 时走完「闸门→表情→等待」后停在出声前，记
`outcome="dry_run"`，且仍占用每小时/话题窗口（便于上线前演练）。

状态 → 表情的唯一映射在 `src/persona.py:map_state_to_emotion()`（纯函数，未知状态回落
`neutral`）；`/debug/emotion` 是手动推送入口，对话状态则由 `Session.push_emotion()` 驱动，
固件/服务端各负责哪些状态见下文「状态-表情：谁负责」。

## 语音质量门：段能量、VAD、垫话与首帧（task-14，2026-10-27）

### 首帧分解（真机日志 `/tmp/barge-soak.log`，fast/deepseek-flash 路由）

`[tts] first frame N s after speech end` 的 `t0` 是 **VAD 段结束、`_handle_turn()` 开始**的时刻，
不含段尾 0.5 s 静音（`vad.min_silence`）。因此：

```
日志 first frame ≈ ASR + LLM + TTS synth + 下发（≈0.00–0.01 s 残差）
真实「人声结束 → 第一帧」≈ 0.5 s（VAD 挂尾）+ 日志 first frame
```

| 回合 | seg rms / 时长 | ASR | LLM | TTS synth | 日志 first frame | ASR+LLM+synth | 实测真实值（+0.5 s） |
|---|---|---|---|---|---|---|---|
| 讲一段话 #1 | 0.0179 / 1.97 s | 0.07 | 1.64 | 1.20 | 2.90 | 2.91 | ~3.40 |
| 讲一段话 #2 | 0.0185 / 1.81 s | 0.06 | 1.26 | 1.13 | 2.45 | 2.45 | ~2.95 |
| 再继续 | 0.0213 / 1.04 s | 0.04 | 1.39 | 1.23 | 2.66 | 2.66 | ~3.16 |
| 等一下（短答） | 0.0272 / 0.62 s | 0.03 | 0.86 | 0.21 | 1.10 | 1.10 | ~1.60 |
| 继续吧 | 0.0162 / 0.62 s | 0.03 | 1.02 | 0.76 | 1.82 | 1.81 | ~2.32 |
| 停止吧（短答） | 0.0210 / 0.62 s | 0.03 | 0.52 | 0.23 | 0.78 | 0.78 | ~1.28 |
| 幻觉段（修复前） | 0.0056 / 1.20 s | 0.04 | 0.94 | 0.26 | 1.25 | 1.24 | ~1.75 |

结论：**LLM 首句（整段回复完成时间）与 TTS 整段合成各占约一半**；段长本身不计入 first frame
（它在 t0 之前），但真实的 0.5 s VAD 挂尾必须加到体感上。因此本轮做了两件事：

1. fast 路由（`tools=None`，不会中途出现 tool_calls）打开**按句流式**：首帧只等
   「第一句生成 + 第一句合成」。DeepSeek 的 agent 路由仍不流式（tool_calls 风险）。
   每句新增 `[tts] sentence synth X s` 日志。
2. 垫话从「整句 TTS」换成 **160 ms 本地 chime**，见下。

> 真机 before/after 首帧数字由 Lead/verifier 复测；离线侧只能证明合成段被移出首帧路径。

**AC1 的 before 基线（已落盘，不是重跑数据）**：`/tmp/barge-soak.log`（2026-10-27 真机会话，
含两段 18–19 s 的无人在场回答）里共 **1 个假 ASR 段 / 1 个假 turn**：
`[seg] 0.0056 rms 1.20 s` → `[asr] 你是否还需要我？` → `[route] fast`（该文件 :161-162）。
采集方法：按 session 前缀筛 `[seg]`，取其后紧跟 `[asr]` 且 rms < 0.01 的段；专门的 30 s 静置
样本待 verifier 按下方复验方法补采。

### 段能量门（`src/audio.py:segment_rms/is_noise_segment`，2026-10-28 重修）

**旧判据（task-14，仅凭日志）**：`rms < 0.008 and 时长 >= 1.0 s` 才丢。当时只有
rms/时长，没有波形；后来用 4 份日志量化发现 **RMS 单独分不开**：接受段 p50=0.0059，
比丢弃段 max=0.0078 还低，0.008 已经切进人声区间。原「固有取舍」里写的耳语被误杀，
9哥 实际遇到的正是这个。

**真音频采集（2026-10-28，`docs/segments/20261028-102709/`）**：开启
`audio.capture_segments` 后用本板正常/小声说话，共 10 段，**全部是人声**。被旧阈值丢掉的
3 段（离线 ASR 复现，0.09 s/段）：
`dropped-0.0053-1.41s.wav` →「今天周几。」、
`dropped-0.0059-1.93s.wav` →「今天天气怎么样？」、
`dropped-0.0064-1.45s.wav` →「今天周几？」。另外 7 段 kept 的 rms 为 0.0084–0.0193、时长 0.77–6.53 s。

**反噪声实验**：Mac 外放白噪声 6 s、风扇样噪声 6 s 对着板子，**没有产生任何 VAD 段**。
→ Silero VAD 本身已经挡住非语音；RMS 地板只需挡数字静音/信道噪声，不必切人声。

**新判据**：

| 判据 | 值 | 依据 |
|---|---|---|
| RMS 下限 | **0.0025** | 低于实测最轻人声 0.0053（>2× 余量），高于数字静音 0.0005 |
| 低能量持续 | 1.0 s | 保持：只丢持续安静，不误伤短唤醒词 |
| 极短段 | < 0.3 s 在 `_on_audio` 丢弃 | `MIN_SEGMENT_SECONDS=0.3` **未放宽** |
| ASR 后兜底 | `_valid_text`：≥2 个字母数字 + 幻觉黑名单 | 见下 |

**幻觉黑名单**（`src/session.py:_HALLUCINATION_MARKERS`，归一化后匹配）：
`谢谢观看` / `感谢观看` / `谢谢大家观看` / `字幕` / `请不吝点赞` / `点赞订阅` / `订阅转发` /
`打赏支持` / `明镜与点点`。放行低能量段的代价是更多噪声会进 ASR，所以这层必须保留；
它只拦「看起来像句子」的静音幻觉，`今天周几？` 等正常问句不受影响。

**真 WAV fixture**：`tests/fixtures/segments/` 放 6 条（3 dropped + 3 kept，共 384 KB，
每个 ≤200 KB）：`dropped-0.0053/0.0059/0.0064`、`kept-0.0084-4.20s`、`kept-0.0086-1.96s`、
`kept-0.0110-0.77s`；`tests/test_noise_gate_real_audio.py` 断言 6 条全部
`is_noise_segment == False`，合成 rms≈0.0005 / 2 s 数字静音仍为 True。
`docs/segments/` 原始采集已 gitignore，fixture 只保留这 6 条。

- 短唤醒词（如 0.77–0.88 s）仍会送 ASR，由 `wake-only` 文本过滤处理，两层互不替代。
- rui 参考值：`vad_min_speech_ms=200`、`vad_end_silence_ms=600`
  （house-ear `src/rui/config/schema.py:331-374`）；我们取 `min_speech=250 ms`、
  `min_silence=0.5 s`（0.5 已小于 600 ms，且早前板上测得 <0.45 s 会切断句中停顿）。

### 延迟遮罩：thinking 表情（默认静音）

三段演进一句话：整句语音垫话（1.8 s）→ 160 ms chime（300 ms lead）→ **只动脸、不出声**。
9哥 2026-10-27：「哒会让人跳出去，而且有字幕，它显示正在聆听，我其实是能看着的，
没有必要有声音」——屏幕已有状态与字幕，声音反而抢注意力。

`conversation.thinking_face: "thinking"`（空串 = 完全不推）：段关闭后经
`conversation.proactive_chime_lead_ms`（默认 **300 ms**，sanitise 到 0–400 ms）推一次
`{"type":"llm","emotion":"thinking"}`，**不发声、不发任何 TTS 帧**。
口径：`_start_filler` 的 t0 是 `_handle_turn` 入口（= VAD 段关闭），已含 0.5 s 挂尾，
所以**真实体感 ≈0.8 s**（0.5 s VAD 挂尾 + 0.3 s lead）；日志 `at N s` 是段关闭口径。
`proactive_chime_lead_ms: 0` 表示**段关闭即推（真实 ≈0.5 s），不是关闭遮罩**；
关闭遮罩用 `thinking_face: ""`；配置 `None` 按空串处理。

- **跳过**：`_first_audio_at` 已置或 `_reply_ready` 已置 → 不改脸，日志
  `[face] face cue skipped (answer ready)`，避免回答前闪一下。
- **cue 必须自己收尾，不能靠状态流**：固件 `kDeviceStateSpeaking` 只 `SetStatus`、
  **不 `SetEmotion`**（`application.cc:1138-1147`）；只有 Idle/Connecting/Listening 会设
  emotion。所以「说话时脸还是思考状」不会被自动覆盖。`conversation.cue_restore_face: "neutral"`
  （空串 = 不收尾）在三条出口各恢复一次，且仅在 `_cue_pushed` 为真时执行：
  1. **真回答首帧发出时**（`_speak` 第一帧发送成功后，`announce=True` 才触发）
     → `[face] cue restore (first audio)`；
  2. **本段被拒绝**（wake-only / noise / 空文本；noise gate 在 cue 之前，通常无 cue 可收）
     → `[face] cue restore (rejected)`；
  3. **turn 结束 finally 兜底**（fire-and-forget，turn 被 cancel 也能发）
     → `[face] cue restore (turn end)`。
  恢复失败只记 `[face] cue restore failed <Type>`，不抛；cue 推送成功的日志是
  `[face] cue thinking at N s`。
- **失败可忽略**：无活会话（`alive=False`）直接跳过；`push_emotion` 抛错只记
  `[face] cue failed <Type>`，绝不影响 TTS/回合路径。
- 实现注意：chime 播放本身也会把 `_first_audio_at` 置位，**不要拿它当「回答已开始」的判据**
  （skip 判断同时看 `_reply_ready`）。

**可选音频 chime（默认关闭）**：`filler_chime_ms: 160` 可恢复 160 ms 880 Hz 软音；
默认 `0` = 静音（9哥 的判断）。chime 仍走 `announce=False`，不向设备下发 `tts_sentence`
（否则脸上会出现一行 `chime 160 ms`，`application.cc:717-730`），并复用同一 300 ms lead、
同一跳过条件与播放锁（chime 若等锁输给真回答会被丢弃，不会在回答之后/之上补一声）。
上限 300 ms：>300 clamp、1–19 ms 禁用、非数字回落 160，均只 warning、不静音。
**face 与 chime 同时开启时只推脸、chime 不响**：`_filler_after` 的表情分支直接 return，
音频路径不会被执行（`filler_chime_ms` 只是保留给「不用脸」的回滚场景）。
`filler_after_seconds: 1.8` 只服务「表情与 chime 都关闭」时的旧整句 TTS 回滚路径
（`thinking_face: ""` + `filler_chime_ms: 0` + 恢复 `filler_phrases`）。

### 状态-表情：谁负责哪个状态（Step 2，2026-10-27）

固件只在 Idle(`application.cc:1101-1110`) / Connecting(`:1116`) / Listening(`:1121`) 调
`SetEmotion("neutral")`；`kDeviceStateSpeaking` 只 `SetStatus`、不 `SetEmotion`(`:1138-1147`)。
所以「说话」必须由服务端补，其他状态不要重复推、避免两边互相覆盖。

| 状态 | 表情 | 谁推 | 现状 |
|---|---|---|---|
| idle | neutral | **固件**（Idle 状态） | 已工作，服务端不重复推 |
| listening | neutral | **固件**（Listening 也是 neutral） | 与 idle **同表情**；`persona` 里虽定义了 `listening` look，但服务端**不推** |
| thinking | thinking | **服务端**（task-17 cue，300 ms） | 首帧/被拒/turn end 三个出口自收回 |
| speaking | speaking | **服务端**（`_speak(..., answer=True)` 首帧发出后） | 新增；**每个 turn 只推首句一次**（流式多句不重发），turn 结束回 neutral |
| tool-running | thinking（语义映射） | 暂无人推 | 映射已定义，留给后续卡 |
| confirm-pending | confused（语义映射） | 暂无人推 | 映射已定义，留给两步确认卡 |

- **speaking 只在确实播了「主回答」音频时推**：`_speak(...)` 的 `answer=True` 参数只由
  `_run_turn` 的回答路径传入；发送第一帧、`announce=True` 且 `not _spoke_answer` 才置
  `_spoke_answer` 并推 `speaking`。因此：
  - 流式回答可能调用多次 `_speak`（每句一次），**每个 turn 只在第一句推一次**，
    不会每句重发 `llm/speaking` 导致 kawaii face 重启动画；
  - 空 audio、chime（`announce=False`）、确认回读（`_say_text`）与主动性播报
    （`answer=False`）都不推，以免和 proactive 的 emotion lead 叠加或破坏其事件序列。
- **与 cue 协调**：首帧时先 `_restore_cue_face("first audio")` 让 cue 收尾，`_cue_pushed`
  为假才推 `speaking`；cue 未收回（如 `cue_restore_face: ""`）时**不抢**同一帧。
- **turn 结束回 neutral（选 neutral 不选 relaxed）**：一段回答结束（`_handle_turn` /
  `start_text_turn` 的 finally）在确实播过音频（`_spoke_answer`）时推一次 `neutral`。
  固件在 Idle 本来就会 `SetEmotion("neutral")`，推同值是幂等的，也避免
  `relaxed → neutral` 的二次闪烁。**这条清脸独立于 `cue_restore_face`**：即使
  `cue_restore_face: ""`（cue 永不恢复），只要本 turn 播过回答音频，turn end 仍会把
  speaking 收回 neutral；`cue_restore_face` 只控制 thinking cue 自己在三条出口的恢复。
- 所有状态推送失败只记 `[face] state failed <state> <Type>` / `cue restore failed`，不抛、
  不阻塞 TTS；`listening` 要真正脱离 idle 需要改固件（Listening 分支改设专用表情），
  不在本卡范围。
- **已知限制**：turn-end 的 `_kick_state_face()` 是 fire-and-forget（`_state_tasks` 持有
  引用防 GC），服务进程关闭时不 await 这些推送，最后一条 neutral 可能丢失；设备断开/Idle
  时固件会自行设 neutral，实际影响仅限「进程退出瞬间的脸上残留」，重启后自然恢复。

### agent（hermes）路由首帧归因（task-16，只归因，未改）

真机日志 `/tmp/server-4.log`（2026-10-27 12:21，task-14 上线后）：

| 回合 | seg | ASR | hermes 首句* | 首句 synth | 下发 | 日志 first frame | 真实(+0.5 s VAD) |
|---|---|---|---|---|---|---|---|
| 中奖故事 | 6.12 s | 0.14 | 1.61 | 0.30 | 0.02 | 2.07 | ~2.57 |
| 富婆/神功 | 20.13 s | 0.50 | 2.07 | 0.19 | 0.02 | 2.78 | ~3.28 |

\* 统一口径：hermes 首句 = first frame − ASR − 首句 synth − 下发（两行同一公式）。

结论：agent 路由首帧的 **75–78% 是 hermes 自己的首句延迟**（1.61 / 2.07 s），TTS 首句 synth
只有 0.19–0.30 s（hermes 本来就走按句流式），ASR 0.14–0.50 s 是第二项。所以：
- 换 TTS/缩短遮罩都救不了 agent 首帧；本轮能做的是让 thinking 表情在段关闭 300 ms
  （真实 ≈0.8 s）先给视觉反馈，把 1.8 s 的「静默 + 迟到的哒」变成「脸先变、随后回答」。
- **能否对 agent 路由安全按句流式？** 文本已经在流式（`on_sentence`），瓶颈是 hermes 在
  首个句子出现前要先跑 agent loop。若要「先猜一句再说」，必须在 tool_call 到达时
  `tts_stop` + 丢弃已播内容 + 撤回字幕，用户会听到半句错误答案；而且 tool-call 回合常常
  在调用前没有可播文本，收益接近 0，风险是说了不该说的话。**结论：不实施**。
- 可选后续（需产品决策，不在本卡）：把「长句闲聊、无任务词」继续留在 fast 路由
  （当前 `_route` 以 `max_chars=20` 把长句直接送 agent，代价是丢 Hermes 记忆/工具），
  或给 hermes 加「先回一个极短确认 token」的协议能力（需改 Hermes，非本仓库）。

### 复验方法（Lead/verifier）

> 注意：流式路由下 `[llm] X s` 是「整段完成时间」，其中还包含 `on_sentence` 播放造成的读取停顿，
> **不能**和上表的 1.26–1.64 直接比；after 对比只看 `[tts] first frame X s` 与
> `[tts] sentence synth X s`（以及真实值再加 0.5 s VAD 挂尾）。

1. 30 s 静置：统计 `[seg] ... rms < 0.01` 之后出现 `[asr]` 的次数（期望 0；被门丢掉的会打
   `[seg] noise gate: dropped`）。
2. 同一句提问连续 3 次：记录 `[asr] X s`、`[tts] first frame X s`、`[tts] sentence synth X s`，
   与上表对比；真实值再加 0.5 s VAD 挂尾。
3. 遮罩时机：同一句触发 agent 路由，`[face] thinking cue at N s` 的 N 应 ≤0.4 s
   （**段关闭口径**，真实体感 ≈N+0.5 s）；若首帧在 0.4 s（段关闭口径）内就绪，应看到
   `face cue skipped (answer ready)` 且**没有任何 TTS 帧**（`[filler] first frame` /
   `[tts] first frame` 都不应因遮罩出现）；`thinking_face: ""` 时应完全没有 `[face]` 日志。

**已知限制（2026-10-27 第五轮后，别再当 bug 报）**
- 事件相对时间（`晚饭后`/`下班后八点`）不解析：`下班后八点`→None；`晚饭后提醒我八点`→按字面 08:00（AM/PM 歧义，未处理）。
- `傍晚十二点` 按 12:00（语义矛盾，表内约定）。
- `晚上五点整` 的「整」会留在提醒内容里（播报成「提醒你整」）。
- 前缀残留守卫是**安全侧**：任何未识别的时间线索（`明儿晚上`/`今早`/`昨天`/`大后天`）一律返回 None —— 宁可不排，也不在错时刻响。

**字幕的替换语义**（固件 `SetChatMessage`）：每来一句**替换**当前缓冲并从头逐字打
（`subtitle_text_ = content; subtitle_pos_ = 0; lv_timer_reset`），不做追加、不做滚动历史。
只有 `user`/`assistant` 进字幕条；`system`（WiFi/OTA/连接）回到上游底部栏。
打字速度 11 字/秒，快于正常语速，所以流式多句不会把上一句截断；验收时看到"每句重头打"是预期行为。

**唤醒方式（2026-10-28 核实，纠正此前说法）**
- **BOOT 键单击** → `HandlePrimaryButtonClick()` → `ToggleChatState()`（`chd_esp32s3_box_board.cc:841-852`），同时 `power_save_timer_->WakeUp()`。
- 唤醒词「你好小智」照常。
- **触摸目前不可依赖**：`InitializeTouch()` 会探 FT5x06 / GT911（`:1084-1104`），本机是否探到未确认；
  9哥 实测是用**按钮**连上会话的，所以脚本/文档里不要再写"点一下屏幕"。

