# 触摸排查交接（2026-10-28 12:0x）

**状态：已完成并真机验收**（最终构建 md5 `7e159681c3e10a2722d1560de6366d43`，2026-10-28 13:0x；收尾结论见 §6）。

> **范围决定（2026-10-28，HANDOFF §「本轮决策」第 2 条）**：触摸**只修 2 条** ——
> ① 幽灵锚点 ±30 px 死区、② 长按 >2 s 假 click；其余 **7 条明确不修**并逐条给原因（§6.5）。
> 本文件从此**不再使用「遗留」表述**：没打算修的东西不该挂在待办里。

> 给独立调研 agent 的完整交接。**结论：面板与驱动都没坏，卡在「LVGL 收到的坐标范围与屏幕不一致」。**
> 本文件只列可复现的事实与代码位置，不做进一步猜测。
>
> 2026-10-28 收尾更新：单击 / 点脸 / 上滑 / 下滑均已在真机验收；§1–§5 保留排查阶段原文（其中「indev 范围 320×480」已被 `docs/touch-research.md` §3.3 纠正），最新事实以 §6 为准。

## 1. 已确证的事实（都有真机日志）

### 1.1 硬件与驱动是好的
```
i2c scan 0x08..0x77: 4 device(s) ACK -> 0x18 0x38 0x40 0x68
addr 0x38 0xA3 chip-id = 0x64          ← FT6336 的 CHIP ID
addr 0x38 0x80 pd      = 0x46
FT5x06 0x00 mode = 0x00                ← WORKING（不是 monitor）
esp_lcd_touch_new_i2c_ft5x06 -> ESP_OK
GPIO3 (CTP_INT) level at init = 0
```
- 4 个 ACK 正好是板上四颗器件：`0x18` ES8311 / `0x38` 触摸 / `0x40` ES7210 / `0x68` IMU → **总线健康，无假 ACK**。
- 厂家确认 IC 是 **FT366 / FT6336**；出厂固件里 `gt911` 字符串是共享 BSP 的别板配置（**GT911 路线已作废**）。

### 1.2 面板能跟手（证明触摸感应正常）
让 9哥 在屏幕上慢慢画圈 5 s，采 41 个触点样本：
```
raw X: min=44  max=145  不同值=14
raw Y: min=289 max=449  不同值=14
```
→ **两轴都跟随手指**，不是死点、不是坏面板。

### 1.3 根因 A：`esp_lcd_touch_ft5x06` **没有实现坐标变换**
`managed_components/espressif__esp_lcd_touch_ft5x06/esp_lcd_touch_ft5x06.c`：
- `:205-207` 直接把**原始寄存器值**写进 `tp->data`
- `:227-234` 的 `get_xy()` 直接拷贝
- **全文没有实现 `swap_xy` / `mirror_x` / `mirror_y`**（三个字段只存进 config，从未使用）
- `esp_lvgl_port_touch.c` 也不做任何变换

→ LVGL 一直收到**竖屏原始坐标（320×480）**，而显示是 **480×320 横屏**，所以 `act=0(none)`（按不到任何对象）。

### 1.4 ~~根因 B（当前未解）：indev 范围与屏幕不一致~~ → ❌ **已证伪（2026-10-28）**

> **校准**：LVGL 9 的 indev **没有**「注册范围」这个概念——`lvgl_port_add_touch()`
> （`esp_lvgl_port_touch.c:41-88`）只做 `lv_indev_create` / `set_type` / `set_read_cb` / `set_disp`，
> 没有 x_max/y_max 参数。那行日志的值与**当时的 touch config 宽高**一致，不是 indev 范围
> （该中间版本源码未进 git，属强推断）。详见 `docs/touch-research.md` §3.3 与 §10.4「已证伪」。
> 单击真正通不了是**三层**：container 吃掉 CLICKED + 坐标被变换两次 + 幽灵点；已在 §6 全部修完。
> 下面的原始记录保留作历史。

补了映射之后（横屏语义下坐标落在屏内）：
```
touch mapping: x_max=320 y_max=480 swap_xy=1 mirror_x=1 mirror_y=0 int=-1 rst=-1
driver = FT5x06 (addr 0x38), indev registered x=0..319 y=0..479    ← ★
```
**LVGL 的 indev 注册范围是 320×480，而屏幕是 480×320。**
手指在 `x=436` 时，indev 认为 x 上限是 319 → 很可能被判越界 → 依然 `act=none`。

### 1.5 ~~现状：`pressed` 从不回落~~ → 现象真实，**解释已纠正（2026-10-28）**

> **校准**：LVGL **没有 pressed 锁存**——`data->state` 每帧由 `touch_cnt > 0` 重算
> （`esp_lvgl_port_touch.c:156-161`）。`pressed=1` 只说明「芯片这一帧仍报 ≥1 点」，也就是**幽灵触点**本身。

```
indev state: pressed=1 points=1 x=436 y=123 act=0(none)
indev state: pressed=1 points=1 x=364 y=52  act=0(none)     ← 坐标已跟随手指且在屏内
```
`pressed` 永远是 1、从不回到 0 → LVGL 凑不出「按下→抬起」→ **永远不会有 CLICKED**。
芯片持续报 1 个触点（静置时也有，坐标为面板底边附近 `raw(123,436)`），疑似底边电极卡住。
（裸板、无外壳、已撕保护膜，均排除结构/膜的原因。）

## 2. 现在接了什么（交互层）
| 通道 | 实现位置 | 状态（2026-10-28 收尾后） |
|---|---|---|
| **BOOT 键 → 开/关对话** | **已删除**（`iot_button` 注册链整体移除，见 §3） | ❌ 按厂家建议去掉（IO0 = SD_CMD，会互相干扰） |
| **上滑手势 → `ToggleChatState()`** | `chd_esp32s3_box_board.cc:586`（`LV_EVENT_GESTURE` 回调） | ✅ **真机已验**：上滑恰好 1 次切换；抬手 CLICKED 被 `face tap ignored: 155 ms after a swipe` 拦下 |
| 左右滑 / 下滑 | 空实现 / 原来被注释 | 下滑**真机已验**：idle 下滑出设置栏（`create_setting_box` in/out），上滑关闭；左右滑无动作 |
| **单击屏幕 → `ToggleChatState()`** | `:647` `ScreenClickCb`；收尾版另注册到 `container_`/`content_`（`:691`/`:694`） | ✅ **真机已可用**：底部字幕区 380259 开 / 386679 关，每次恰好 1 次 toggle |
| **点脸 → 表情反应 + 切换对话** | `:701` `FaceClickCb`；收尾版在 `~:500` 调 `tap_handler_` | ✅ **真机已可用**：394509 开 / 399199 关，各 1 次 toggle；表情被对话状态在 20–30 ms 后覆盖（本阶段只保留 toggle） |
| 唤醒词「你好小智」 | 上游实现，未改 | ✅ 真机可用（410519 idle→connecting→listening / 414899 thinking / 418569 speaking） |

**点击在哪一层被拦掉**：不是应用层。链条是
`触摸 IC → esp_lcd_touch_ft5x06（不实现 swap/mirror）→ 我们的包装层（补映射/过滤）→
LVGL indev（范围 320×480 与屏幕 480×320 不一致）→ lv_indev_search_obj（按不到对象, act=none）
→ LV_EVENT_CLICKED（从未产生）→ 应用回调`

## 3. 固件侧代码位置
板级文件：`05_Tools/xiaozhi-esp32/main/boards/chd/chd-esp32s3-box/chd_esp32s3_box_board.cc`
| 内容 | 位置 |
|---|---|
| `InitializeTouch()`（依次 probe 0x38 / 0x5D / 0x14，选驱动） | 约 `:1560-1620` |
| `InitializeTouch_ft6336()`（正式触摸初始化） | 约 `:1500-1560` |
| `InitializeTouch_gt911()`（含 `user_touch_process_coordinates` +80 偏移，**仅 GT911 分支**） | 约 `:1440-1500` |
| 触摸读取包装层（映射 + 越界丢弃 + 卡点丢弃 + 合成抬手） | `#if CHD_TOUCH_POINT_FILTER` 段，约 `:1331-1427`、`:1441+` |
| 手势表（唯一 `LV_EVENT_GESTURE` 回调） | `:246` 注册，`:560-600` 实现（只有上滑有动作） |
| 单击屏幕回调注册 | `:647` |
| 点脸回调注册 | `:701` |
| `HandleTap()` → `ToggleChatState()` + 日志 `CHD_UI: tap` | `:1688` |
| 开关宏 | `config.h`：`CHD_TOUCH_DIAG=0`、`CHD_TOUCH_PHANTOM_FILTER=0`、`CHD_TOUCH_POINT_FILTER=1`、`CHD_TOUCH_LOG_INDEV=1`、`CHD_TOUCH_FORCE_GT911=0` |

## 4. 今天刷过的固件（按时间顺序，全部有备份）
| # | 内容 | 刷后现象 |
|---|---|---|
| 1 | 清埋点（`4472e2f`，2,805,088 B） | 正常启动、SD 未接 → 无 SD 日志 |
| 2 | SD 冒烟（2,874,080 B） | `mount failed: ESP_FAIL`（exFAT）→ 卡格 FAT32 后 **mount OK、读写通过** |
| 3 | SD 诊断版（2,876,128 B） | 逐级打码：`card_init ESP_OK` → 确认硬件无问题；`partition type=0xee` = GPT/exFAT |
| 4 | task-29 触摸接管 + 去按键（2,870,880 B） | 启动/SD 正常；删除 BOOT 键后 `CHD_UI` **0 条** → 暴露"触摸从来没工作过" |
| 5 | 强制 GT911（2,870,608 B） | 0x5D/0x14 `NOT_FOUND`、`new_i2c_gt911 -> ESP_ERR_INVALID_RESPONSE` → **GT911 路线作废** |
| 6 | 三观测：扫描/身份/rst=IO47（2,871,392 B） | **4 个 ACK、0xA3=0x64** → 确认 FT6336；屏幕未被 IO47 影响 |
| 7 | 回 FT5x06 + 模式观测（2,870,512 B） | `mode=WORKING`、`poll: n=1` **出现触点** → 之前"没触摸"是因为 5 号固件把驱动弄坏了 |
| 8 | 幽灵点过滤（2,871,136 B） | 过滤未触发（幽灵点在 ±16 px 抖动，超出 ±2 px 判据） |
| 9 | 静音版（2,869,232 B） | 关闭全部轮询 → **仍无 `CHD_UI`** → 推翻"多读者抢数据"假设 |
| 10 | LVGL 视角观测（2,869,760 B） | 抓到 `act=0(none)`、`pressed` 永不回落、真实触摸是"第二个点" |
| 11 | 点过滤 + 映射（2,870,192 B） | **坐标终于落在屏内并跟随手指**（`x=364→431`），但仍 `act=none` |
| 12 | 合成抬手 + act 取样时机（2,870,880 B，**当前板上版本**） | `post-frame` 定时器 **0 次输出**；indev 范围仍 320×480 |

**当前板子可用能力（⚠️ 历史快照，已被 §6 取代）**：语音对话（唤醒词）、字幕、表情、SD 235 GB 读写 —— ~~只有触摸不可用~~。
**现状**：2026-10-28 收尾后触摸已可用（单击 / 点脸 / 上滑 / 下滑，8 条 PASS，见 §6.4）。

## 5. 给调研 agent 的建议起点
1. `esp_lcd_touch_ft5x06` 不实现 `swap_xy/mirror` 是**上游已知缺陷还是本版本问题**？（查该组件的 issue/CHANGELOG）
2. `esp_lvgl_port` 里 indev 的范围到底取的是 `touch.x_max/y_max` 还是 `lv_display_get_*_resolution()`？
   （决定 §1.4 的修法是"改 touch config"还是"改 lvgl_port 传参"）
3. 上游 xiaozhi / ESP-BOX-3 官方固件在 **480×320 横屏 + FT6336** 下是怎么处理的（是否有现成的正确配置可抄）。
4. `pressed` 不回落是否与"芯片持续报 1 点"有关；官方驱动是否提供 `esp_lcd_touch` 的超时释放机制。

---

## 6. 2026-10-28 收尾（A1-A5 + C1-C4）

> 结论：**单击已通，四角闭合，静置无幽灵，SD 读写期间不误触。** 最终构建 `build/xiaozhi.bin` 2,872,128 B，md5 `7e159681c3e10a2722d1560de6366d43`，已刷入当前板子。
> 代码在固件仓库 `<workspace>/05_Tools/xiaozhi-esp32`（分支 `feat/persona-face`）：基线 `9d3c445`，最终提交 **`d6efc16`**（仅本地；push 被拒，见 §6.5）。唯一改动文件 `main/boards/chd/chd-esp32s3-box/chd_esp32s3_box_board.cc`（+167/−37），未改组件、显示层、服务端。

### 6.1 最终代码改动（行号按 `d6efc16` 工作区）

| 编号 | 内容 | 位置 |
|---|---|---|
| A1 | FT5x06 `flags` 全部置 `false`，坐标只由板级 `TouchMapRawToDisplay()` 变换一次 | `~2123-2125` |
| A2 | 幽灵过滤改 sticky（判死后保持丢弃）+ 阈值 10→**30 px** | `~1405`、`~1480+` |
| A3 | `ScreenClickCb` 同时注册到 `container_` / `content_`（`content_` 在当前消息样式下为 `nullptr`，无害） | `691` / `694` |
| A4 | 点脸回调调 `tap_handler_` → 切换对话 | `~500` |
| A5 | boot guard 3 s，锚到**首个过滤帧**（不是 touch init） | `397` / `1429-1431` / `455` / `483` |
| C1 | 点脸补 400 ms 手势守卫 | `493` |
| C3 | 开机幽灵锚点：首个过滤帧学锚点，`reason "ghost"`，心跳打 `ghost=%u` | `1414`、`1474-1486` |
| C4 | 触摸 Y 镜像：常量 `1396-1397`，映射 `X=raw_y`、`Y=319-raw_x` | `1431-1444` |
| R1 | `if (kept==0) s_last_release_ms=now;`（合成抬手在点被 stale 丢光时也能生效） | 见 diff |

### 6.2 真机新发现（都改变了对根因的判断）

1. **幽灵点确实存在，且跨启动稳定。** 每次启动首读 `TD_STATUS=0x01 points=1`（无人触碰；boot log `I 518/519`），raw `(117,437~442)` → 映射 `(442,202)`。**H1 成立**（面板底边/右缘物理接触）；**H2（init 写 9 个寄存器自触发）未被排除**——首读在 init 之后，没有 pre-init 读数——但两者的软件修法相同（遮蔽）。
2. **幽灵点行为超出方案 A 的假设。** 手指按下时幽灵消失（真实手指占 index 0），抬手后幽灵回到锚点。仅靠「按索引 sticky」会把返回的幽灵当新点接回 → 20 ms 内指针跳变产生假 `Swipe Right`，2 s 后 stale 判死产生一次**延迟 toggle**（构建 #1 日志 `26468/26488/28508/28518`、`51598/51628/53638/53648`）。C3 的锚点解决。
3. **Y 轴整体翻转（实测）。** 可见左上角 raw `(319,10)` → 旧映射 `(10,319)`（左下）；可见左下角 raw `(0,44)` → 旧映射 `(44,0)`（左上）。旧固件点屏幕底部会落到顶部状态栏（无回调）→ 用户体感「底部一行没反应」。C4 改为 `Y=319-raw_x` 后四角闭合。
4. **点击链路时序**：按下→抬手 → `CLICKED` 在 **40–80 ms** 内，一次 toggle；无 2 s 延迟、无假滑动（最终版）。
5. **点脸的表情反应会被对话状态覆盖**：20–30 ms 后出现 `face emotion: neutral -> 0`，肉眼只见切换。A4 本阶段目标就是切换，表情玩法留后续。

### 6.3 构建与刷机

- 最终 bin：`build/xiaozhi.bin` **2,872,128 B (0x2bd340)**，md5 `7e159681c3e10a2722d1560de6366d43`；5 条 warning 全为基线既有的 `unused variable`；app 分区余量 **30%**。
- 刷前整片备份：`02_Archive/esp32-voice-firmware/rev-pre-clickfix-20261028-1243.bin`，16,777,216 B，md5 `e6a965fe364daa3ad6c1b105ca5df5fa`。
- `esptool flash-id`：16 MB / quad / 3.3 V；端口 `/dev/cu.usbmodem31301`（USB JTAG/serial debug unit）。
- 三次刷机均为 `idf.py flash`（write-flash @flash_args，**不动 `nvs@0x9000`**，WiFi 凭据保留）：

| # | 内容 | 结果 |
|---|---|---|
| 1 | md5 `a8c9cb38…`，2,871,840 B，A1-A5 + C1/C2 | 暴露幽灵回归 / 2 s 延迟 toggle |
| 2 | md5 `fa2de6b9…`，2,872,128 B，+C3 | 暴露 Y 翻转 |
| 3 | md5 `7e159681…`，2,872,128 B，+C4 | 当前板上，验收通过 |

- 启动日志（本地、已 gitignore，只引用路径）：`docs/segments/boot-preflash-20261028-1225.log`、`boot-postclickfix-20261028-1246.log`、`boot-ghostanchor-20261028-1255.log`、`boot-coordinates-20261028-1308.log`。

### 6.4 最终验收（构建 `7e159681`，用户在场逐项确认 + Lead 日志核对）

| # | 项目 | 结果 | 证据 |
|---|---|---|---|
| 1 | 开机正常、无 panic | **PASS** | `swap=1 mirror_x=0 mirror_y=1`、`ranges MATCH`、`ghost anchor learned at mapped(442,202)`；WiFi、Activation done、WS session 建立 |
| 2 | 静置无幽灵 | **PASS** | `indev points=0/pressed=0`；心跳 `kept_last=0`、`stale=0`、`ghost` 持续增长（833 s 时 24,495）；数分钟 0 条 `CHD_UI` |
| 3 | 点底部字幕区 | **PASS** | 380259 开（idle→connecting→listening）、386679 关，各恰好 1 次 toggle |
| 4 | 点脸 | **PASS** | 394509 开、399199 关，各恰好 1 次 toggle（表情被状态覆盖，预期） |
| 5 | 唤醒词「你好小智」 | **PASS** | 410519 idle→connecting→listening；414899 thinking；418569 speaking，有语音回答 |
| 6 | SD 持续读写 | **PASS** | 两轮 30 s（574279–609989、795089–830819），各 1728 KiB / 64 KiB/s；窗口内 0 条真实 `CHD_UI`（仅 START 提示文字含 "CHD_UI" 字样） |
| 7 | 配网/恢复入口 | **PASS（代码级）** | 未改任何 WiFi/MCP/配网代码（`git diff` 可证）；启动激活 + WiFi 重连正常；**未做清空 WiFi 的破坏性测试** |
| 8 | 文字/字幕/表情显示 | **PASS** | 无新报错；用户确认 |

附加实测：四角一致（TL `(16,18)` / BL `(34,319)` / 右缘 `x=442` / 底部 `y=319` / 脸中央 `(246,172)`）；连点 5 次恰好 5 次 toggle；上滑恰好 1 次切换，抬手 CLICKED 被 `face tap ignored: 155 ms after a swipe` 拦下；idle 下滑出设置栏（`create_setting_box` in/out）、上滑关闭；左右滑无动作。

### 6.5 收尾结论：只修 2 条，其余 7 条明确不修

> **2026-10-28 决定（HANDOFF §「本轮决策」第 2 条）**：本阶段触摸**只修 2 条**，其余 7 条**明确不修**并逐条给原因。
> 本节原来叫「遗留 / 风险」，现在不叫了——没打算修的项不该挂在待办里。

**要修的 2 条**

| # | 问题 | 处理 |
|---|---|---|
| ① | **幽灵锚点 ±30 px 死区**（锚点 `(442,202)`，脸右侧的真实触摸被吞） | 待修（缩小死区，或按位移判定复活） |
| ② | **长按 >2 s 假 click**（stale 判死后合成 release → CLICKED） | 待修（长按不产生合成抬手，或按按下时长抑制 click） |

**不修的 7 条（原因写死，别再翻）**

| # | 问题 | 为什么不修 |
|---|---|---|
| ③ | 会话中幽灵漂出 30 px 回落 sticky，**可能**重现 2 s 延迟 toggle | 需长时间会话才有机会复现，本轮 833 s 会话零观测；收紧判据会把真实触摸一起丢掉（30 px 已覆盖实测 ±16 px 抖动），风险 > 收益 |
| ④ | 冷启动 3 s 内先按住屏幕，锚点会学成手指位置 | 窗口 ≤3 s 且操作反直觉；加「锚点合法性校验」等于引入新的误判面，代价高于收益 |
| ⑤ | 滑动后 >400 ms 才抬手仍可能双 toggle | 400 ms 手势守卫是既有启发式上限，拉长会吃掉「滑完立刻点」的正常操作 |
| ⑥ | 2.8" 变体共用同一组镜像常量、**未标定** | 本 SKU 不发货；标定必须真机四角实测，出货前单独开卡，本轮不改代码 |
| ⑦ | 竖屏 `display_mode` 仍用横屏映射 | 产品形态是 480×320 常驻横屏，改映射要重跑四角验收，零收益 |
| ⑧ | 点脸的表情反应被对话状态在 20–30 ms 后覆盖 | 本阶段需求只是「点脸切换对话」；表情玩法属 M7 形象线（独立线），不在本卡 |
| ⑨ | 日志措辞 `boot guard ... after touch init` 实指「距首个过滤帧」 | 纯文案 nit；改一行日志要重新刷机取证，不值 |

**另外（不是触摸问题）**：**固件 push 仍未完成** —— `origin` 是上游 `78/xiaozhi-esp32`，无推送权限（HTTP 403），
提交仅本地 `d6efc16`。2026-10-28 决定：Lead 自查 fork（`yes999zc/xiaozhi-esp32`）推送，**保留 upstream**，**禁 force push**。
