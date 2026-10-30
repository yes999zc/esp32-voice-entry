# T1 复现证据：ABCD 四视图真机采集（persona.2）

- 任务卡：`task-1`（T1 真机四视图复现与证据采集）
- 采集时间：2026-10-29 22:06–22:21 CST（设备本机时区）
- 板上固件：release `v2.5.3-persona.2`（app @ 0x20000，release sha256 `a67645c8…eeab4`，Lead 已核实；串口启动行见 §2）
- 设备：`chd-esp32s3-box-lcd35`，LCD 480×320（截图分辨率 480×320），IP `<device-ip>`，服务端 `<nas-ip>:4411`
- 服务端：`Esp32VoiceService` PID 11978，`/tmp/esp32-voice-service.log`
- 结论标记：`[事实]` = 本次真机实测/日志原文；`[推断]` = 基于代码或时序的解释，需 T2 复核

## 0. 一句话结论（逐视图）

| 视图 | view | 截图 | 一句话现象 |
|---|---|---|---|
| A | 0 | `view-A-20261029-221214.jpg` | 7 行日志 + 3 个指标 + Hermes 头像；底部 A 条恐龙正常出现（墨迹 x 26–54 / y 290–319，底部约 1px 越出屏幕下缘、肉眼不可辨）；标题栏与指标 CJK 均正常，未见方块；无仙人掌（截图时刻仍在屏外）。 |
| B | 1 | `view-B-20261029-221217.jpg` | 6 张状态卡 + 3 行日志 + 橙色 ECG 波形；**底部 A 条恐龙与仙人掌仍然出现**（本应隐藏）。A 条仙人掌墨迹静止在 x 452–464（右缘留白 15px，未被右缘裁切；底部约 2px 越出屏幕下缘）。 |
| C | 2 | `view-C-20261029-221220.jpg` | 8 行日志 + 小尺寸头像（56×64 @416,212）+ 底部 debug 行；**A 条恐龙/仙人掌仍在**，且 debug 行文字与左下小恐龙**重叠**（`crops/C-dino-strip-3x.png`）。 |
| D | 3 | `view-D-second-20261029-221223.jpg`（22:12:46）、`view-D-extra5-20261029-221650.jpg`（22:16:54） | 恐龙游戏可见并运行：分数 `00001`→`00165`，仙人掌移动，串口 `DINO 60s fps=27–28、dirty≈8.4–9.0k px`；**但 A 条小恐龙/仙人掌也在底部同屏**，与游戏恐龙、地面（y=303 全宽实线 + 点状带）叠加，出现"两只恐龙"。 |

**persona.2 自身缺陷（本次复现到）**：A 条 `dino_root_` 只在 A 视图被 `move_foreground`、从不 `HIDDEN`，因此在 B/C/D 全部残留（对应 persona.3 修复 `d2d47c7`）。
**未复现的两条 persona.3 修复点**：① A 指标标题 CJK 方块（`175056b`）——本次标题/正文中文全部正常；② D 游戏被完全压层不可见（`0a43f23`）——本次游戏可见可玩。需 T2 复核这两条的触发条件。
**触摸状态（事实更正）**：本次 persona.2 会话触摸/点击是通的——`tap -> ToggleChatState` 15 次、`pressed=1 points=1` **167 次**（裸 `grep -c 'pressed=1'` 为 310：含 138 条 `pressed=1 points=0` 零点帧、5 条双指 `pressed=1 points=2`）、滑动切视图 1 次；右下头像区（x≈425–440, y≈204–215）的静音点击与 4 次服务端 mute 变更**毫秒级一一对应**；过滤器心跳 133 条全部 `stale=0/ghost=0/forced=0`，**HANDOFF 21:47 的「幽灵点自锁」本次没有复现**；但本次没有出现幽灵点，故只覆盖正常点按路径（详见 §4.6）。

## 1. 环境与端口确认

| 项 | 值 | 证据 |
|---|---|---|
| 服务 | `http://127.0.0.1:4411`，LISTEN `*:4411`/`*:4410` | `lsof -nP -iTCP -sTCP:LISTEN` |
| Token | `~/.esp32-voice/control.token`（chmod 600） | `ls -l` |
| 设备在线 | `ping <device-ip>` 通，RTT 4.6–11.2 ms | 本次命令输出 |
| 串口候选 | `/dev/cu.usbmodem31301` = **板子**（12346:4097 USB JTAG/serial debug unit）；`/dev/cu.usbmodem31406` = USB 摄像头（11231:677 2K USB Camera），**排除** | `pyserial list_ports` + `ls -l /dev/cu.*` |
| WS 会话 | `e1c919`，来自 `('<device-ip>', 61382)`，22:11:45 建立 | service log 1693–1694 |
| 串口采集 | `/dev/cu.usbmodem31301` 115200 8N1，pyserial 3.5，全程落盘 | `evidence/serial-persona2-2210.log`（采集结束 3781 行 / 256134 bytes，22:21:05 停止），脚本 `evidence/scripts/capture_serial.py` |

## 2. 板上固件身份与"未刷机未改码"确认

串口启动原文（`evidence/serial-persona2-2210.log`）：

```
1:ESP-ROM:esp32s3-20210327
3:rst:0x15 (USB_UART_CHIP_RESET),boot:0xa (SPI_FAST_FLASH_BOOT)
31:I (107) app_init: App version:      2.5.3
32:I (110) app_init: Compile time:     Oct 28 2026 23:36:05
33:I (115) app_init: ELF file SHA256:  e9e4c18be...
```

- `[事实]` 本次采集期间**没有执行任何刷机命令**（未运行 `idf.py flash`/`esptool write_flash`；全程只用了 curl、pyserial、PIL）。
- `[事实]` 固件仓 `05_Tools/xiaozhi-esp32` 采集后 `git status --short` 为空，HEAD = `64d13ba`（persona.3+4，未上板）；服务端仓 `01_Code/projects/esp32-voice-entry` 的 `src/` `git status --short` 为空。本次只写了 `docs/tasks/abcd-views/**`。
- **固件身份（F1，已闭环）**：串口 `Compile time: Oct 28 2026 23:36:05` 早于 persona.2 的首个 commit（`bd193e4` 2026-10-29 09:41:22；tag commit `81b3b20` 09:49:55），**仅凭启动行无法唯一钉住固件版本**。本卡归属依据是：① 21:58 回读 app 分区 md5 `7ad4b6f7…` = release 资产（`docs/HANDOFF.md:15`）；② **行为反证**：B/C/D 出现 A 条恐龙残留，而这是 persona.3 `d2d47c7` 已修的行为，故板上必不是 persona.3。③ **内容级闭环（verifier）**：`read_flash 0x20000 2920928` → 板上 sha256 = release 资产 sha256 = `a67645c88d…eeab4`，`cmp` 逐字节一致、双端 md5 均为 `7ad4b6f7…`；启动戳 `Oct 28 23:36:05` 即 persona.2 资产自身的构建时间（夜间构建、次日提交）。
- `[事实]` 本机 `build/SHA256SUMS-persona.2` 记录 release 资产 `a67645c8…eeab4`，但 `build/xiaozhi.bin` 已于 10-29 21:52 被 persona.3 重编译覆盖（现 sha256 `56d96d7d…`），**本机 build/ 无 persona.2 副本**；但 verifier 已从 GitHub release 下载该资产（2920928 B，sha256 `a67645c8…eeab4`），并用 `read_flash 0x20000 2920928` 与板上 app 做 `cmp`，**逐字节一致**——板上身份已有内容级强证据。串口启动行（2.5.3 / 10-28 23:36:05 / ELF `e9e4c18be…`）仅作辅助。

## 3. 设备复位与 mute 变更记录

### 3.1 设备是否重启

- `[事实]` **是，且仅一次**：2026-10-29 22:06:57 打开串口时复位（`rst:0x15 (USB_UART_CHIP_RESET)`，serial 1–3 行）。整个 log 中 `ESP-ROM` 只出现 1 次，之后无第二次复位。
- `[事实]` 复位后设备从 NVS 恢复静音真相：serial 251 `Mute: sync ok: muted=1 via GET`，254 `mute: server-confirmed muted, capture/uplink held`，281 `wake word running=0`（静音锁住唤醒词）。
- `[事实]` 复位导致原会话 `de3606` 关闭（service 1678–1679），且静音态下固件不会自动开 WS（`/debug/mcp` 返回 `{"sent":0}`，service 1680）；这也是 22:06–22:11 无法截图的原因。

### 3.2 mute 变更记录（本卡要求逐项记录）

| 时间 | 动作 | 结果 | 证据 |
|---|---|---|---|
| 22:00:00 | （采集前基线）静音 ON | `muted=true since=2026-10-29T22:00:00` | service 1667 / `mute.json` |
| 22:06:58 | 复位后设备同步 | `muted=1`，UI 同步成功 | serial 251–254 |
| **22:11:45** | **解除静音**（非本脚本；`changed_by` 固定写 http 无法区分来源）。同刻串口有 3 个落点 (446,199)/(426,225)/(402,243)，**只有 (426,225) 落在头像热区 408–471×204–275**；最硬证据是 serial 1325 `Application: mute: toggle requested by UI (last-confirmed muted=1)` → 1328 `Mute: sync ok: muted=0 via POST` | `muted=false`，随后 WS 会话 `a56897`→`e1c919` 建立 | service 1681–1694；serial 1325/1328 |
| 22:11:58 | 本脚本 `POST /debug/mute {"muted":false}` | `changed:false`（已是 false，无副作用） | `evidence/mute-change.log` |
| 22:12:02 | 置 ON（对应触摸 (439,207) @22:12:02.008，见 §4.6） | `muted=true` | service 1704；serial 触摸 |
| 22:12:10 / 22:12:12 / 22:12:13 | 反复 OFF/ON/OFF，与触摸 (425,204)/(429,204)/(440,215) 毫秒级对应（现场在点头像区） | 设备侧静音点击，见 §4.6 | service 1708/1710/1711；serial 触摸行 |
| **22:12:14** | 置 ON → 稳定至采集结束（未匹配到采样点，属同批连点） | `muted=true since=2026-10-29T22:12:14` | service 1715；`/debug/mute` 多次 GET |
| 22:19:05 | 本脚本恢复性 `POST /debug/mute {"muted":true}` | `changed:false`，已为 true（等于 22:06 基线） | `evidence/mute-change.log` |
| 22:19:06 | 复核 | `{"muted":true,"since":"2026-10-29T22:12:14","changed_by":"http"}`；session 仍活（`sent:1`） | `evidence/mute-change.log` |

**结论**：采集开始前服务端 muted=true；采集期间由**外部调用**短暂改为 false（22:11:45–22:12:14，用于唤醒设备），22:12:14 起恢复 true 并保持到结束。本脚本自身的两次 POST 均为 `changed:false` 的空操作。**最终状态 = muted:true，与基线一致；A/B/C/D 四张截图均在 muted=true 下拍摄**（D1 抓拍瞬间设备 UI 显示"同步失败"，见 §4.5）。

## 4. 逐视图证据与观察

### 4.1 复现命令（逐条可重跑）

```bash
TOK=$(cat ~/.esp32-voice/control.token)
# 切视图：view 0=A 1=B 2=C 3=D
curl -s -H "Authorization: Bearer $TOK" -H 'Content-Type: application/json' \
  -d '{"name":"self.screen.set_view","arguments":{"view":0}}' http://127.0.0.1:4411/debug/mcp
# 设备截屏：固件工具 self.screen.snapshot（main/mcp_server.cc:182，参数 url/quality）
curl -s -H "Authorization: Bearer $TOK" -H 'Content-Type: application/json' \
  -d '{"name":"self.screen.snapshot","arguments":{"url":"http://<nas-ip>:4411/debug/upload","quality":90}}' \
  http://127.0.0.1:4411/debug/mcp
# 取回：上传落在 PHOTO_DIR，经 /debug/photo/<name> 下载（src/vision.py:199 debug_upload / 269 debug_file）
curl -s -H "Authorization: Bearer $TOK" -o view-A.jpg \
  http://127.0.0.1:4411/debug/photo/snapshot-20261029-221216.jpg
```

逐视图执行序列（在上面的命令上只替换 `view` 与取回文件名；文件名中的时间码是**脚本发起时刻**，设备实际上传时刻见 §4.x 表与日志）：

| 视图 | set_view 参数 | 设备上传文件 → 落盘证据文件 |
|---|---|---|
| A | `{"view":0}` | `snapshot-20261029-221216.jpg` → `view-A-20261029-221214.jpg` |
| B | `{"view":1}` | `snapshot-20261029-221219.jpg` → `view-B-20261029-221217.jpg` |
| C | `{"view":2}` | `snapshot-20261029-221222.jpg` → `view-C-20261029-221220.jpg` |
| D | `{"view":3}` | 首次尝试 22:12:26 **上传失败**（服务端无文件）；重试至 `snapshot-20261029-221246.jpg` → `view-D-second-20261029-221223.jpg`（22:12:46）；间隔 3 s 后再连拍，经多次重试至 `snapshot-20261029-221654.jpg` → `view-D-extra5-20261029-221650.jpg`（22:16:54） |

- 每次 set_view 后等 2 s 再 snapshot；snapshot 后轮询 service log 的 `[debug] upload … -> <path>`，再按 basename 取回。
- 串口采集：`python3 evidence/scripts/capture_serial.py serial-persona2-2210.log`（脚本原文在同目录，115200，DTR/RTS 置低；打开即复位，见 §3.1）。
- 四视图连拍脚本：`evidence/scripts/four_views.sh`；D 视图补充重试：`evidence/scripts/capture_d.sh`、`evidence/scripts/retry_d.sh`。
- 每次 curl 的完整回显（含 `sent` 数、上传路径、HTTP 码、文件大小、sha256）见 `evidence/curl-e2e.log`。

### 4.2 A 视图（view=0）

| 项 | 值 |
|---|---|
| 截图绝对路径 | `/Users/bakeyzhang/AI_Workspace/01_Code/projects/esp32-voice-entry/docs/tasks/abcd-views/evidence/view-A-20261029-221214.jpg` |
| 文件大小 / sha256 | 37283 bytes / `bf10712fc466af113b77164ed7e1b1cba7a2dda41ed6e35c06587ece1a7be1ec` |
| 采集时刻 | 22:12:16（设备上传 `snapshot-20261029-221216.jpg`；serial 1627，I=319108） |
| view / mute | 0 / muted=true（标题栏「已静音」）；文件可再次打开（`file`: JPEG JFIF 480×320） |
| 链路证据 | service 1712 `[mcp] call self.screen.set_view {'view': 0}` → 1713 `-> 1 session(s)` → 1714 `result true`；serial 1605 `CHD_UI: set view=0`；service 1716–1718 snapshot → upload 37283 bytes |

逐项观察（对照 480×320 图）：
- **恐龙条**：`[事实]` 出现。深色（代码 recolor `0x202B2D`，截图呈近黑）恐龙，**墨迹实测 bbox x 26–54、y 290–319**（319 为屏幕最后一行）。名义坐标 (18,282) 忽略了 `lv_image_set_scale` 的**中心枢轴**：渲染框顶 = 273+9+(47−47×0.7266)/2 ≈ 288.4，按墨迹行 2..44 推得 289.9–321.1，故**底部约 1px（脚趾尖）越出屏幕下缘**、肉眼不可辨（与 T2 的 1.3px 口径一致）。底部 47px 条带背景与页面同色，无边框。
- **地面**：`[事实]` A 条内部**无地面线**；页面 `baseline_`（1px `#D8D5C6` @y=276）**存在但极淡**：y=276 采样 RGB (213,209,197) vs 背景 (239,235,223)，ΔL≈26。`[推断]` 属设计（A 条只画 dino+cactus），非缺失。
- **仙人掌**：`[事实]` 本图**看不到仙人掌**——右下角 (440–480, 273–320) 按灰度 **<90** 计数 = **0**；切到 B 后 0.7 s 内它已移到 x≈452 并冻结（同口径 <90 计数 = **152 px**）。说明 A 截图瞬间仙人掌仍在屏外 x≈480 附近，属**时序**而非缺失。
- **分数**：A 无分数（分数只在 D 游戏视图）。
- **标题栏**：`● Hermes 在线 已静音 22:12`；中文"在线/已静音"字形完整，**无方块、无缺字**（`crops/A-titlebar-3x.png`）。
- **指标区**：`状态/空闲`、`内存/17K`、`帧/1987`；三组标题+数值 **CJK 全部可读**（`crops/A-metrics-3x.png`），未见 persona.3 `175056b` 所修的字形问题。
- **日志区**：7 行（05:13.004 … 05:17.030），从 y≈44 起，行距 33，无重叠。
- **背景色**：米白，≈ `#EFEBDF`（像素采样 237–241 / 235–241 / 223–234，JPEG 有轻微噪点），无渐变异常。
- **图层遮挡 / 残影**：Hermes 头像 64×72 @(408,204) 正常、未被遮挡；未观察到残影或错位。

### 4.3 B 视图（view=1）

| 项 | 值 |
|---|---|
| 截图绝对路径 | `…/evidence/view-B-20261029-221217.jpg` |
| 文件大小 / sha256 | 33897 bytes / `eece52fd8ade15e56091feb5e96a3c9cc009c229bea60f89b9114c0f9cece0e5` |
| 采集时刻 | 22:12:19（`snapshot-20261029-221219.jpg`；serial 1643，I=322158） |
| view / mute | 1 / muted=true（标题栏"已静音"） |
| 链路证据 | service 1720–1722 set_view → `result true`；serial 1635 `CHD_UI: set view=1`；service 1723–1725 snapshot → upload 33897 bytes |

逐项观察：
- **恐龙条**：`[事实]` **仍然出现**（左下小恐龙墨迹 x 26–54、y 290–317；右侧仙人掌墨迹 x 452–464、y 295–319）。这是 persona.2 的缺陷：`ApplyViewLayout` 只在 A 调 `move_foreground`，从不 `HIDDEN`（persona.2 源码，对应 persona.3 `d2d47c7` 修复）。
- **位置/缩放/颜色**：名义坐标与 A 相同（dino_root_ 18,282、cactus 起点 x=480），因中心枢轴实际墨迹为 x 26–54 / y 290–317 与 x 452–464 / y 295–319；深色近黑，dino ~33×35、仙人掌 ~14×29。
- **地面**：A 条无地面线；`idle_wave_` 是 B 专属橙色 ECG（`0xE2703A`，y≈276–320，贯穿全宽，见 `crops/B-dino-strip-3x.png`）；`baseline_` 1px 存在但极淡（同上，y=276 采样 (213,209,197) vs 背景 (239,235,223)）。
- **仙人掌**：**静止**在 x 452–464、y 295–319；B/C/D1/D2 四帧像素级同位，说明 `ADinoTick` 在 `phase_b_view_≠kA` 时 early-return，A 条只残留、不动画。右缘留白 15px，未被右缘裁切；底部约 2px 越出屏幕下缘。
- **卡片**：6 张 2×3（状态/空闲、静音/已静音、音量/85、RSSI/-52、SRAM/17K、音频帧/A1987 D18），边框与文字正常。
- **日志**：3 行（05:15.111、05:16.108、05:17.030），位于卡片下方。
- **标题栏 / 字体**：同 A，CJK 正常。
- **背景色**：同 A。
- **图层遮挡 / 残影**：恐龙条与 ECG 都在卡片区域之下，未遮挡卡片；未见残影。

### 4.4 C 视图（view=2）

| 项 | 值 |
|---|---|
| 截图绝对路径 | `…/evidence/view-C-20261029-221220.jpg` |
| 文件大小 / sha256 | 42648 bytes / `9d8ac3338ed1ce0ac4bd34d97b97f80472cdcd8ba18d806e758f0a062bed7b99` |
| 采集时刻 | 22:12:22（`snapshot-20261029-221222.jpg`；serial 1660，I=325018） |
| view / mute | 2 / muted=true（标题栏"已静音"） |
| 链路证据 | service 1727–1729 set_view → `result true`；serial 1651 `CHD_UI: set view=2`；service 1730–1732 snapshot → upload 42648 bytes |

逐项观察：
- **恐龙条**：`[事实]` **仍然出现**（左下小恐龙 + 右缘仙人掌），同 B，属同一缺陷。
- **图层冲突（C 特有）**：底部 `debug_line_` 文本（y≈300）**压在小恐龙身上**；可见部分为 `05:24 heap 17K A 1987/D 18`，**前半截被恐龙覆盖、不可读**（`crops/C-dino-strip-3x.png` 可见 "up…" 与恐龙重叠）。
- **日志**：8 行（05:05.095 … 05:17.030），x=8 起、行距 27、宽 400，无换行截断。
- **仙人掌**：A 条残留，静止在 x 452–464、y 295–319（与 B/D 帧像素级同位，未移动）；底部约 2px 越出屏幕下缘。
- **地面**：A 条无地面；`baseline_` 存在但极淡（y=276 采样 (213,209,197) vs 背景 (239,235,223)，ΔL≈26）；C 不显示 `idle_wave_`（代码仅 B 显示）。
- **标题栏 / 字体**：CJK 正常，无方块。
- **头像**：缩小版 56×64 @(416,212) 可见，未被日志覆盖。
- **背景色**：同 A。
- **残影**：未见；debug 文本与恐龙是"同层叠加"而非残影。

### 4.5 D 视图（view=3，两帧）

| 项 | 第一帧 | 第二帧 |
|---|---|---|
| 截图绝对路径 | `…/evidence/view-D-second-20261029-221223.jpg` | `…/evidence/view-D-extra5-20261029-221650.jpg` |
| 文件大小 / sha256 | 21236 bytes / `7e9e86c0e96ae363d9fbc5e04cc7d42e8bc3c2129a5901e985c52c28f192f90b` | 24281 bytes / `1b188c4dc5259d3ad933bcf83a0d27b4f4d2f2febe4b91442a7ab1460df6bed1` |
| 采集时刻 | 22:12:46（`snapshot-20261029-221246.jpg`；serial 1739，I=348898） | 22:16:54（`snapshot-20261029-221654.jpg`；serial 2797，I=596608） |
| view / mute | 3 / muted=true（但标题栏显示**"同步失败"**） | 3 / muted=true（标题栏"已静音"） |
| 链路证据 | service 1734–1736 set_view → `result true`；serial 1666 `CHD_UI: set view=3`；service 1739–1741 snapshot → upload 21236 bytes | service 1775–1777 set_view；serial 1780 `CHD_UI: set view=3`；service 1920–1922 snapshot → upload 24281 bytes |

逐项观察：
- **恐龙游戏**：`[事实]` **可见、可跑**。游戏大恐龙、仙人掌、地面（y=303 全宽实线 + y≈306–308 点状带）、左上分数均正常渲染；`[事实]` 4 分 8 秒内分数 `00001`（22:12:46）→ `00165`（22:16:54），说明 `GameTick` 计分与移动在跑。
- **帧率/Dirty**：`[事实]` 共 8 条采样：serial 1887/2123/2287/2583/2928 `fps=28`，3215/3425/3632 `fps=27`；`dirty=8896/9001/8642/8797/8916/8423/8423/8423 px`（D 期间 27–28fps）。
- **分数**：小号灰字 5 位补零，位于 (x≈10, y≈185–195)；两帧数值不同（可对照）。
- **地面**：y=303 为**全宽实线**（该行 480/480 像素非背景，RGB≈111,108,99），y≈306–308 为点状带（x 60–440 在 y=304/305 无暗像素）；D 隐藏 `baseline_`（符合 `ApplyViewLayout`）。
- **仙人掌（分两类，别混）**：**游戏仙人掌**——第一帧在右缘 x 469–479、y 248–293（`chrome_cactus_large_dsc` 25×50，`y=77`→170+77=247，ink rows 1..48；右缘被裁），第二帧在左缘 x 1–15、y 263–295（`chrome_cactus_small_dsc` 17×35，`y=92`→262，ink rows 1..33）；两帧一大一小 = persona.2 源码 `GameTick` 1494–1501 的 `game_large_cactus_` 轮换，证明重生循环。**A 条残留仙人掌**——两帧都静止在 x 452–464、y 295–319，不动。
- **恐龙条残留（缺陷）**：`[事实]` 底部仍有 **A 条小恐龙**（墨迹 x 25–54、y 290–317，暗像素 354）与**A 条仙人掌**（x 452–464、y 295–319），与游戏恐龙/地面同屏 → 画面出现"两只恐龙"，小恐龙脚部与游戏地面带重叠。
- **日志**：3 行（第一帧 05:13.004/05:14.212/05:14.935；第二帧 06:19.578/07:03.575/07:04.086），位于 y≈44–143，覆盖游戏上部空白区。
- **头像**：隐藏（符合 D）。
- **标题栏 / 字体**：CJK 正常；第一帧"同步失败"对应串口 1706–1707 `Mute: open … failed: Connection timed out` / `sync failed(network)`（22:12:35），22:12:47 sync 恢复正常（serial 1742）；**不是视图渲染问题**，但会改变标题栏文案。
- **图层遮挡 / 残影**：游戏视图本身未见大范围被压层；可见的层级问题只有 A 条（小恐龙/仙人掌）叠在游戏地带之上/之中。未见残影。

两帧的含义（GameTick 状态不同，不是重复帧）：
- **第一帧 22:12:46**：分数 `00001`，游戏大恐龙**离地**（y≈205–245，跳跃中）。此前 0.5 s 的触摸 `x=62 y=265`（serial 1724–1728，I=348388）触发 `GameTapCb`；serial 1793 的 `x=57 y=263` 在 22:12:56.4，晚于本帧 10.5 s，不能解释本帧。用于证明跳跃动画/初始计分。
- **第二帧 22:16:54**：分数 `00165`，大恐龙**落地**（y≈250–290），左右各一仙人掌。用于证明 4 分 8 秒后 `GameTick` 仍在推进（分数 + 位移变化），不是静止画面。

`extra5` 命名与 WS 说明（回应评审疑问）：
- `view-D-extra5-*` 是 D 视图**第 9 次 snapshot 尝试（第 5 轮重试）**成功的文件，编号是"重试轮次"，不是"第 5 帧"；前 8 次尝试中 7 次失败（见 §6）。
- **不是"WS 恢复后"拍的**：会话 `e1c919` 自 22:11:45 建立到采集结束**全程未断**（service log 1694–1926 无 `connection error`，每次 snapshot 都返回 `sent=1`）。第二帧是在**同一 WS 会话内**、多次设备侧 HTTP 上传失败后的成功重试，不涉及 WS 重连。

### 4.6 触摸/点击状态（与 HANDOFF 21:47 故障的关系）

`[事实]` 本次 persona.2 会话（`e1c919`，22:11:45–22:22）触摸/点击是通的：

- `CHD_UI: tap -> ToggleChatState` 共 **15 次**（serial 1204–2973，state=3/5），最后一次在 **22:17:40**；静音期间这些 tap 在输入层正常触发，但对话通路被静音门挡住（serial 2853/2974 `Application: mute: dialogue/wake path blocked while muted`）——属预期；
- 触摸按下采样 `CHD_TOUCH: indev state: pressed=1 points=1` 共 **167 次**、均带真实坐标（例：serial 1793 `x=57 y=263`、serial 1726 `x=62 y=265`）；
- **右下头像区点击 = 静音切换，本次实测可用**：最硬证据是 serial 1325 `Application: mute: toggle requested by UI (last-confirmed muted=1)` → 1328 `Mute: sync ok: muted=0 via POST`（22:11:45 解除静音，随后 WS 建立）。其余点击与 service log 的 mute 变更毫秒级对应：22:12:02.008 (439,207) ↔ `ON 22:12:02`；22:12:10.098 (425,204) ↔ `OFF 22:12:10`；22:12:12.008 (429,204) ↔ `ON 22:12:12`；22:12:13.058 (440,215) ↔ `OFF 22:12:13`；22:12:14 的 ON 未匹配到采样点。服务端 `changed_by` 固定写 `http`（`src/vision.py:526`），不能靠该字段区分设备/外部，但时间对应关系高度指向设备触摸触发；
- **触摸滑动切视图成功**：serial 1195 `CHD_UI: view=1`（22:11:28，当时尚未建立 WS，说明该路径不依赖会话）；
- MCP 切视图同样正常：`set view=0/1/2/3` 四次全部下发并被设备执行（serial 1605/1635/1651/1666，service `result true`）；
- 触摸过滤器心跳 **133 条全部** `stale=0 oob=0 ghost=0 forced=0`（末条 `post-frame heartbeat` 为 serial **3774**：`state=RELEASED | … stale=0 oob=0 ghost=0 forced=0`；3781 是 `indev heartbeat`，无 stale 字段）；
- **是否长时间静止**：本会话最长无触摸间隔 **46.9 s**（I467138→I514038，22:14:44→22:15:31）；该间隔内 heartbeat 一直是 `state=RELEASED, raw_points=0, stale=0`，间隔结束后触摸立即恢复（`pressed=1` 连续出现，并在 D 视图触发 `GameTapCb` 跳跃）——**没有出现"LVGL 被永久按住"**；
- 仅有 1 次守卫日志 `tap ignored: 170 ms after a swipe`（serial 3009），属滑动手势后的正常防误触，不是 stale/ghost。

**静音点击目标核对（代码 + 实测）**：
- `[事实]` persona.2 源码里可点的静音目标只有三处：`mute_hit_`（376,0 起 44×44 透明热区）、`hermes_avatar_`（408,204 起 64×72）、`mute_button_`；**顶部状态文字 `mute_text_`（x=300–390, y=10）没有 click 回调**（persona.3 `6a6697b` 才把它补成可点）。
- `[事实]` 本次会话实测点在右下头像区（x≈425–440, y≈204–215），4 次点击与 4 次 mute 变更毫秒级对应 → **右下角静音可用**。
- `[事实]` 右上角 `mute_hit_`（x=376–420, y=0–44）本次**没有落点**（5 次 y<44 的触摸分别在 x=35 与 x=188–250），所以「右上角」本次未验证；但按 persona.2 代码，`mute_text_` 文字本身不可点，只有 376–420 的透明热区可点 → 9哥 说的「右上角不响应」更可能是**persona.2 缺可点文字区域**（persona.3 `6a6697b` 的修复点），而不是触摸失灵。

`[推断]` 与 HANDOFF 21:47 故障的关系：那次根因是面板**幽灵点** `raw(145,70) -> mapped(70,174)` 静止 >2 s，被 `TouchPointFilter` 判 `stale` 后 HOLD，LVGL 永久按住、后续点击全失效。本次会话**没有出现幽灵点**（ghost=0），也没有 >2 s 的静止单点，因此 **「幽灵点自锁」这次没有复现**。据此只能确认"persona.2 正常点按/滑动/切视图可用"，**没有覆盖幽灵点路径**，不能断言 stale-HOLD 自锁已被修复（persona.2 仍含 `68f0f06` 的 HOLD 策略，D3 `64d13ba` 未上板）。

## 5. 串口关键行（原文，带行号）

文件：`evidence/serial-persona2-2210.log`（采集结束 3781 行 / 256134 bytes，停于 22:21:05；设备单调时间 I(t) 与墙钟关系：I=0 ≈ 22:06:57）。

> 行号取法（给 T2/T3）：串口行号一律用 `grep -n` / `sed -n` 取（按 `\n` 计数），**不要用 Python `splitlines()`** —— `final.log` 第 133 行含一个孤立 CR，会让其后的行号整体 +1。

> 关于 `ApplyViewLayout`：该函数本身**不打日志**（persona.2 源码只在该函数内改 LVGL 对象属性），因此串口侧用它的调用者 `CHD_UI: set view=N`（`SetPhaseBView`）作为「布局重算已触发」的锚点，布局结果以同刻设备截图为证；游戏 tick 用 `CHD_UI: DINO 60s fps=…` 行作证。

**冻结快照（以此为准）**：`evidence/serial-persona2-2210.final.log`，3781 行 / 256134 bytes，sha256 `5307aef702a3640405bf94b8c0f1854d1a7631f5e7190cb05aefbd26e403e336`，截取时间 2026-10-29 22:22:27 CST。原始 `serial-persona2-2210.log` 与快照内容相同（同一 sha256），采集已停止、不再追加。**后续 T2/T3 引用串口行号一律以 final 快照为准。**

| 行号 | 原文 | 说明 |
|---|---|---|
| 1–3 | `ESP-ROM…` / `rst:0x15 (USB_UART_CHIP_RESET),boot:0xa…` | 打开串口导致复位（仅此一次） |
| 31–33 | `App version: 2.5.3` / `Compile time: Oct 28 2026 23:36:05` / `ELF file SHA256: e9e4c18be...` | 板上固件身份 |
| 239 / 254 / 281 | `Application: Network connected` / `mute: server-confirmed muted, capture/uplink held` / `Startup wake word hint skipped (state=3, wake word running=0…` | 复位后网络 OK，静音锁麦克与唤醒词 |
| 251 | `Mute: sync ok: muted=1 via GET (next in 1000 ms)` | 复位后静音真相同步 |
| 1491 / 1605 | `CHD_UI: set view=0` | A（22:12:06 首次 / 22:12:13 正式） |
| 1635 | `CHD_UI: set view=1` | B |
| 1651 | `CHD_UI: set view=2` | C |
| 1666 / 1780 | `CHD_UI: set view=3` | D（22:12:26 / 22:12:53 重拍） |
| 1627 / 1631 | `MCP: Upload snapshot 37283 bytes…` / `Snapshot screen result: {"ok": true, …221216.jpg …}` | A 截图成功 |
| 1643 / 1647 | `… 33897 bytes …` / `… 221219.jpg …` | B 截图成功 |
| 1660 / 1665 | `… 42648 bytes …` / `… 221222.jpg …` | C 截图成功 |
| 1677 | `MCP: Upload snapshot 20985 bytes …` | D 首次截图（**失败**，无 result 行） |
| 1735 / 1739 | `… 21236 bytes …` / `… 221246.jpg …` | D 第一帧成功 |
| 2776 / 2797 | `… 24281 bytes …` / `… 221654.jpg …` | D 第二帧成功 |
| 1706–1707 | `Mute: open http://<nas-ip>:4411/debug/mute failed: Connection timed out` / `Mute: sync failed(network) via GET …` | D1 标题栏"同步失败"的原因（22:12:35） |
| 1742 | `Mute: sync ok: muted=1 via GET` | 22:12:47 恢复同步 |
| 1887 / 2123 / 2287 / 2583 / 2928 | `CHD_UI: DINO 60s fps=28 dirty=…` | D 游戏 tick 持续运行 |
| 1791–1794 | `CHD_TOUCH: indev state: pressed=1 points=1 x=57 y=263`（22:12:56；另 1724–1728 为 D1 前 0.5 s 的 `x=62 y=265`） | 采集期间**现场有人触摸屏幕**（触发 D 跳跃；静音点击见 §4.6 的坐标-事件对应），非脚本行为 |

> 说明：开串口复位是本次唯一的设备重启；采集结束（22:21:05）前无第二次 `ESP-ROM`。关闭串口后计数仍为 1，且会话 `e1c919` 保持在线，说明**关闭串口未再复位设备**。

## 6. 服务端日志关键行（带行号）

文件：`/tmp/esp32-voice-service.log`（采集窗口摘录另存 `evidence/service-log-capture-window.txt`，71 行）。

| 行号 | 原文 |
|---|---|
| 1681 | `[mute] OFF by=http at=2026-10-29T22:11:45`（外部唤醒） |
| 1693–1694 | `[conn] ('<device-ip>', 61382)` / `[e1c919] hello sr= 16000 frame= 60` |
| 1705–1707 | `[e1c919] [mcp] call self.screen.set_view {'view': 0}` / `[debug] mcp … -> 1 session(s)` / `[mcp] result true` |
| 1712–1714 | 同上（view=0 正式采集） |
| 1716–1718 | `[mcp] call self.screen.snapshot {'url': 'http://<nas-ip>:4411/debug/upload', 'quality': 90}` / `[debug] mcp … -> 1 session(s)` / `[debug] upload 37283 bytes -> …221216.jpg` |
| 1720–1725 | B：set_view(1) + snapshot + upload 33897 bytes |
| 1727–1732 | C：set_view(2) + snapshot + upload 42648 bytes |
| 1734–1741 | D：set_view(3) + snapshot×2 + upload 21236 bytes（第一帧成功） |
| 1742 | `[e1c919] [mcp] error {"code": -32603, "message": "Failed to upload screenshot: Transmit failed (transmit_failed)"}`（D 首次失败） |
| 1775–1780 | D 重拍：set_view(3) + snapshot → `Transmit failed` |
| 1779–1922 | D 重试：9 次 snapshot 共 2 次成功（第 2 次 1741 = 22:12:46、第 9 次 1922 = 22:16:54），7 次失败（`Transmit failed` ×5、`connect_failed, native=12` ×2） |
| 1704 / 1708 / 1710–1711 / 1715 | mute ON/OFF 抖动，最终 1715 `[mute] ON by=http since=2026-10-29T22:12:14` |

**D 视图截图成功率**：`[事实]` D 共 9 次 snapshot 尝试，成功 2 次（1741、1922），失败 7 次。失败均为设备侧 HTTP 上传：`Transmit failed (transmit_failed)` / `Failed to open URL … (connect_failed, native=12)`，同时串口伴随 `Mute:` 网络失败——`Connection timed out`：1706/1815/1988/2217/2283；`connect_failed, native=12`：2782。`[推断]` 与 D 视图 GameTick（28fps、dirty ~9k px）期间设备 HTTP 客户端资源/超时竞争有关，属**取证可靠性问题**，不是视图渲染缺陷——`[事实]` 成功帧中游戏画面完整。

## 7. 与 persona.2 期望的差异（供 T2 归因）

| # | 现象（本次实测） | persona.2 期望 / 代码事实 | 归属线索 |
|---|---|---|---|
| 1 | B/C/D 底部仍有 A 条小恐龙 + 仙人掌 | A 条只应在 A 显示；persona.2 `ApplyViewLayout` 对 `dino_root_` 仅 `move_foreground`（is_a 分支），从不 `HIDDEN` | persona.2 自身缺陷，persona.3 `d2d47c7` 已修 |
| 2 | C 底部 debug 行与 A 条小恐龙文字重叠 | C 应显示 8 行日志 + debug 行；A 条本不该出现在 C | 同 #1 的衍生；修 #1 即消失（`crops/C-dino-strip-3x.png`） |
| 3 | D 出现"两只恐龙"：游戏大恐龙 + A 条小恐龙，小恐龙压在地面带 | D 只应有 `game_view_`，A 条应隐藏 | 同 #1；`0a43f23` 另修 `game_view_` 前景层级 |
| 4 | D 游戏视图可见、可玩、分数增长（00001→00165），未见被完全压层 | persona.3 `0a43f23` 声称修"D 被 B1 压层" | **未复现**该症状；需 T2 确认触发条件（可能需 subtitle/媒体等状态） |
| 5 | A 指标标题 `状态/内存/帧` CJK 正常，无方块 | persona.3 `175056b` 声称修 A 标题 CJK 字体 | **未复现**；需 T2 复核（`crops/A-metrics-3x.png`） |
| 6 | A 截图时刻无仙人掌 | A 条仙人掌从 x=480 起左移（`ADinoTick` 每 80 ms −5 px，约 62.5 px/s），切到 B 前已到 x≈452；B/C/D 帧证明它存在但**冻结不动**（`ADinoTick` 在非 A 视图 early-return） | 时序现象 + A 条 tick 被 view 门控，非渲染缺陷 |
| 7 | D 标题栏一帧显示"同步失败" | 静音同步失败（网络超时），与视图无关 | 环境/网络；服务端 muted 仍为 true |
| 8 | D snapshot 高失败率（7/9） | 无此预期；固件 `self.screen.snapshot` 应成功 | 设备 HTTP 并发/超时，取证风险，非渲染问题 |
| 9 | 右下头像区点击静音可用（4 次点击 ↔ 4 次 mute 变更）；右上角文字区未验证/按代码不可点 | persona.2 只有 `mute_hit_`/头像/`mute_button_` 可点，`mute_text_` 无回调 | persona.2 缺「顶部状态文字可点」；persona.3 `6a6697b` 修复；不是触摸失灵 |

## 8. 风险 / 未完成

1. **mute 在采集前段被短暂改过**（22:11:45–22:12:14），最终已还原 `muted=true`；按 §4.6 的触摸-事件对应，这些变更高度指向现场右下头像区点击（服务端 `changed_by` 固定写 http，无法区分设备/外部）。本脚本自身两次 POST 都是 `changed:false`；逐条留证见 §3.2。
2. **D 视图 snapshot 成功率低**（2/9）。已用 22:16:54 的成功帧补齐；若需第三帧，建议在 D 下间隔 ≥5 s 重试并在失败时重发（脚本已就绪）。
3. **板上 app 身份已闭环**：本机 `build/xiaozhi.bin` 虽被 persona.3 覆盖，但 verifier 于 22:43 从 GitHub release 下载 persona.2 资产（2920928 B，sha256 `a67645c8…eeab4`），执行 `read_flash 0x20000 2920928 --after hard_reset`，板上 sha256 = 资产 sha256、`cmp` 一致；代价是复位一次（NVS/Wi-Fi 未受影响，mute 仍 true，ping 3/3）。
4. **采集期间有人触摸板子**（x≈57,y≈263，serial 1791–1794；D1 前 0.5 s 为 x=62,y=265，serial 1724–1728），并造成 mute 抖动与 D 跳跃；评分帧（00001/00165）可能含人为跳跃影响，但分数递增已足以证明 GameTick 在跑。
5. **"D 被压层"与"A 标题字体"两条 persona.3 修复点在本次未复现**，需 T2/后续卡确认触发条件，不能据此断言 persona.3 修复无效。
6. 未做 `/admin` 截屏降级（不需要：`self.screen.snapshot` 可用）。

## 9. 证据文件清单

目录：`/Users/bakeyzhang/AI_Workspace/01_Code/projects/esp32-voice-entry/docs/tasks/abcd-views/evidence/`

| 文件 | 大小 | 说明 |
|---|---|---|
| `view-A-20261029-221214.jpg` | 37283 | A 视图（22:12:16） |
| `view-B-20261029-221217.jpg` | 33897 | B 视图（22:12:19） |
| `view-C-20261029-221220.jpg` | 42648 | C 视图（22:12:22） |
| `view-D-second-20261029-221223.jpg` | 21236 | D 视图第一帧（22:12:46，分数 00001） |
| `view-D-extra5-20261029-221650.jpg` | 24281 | D 视图第二帧（22:16:54，分数 00165） |
| `crops/A-dino-strip-3x.png`、`B-…`、`C-…`、`D1-…`、`D2-dino-strip-3x.png` | 11–28 KB | 底部 60px 条带 3× 放大（恐龙条/地面/文字重叠） |
| `crops/A-titlebar-3x.png` / `A-metrics-3x.png` / `D2-game-area-3x.png` | 80–95 KB | 标题栏/指标/游戏区放大 |
| `serial-persona2-2210.log` | 256134 | 串口原文（3781 行，22:06:57–22:21:05），已冻结 |
| `serial-persona2-2210.final.log` | 256134 | **冻结快照**（3781 行，sha256 `5307aef7…e336`，22:22:27 截取；T2/T3 引用以此为准） |
| `serial-key-lines.txt` | — | 串口关键行摘录（带行号） |
| `service-log-capture-window.txt` | — | 服务端日志 1681–1923 摘录（带行号） |
| `curl-e2e.log` | — | 每次 /debug/mcp 的完整命令 + 回显 + 上传路径 + HTTP 码 + sha256 |
| `mute-change.log` | — | mute 基线/变更/恢复的 GET/POST 回显 |
| `scripts/*.py|sh` | — | 串口采集、四视图连拍、D 重试脚本原文 |

## 10. 交接块（给 T2 / 修复卡）

- 目标：ABCD 四视图 persona.2 真机现象取证（已完成）。
- 已定决策：不刷机、不改码；设备截图 = `self.screen.snapshot` → `/debug/upload` → `/debug/photo/<name>`；四图均在 muted=true 下拍摄。
- 涉及文件：本目录（md + evidence）。
- 下一步（T2）：按 §7 表逐条归因，重点确认 #4、#5 两条「未复现」的 persona.3 修复点、#9 的静音可点区域差异，以及 D snapshot 失败是否与 D GameTick 资源竞争有关。
- 触摸结论：persona.2 正常点按/滑动/右下角静音可用，幽灵点自锁本次未复现（但未覆盖幽灵点路径）；串口引用以 `serial-persona2-2210.final.log`（sha256 `5307aef7…`）为准。
- 验收命令：§4.1 三条 curl + `python3 evidence/scripts/capture_serial.py`；日志行号见 §5/§6。


---

## 证据可访问性（隐私清理，2026-10-30）

原始串口日志 `evidence/serial-persona2-2210.log` 与 `evidence/serial-persona2-2210.final.log` 已改为**本地未跟踪**（`.gitignore` 规则 `docs/tasks/**/serial-*.log`），仓库内不再包含；本文件所引 sha256（`5307aef7…e336`）、行号与结论均未改动，复算需在本机同一份本地文件上执行。
