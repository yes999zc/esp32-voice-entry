# 触摸单击深度调研（只读）

- 日期：2026-10-28（调研 11:5x；**收尾更新 13:0x**）
- 性质：调研阶段**只读**（未刷机、未开串口、未改代码）；**方案 A 已于 2026-10-28 12:4x–13:0x 实施、刷机、真机验收通过**。实施与验收事实见 `docs/touch-handoff.md` §6。
- 最终状态：**已实施 / 已刷机 / 已验收**（构建 `7e159681c3e10a2722d1560de6366d43`，2,872,128 B；单击、点脸、上滑、下滑均可用）。
- 目标：把「单击 = 开始/结束对话」查清，并给出可与「去 BOOT 键 + SD 卡」合并为一次刷机的最小方案。
- 标注约定：**【代码】** = 有 file:line 可查；**【日志】** = 有真机日志/文档记录；**【假设】** = 未实测；**【证伪】** = 有代码或日志足以排除；**【实测】** = 2026-10-28 收尾轮真机验证。

---

## 0. 结论（先看这 6 行）

1. **不是「手势识别没接」**。`LV_EVENT_GESTURE`（上滑）和 `LV_EVENT_CLICKED`（单击）两套回调都在，`ToggleChatState()` 也接好了；单击回调是**注册在根 screen 上，但落点被全屏 `container_` 吃掉**，回调永远不执行。【代码】
2. **面板确实报了一个「卡住的触点」**：FT6336 的 `TD_STATUS(0x02)=0x01`，点 1 event flag 恒为 `0b10 (contact)`，坐标恒在 raw `(126,429)` 附近；手离开 15 s 仍报 1 点。这是 `673d495` 说的事，**成立**。【日志】
3. 但「pressed 永不回落」只是表象；**LVGL 本身没有 pressed 锁存**——`data->state` 每帧由 `touch_cnt>0` 重新决定（`esp_lvgl_port_touch.c:156-161`）。【代码】
4. **还有一个此前没被指出的硬 bug**：板级包装层 `TouchMapRawToDisplay()` 做了一次 swap/mirror，`esp_lcd_touch_get_data()` 又按 `tp_cfg.flags` 做了一次；FT5x06 没有 `set_swap_xy/set_mirror_*`，所以通用层**真的会再变换一次**。坐标被变换两次。【代码】
5. 交接文档里「indev 注册范围 320×480 与屏幕不一致」的说法**不成立**：LVGL 9 的 indev 没有 x_max/y_max，`lvgl_port_add_touch()` 只做 `lv_indev_set_disp()`；那行日志的值与当时的 touch config 宽高一致，**不是 indev 范围**（该中间版本源码未进 git，属强推断）。【代码 + 推断】
6. **单击要通，必须同时修三层**：事件路由（container 吃落点）＋ 幽灵点释放（ sticky 过滤）＋ 坐标只变换一次。只修其中一层仍然点不出来。

> **2026-10-28 收尾**：三层均已按方案 A 修复并真机验收（A1 flags 全关 + A2 sticky/30 px + A3 注册 `container_`/`content_`，另加 C3 幽灵锚点、C4 Y 镜像）；单击/点脸/上滑/下滑均已可用，实测见 §9.1 与 §11。§0 的 6 条保留调研时结论。

---

## 1. 证据快照（2026-10-28 11:5x，**历史快照**，已过期）

| 项 | 值 |
|---|---|
| 固件仓库 | `<workspace>/05_Tools/xiaozhi-esp32`，分支 `feat/persona-face`，HEAD **2549a57** |
| 固件工作区 | **脏**：`board.cc` 993 行变更（约 +920/−73）、`config.h +38`、`README.md +43`，均未 commit |
| 本文固件行号对应 | `chd_esp32s3_box_board.cc` **md5 95eba617f34df3bf8a3b0543565a6cad**，mtime **2026-10-28 11:59:24**，2475 行 |
| 最后一次构建 | `build/xiaozhi.bin` **2,871,312 B**，2026-10-28 12:00:20；`docs/touch-changes-status.md:19-20` 明确写「未刷机」 |
| 板上实际固件 | 第 12 版 **2,870,880 B**（`docs/touch-handoff.md:98`），**不含** 11:59 的 `x_max=480` 修正 |
| 服务端 | `<workspace>/01_Code/projects/esp32-voice-entry`，HEAD **58ec0b6**，工作区干净 |
| 服务端相关性 | `src/` 内无 touch/gesture/tap 处理（只命中注释与 `Session` 的无关文字）；**单击完全在固件侧，服务端不需要改** |

> **⚠️ 本表是 2026-10-28 11:5x 的调研快照，状态已过期，保留作历史。实查（2026-10-28 13:0x 收尾 / 14:1x 复核）：**
> 固件 HEAD **`d6efc16`**、**工作区干净**（全部已 commit）、**刷入的构建 md5** **`7e159681c3e10a2722d1560de6366d43`**（2,872,128 B，**未从板上读回**——板上运行由启动日志证明）；
> 服务端 HEAD **`8f39c01`**（B1 静音实现 `4a398be`；本文写作时是 `58ec0b6`，巡检时曾为 `2feb7c5`）。
> 上表里的 `2549a57`、md5 `95eba617…`、「993 行未 commit」、「未刷机」都是**当时**状态，**不要据此判断现状**。

> 行号缩写：`B` = `main/boards/chd/chd-esp32s3-box/chd_esp32s3_box_board.cc`；`C` = `main/boards/chd/chd-esp32s3-box/config.h`。完整路径在 §13 索引里。

---

## 2. 硬件事实（带证据）

### 2.1 板子与屏

| 事实 | 值 | 证据 |
|---|---|---|
| SoC / 板 | ESP32-S3，CHD-ESP32-S3-BOX（3.5 寸版） | `sdkconfig:1135` `CONFIG_CHD_ESP32S3_BOX_LCD_35=y` |
| 显示分辨率 | **480×320 横屏** | `C:96-97`（`DISPLAY_WIDTH 480` / `DISPLAY_HEIGHT 320`）；`C:101` `swap_xy=true` |
| 屏驱动 IC（代码） | 代码实际调用 **ST7789** 驱动 | `B:1809` `esp_lcd_new_panel_st7789(...)` |
| 屏驱动 IC（资料） | 产品规格书写 3.5" 320×480 **ST7796U** | `docs/touch-investigation.md:90`（规格书原文检索） |
| 屏总线 | SPI3，MOSI IO6 / CLK IO7 / CS IO5 / DC IO4，40 MHz | `C:70-74`；`B:1746-1754`；`B:1794-1802` |
| 背光 | IO47 | `C:76` |
| 屏复位 | `GPIO_NUM_NC`（无 GPIO 复位） | `C:74`；`B:1806` |

> **注意两处与口头描述不一致**：① 屏是 **480×320**，不是 320×320；② 代码用 ST7789 驱动一块规格书标 ST7796U 的屏。后者能显示，但属于既有事实矛盾，**未证实**是否影响触摸（触摸不走这条 SPI）。

### 2.2 触摸控制器

| 事实 | 值 | 证据 |
|---|---|---|
| 型号 | **FT6336**（厂家确认；芯片 ID 佐证） | `docs/touch-handoff.md:17-18`；`docs/HANDOFF.md:157-166` |
| 芯片 ID | `0xA3 = 0x64` | 【日志】`docs/touch-handoff.md:11` |
| I2C 地址 | **0x38**（7-bit） | `B:2053` `ESP_LCD_TOUCH_IO_I2C_FT5x06_ADDRESS`；【日志】扫描只有 `0x18/0x38/0x40/0x68`，`docs/touch-handoff.md:10` |
| 寄存器位宽 | **8-bit**（FT5x06 语义） | `B:2056` `lcd_cmd_bits = 8` |
| 总线 | **I2C port 1**，SDA **IO8**，SCL **IO18**，400 kHz | `B:1730-1743`；`C:18-19`；`C:137`；`B:2059` |
| 中断 | **CTP_INT = IO3**，但 FT5x06 路径 **不注册中断**（`int_gpio_num=NC`），只把 IO3 配成输入+上拉观测 | `C:41`；`B:2040`；`B:2099-2107` |
| 复位 | **无 CTP_RST 网络**；代码 `rst_gpio_num=NC` | 引脚表/PCB 网表见 `docs/touch-investigation.md:88-89`；`B:2039` |
| 原生坐标 | 竖屏 **320×480**（raw），横屏靠 swap | 【推断，与日志一致】raw X 44–145 / raw Y 289–449（`docs/touch-handoff.md:23-25`）；`docs/touch-handoff.md:40` 记录旧配置 `x_max=320 y_max=480` |

> **INT 不参与 FT5x06 路径**这一点很重要：任何「中断没清 / release 事件丢失」的假设，在当前配置下都没有可执行的机制——驱动是纯轮询（`B:2036-2050` 没有中断注册；`esp_lvgl_port_touch.c:59-64` 只在 `int_gpio_num != NC` 时注册）。

### 2.3 板上其它 I2C 器件（判断「0x38 是不是触摸」的旁证）

`0x18` ES8311、`0x38` FT6336、`0x40` ES7210、`0x68` IMU；全地址扫描 4 个 ACK，没有假 ACK。【日志】`docs/touch-handoff.md:10-17`

---

## 3. 固件驱动现状

### 3.1 初始化顺序

`B:2409-2413`（构造函数里的 `InitializeI2c → InitializeSpi → InitializeDisplay → InitializeTouch`）：

```
InitializeI2c()      B:1730-1743   i2c_new_master_bus(port=1, SDA=8, SCL=18)
InitializeSpi()      B:1746-1755   SPI3, 40 MHz
InitializeDisplay()  B:1789-1845   ST7789 + CustomLcdDisplay + SetTapHandler
InitializeTouch()    B:2160-2198   scan → identify 0x38 → probe 0x38/0x5D/0x14 → FT5x06 优先
```

`i2c_bus_` 只建一次，没有 `i2c_del_bus`；不存在「先触摸后显示」的句柄失效。【代码】

### 3.2 触摸初始化（FT5x06 路径）

`B:2015-2158` `InitializeTouch_ft6336()`：

| 步骤 | 行 | 说明 |
|---|---|---|
| 计算 width/height/mirror/swap | 2017-2034 | 当前工作区已改成 `width=480, height=320`；`mirror_x = !DISPLAY_MIRROR_X = true`；`swap_xy = true` |
| `esp_lcd_touch_config_t` | 2036-2050 | `x_max=480 y_max=320`、`rst=NC`、`int=NC`、`flags={swap=true, mirror_x=true, mirror_y=false}` |
| I2C panel IO | 2051-2061 | `0x38`、8-bit 寄存器、400 kHz |
| `esp_lcd_touch_new_i2c_ft5x06` | 2062-2065 | 返回 `ESP_OK`【日志】`docs/touch-handoff.md:14` |
| 读寄存器取证 | 2078 → 1544-1598 | 读 `0xA3/0xA8/0x80/0x00/0x02` |
| 强制 WORKING | 2083-2096 | 若 `DEVICE_MODE & 0x07 != 0`，写 `0x00=0` |
| IO3 观测 | 2099-2107 | 输入+上拉，无 ISR |
| 日志 | 2113-2128 | `touch mapping:` / `ranges: display=… touch=… MATCH/MISMATCH` |
| `lvgl_port_add_touch` | 2135-2141 | 注册 indev；`disp = lv_display_get_default()` |
| 帧后 act 定时器 | 2142-2149 | 300 ms `IndevActTimerCb` |

### 3.3 indev 是怎么注册的（关键纠正）

`lvgl_port_add_touch()`（`managed_components/espressif__esp_lvgl_port/src/lvgl9/esp_lvgl_port_touch.c:41-88`）：

- 只做 `lv_indev_create()` / `lv_indev_set_type(POINTER)` / `lv_indev_set_read_cb()` / `lv_indev_set_disp(indev, touch_cfg->disp)`（`:68-77`）。
- **没有** `x_max` / `y_max` / 范围参数；LVGL 9 的 indev 也没有「注册范围」这个概念。
- 因此交接文档里「indev registered x=0..319 y=0..479」**不是 LVGL 的 indev 范围**；该值与当时那版代码的 touch config 宽高一致，最合理的解释是它打印了 touch config（该中间版本源码未进 git，属强推断）。当前代码已改成打印 display 分辨率（`B:2113-2141`）。【代码 + 推断】

### 3.4 indev read 回调怎么读坐标

`esp_lvgl_port_touch.c:116-163`：

```
esp_lcd_touch_read_data(handle)                 // 调 tp->read_data
esp_lcd_touch_get_data(handle, touch_data, &touch_cnt, MAX)
if (touch_cnt > 0) { data->point = touch_data[0]; data->state = PRESSED; }
else               { data->state = RELEASED; }
```

两个硬事实：
1. **只用 `touch_data[0]`**（`:156-161`）。真实手指如果是第 2 点，LVGL 看不到它。
2. `pressed` 不是锁存状态，每帧由 `touch_cnt` 重算；`pressed=1` 只说明 chip 这一帧仍报 ≥1 点。

### 3.5 板级包装层做了什么

`TouchCountedRead()` 被安装成 `tp->read_data`（`B:2075-2076`），LVGL 每次轮询都经过它：

```
read_data(原驱动) → [PHANTOM_FILTER] → [POINT_FILTER] → [LOG_INDEV]
```

- `TouchMapRawToDisplay()`（`B:1353-1368`）：`swap ? (raw_y, raw_x) : (raw_x, raw_y)`，再按 `DISPLAY_MIRROR_X/Y` 取反。本板 `DISPLAY_MIRROR_X/Y=false`，所以**只 swap**。
- `TouchPointFilter()`（`B:1370-1460`）：越界丢弃 → ±10 px/2 s 卡点丢弃 → 合成抬手（`kForceReleaseMs=2500`，`B:1446-1456`）。
- `TouchLogIndevState()`（`B:1285-1318`）：在 `read_data` 内部打印 `pressed/points/x/y`，**取的是未经过通用层变换的值**。

### 3.6 通用层又变换了一次（核心 bug）

`managed_components/espressif__esp_lcd_touch/esp_lcd_touch.c:137-160`：

```c
bool sw_adj_needed = (mirror_x && tp->set_mirror_x == NULL) ||
                     (mirror_y && tp->set_mirror_y == NULL) ||
                     (swap_xy  && tp->set_swap_xy  == NULL);
if (mirror_x) x[i] = tp->config.x_max - x[i];
if (mirror_y) y[i] = tp->config.y_max - y[i];
if (swap_xy)  swap(x[i], y[i]);
```

FT5x06 驱动**没有实现** `set_swap_xy/set_mirror_x/set_mirror_y`（`grep` 该文件 0 命中），所以 `sw_adj_needed = true`，通用层会真的再变换一次。

当前工作区的实际变换：

```
raw (x, y)
 --TouchPointFilter-->  (y, x)                       // swap only
 --esp_lcd_touch_get_data-->  (x, 480 - y)           // mirror_x with x_max=480, then swap
```

所以落点会整体**转置并翻转**，具体方向由 raw 轴向决定，必须四角实测才能定；这不是「越界」，而是「变换两次」。旧版 #12 的 `x_max=320` 还会让 `320 - y` 对 `y>320` 变成 uint16 下溢（`320-437 → 65419`），表现为彻底越界。【代码 + 算术】

### 3.7 交互层现状

| 通道 | 实现 | 状态 |
|---|---|---|
| 上滑 → `ToggleChatState()` | `B:546-597`，`LV_DIR_TOP` 分支 `B:586-589`；注册在 `lv_scr_act()` `B:645` | 代码在；受同一条触摸链阻断（幽灵点占住 point 0 / 没有 release），不是 Kconfig 问题 |
| 单击空白 → `ToggleChatState()` | `ScreenClickCb` `B:440-457`；注册 `B:647` | **死代码**，见 §4A |
| 单击脸 → 表情轮换 | `FaceClickCb` `B:461-478`；注册 `B:701` | 依赖 release，见 §4B |
| 下滑 → 设置栏 | `B:590-593` + `create_setting_box()` | 代码在，未验证 |
| 左右滑 | 空实现 | — |
| BOOT 键 | 已彻底移除 `boot_button_` / `InitializeButtons` / `HandlePrimaryButton*`（`B:1704-1709` 注释；全文件无 `iot_button`） | ✅ 与 SD 改动同在工作区 |
| `HandleTap()` | `B:1774-1787`：`starting` 时进配网，否则 `ToggleChatState()` + `WakeUp()` | 只被 `B:1843` 的 `SetTapHandler` 调用 |

**上滑是在哪一层识别的？** 不是应用层自己算，是 **LVGL 内置 gesture 识别**（`LV_EVENT_GESTURE` + `lv_indev_get_gesture_dir()`，`B:546-557`）；注册在根 screen 上，靠子对象的 `LV_OBJ_FLAG_GESTURE_BUBBLE`（`lv_obj.c:593`）冒泡上来。

> **上滑为什么也没工作？** 它走的是 LVGL 的 **legacy 单指 gesture** 路径（`indev_gesture()`，`managed_components/lvgl__lvgl/src/indev/lv_indev.c:1773-1820`），不受 `CONFIG_LV_USE_GESTURE_RECOGNITION` 影响（后者只控制 `esp_lvgl_port_touch.c:132-154` 的多指 recognizer，本板确实没开）。legacy 路径要求 `indev->pointer.vect` 随手指移动；但 point 0 恒为幽灵点、真实手指是 point 1 且被 `touch_data[0]` 忽略，`act_point` 永远不动 → `gesture_sum` 不增长 → 不发 `LV_EVENT_GESTURE`。所以上滑和单击是**同一条链上的两个受害者**；把 §4 的三层修好，上滑会自然恢复（400 ms 的 tap-after-swipe 守卫仍然有效）。【代码】

---

## 4. 为什么单击仍然不可能：三层独立阻断

### A. 事件路由：`container_` 吃掉落点，`ScreenClickCb` 永远不是 target

- 默认 UI 在 `LcdDisplay::SetupUI()` 里创建了一个**全屏、默认可点**的 `container_`：`main/display/lcd_display.cc:906-913`（`lv_obj_set_size(container_, LV_HOR_RES, LV_VER_RES)`）。
- LVGL 9 的 `lv_obj` 构造函数默认带 `LV_OBJ_FLAG_CLICKABLE`：`managed_components/lvgl__lvgl/src/core/lv_obj.c:584`。
- `content_` 又是 `container_` 的子对象且可点：`lcd_display.cc:493`。
- 点击空白处时，`lv_indev_search_obj()` 命中的是 `container_` 或 `content_`，不是 screen；而 **`LV_OBJ_FLAG_EVENT_BUBBLE` 默认没有设置**（`lv_obj.c:584-593` 只给了 `PRESS_LOCK`/`SCROLL_CHAIN`/`GESTURE_BUBBLE`），所以 CLICKED 不会冒到 screen。
- 即使冒泡了，`ScreenClickCb` 的第一道守卫也会把它扔掉：`if (lv_event_get_target(e) != lv_event_get_current_target(e)) return;`（`B:445-446`）。
- 结论：`B:647` 注册的单击回调**从未执行**。这不是「坐标不对」，是「target 根本不是 screen」。【代码】

> **连字幕条也不是例外**：字幕条和 label 被显式去掉 CLICKABLE（`B:730`、`B:740`），但 LVGL 的命中测试对不可点对象只是「跳过并继续找兄弟」，不会把事件交给父对象（`lv_indev.c:636-651`）。字幕条下面是全屏可点的 `container_`，所以点字幕条命中的仍是 `container_`。`B:728-729` 的注释「must still reach the screen」是一厢情愿——**`ScreenClickCb` 在整个屏幕上都是死代码**，不只是空白区。

### B. 幽灵点：chip 永远报 ≥1 点，LVGL 永远没有 release

- `esp_lcd_touch_ft5x06.c:188-190`：`read_data` 读到 `points==0` 时**直接 return，不把 `tp->data.points` 清零**。
- `esp_lcd_touch_ft5x06.c:239`：`get_xy()` 在返回前把 `tp->data.points=0`。所以正常单读者时，release 不会被永久锁住；**能让 `pressed` 一直为 1 的只有 chip 每帧都报点**。
- 日志正是这样：`TD_STATUS(0x02)=0x01`，点 1 event flag=contact，raw `(126,429)`，手离开 15 s 仍 75 次触点。【日志】`docs/HANDOFF.md:160-166`、`:930-934`
- 真实的第二点会被 `touch_data[0]` 忽略（`esp_lvgl_port_touch.c:156-161`）。日志 `points=2` 时第一点是幽灵、第二点才是手指（`docs/HANDOFF.md:854-858`）。

### C. 坐标变换两次：即使 release 有了，落点也不对

见 §3.6。板级 `TouchMapRawToDisplay()` 与通用 `esp_lcd_touch_get_data()` 各做一次。当前构建（`x_max=480`）会把 raw `(126,429)` 变成 `(126,51)`；旧 #12（`x_max=320`）会下溢成 `(126,65419)`。【代码 + 算术】

### D. 附带发现：`forced release` / `act` 日志为什么一条都没有

- `docs/touch-changes-status.md:62-67` 已经怀疑「stale 丢弃让 `kept==0`，合成抬手分支 `kept>0` 永不进入」。
- 更严重的是 `TouchPointFilter` 的状态机 bug：`B:1400` `if (!track.seen || track.dropped || moved)` 会在**下一帧**把刚被 drop 的点重新接回，并把 `same_since` 重置；于是幽灵点每 2 s 只被丢 **1 帧**，其余时间仍被接受。`track.dropped` 本意是「已判死」，却成了「立即复活」的开关。（这是代码证实的行为；它是否就是 #12 没打出 forced release 的原因，**未证实**——也可能那版镜像/日志没覆盖到。）【代码】
- 这个 bug 在坐标修好之后会变成**每 2 s 一次 press→release**；如果落点在脸上，会周期性触发 `FaceClickCb`（`ScreenClickCb` 仍是死代码，见 §4A）。**当前构建直接刷上去有「每 2 秒自己变一次表情」的风险；若同时加了 A4，就会变成每 2 秒开关一次对话。**
- `IndevActTimerCb` 在 #12 上 0 输出（`docs/touch-handoff.md:98`）原因**未证实**；可能是 timer 未创建/未运行，也可能是刷的镜像不含该版本。不能拿 `act=none` 当证据——`act` 在 `read_data` 里采样时**永远是 NULL**（代码注释 `B:1308-1310` 自己承认），#8 那些 `act=0(none)` 日志（`docs/HANDOFF.md:854-856`）因此**无效**。

---

## 5. stuck point 的技术还原（`673d495` 说的到底是什么）

### 5.1 接口与值

FT6336 走 I2C `0x38`，8-bit 寄存器：

| 寄存器 | 含义 | 实测值 | 解码 |
|---|---|---|---|
| `0x02` | TD_STATUS | `0x01` | 低 4 位 = 1 点 |
| `0x03` | 点 1 XH | `0x80` | event flag=`0b10`（contact，按 FT5x06 惯例）、track id=0、X[11:8]=0 |
| `0x04` | 点 1 XL | `0x7e` | **X = 0x07e = 126** |
| `0x05` | 点 1 YH | `0x11` | Y[11:8]=1 |
| `0x06` | 点 1 YL | `0xad` | **Y = 0x1ad = 429** |

原始样本：`TD_STATUS points=1 (raw 0x01 80 7e 11 ad)`【日志】`docs/HANDOFF.md:166`。
坐标恒在 raw `(126,429)` 附近；换一次启动会变成 `(142,437)`，即 **±16 px 抖动**（`docs/HANDOFF.md:854-856`、`:911`）。

### 5.2 它为什么等于「永不抬手」

`esp_lvgl_port_touchpad_read()` 只看 `touch_cnt>0` 就置 `PRESSED`（`esp_lvgl_port_touch.c:156-161`）；LVGL 只在 **press→release** 边沿发 `LV_EVENT_CLICKED`。`points` 恒为 1，就没有 release 边沿，也就没有 CLICKED。这个推理链**成立**。

### 5.3 但 `673d495` 的结论不完整

它说「所以 LVGL 看到一个手指永远按着，永远发不出 click」——**对**；但它把「click 出不来」全部归给幽灵点。代码证明还有 §4A（事件路由）和 §4C（双重变换）两个独立阻断。**只修幽灵点，单击仍然不会通。**

---

## 6. 根因假设（按可能性排序，每条给验证方法）

### H1（最可能）面板/电极物理性持续接触 —— 【假设，强】

- **机制**：CTP 底边（raw y≈429/480）某一根电极/走线对地漏电或被 FPC 压住，ASIC 真的检测到电容，于是持续报 contact；真实手指出现时是**第二个点**。
- **支持**：点从静置就在、坐标固定在底边、芯片 ID/模式/总线都正常、真实手指能作为第二点跟手（`docs/touch-handoff.md:20-26`）；裸板/无外壳/已撕膜（`docs/touch-handoff.md:53`）。
- **只读验证**：看**开机第一次** `TouchReadRegs()` 打的 `FT5x06 TD_STATUS(0x02)=… -> points=…`（`B:1589-1597`，在 `B:2078` 调一次）。如果**上电后、任何人没碰之前**就是 points=1，则不存在「上一次触摸的 release 丢了」——只能是面板/ASIC 的实时接触。再配合静置 60 s 的 `indev heartbeat`（`B:1312-1316`）确认坐标不动。
- **判定**：开机首读 points=1 且坐标在底边 → H1 成立（软件只能遮，不能治）。

### H2（次可能）初始化写入了 FT5x06 的阈值/周期，FT6336 语义不同 → 自触发 —— 【假设】

- **机制**：`touch_ft5x06_init()` 无条件写 9 个寄存器（`THGROUP=70`、`THPEAK=60`、`PERIODACTIVE=12`、`PERIODMONITOR=40` 等，`esp_lcd_touch_ft5x06.c:289-323`），而 `rst_gpio_num=NC` 时 `touch_ft5x06_reset()` 直接返回（`:326-338`），等于没复位。FT6336 与 FT5x06 的寄存器映射若不完全一致，可能被置成自触发/未校准。
- **验证（一行日志 / 一次构建）**：在 `esp_lcd_touch_new_i2c_ft5x06()` **之前**读一次 `0x02`，之后立刻再读一次（当前 `TouchReadRegs()` 只在 init 之后）。若「写之前就有 1 点」→ H2 被证伪；若「写之后才出现」→ H2 成立，下一步试跳过这 9 个写或提高 THGROUP。
- **现状**：**未证实**；没有 pre-init 读数。

### H3（低）读清/中断/多读者导致状态残留 —— 【对当前配置基本证伪】

- FT5x06 路径 **不注册中断**（`int_gpio_num=NC`，`B:2040`），所以「中断没清」没有机制。
- `read_data` 在 `points==0` 时不清 `tp->data.points`（`ft5x06.c:188-190`），但 `get_xy()` 每次读完都清零（`:239`）；单读者时 release 最多迟到一帧，不会永久卡住。
- 多读者确实是真风险：`CHD_TOUCH_DIAG=1` 会额外起 200 ms poll + 10 Hz TD_STATUS（`B:1603-1698`），它们和 LVGL 抢同一个 `tp->data`、互相清点；但 `C:53` 当前是 **0**，静音版真机仍然失败（`docs/HANDOFF.md:880-905`）。
- **只读验证**：确认 `C:53` 为 0、`C:47` 为 0；全文件搜 `read_data` 只有 `TouchCountedRead` 一个安装点（`B:2076`）。→ 证伪。

### H4（不是假设，是已确认的次因）坐标轴/镜像导致落点错 —— 【代码证实】

- 双重变换见 §3.6。它**不**导致 pressed=1，但会导致「即使按下/抬起都对，点到的也不是你点的位置」。
- **验证**：不用刷机。按 `esp_lcd_touch.c:137-160` 的公式算一遍；或加一行 post-`get_data` 日志（见 §7 A4）对照 raw 与最终值。

### H5（证伪）LVGL indev 的 pressed 没被清 —— 【证伪】

- `data->state` 每帧由 `touch_cnt` 重算（`esp_lvgl_port_touch.c:156-161`），LVGL 侧没有独立的 pressed 锁存可清。
- **验证**：读代码即可；不存在 `lv_indev_set_state()` 之类的残留路径。

### H6（未证实）上电时序 / 无 CTP_RST + 与 LCD 共用复位 —— 【假设】

- 引脚表无 CTP_RST（`docs/touch-investigation.md:88-89`），CTP 与 LCD 共用 3V3/复位网络；若 CTP 在电源未稳时完成 baseline，可能锁在一个错误基线。
- **验证**：一次构建，把 `InitializeTouch()` 相对 `InitializeDisplay()` 延后 200 ms，或在上电后 0/100/500 ms 各读一次 `0x02`，看幽灵点何时出现。**未证实**。

---

## 7. 实施方案

### 方案 A（推荐，最小改动，一次刷机）

**改动文件**：只有 `B`（`chd_esp32s3_box_board.cc`）和 `C`（`config.h`）。**不改服务端、不改 `esp_lcd_touch`/`esp_lvgl_port` 组件、不改显示层。**

#### A1. 坐标只变换一次（3 行）

`B:2045-2049`，把 FT5x06 的 flags 全部关掉，让板级 `TouchMapRawToDisplay()` 成为唯一 owner：

```c
.flags = { .swap_xy = false, .mirror_x = false, .mirror_y = false },
```

`x_max=480 / y_max=320` 保持不变（`B:2037-2038`）。依据：通用层只在驱动没有 `set_*` 时变换（`esp_lcd_touch.c:137-160`），FT5x06 没有 `set_*`；而 `TouchMapRawToDisplay()` 已按 `DISPLAY_SWAP_XY=true` 做了 swap（`B:1353-1368`）。屏与触摸是同一块玻璃，显示侧也是 `swap_xy=true, mirror=false`（`C:99-101`），所以「只 swap」方向一致。

- 风险：若方向仍反，四角测试会暴露；届时只改 `TouchMapRawToDisplay()` 里的 mirror（加触摸专用宏），不动显示。
- 回滚：改回三行即可，无需回滚整个提交。

#### A2. 把幽灵过滤改成「粘住不复活」（约 10 行）

`B:1400-1418` 的状态机改为：

```c
if (!track.seen) { track.x=mx; track.y=my; track.same_since=now; track.dropped=false; }
else if (moved)  { track.x=mx; track.y=my; track.same_since=now; track.dropped=false; }
// 已判死的点，只有移动超过阈值才复活
const bool stale = !track.dropped && (now - track.same_since) >= kPointStaleMs;
if (track.dropped)      { accept = false; reason = "stale"; }
else if (stale)         { accept = false; track.dropped = true; reason = "stale"; }
```

同时把 `kPointStalePx` 从 10 提到 **30**（`B:1340`），覆盖实测 ±16 px 抖动。这样幽灵点在第 1 次判死后**持续**被丢，真实手指（第 2 点）会连续被 compact 到 `coords[0]`（`B:1435-1440`），LVGL 才能连续看到真实坐标。

- **开机首点**：若幽灵点在开机 2 s 内被误当成「按下」，会在判死时产生一次 release → 可能触发一次 click。建议再加一个 boot guard：`s_touch_init_ms`，两个 click 回调在 `lv_tick_elaps(s_touch_init_ms) < 3000` 时直接 return（约 4 行，`B:440-457`、`B:461-478`）。
- 风险：真实长按 >2 s 会被判死（本项目只需要 click，不需要长按）；真实手指若恰好落在幽灵点 30 px 内会被忽略（幽灵在屏右缘，可接受）。
- 回滚：`CHD_TOUCH_POINT_FILTER 0` 即可退回原驱动直喂 raw（但单击仍被 §A 阻断，不建议单关）。

#### A3. 让 CLICKED 真正到达回调（约 10 行）

在 `SetupUI()` 的 `B:647` 之后，把同一个 `ScreenClickCb` 注册到真正会收到落点的对象上：

```c
lv_obj_add_event_cb(container_, ScreenClickCb, LV_EVENT_CLICKED, this);
lv_obj_add_event_cb(content_,   ScreenClickCb, LV_EVENT_CLICKED, this);
```

`container_` / `content_` 是 `LcdDisplay` 的 `protected` 成员（`main/display/lcd_display.h:22-23`），板级子类可直接用。保留 `B:445-446` 的 `target==current_target` 守卫即可（直接命中时两者相等）。

若希望「点顶部状态栏/底部条也能开对话」，再对 `top_bar_`/`status_bar_`/`bottom_bar_` 做同样注册，或给它们加 `LV_OBJ_FLAG_EVENT_BUBBLE` 并放宽守卫。最小版本只注册 `container_` + `content_` 就覆盖了中间空白区。

- 风险：点聊天区/空白区会开对话（这正是需求）；设置栏是后来创建的 screen 子对象，不会被这条路径命中。
- 回滚：删两行。

#### A4. （产品决策）点脸是否也开对话（1–3 行）

当前 `FaceClickCb` 只做表情轮换（`B:461-478`），**不**调 `ToggleChatState()`。但脸面板覆盖 y=46..274、几乎全屏宽（`B:378-379`、`B:667-676`），用户最自然的落点就是脸。若坚持「单击 = 开/停对话」，建议在 `FaceClickCb` 末尾加：

```c
if (self->tap_handler_) self->tap_handler_();   // 表情反馈 + 对话切换
```

否则「点脸只会变表情」，用户会认为单击没生效。代价：对话中误触脸会结束对话；可在 `HandleTap()` 里按状态决定（例如只在 idle/listening 时切换）。

> ⚠️ **A4 必须在 A2 之后**：如果幽灵过滤还是「每 2 s 只丢 1 帧」的状态，A4 会把那一次 release 变成**每 2 秒自动开/关一次对话**。先确认 A2 的 sticky 过滤生效，再加 A4。

#### A5. （可选，验收用）post-get_data 坐标日志（5 行）

在 `IndevActTimerCb`（`B:1466-1513`）里，press 变化时打印 `lv_indev_get_point()` 的最终坐标。这是唯一能直接看到「LVGL 实际拿到什么」的位置；修完后应看到四角坐标与手指一致。

**方案 A 规模**：`B` +45/−12 行左右（30 px 阈值、boot guard、filter 状态机、两处点击注册、A4 一行）；`C` 0 行（若把阈值/宽限做成宏则 +2）；**需要改固件并刷机一次**；不碰 SD/BOOT 相关代码。

---

### 方案 B（更干净，但风险大，不建议赶这一次刷机）

- 删掉 `TouchMapRawToDisplay()` + 越界/卡点整段（`B:1353-1460`），把 `tp_cfg.flags` 恢复成 `swap_xy=true, mirror_x=?, mirror_y=?`，让 `esp_lcd_touch_get_data()` 做唯一变换；只保留一个 ~25 行的「幽灵点 anchor 过滤」和 A3 的事件路由。
- 规模：`B` +35/−100 行；**需要刷机**；方向需要四角标定，可能要第二次刷机。
- 优点：与 Espressif BSP 的标准路径一致，少一层私有数学。
- 缺点：方向不确定、diff 大、回归面大；不适合「一次刷机同时完成三件事」的窗口。
- 回滚：刷回刷机前的 16 MB 备份；代码侧改前先 `cp` 一份 `B`/`C`
  （**历史快照**：写这句时改动未 commit、不能靠 `git checkout` 找回；**2026-10-28 收尾后已提交 `d6efc16`、固件工作区干净**）。

### 方案 C（只做实验，不进产品刷机）

- 在诊断构建里试：① 跳过 `touch_ft5x06_init()` 的 9 个写；② 把 `THGROUP` 从 70 提高；③ 每次读后向 `0x02` 写 0 清状态；④ 上电延时 200 ms 再 init。
- 目的：判定 H2/H6，若某个实验能让幽灵点消失，就能在后续版本删掉过滤层。
- 风险：寄存器语义无 datasheet，可能把触摸弄得更糟；**只用于实验机**。
- 回滚：实验机刷回产品镜像（16 MB 备份）；不要把这版带进「一次刷机」。

### 推荐

**方案 A**。理由：diff 最小、不碰组件、不碰显示层、一次刷机就能和「去 BOOT + SD」合并；三层阻断都有明确的代码落点；失败可只回滚 `config.h` 的开关或重刷备份。

---

## 8. 与「去 BOOT 键 + SD 卡」合并成一次刷机

当前工作区**已经同时包含**三件事，不需要合并分支：

| 事项 | 现状 | 证据 |
|---|---|---|
| 去 BOOT 键对话用途 | `boot_button_`/`InitializeButtons`/`HandlePrimaryButton*` 全删；只剩注释 | `B:1704-1709`；全文件 `iot_button` 0 命中 |
| SD 卡 | `CHD_SD_ENABLE=1`，`SdCardProbe` + `SdStormTask` + MCP `self.debug.sd_storm` | `B:61-65`、`B:108-177`、`B:303-364`、`B:2370-2381` |
| 触摸（方案 A） | 在 `B`/`C` 上继续改 | 本文 §7 |

**刷机注意**（来自既有文档，不是本次实测）：
- 用 `write-flash "@flash_args"` 只写 bootloader/分区表/otadata/app/assets，**不写 `nvs@0x9000`**，Wi-Fi 凭据保留；整片 `0x0 merged-binary.bin` 会擦 NVS（`docs/HANDOFF.md` 的刷机记录）。
- 刷前备份当前 16 MB 镜像到 `02_Archive/esp32-voice-firmware/`（现有 `rev-touch-takeover-20261028-1127.bin` 等可作格式参考）。
- 恢复路径：USB-Serial-JTAG 始终可用（板级 `README.md` 的「恢复路径」节），触摸/LVGL 全坏也能重刷。
- 构建基线：**当时** `build/xiaozhi.bin` 2,871,312 B（**现为 2,872,128 B，md5 `7e159681…`**）；方案 A 预计 +0.5–1 KB，仍远小于 ota_0 分区。

**建议的提交拆分**（当时写的「不要在本会话执行」）：`fix(touch): one transform, sticky ghost filter, click routing` 与 `feat(board): drop BOOT dialogue + SD storm` 分开。
**现状**：调研会话确实没 commit，但收尾轮已提交 **`d6efc16`**（`fix(touch): route clicks to the containers and drop the stuck ghost point`，仅本地未推）。

---

## 9. 刷机后真机验证清单（≤8 条）

| # | 动作 | 通过判据 |
|---|---|---|
| 1 | 冷启动看前 3 s 日志 | `0xA3=0x64`、`DEVICE_MODE=WORKING`、`ranges: display=480x320 touch=480x320 MATCH`、只有 LVGL 一个读者（`DIAG=0`）；无 panic |
| 2 | 静置 60 s 不碰 | 0 条 `CHD_UI`、0 条 `face tap`；`post-frame heartbeat state=RELEASED`、`points=0`（若 post-frame timer 仍 0 输出，用 `indev heartbeat` 判，等价） |
| 3 | 点空白区一下，再点一下 | 每次恰好 1 条 `CHD_UI: tap -> ToggleChatState`；状态 idle→聆听/连接，再点回 idle；无连发 |
| 4 | 点脸一下 | 恰好 1 条 `face tap -> reaction N`；若采纳 A4，同时恰好 1 条 `tap -> ToggleChatState`（不能 0 条，也不能 2 条） |
| 5 | 四角各点一次 | A5 日志里最终坐标落在对应角 ±20 px；无转置/镜像（左上→(0,0)，右下→(479,319)） |
| 6 | `self.debug.sd_storm(30)` 持续读写 30 s | `storm: START`→`STOP` 之间 **0 条 `CHD_UI`**；SD 无错误 |
| 7 | 空闲时短按 BOOT 键 5 次 | 0 条 `CHD_UI`（BOOT 不再切换对话）；SD 不报错 |
| 8 | 重启后再静置 10 min，做一轮完整对话 | 0 次自发切换；唤醒词/字幕/表情不受影响；上滑应恢复为只切换 1 次（与单击不叠加） |

### 9.1 实测结果（构建 `7e159681`，2026-10-28 13:0x）

| # | 结果 | 实测证据 |
|---|---|---|
| 1 | **PASS** | `touch mapping: swap=1 mirror_x=0 mirror_y=1`、`ranges MATCH`、`ghost anchor learned at mapped(442,202)`；WiFi / Activation done / WS session 建立；无 panic |
| 2 | **PASS** | 静置 `indev points=0 pressed=0`；心跳 `kept_last=0`、`stale=0`；`ghost` 计数持续增长（833 s 时 24,495）；数分钟 0 条 `CHD_UI` |
| 3 | **PASS** | 底部字幕区 380259 开（idle→connecting→listening）、386679 关，各恰好 1 次 toggle；连点 5 次 = 恰好 5 次 toggle |
| 4 | **PASS** | 点脸 394509 开、399199 关，各 1 次 toggle；表情反应被 `face emotion: neutral -> 0` 在 20–30 ms 后覆盖（预期，本阶段只要 toggle） |
| 5 | **PASS**（改用映射/点击坐标核对） | 四角一致：TL `(16,18)`、BL `(34,319)`、右缘 `x=442`、底部 `y=319`、脸中央 `(246,172)`。A5 实际实现为 boot guard（不是原计划的 post-get_data 日志），故未逐次打印 post-get_data 坐标 |
| 6 | **PASS** | 两轮 30 s（574279–609989、795089–830819），各 1728 KiB / 64 KiB/s；窗口内 0 条真实 `CHD_UI`（仅 START 提示文字含 "CHD_UI" 字样） |
| 7 | **未按原判据执行** | BOOT 键对话用途已删除，本轮未单独连按 5 次复测；替代证据：未改 WiFi/MCP/配网代码（`git diff` 可证）、启动激活 + WiFi 重连正常，记为**代码级确认**；未做清空 WiFi 的破坏性测试 |
| 8 | **部分通过** | 唤醒词 410519/414899/418569（idle→connecting→listening→thinking→speaking，有语音回答）；上滑恰好 1 次切换且抬手 CLICKED 被 `face tap ignored: 155 ms after a swipe` 拦下；显示正常。**未做「重启后静置 10 min」的长时间复测** |

---

## 10. 事实 / 假设分栏

### 10.1 代码证实

- 触摸 IC 在 `0x38`，8-bit 寄存器（`B:2053-2056`）。
- I2C port 1 / IO8 / IO18（`B:1730-1743`、`C:18-19`）。
- FT5x06 路径 `int=NC`、`rst=NC`（`B:2039-2040`），IO3 只观测（`B:2099-2107`）。
- `lvgl_port_add_touch` 只设 read_cb + disp，无范围参数（`esp_lvgl_port_touch.c:68-77`）。
- `data->state` 每帧由 `touch_cnt` 重算（`esp_lvgl_port_touch.c:156-161`）。
- 通用层会二次应用 swap/mirror（`esp_lcd_touch.c:137-160`），FT5x06 无 `set_*`。
- 板级 filter 又做一次 swap（`B:1353-1368`）。
- filter 的 `track.dropped` 会在下一帧被重置（`B:1400-1405`），幽灵点只丢 1 帧/2 s。
- `container_`/`content_` 全屏且默认可点（`lcd_display.cc:493,906-913`、`lv_obj.c:584`），CLICKED 不冒泡（`lv_obj.c:584-593`），`ScreenClickCb` 的 target 守卫（`B:445-446`）→ 回调是死代码。
- BOOT 键代码已移除（`B:1704-1709`）；SD 代码在工作区（`B:61-65` 等）。

### 10.2 日志证实

- `0xA3=0x64`（FT6336）、4 个 I2C 器件、`new_i2c_ft5x06=ESP_OK`、`mode=WORKING`、`indev reads≈166/5s`（`docs/touch-handoff.md:10-16`）。
- 静置 15 s 仍报 75 次触点；`TD_STATUS raw 01 80 7e 11 ad`（`docs/HANDOFF.md:160-166`、`:930-934`）。
- 真实手指是第 2 点：`points=2 x=226 y=308` 与 `points=1 x=142 y=437` 同时出现（`docs/HANDOFF.md:854-856`）。
- `pressed` 从不回 0（`docs/touch-handoff.md:46-52`）。
- 画圈时两轴跟随手指（`docs/touch-handoff.md:20-26`）。
- #12 的 `post-frame` timer 0 输出（`docs/touch-handoff.md:98`）。

### 10.3 假设待验（2026-10-28 收尾后更新）

- **H1 面板/电极物理漏电 → 成立。【实测】** 每次启动首读 `TD_STATUS=0x01 points=1`（无人触碰，boot log `I 518/519`），raw `(117,437~442)` → 映射 `(442,202)`，跨启动稳定；软件只能遮蔽。
- **H2 9 个 FT5x06 写让 FT6336 自触发 → 未排除。【假设】** 首读发生在 init 之后，没有 pre-init 读数；与 H1 的修法相同（软件锚点遮蔽）。
- **H6 无 CTP_RST / 上电时序导致 baseline 错误 → 未验证。** 本轮未做延时 init / 上电多点读取实验。
- **`IndevActTimerCb` 为何在 #12 上 0 输出 → 仍未查证。** 最终构建心跳（`kept_last`/`stale`/`ghost`）正常输出，说明机制本身可用；#12 的 0 输出最可能是所刷镜像不含该段代码，但未核对。
- **ST7789 驱动 ST7796U 屏是否影响触摸 → 未验证（预计无关）。**

### 10.4 已证伪

- 「indev 注册范围 320×480」——LVGL 9 没有这个范围；日志值最合理的解释是 touch config 宽高（`esp_lvgl_port_touch.c:68-77`；中间版本源码未进 git，强推断）。
- 「LVGL pressed 没清」——每帧由 `touch_cnt` 重算（`:156-161`）。
- 「GT911 / 0x5D / 0x14」——0x5D/0x14 都不 ACK，`0xA3=0x64` 证明是 FT 系（`docs/touch-handoff.md:10-18`）。
- 「IO47 是触摸复位」——IO47 是背光（`C:76`），实测无改善（`docs/HANDOFF.md` 12:0x 段）。
- 「多读者互相清状态是主因」——`DIAG=0` 的静音版仍 0 条 `CHD_UI`（`docs/HANDOFF.md:880-905`）。

---

## 11. 未证实 / 下一步只读实验（2026-10-28 收尾后逐条标注）

1. **幽灵点是否在上电首读就存在（H1 vs H2 的分水岭）→ 已验证（H1 成立）。【实测】** 每次启动首读 `TD_STATUS=0x01 points=1`（无人触碰，boot log `I 518/519`），raw `(117,437~442)` → 映射 `(442,202)`，跨本次多次启动稳定（更早两次样本 `(126,429)`/`(142,437)` 见 §5.1）。但首读在 init 之后，**H2 仍未被排除**。
2. **FT6336 的 event flag 编码是否严格等于 FT5x06 惯例（`0b10=contact`）→ 仍待验。** 没有该型号 datasheet，只有 `0xA3=0x64` 与厂家口头确认；本轮未做寄存器级实验。
3. **单次 swap 后的真实方向（是否需要 mirror）→ 已验证并修正。【实测】** 单次 swap 后 **Y 轴整体翻转**：可见左上角 raw `(319,10)` → 旧映射 `(10,319)`（左下），可见左下角 raw `(0,44)` → 旧映射 `(44,0)`（左上）。C4 改为 `X=raw_y`、`Y=319-raw_x` 后四角闭合（TL `(16,18)`、BL `(34,319)`、右缘 `x=442`、底部 `y=319`）。
4. **#12 的 `post-frame` timer 为什么 0 输出 → 仍未查。** 最终构建心跳正常输出，机制可用；#12 的 0 输出最可能是所刷镜像不含该段代码，未核对。
5. **#12 的 `x_max` 到底是 320 还是 480 → 仍未查。** 日志 `touch mapping: x_max=320 y_max=480`（`docs/touch-handoff.md:40`）是直接证据，但该中间版本源码未进 git，无法逐行核对。
6. **幽灵点是否会随温度/时间漂移 → 仍只有有限样本。** 本轮 833 s 会话内锚点稳定（`ghost` 计数增至 24,495、`kept_last=0`、`stale=0`），但跨温度/长时间仍只有两次早期启动样本 + 本轮多次启动，不足以定论。

---

## 12. 只读复现命令（全部不改文件）

```bash
# 1) 确认芯片身份/驱动/地址
grep -n "ESP_LCD_TOUCH_IO_I2C_FT5x06_ADDRESS\|lcd_cmd_bits" \
  main/boards/chd/chd-esp32s3-box/chd_esp32s3_box_board.cc | sed -n '1,10p'

# 2) 确认通用层会二次变换，且 FT5x06 没有 set_*
sed -n '137,160p' managed_components/espressif__esp_lcd_touch/esp_lcd_touch.c
grep -n 'set_swap_xy\|set_mirror_x\|set_mirror_y' \
  managed_components/espressif__esp_lcd_touch_ft5x06/esp_lcd_touch_ft5x06.c   # 0 命中

# 3) 确认 indev 没有范围参数
sed -n '41,88p' managed_components/espressif__esp_lvgl_port/src/lvgl9/esp_lvgl_port_touch.c

# 4) 确认全屏 container 可点、且 CLICKED 不冒泡
sed -n '906,913p' main/display/lcd_display.cc
sed -n '584,593p' managed_components/lvgl__lvgl/src/core/lv_obj.c

# 5) 确认 filter 的 dropped 复活 bug
sed -n '1396,1418p' main/boards/chd/chd-esp32s3-box/chd_esp32s3_box_board.cc

# 6) 构建产物里确认日志字符串（不刷机）
strings -a build/xiaozhi.bin | grep -E 'ranges: display|indev heartbeat|forced release'

# 7) 看清 gesture 走的是 legacy 路径（不依赖 CONFIG_LV_USE_GESTURE_RECOGNITION）
sed -n '1773,1820p' managed_components/lvgl__lvgl/src/indev/lv_indev.c
```

---

## 13. 引用索引（本文所有 file:line 的完整路径）

- `B` = `<workspace>/05_Tools/xiaozhi-esp32/main/boards/chd/chd-esp32s3-box/chd_esp32s3_box_board.cc`（md5 `95eba617f34df3bf8a3b0543565a6cad`，2475 行）
- `C` = `<workspace>/05_Tools/xiaozhi-esp32/main/boards/chd/chd-esp32s3-box/config.h`（174 行，md5 `bf04816f44f8b6db88dc29fd683b46bd`）
- `main/display/lcd_display.cc`（`LcdDisplay::SetupUI`，默认 UI 分支从 `:886` 开始）
- `main/display/lcd_display.h`（`container_`/`content_` 在 `:22-23`，`protected` 在 `:15`）
- `managed_components/espressif__esp_lvgl_port/src/lvgl9/esp_lvgl_port_touch.c`（v2.9.0）
- `managed_components/espressif__esp_lcd_touch/esp_lcd_touch.c`
- `managed_components/espressif__esp_lcd_touch_ft5x06/esp_lcd_touch_ft5x06.c`
- `managed_components/lvgl__lvgl/src/core/lv_obj.c`（LVGL 9.5.0）
- `managed_components/lvgl__lvgl/src/indev/lv_indev.c`（`pointer_search_obj` `:1654-1668`；命中测试 `:618-652`）
- `managed_components/lvgl__lvgl/Kconfig`（`LV_USE_GESTURE_RECOGNITION` 只控制多指 recognizer，默认 n；legacy 单指 gesture 不受它影响，`:878-881`）
- 服务端：`docs/HANDOFF.md`、`docs/touch-handoff.md`、`docs/touch-changes-status.md`、`docs/touch-investigation.md`（HEAD `58ec0b6`）

---

## 14. 一句话交接

**幽灵点是真的（`TD_STATUS=0x01`，raw `(126,429)`），但它只是三层阻断之一；另外两层是「全屏 container 吃掉 CLICKED」和「板级+通用层各变换一次坐标」。按方案 A 三处一起改，才可能在这一次刷机里让单击起/停对话；只修幽灵点，仍然点不出来。**
