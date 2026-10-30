# C1 真机验收（task-6）

- 日期：2026-10-29 23:43–23:48 CST
- 设备：`chd-esp32s3-box-lcd35`，480×320，IP <device-ip>；服务端 `<nas-ip>:4411`
- 板上固件：**C1**（`02_Archive/esp32-firmware/c1-hide-dino/xiaozhi.bin`，sha256 `11b77dc2ef91dd304ff2acdf705a010e4da33f3e3940b87302f18d7a7ece37e3`，2920944 B）
- 验收人：impl-repro（真机执行）；复核：lead + 9哥 目视

## 0. 结论总表

| # | 验收项 | 判定 | 一句话证据 |
|---|---|---|---|
| 1 | A 视图 A 条仍在、恐龙/仙人掌随 tick 移动、位置颜色同 persona.2、无新增裁切 | **PASS** | A1/A2 恐龙墨迹 x 26–54 / y 290–319 与 persona.2 完全一致；仙人掌 1.8 s 内 x 162–174 → x 57–69；重启后同 |
| 2 | B 视图无 A 条恐龙/仙人掌 | **PASS** | B 底部条带 `x18–56` 暗像素 = **0**；全条带仅剩头像下缘（x422–432,y273–275）；6 卡+3 日志+ECG+头像；重启后同 |
| 3 | C 视图无 A 条残留；debug 行首字符可读 | **PASS** | C 底部条带无暗色连通域，`x18–56` = 0；debug 行完整显示 `up 00:01:05 heap 16K A 2632/D 18`（重启帧 `up 00:00:46 heap 24K A 3637/D 42`） |
| 4 | D 视图只剩游戏恐龙一只；分数递增、仙人掌移动；A 条不叠进游戏区 | **PASS** | D 底部 `x18–56` = 0；仅有游戏恐龙（x52–79,y273–294 顶部条带）+ 游戏仙人掌；4 连拍分数 00019→00043（+24/s）→ 碰撞重置 00000→00023；重启帧 00052 |
| 5 | 重启后四条仍成立 | **PASS** | 23:46:04 esptool `--after hard_reset`；重启后固件身份同（23:27:54 / ELF ca03d59f1…）；A/B/C/D 重拍，底部条带判定与首轮一致 |
| 6 | 回归：右下头像静音可切、屏幕点按能切视图、无新增 UI 变化 | **PARTIAL（2/3 PASS，1 项未覆盖）** | 头像静音 **PASS**（serial 439/480 `mute: toggle requested by UI` ↔ service 1949/1950 ON/OFF）；点按链路 **PASS**（`tap -> ToggleChatState` ×3，serial 456/467/509）；**"点按切视图" 本次无物理滑动/视图区点击事件，未覆盖**（MCP set_view 4/4 正常）；UI 布局/字体/卡片与 persona.2 一致，无新增变化 |

**唯一未覆盖项**：`屏幕点按→切换视图` 需要真人做一次滑动（上次 persona.2 的对应日志是 `CHD_UI: view=1`）。本次两段串口（首轮 805 行、重启后 578 行）均无 `CHD_UI: view=` / `view tap`，也无滑动事件。若 9哥 现场滑一下，我可补一条串口证据。

## 1. 刷写与固件身份（Lead 执行，本卡复核）

- 刷写（Lead）：`esptool.py --port /dev/cu.usbmodem31301 --baud 460800 write_flash 0x20000 02_Archive/esp32-firmware/c1-hide-dino/xiaozhi.bin` → `Wrote 2920944 bytes ... Hash of data verified.`
- 回读（Lead）：`read_flash 0x20000 2920944 /tmp/c1-readback.bin` → sha256 `11b77dc2…37e3`，与交付物 `cmp` **BYTE-IDENTICAL**
- 本卡复核：交付物与 `/tmp/c1-readback.bin` 本地 `shasum -a 256` 均为 `11b77dc2ef91dd304ff2acdf705a010e4da33f3e3940b87302f18d7a7ece37e3`（2920944 B）
- 只写 app `0x20000`，未写 `0x0`；NVS/Wi-Fi 保留（重启后 23:46 仍自动连上 <nas-ip> 并可唤醒）
- 串口启动身份（`serial-c1-verify.log:31–33`）：`App version: 2.5.3` / `Compile time: Oct 29 2026 23:27:54` / `ELF file SHA256: ca03d59f1...`
  → 落在 Lead 给出的 23:2x–23:31 构建窗口，**不再是 persona.2 的 `Oct 28 2026 23:36:05` / `e9e4c18be…`**
- 回滚锚（随时可用，本卡未执行）：`02_Archive/esp32-firmware/v2.5.3-persona.2/xiaozhi.bin`，sha256 `a67645c8…eeab4`，2920928 B

## 2. mute 变更与还原记录

| 时间 | 动作 | 结果 | 证据 |
|---|---|---|---|
| 22:48:30 | 采集前基线（静音 ON） | `muted=true` | service 1943 |
| 23:43:35± | 打开串口复位，设备同步静音 | `Mute: sync ok: muted=1` | `serial-c1-verify.log:304` |
| 23:44:04 | 本卡按授权路径解除静音 | `changed:true, muted=false` | `mute-change.log`；service 1948 |
| 23:44:10 | 现场点头像 → 静音 ON | `muted=true` | serial 439；service 1949 |
| 23:44:13 | 现场再点头像 → 静音 OFF | `muted=false`；`Mute: sync ok: muted=0 via POST` | serial 480/484；service 1950 |
| 23:44:23–23:46:58 | 采集期间 | `muted=false`（有 WS；标题栏"未静音"） | `curl-e2e.log` |
| **23:47:36** | **本卡还原 `POST {"muted":true}`** | `changed:true, muted=true since 23:47:36` | `mute-change.log`；service 2098 |
| 23:47:39 | 设备同步 + 复核 | serial 515/519 `sync ok muted=1` / `capture/uplink held`；`/debug/mcp` 仍 `sent:1` | `serial-c1-reboot.log` |

**最终状态 = muted:true，与采集前基线一致。**

## 3. 逐条验收证据

### 3.1 A 视图（view=0）

- 截图：`view-A1-20261029-234423.jpg`（39164 B, `e5406077…`）、`view-A2-20261029-234423.jpg`（39314 B, `5f49c4d6…`），间隔 1.8 s
- 像素：恐龙墨迹 bbox **A1 x 26–54 / y 290–319；A2 x 26–54 / y 290–317**（腿帧切换），`x18–56,y288–320` 暗像素 353/352；与 persona.2 的 `x26–54,y290–319` **完全一致**，底部约 1px 越出屏幕下缘（同 persona.2，非新增裁切）
- 仙人掌：A1 at **x 162–174, y 295–319** → A2 at **x 57–69**, 移动 105 px / 1.8 s ≈ 58 px/s（`ADinoTick` 每 80 ms −5 px ≈ 62.5 px/s，吻合）
- 颜色：recolor `0x202B2D`（近黑）；指标列/7 行日志/头像布局与 persona.2 相同
- 串口：`set view=0` serial 547；snapshot result 556/568
- 服务端：1964 set_view → `1 session(s)`；1968/1972 upload

### 3.2 B 视图（view=1）

- 截图：`view-B-20261029-234423.jpg`（32469 B, `ea7e6ff0…`）
- 底部分层：3× crop `crops/B-strip3x.png`；全条带（y273–320）连通域仅 `(31px, x422–432, y273–275)` = **头像下缘**，无恐龙/仙人掌；`x18–56,y288–320` 暗像素 = **0**
- 内容：6 卡（状态/在听、静音/未静音、音量/85、RSSI/-42、SRAM/17K、音频帧/A2348 D18）+ 3 行日志 + 橙色 ECG + 头像
- 串口：serial 569 `set view=1`；579 snapshot；服务端 1975/1979

### 3.3 C 视图（view=2）

- 截图：`view-C-20261029-234423.jpg`（44245 B, `c7ed522f…`）
- 底部：`crops/C-strip3x.png`；y273–320 无可达阈值的暗色连通域（debug 文字灰度约 107，>90 阈值不计），`x18–56` = 0；**无 A 条残留**
- debug 行：完整可读 **`up 00:01:05 heap 16K A 2632/D 18`**，首字符 "up" 未被遮挡（persona.2 同位置被恐龙压住）
- 其余：8 行日志、56×64 头像 @416,212、CJK 正常
- 串口：serial 580 `set view=2`；591 snapshot；服务端 1982/1986

### 3.4 D 视图（view=3）

- 截图：首轮 `view-D1-…234423.jpg`（23836 B, `38b0d398…`）、`view-D2-…234423.jpg`（23898 B, `6c0c7452…`）；短间隔 `view-D3-…234515.jpg`（17889 B）、`view-D4-…234517.jpg`（17766 B）；4 连拍 `view-Dburst1..4-*.jpg`
- 底部条带：只有**游戏恐龙**（x52–79, y273–294 为条带内可见顶部，整只 y248–294）与游戏仙人掌；`x18–56,y288–320` 暗像素 = **0** → 不再有 A 条小恐龙/仙人掌叠入
- 仙人掌移动：D1 x≈205–219 → D2/D4 x≈451–465（重生后位置不同）；4 连拍可复现
- 分数：`crops/D-burst-scores.png` 4 连拍 00019 → **00043**（1 s 内 +24，≈28/s）→ **00000**（撞仙人掌重置，游戏设计）→ 00023；重启帧 D-reboot = 00052
- 串口：serial 595 `set view=3`；603/612 snapshot；重启 428/436
- 说明：D 为自动跑（无人跳跃），每隔数秒会撞仙人掌重置分数——属 persona.2 既有碰撞逻辑，不是 C1 新增；"分数递增"以 00019→00043 为证

### 3.5 重启后（#5）

- 方式：esptool `read_mac --before default_reset --after hard_reset`（23:46:04，`reboot.log`）；打开串口重新采集时又触发一次 chip reset（`serial-c1-reboot.log:3 rst:0x15`），两次均为正常复位
- 启动身份：`serial-c1-reboot.log:32–33` Compile `Oct 29 2026 23:27:54` / ELF `ca03d59f1...`（与首轮相同，确认没有掉回 persona.2）
- 重启后 mute 同步为 false（基线沿用采集期），TTS `你好小智` 一次唤醒成功（`WebSocket handshake done` serial 355；session `69534a`）
- 重拍：`view-A-reboot-…234647.jpg`（34182 B）、`view-B-reboot-…`（33499 B）、`view-C-reboot-…`（36292 B）、`view-D-reboot-…`（18904 B）
- 重拍判定：A 恐龙 bbox `x26–54,y290–319` ✓；B/C `x18–56` 暗像素 0 ✓；D 仅游戏恐龙、`x18–56` = 0 ✓；C debug `up 00:00:46 heap 24K A 3637/D 42` 可读 ✓

### 3.6 回归（#6）

- **右下头像静音：PASS**——serial 439 `Application: mute: toggle requested by UI (last-confirmed muted=0)` → service 1949 `[mute] ON 23:44:10`；serial 480 `... (last-confirmed muted=1)` → serial 484 `Mute: sync ok: muted=0 via POST` → service 1950 `[mute] OFF 23:44:13`。两次点击双向切换均到达服务端
- **点按链路：PASS**——serial 456/467/509 `CHD_UI: tap -> ToggleChatState (state=3)` ×3（点按被识别；静音期间对话通路被 mute 门挡住属预期）
- **点按切视图：未覆盖**——本次无滑动手势，两段串口均无 `CHD_UI: view=` / `view tap` / `tap ignored: ... after a swipe`；MCP `set_view` 4/4 成功，但这不是触摸路径
- **无新增 UI 变化：PASS**——与 persona.2 截图逐项对照：A（3 指标 + 7 日志 + 头像 + 底部 A 条）、B（6 卡 2×3 + 3 日志 + ECG + 头像）、C（8 日志 + 56×64 头像 + debug 行）、D（游戏恐龙/仙人掌/点状地面/分数）布局一致；CJK 标题/卡片/日志无方块；未见新控件或图层变化
- 串口 `stale=0 / ghost=0 / forced=0`：首轮 25 条心跳、重启后 12 条心跳，全 0

## 4. 截图清单（本目录）

| 文件 | 大小 | sha256 前 8 |
|---|---|---|
| `view-A1-20261029-234423.jpg` | 39164 | e5406077 |
| `view-A2-20261029-234423.jpg` | 39314 | 5f49c4d6 |
| `view-B-20261029-234423.jpg` | 32469 | ea7e6ff0 |
| `view-C-20261029-234423.jpg` | 44245 | c7ed522f |
| `view-D1-20261029-234423.jpg` | 23836 | 38b0d398 |
| `view-D2-20261029-234423.jpg` | 23898 | 6c0c7452 |
| `view-D3-20261029-234515.jpg` | 17889 | 1aad507c |
| `view-D4-20261029-234517.jpg` | 17766 | 31057009 |
| `view-Dburst1..4-*.jpg` | 17794–17869 | — |
| `view-A-reboot-20261029-234647.jpg` | 34182 | b326f2cc |
| `view-B-reboot-20261029-234647.jpg` | 33499 | 43cfacd6 |
| `view-C-reboot-20261029-234647.jpg` | 36292 | 488d5a9f |
| `view-D-reboot-20261029-234647.jpg` | 18904 | eefa389f |
| `crops/*-strip3x.png` | — | A1/A2/B/C/D1/D2 + reboot 四张，底部 60px 3× |
| `crops/D-burst-scores.png` | — | 4 连拍分数拼图 |

## 5. 日志与命令

- 串口（一次开、采到底后冻结）：
  - `serial-c1-verify.log`：805 行 / 53007 B / sha256 `ad9778558ba218193e5d95c029685ba138d6698f5350b6a0b4f437ecdf3378bd`
  - `serial-c1-reboot.log`：578 行 / 36588 B / sha256 `7908dc1ea51a2c00b70c3547b473ba97eb48d54ca4c3548f7c75b26a7b43e3c3`
  - 行号用 `grep -n`（按 `\n`）取得
- 服务端：`/tmp/esp32-voice-service.log`，本卡相关行号 1948–2098（见 §3 各条）
- 命令回显：`curl-e2e.log`（每次 set_view/snapshot 的 `sent`、上传路径、HTTP 码、文件大小、sha256）
- 唤醒记录：`wake-attempts.log`（两次均第 1 次 TTS 即成功）
- 复位记录：`reboot.log`（esptool hard reset + MAC）
- mute 记录：`mute-change.log`

## 6. 未覆盖 / 风险

1. **仅 `点按切视图` 未覆盖**（无真人滑动）；其余 5 条与 #6 的另外两项均通过。
2. 重启验证采用的复位 = esptool hard reset + 串口打开触发 chip reset（两次都记录在 `reboot.log` / 串口 rst 行），不是物理断电；行为等价（冷启动 + NVS 保留）。
3. 采集期间有人点按（头像静音、对话键）；D 分数会因自动碰撞周期重置，已用 4 连拍区分"递增"与"重置"。
4. 本次未重新刷机、未改任何代码；C1 资产与回读 sha256 已在本地复核一致（板上↔资产 cmp 为 Lead 执行）。

## 7. 交接块

- 目标：C1 真机六条验收。
- 已定决策：只写 app 0x20000；失败即回滚 persona.2（本次未触发回滚）。
- 结论：5 PASS + 1 PARTIAL（仅"触摸切视图"未覆盖，需 9哥 滑一次即可补证）。
- 下一步：若 Lead/9哥 认可 → task-6 收口、解锁 C4；若要求补触摸切视图 → 我保留会话，现场滑一下即读 `CHD_UI: view=N`。
- 板上当前：C1，muted=true（23:47:36 还原），WS 会话 `69534a` 仍在线；板子停留视图 D（最后一次 set_view=3）。

## 8. Lead 复核补充（2026-10-30 00:1x，C1 收口）

- **#6「触摸切视图」按 9哥 现场滑动确认判 PASS**（口头确认「划了」，A↔B 往返）。
- **取证缺口（如实记录）**：滑动发生时串口**未挂**，没有取到 `CHD_UI: view=N` 行；且 Lead 在 23:48 做通路探针时执行过一次
  `self.screen.set_view {"view": 0}`（service log 2102–2103），板子已置 A，滑动后停在 A，事后截图无法区分「滑动生效」与「未生效」。
- 替代证据：① C1 的 diff 只改 `dino_root_` 可见性，**完全不触碰**触摸/滑动/点击路由代码；
  ② persona.2 基线调查已实测 1 次真实滑动切视图（`serial-persona2-2210.final.log:1195` → `view=1`）。
- 如需硬证据：下次串口挂着再滑一次，读 `CHD_UI: view=N`（纯取证，不改代码）。
- Lead 独立复核：刷写回读 sha256 `11b77dc2…37e3` 与资产 `cmp` 一致；四视图截图逐张目视（B/C 底部干净、D 单只恐龙、A 条在动）。


---

## 证据可访问性（隐私清理，2026-10-30）

原始串口日志 `serial-c1-verify.log`（805 行）与 `serial-c1-reboot.log`（578 行）已改为**本地未跟踪**（`.gitignore` 规则 `docs/tasks/**/serial-*.log`），仓库内不再包含；本文件所引 sha256、行号与结论均未改动，复算需在本机同一份本地文件上执行。
