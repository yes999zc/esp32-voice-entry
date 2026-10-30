# 触摸改动现状说明（给独立调研 agent 的输入）

> 作者：impl-face（实现者），2026-10-28。
> 状态：**已被 2026-10-28 收尾更新**（A1-A5 + C1-C4，已刷机并真机验收；最终构建 md5 `7e159681c3e10a2722d1560de6366d43`）。
> §0–§4 是 11:5x 的「最后一版未刷机」工作区快照，保留作历史；**最终代码、行号与结论以 §1.1 为准**。
> 证据链、12 次刷机对照、交互层现状见 Lead 的 `docs/touch-handoff.md`，本文不重复。

## 0. 工作区状态（回答 Lead 的问题：**保留，未回退**）

```
仓库 <workspace>/05_Tools/xiaozhi-esp32，分支 feat/persona-face
 M main/boards/chd/chd-esp32s3-box/chd_esp32s3_box_board.cc   (+993 / -73)
 M main/boards/chd/chd-esp32s3-box/config.h                   (+38)
 M main/boards/chd/chd-esp32s3-box/README.md                  (+43)
未 commit、未刷机。   ← 2026-10-28 11:5x 的历史快照
```

> **⚠️ 上面这段「未 commit、未刷机」已过期（保留作历史）**：2026-10-28 收尾后——
> 已提交 **`d6efc16`**（唯一文件 `chd_esp32s3_box_board.cc`，+167/−37；`config.h` 未再改）、
> **已刷机三次**（#1 `a8c9cb38…` → #2 `fa2de6b9…` → **#3 `7e159681…` 验收通过**）、固件**工作区干净**。

**保留**的理由：所有触摸改动都在 5 个宏后面，**能一键编译掉**（见 §2）。SD 卡与"去掉 BOOT 键对话用途"这两块**与触摸开关无关**，即使把触摸全部关掉也照常工作。

最后一次构建（"indev 范围修正 + 无条件 heartbeat"那版，**当时未刷机 → 后来已被 #3 `7e159681` 取代**）：
`EXIT=0`，`build/xiaozhi.bin` = **2,871,312 B**，新增 warning **0**（基线 5 条 `unused variable` 全部是既有的）。

## 1. 我在触摸链路上加了什么（文件内行号，当前工作区版本）

文件：`main/boards/chd/chd-esp32s3-box/chd_esp32s3_box_board.cc`

| 行范围 | 符号 | 作用 | 开关 |
|---|---|---|---|
| 1518–1542 | `TouchCountedRead` | **唯一入口**：被安装成 `tp->read_data`，LVGL 每次轮询都经过它；计数 + 依次调用下面的过滤器/日志 | 总是安装 |
| 1353–1368 | `TouchMapRawToDisplay` | raw→显示坐标：`swap ? (raw_y, raw_x)` + 按 `DISPLAY_MIRROR_X/Y` 取反 | `POINT_FILTER` |
| 1370–1459 | `TouchPointFilter` | ①越界丢弃 ②±10px/≥2s 卡点丢弃 ③**合成抬手** ④统计计数器 | `POINT_FILTER` |
| 1285–1317 | `TouchLogIndevState` | 在**同一读者内部**打印 LVGL 将看到的内容（`indev state:` / 10 s `indev heartbeat:`） | `LOG_INDEV` |
| 1466–1516 | `IndevActTimerCb` | **帧后**采样 `lv_indev_get_active_obj()`（300 ms lv_timer，在 LVGL 任务里跑）；本版已改成**无条件 5 s** 打 heartbeat + filter 计数 | `LOG_INDEV` |
| 1227–1277 | `TouchFilterApply` | 第一代"幽灵点"过滤器（判据：从未移动+从未抬起 ≥1.5 s）**已废弃**，仅留作参考 | `PHANTOM_FILTER`（0） |
| 1544–1601 | `TouchReadRegs` | 一次性寄存器取证：FT5x06 读 `0xA3/0xA8/0x80/0x02`；GT911 读 `0x8140/0x814E` | 总是跑（一次） |
| 1604–1645 | `TdStatusPollTask` | 10 Hz 直读 `0x02` TD_STATUS + `0x00` 模式 + IO3 电平 | `DIAG`（0） |
| 1647–1697 | `TouchDiagTask` | 200 ms 驱动级轮询 + `raw:` 变化日志 | `DIAG`（0） |
| 1858–1878 | `TouchScanI2cBus` | 全地址扫描 `0x08..0x77`，打印所有 ACK | 总是跑（一次） |
| 1880–1912 | `TouchIdentifyAddr38` | 用临时 io 读 `0x38` 的 `0xA3/0xA8/0x80` | 总是跑（一次） |
| 2015–2158 | `InitializeTouch_ft6336` | FT5x06 路径：`x_max/y_max` 本版已改成**显示尺寸**；`rst=NC`、`int=NC`；mode 检查（非 WORKING 则写 `0x00=0`）；`touch mapping:` / `ranges:` 日志 | — |
| 2160–2205 | `InitializeTouch` | 先 probe 三个地址 → 按 `FORCE_GT911` 选驱动 | `FORCE_GT911` |
| 440 / 461 / 480 / 493 | `ScreenClickCb` / `FaceClickCb` / `FaceReactionResetCb` / `MakeChildrenNonClickable` | 交互层：screen 单击、脸单击（表情轮换 900 ms 回 neutral）、脸子树只剥子对象 | 无（交互，非触摸链路） |
| 546 / 632 / 647 / 655 / 701 | `gesture_event_cb` / `SetupUI` / 单击注册 / `SetupFace` / 脸单击注册 | 手势表（上滑=开对话、下滑=设置栏、左右空）、`LV_EVENT_CLICKED` 注册 | 无 |
| 1774 | `HandleTap` | 单击动作实体：`starting` 时进配网，否则 `ToggleChatState()` + `WakeUp` | 无 |

数据流（一句话）：`ft5x06 read_data` → `TouchCountedRead`（计数 → `TouchPointFilter`（映射/过滤/合成抬手） → `TouchLogIndevState`）→ LVGL indev 取数；`IndevActTimerCb` 在帧后单独采样活动对象。

## 1.1 最终提交里的触摸改动（2026-10-28 收尾，`d6efc16`）

基线 `9d3c445` → 最终 `d6efc16`，唯一文件 `main/boards/chd/chd-esp32s3-box/chd_esp32s3_box_board.cc`（**+167/−37**），`config.h` 未再改。下表行号按最终工作区（与 §1 的 11:5x 行号不同）：

| 编号 | 改动 | 行号 |
|---|---|---|
| A1 | FT5x06 `flags` 全部 `false`（`swap_xy`/`mirror_x`/`mirror_y`），坐标只由板级映射变换一次 | `~2123-2125` |
| A2 | 幽灵过滤改 sticky（判死后保持丢弃）+ 阈值 10→**30 px** | `~1405`、`~1480+` |
| A3 | `ScreenClickCb` 同时注册到 `container_` / `content_`（`content_` 在当前消息样式下为 `nullptr`，无害） | `691` / `694` |
| A4 | 点脸回调调 `tap_handler_`（切换对话） | `~500` |
| A5 | boot guard 3 s，锚到**首个过滤帧**（不是 touch init） | `397`、`1429-1431`、`455`、`483` |
| C1 | 点脸补 400 ms 手势守卫 | `493` |
| C3 | 开机幽灵锚点（`reason "ghost"`，心跳 `ghost=%u`） | `1414`、`1474-1486` |
| C4 | 触摸 Y 镜像（`X=raw_y`、`Y=319-raw_x`） | 常量 `1396-1397`、映射 `1431-1444` |
| R1 | `if (kept==0) s_last_release_ms=now;`（点被 stale 丢光时也能合成抬手） | 见 diff |

**刷机与验收**：三次刷机（`#1 a8c9cb38…` 暴露幽灵回归 / `#2 fa2de6b9…` 暴露 Y 翻转 / `#3 7e159681…` 通过）；最终 bin 2,872,128 B，app 分区余量 30%。8 条验收全部 PASS（第 7 条为代码级），详见 `docs/touch-handoff.md` §6.4。
**未提交/未推送**：服务端仓库不涉及触摸代码；固件提交 `d6efc16` 仅本地，`origin=78/xiaozhi-esp32` 无推送权限（HTTP 403）。

## 2. 五个开关宏（`main/boards/chd/chd-esp32s3-box/config.h`，**当前默认值**）

| 宏 | 当前值 | 作用 | 置 0/1 的后果 |
|---|---|---|---|
| `CHD_TOUCH_FORCE_GT911` | **0** | 1 = 只用 GT911（已证伪，0x5D/0x14 都不 ACK）；0 = **FT5x06 优先**，失败才回退 GT911 | 改 1 会走不通（芯片是 FT6336） |
| `CHD_TOUCH_INT_GPIO` | `GPIO_NUM_3` | 仅 GT911 分支用；FT5x06 分支 `int_gpio_num=NC`，只把 IO3 配成输入+上拉观测电平 | — |
| `CHD_TOUCH_PHANTOM_FILTER` | **0** | 第一代幽灵过滤（从未移动+从未抬起 ≥1.5 s 判幽灵） | 已废弃，建议删除 |
| `CHD_TOUCH_DIAG` | **0** | 轮询型诊断（200 ms poll / 10 Hz TD_STATUS / 5 s 汇总）。**1 = 会出现多个 I2C 读者**（曾疑似互相清状态） | 排查芯片层时才置 1 |
| `CHD_TOUCH_LOG_INDEV` | **1** | 在唯一读者内部打印 `indev state:`；帧后 timer 打 `post-frame heartbeat` + filter 计数 | 置 0 = 完全静默 |
| `CHD_TOUCH_POINT_FILTER` | **1** | 映射 + 越界丢弃 + 卡点丢弃 + 合成抬手 | **置 0 = 退回原厂驱动直接喂 raw 坐标（触摸会立刻回到"点哪都不响应"）** |
| —（`POINT_FILTER` 内常量） | `kPointStalePx=30` | **sticky 过滤**：点被判死后保持丢弃，只有移动超阈值才复活；30 px 覆盖实测 ±16 px 幽灵抖动 | 调小可能让幽灵每 2 s 复活并产生延迟 toggle；调大会扩大真实触摸被忽略的区域 |
| —（`POINT_FILTER` 内，C3） | 幽灵锚点 | 开机首个过滤帧学锚点，锚点 ±30 px 内的点直接丢弃；心跳打 `ghost=%u` | 无开关；冷启动 3 s 内先按住屏幕会把锚点学成手指位置（异常需重启） |
| —（`POINT_FILTER` 内，C4） | Y 镜像常量 | 映射为 `X=raw_y`、`Y=319-raw_x`（显示 480×320） | 无开关；2.8" 变体共用该常量但**未标定** |

> **坐标口径（最终版）**：`CHD_TOUCH_POINT_FILTER=1` 时，`TouchCountedRead` 输出的坐标**已经含 Y 镜像**（并已完成唯一一次 swap），下游 LVGL 收到的是显示坐标；不要再叠加 swap/mirror。A1 已把 FT5x06 `flags` 全关，通用层不会再变换第二次。
> **开关语义变化**：`POINT_FILTER=0` 现在等于「板级映射/过滤/合成抬手全关 + 驱动 flags 全关」→ 连原来的 swap 都没有，比 §0 描述的那版更彻底地不可用；要回退到原厂行为需同时把 A1 的 flags 改回 `swap=true,mirror_x=true`。

**"一键回到干净状态"（已被最终版改写）**：最终版 A1 已把驱动 `flags` 全关，因此把 `POINT_FILTER` / `LOG_INDEV` / `PHANTOM_FILTER` / `DIAG` 全设 0 **不再**等于改造前行为（会连唯一的 swap 都没有 → 坐标是竖屏 raw）。要真正回到「原厂驱动 + 原 320×480 配置」，除上述开关外还需把 A1 的 flags 改回 `swap=true, mirror_x=true`。
> 收尾状态：`POINT_FILTER=1` 下单击/点脸/上滑/下滑均已真机验收；`POINT_FILTER=0` 不可用属预期（见上）。

## 3. 我认为最可疑的一处（一句话 + 行号）

> ~~**`TouchPointFilter` 的"合成抬手"条件要求 `kept > 0`（`:1447`），而同一函数会在 2 s 后把幽灵点判成 `stale` 丢弃 →
> `kept == 0` → 合成抬手分支永不进入；也就是说"我们以为在合成抬手，实际上一次都没执行"——这与真机上
> `forced_release=0`、`post-frame` 一行都没有的现象完全一致。**~~
>
> ✅ **2026-10-28 校准：这个判断当时成立，但已经修掉了** —— R1 加 `if (kept==0) s_last_release_ms=now;`，
> 最终构建 `7e159681` 的合成抬手在幽灵点被丢光时也生效（真机无 2 s 延迟 toggle，三条刷机 #3 通过）。
> 原句保留作历史。
>
> **收尾结果**：该判断成立；R1 已加 `if (kept==0) s_last_release_ms=now;`，最终构建的合成抬手在幽灵被丢光时也生效（最终版无 2 s 延迟 toggle）。

补充两条次要可疑点（供调研 agent 交叉验证）：
1. `IndevActTimerCb`（`:1466`）在真机上一次都没输出 ⇒ 要么 `lv_timer_create` 返回 null，要么该 timer 没被 LVGL 任务处理；
   如果它其实在跑，那 `act` 从 `nullptr` 变成真实对象的时刻说明点击**已经**被 LVGL 接受——两种可能性指向完全不同的根因。
2. `esp_lcd_touch_ft5x06.c:239` 在 `get_xy()` 末尾把 `tp->data.points` 清零（读取即清除），
   而 `read_data` 不会主动写 0 清 TD_STATUS 之外的接触状态 —— 需要在硬件层面确认"抬手"到底有没有被芯片报出来。
   若芯片从不报抬手，任何软件合成都只是权宜之计，根因在面板/排线。

## 4. 我没有做的事（避免调研重复）

- 没有改 `esp_lcd_touch_ft5x06` 组件本身（只在外部包了一层）。
- 没有改 `esp_lvgl_port`。
- 没有改 `main/display/*`、音频/AEC/唤醒词/协议/分区表。
- 没有回退任何改动（工作区就是"最后一版未刷机"的状态）。
