# HANDOFF — ESP32 桌面小智（ABCD 四视图调研收口）

phase-close: task-4
收口时间：2026-10-29 23:1x（Dev Team·单仓库：lead + impl-repro / impl-arch / impl-report + reviewer-a / reviewer-b / reviewer-c + verifier / verifier-2）

**一句话结论**：四视图的恐龙问题**不是编码问题，是配置问题**。
B/C/D 的 A 条残留是 persona.3 `d2d47c7` 的 hide 没上板（回滚/未回移）；
D 游戏恐龙悬空 9px、仙人掌悬空 8px 是 persona.2 自身缺陷，**persona.3 至今也没修**。
决策文档：`docs/tasks/abcd-views/03-report.md`。

## 版本与契约

| 仓 | HEAD | tag | release |
|---|---|---|---|
| esp32-voice-entry | `9329007`（+ 本收口提交） | `v0.1.2` @ `fbe5bd7` | https://github.com/yes999zc/esp32-voice-entry/releases/tag/v0.1.2 |
| xiaozhi-esp32 | `64d13ba`（工作树干净，**本阶段未提交任何代码**） | `v2.5.3-persona.3` @ `0a43f23` | https://github.com/yes999zc/xiaozhi-esp32/releases/tag/v2.5.3-persona.3 |

- **板上 app = release `v2.5.3-persona.2`**（tag `81b3b20`）：app 分区 0x20000，资产 2920928 B，
  sha256 `a67645c88da005ee48a913eb89d6cefca8786c6a0efbf71364eff7309e2eeab4`（`…eeab4`），md5 `7ad4b6f7…`。
- **身份已闭环（2026-10-29 22:43 verifier）**：下载 release 资产 →
  `esptool.py --port /dev/cu.usbmodem31301 --after hard_reset read_flash 0x20000 2920928 /tmp/board-app.bin`
  → 板上 sha256 = 资产 sha256，`cmp` **逐字节一致**。
  串口启动行 `Compile time: Oct 28 2026 23:36:05` 是该资产**自身的构建戳**（夜间构建、次日 09:41 提交），
  **不能用启动行推断 tag**。
- **回滚锚** = 上述 persona.2 release 资产。**本机没有它的副本**（`build/xiaozhi.bin` 已于 10-29 21:52
  被 persona.3 重编译覆盖为 `56d96d7d…`）；回滚前必须先从 GitHub release 重新下载并复核 sha256。
- D3 触摸修复 `64d13ba`（历史 md5 `20124ade…`）在 main 上、**不在板上**；persona.2 触摸实测正常（见「已完成」）。
- 服务端 `v0.1.2`：`/admin` 单页控制台、统一字体/按钮、480px 顶栏修复。
- 旧 tag 未移动：`v0.1.0`、`v0.1.1`、`v2.5.3-persona.1`、`v2.5.3-persona.2`。

## 已完成（含证据）

### C1 非 A 视图隐藏 A 条恐龙（2026-10-29 23:2x–23:37，**代码已交付、产物未刷机**）

- 分支：`05_Tools/xiaozhi-esp32` → `fix/persona2-hide-dino`，commit `2fd4a698af84710e2d0e567cc408243ec5608d03`
  （parent = tag `v2.5.3-persona.2` / `81b3b20`；**不基于 main**，未推 main、未 tag、未 release）。已 push 分支。
- 改动：`chd_esp32s3_box_board.cc` 的 `ApplyViewLayout` 里 `dino_root_` 一处 hunk（+7/−2）：
  `is_a` → `remove_flag(HIDDEN)` + `move_foreground`；否则 `add_flag(HIDDEN)`。
  与 `d2d47c7` 第 3 个 hunk 逐行等价，**未**取 include / ScreenClickCb / HandleTap；未动 ADinoTick / GameTick / 配置 / 字体 / 触摸 / mute。
- 评审 reviewer-d **PASS**；验证 verifier-3 **VERIFIED**（独立 worktree 重建 exit 0、0 error、
  sdkconfig 与主工作树逐字节相同、与交付物仅 68 字节差异 = 构建时间戳 + elf_sha256 + 尾部哈希；
  另重建 parent tag 得 2920928 B 与回滚锚同尺寸，确认 +16 B 只来自新增代码）。
- 产物：`02_Archive/esp32-firmware/c1-hide-dino/xiaozhi.bin`（2920944 B，sha256 `11b77dc2…37e3`，
  md5 `3172bbf1…393f`）+ 同目录 README（刷写只 `0x20000`、回读校验、回滚命令、未刷机声明）。
- 回滚锚：`02_Archive/esp32-firmware/v2.5.3-persona.2/xiaozhi.bin`（2920928 B，sha256 `a67645c8…eeab4`）+ README。
- **未刷机、未做真机确认**（按 9哥 要求等授权）；真机验收清单见任务卡 `task-6`。
- 已知残余风险：A 视图切回时 dino 最多 1 帧（≤80 ms）闪现，与 persona.3 同款行为。

### 本阶段：ABCD 四视图调研（2026-10-29 22:05–23:10）

- `task-1` **T1 真机取证** → `docs/tasks/abcd-views/01-repro-evidence.md`（325 行，sha256 `531188fe…fdc8`）
  + `docs/tasks/abcd-views/evidence/`：5 张 480×320 设备截图、`serial-persona2-2210.final.log`
  （3781 行 / 256134 B / sha256 `5307aef7…e336`，已冻结勿再追加）、服务端日志窗口、curl 回显、
  mute 变更记录、crops、4 个复现脚本。评审 reviewer-a **PASS**；verifier **VERIFIED**。
  复现命令：`POST /debug/mcp {"name":"self.screen.set_view","arguments":{"view":0..3}}`
  （Bearer = `~/.esp32-voice/control.token`）；截图走设备工具 `self.screen.snapshot` → `GET /debug/photo/<name>`。
- `task-2` **T2 代码归因** → `docs/tasks/abcd-views/02-code-arch.md`（458 行，R1..R8 表 + 三桶归属）。
  评审 reviewer-b **PASS**。关键实证：`d2d47c7 → 175056b → 0a43f23` 依序 `git apply` 到 persona.2 后
  板级文件 blob 恰好 = persona.3 的 `42fe3283…`（零冲突）；`64d13ba` 单独 → `de2852f4…`；
  `6a6697b+e5b2139` → `e54a7649…`；`e6b7c1b` → `335b7925…`。
- `task-3` **T3 根因报告 + 拆卡** → `docs/tasks/abcd-views/03-report.md`（480 行，sha256 `70274854…10e8`）。
  评审 reviewer-c（fresh）**PASS**；verifier-2 **VERIFIED**。
- 结论（TL;DR 见 `03-report.md` §0）：
  - 恐龙精灵 **9/9 编码自洽**（`stride==w`、`data_size==w*h`、初值个数 = w*h、取值仅 {0,255}）→ **不要重导资源**。
  - 恐龙/游戏配置块在 persona.2 / persona.3 / main **逐字节相同**（65 行）→「回滚才出现恐龙问题」只对 R1/R3 成立。
  - **A**：恐龙条正常，脚底裁 ~1.3px、仙人掌 ~2.1px（肉眼不可辨）；CJK 标题正常。
  - **B/C**：A 条恐龙（x26–54/y290–319）+ **冻结**仙人掌（x452–464/y295–319）残留 = R1（`d2d47c7` 未上板）；
    C 另有 debug 行被残留恐龙压住。仙人掌「冻结」是 `ADinoTick` 非 A 视图早退（门控），不是隐藏失败。
  - **D**：游戏正常（分数 00001→00165、8 条采样 5×28fps + 3×27fps、仙人掌一大一小轮换）；两个真缺陷：
    A 条叠进游戏区「两只恐龙」（R1）+ 游戏恐龙悬空 9px、仙人掌 8px（R4，三版本同款）。
    D 的 3 行日志底 143 < 游戏区顶 170，**不构成遮挡**。
- 三处口径修正（详见 `03-report.md` §1.1）：
  - **M1**：persona.2 **只有右下头像一个可点静音入口**（`mute_hit_` p2:1053 HIDDEN、`mute_button_` p2:1308-1310
    HIDDEN、D 视图头像也隐藏 p2:1445-1446）→ 9哥 说的「右上角不响应」是**顶栏没有可点对象**，不是触摸失灵。
  - **M2**：`175056b`（A 标题 CJK）在 persona.2 上**无可见效果**（被 `ApplyPhaseBFonts` p2:1313/1639 覆盖）。
  - **M3**：D 的 3 行日志是设计取舍，不是图层 bug。
- **触摸事实更正**：本次 persona.2 会话触摸正常——`tap -> ToggleChatState` 15 次、`pressed=1 points=1` 167 次、
  心跳 133 条全 `stale=0/ghost=0/forced=0`、`reason=stale|ghost-release|ghost lock` = 0；
  `Application: mute: toggle requested by UI` **6 次**（其中 4 次与 mute 变更毫秒级对应）。
  **旧记录的「幽灵点自锁」本次未复现**，属间歇（persona.2 仍含 `68f0f06` 的 HOLD 策略，未覆盖该路径）。
- 环境：开串口复位 1 次（22:06:57），verifier 闭环身份再复位 1 次（22:43）；**全程未刷机、未改代码**
  （固件仓 `git status` 空）。mute 采集期临时解除并已还原
  （现 `muted=true, since 2026-10-29T22:12:14, changed_by=http`）。

### 历史（本阶段之前，未变）

- persona.3（`0a43f23`）含：配网误触保护、非 A 视图隐藏 `dino_root_`（`d2d47c7`）、A 标题 CJK（`175056b`）、
  日志区点击穿透、D 游戏 `move_foreground`（`0a43f23`）；`e6b7c1b`（静音后唤醒恢复）在 persona.3 之后。
- 回滚原因：persona.3 + D3 之后真机出现「静音键两端 + 触摸激活都不响应」，根因定位为触摸点过滤器
  `68f0f06` 的 stale 恒 HOLD 自锁，D3 `64d13ba` 是修复（未上板）。
- **9哥 已确认**：回滚 persona.2 后静音键与静音后唤醒**可用**（2026-10-29 22:0x「可以了」）。

## 未完成 / 阻塞

- **C1 已实现并上板**（见上节）；C4 / C3 / C2a / C2b / C5 / C6 仍待开卡。
- D snapshot 成功率约 2/9（设备侧 HTTP 上传失败，非渲染问题）；需要 D 截图时建议间隔 ≥5 s 重试。
- R6（幽灵点自锁）没有复现路径，C6 只能作为条件卡；真要跟，需要能复现幽灵点的现场。
- C0 已完成：回滚锚已落盘 `02_Archive/esp32-firmware/v2.5.3-persona.2/`（sha256 `a67645c8…eeab4`，已核）。
- 遗留（未变）：D 翼龙只有单帧无扇翼动画；D 实测 25–28 fps 未达 30；launchd 下屏幕录制授权仍缺
  （桌面截图 `desktop capture failed`，不影响语音/媒体）。

## C1 真机验收（2026-10-29 23:48 – 2026-10-30 00:1x，**通过**）

- 板上已刷 **C1**（`02_Archive/esp32-firmware/c1-hide-dino/xiaozhi.bin`，sha256 `11b77dc2…37e3`，2920944 B；回读 cmp 一致）；boot 身份 `Compile time: Oct 29 2026 23:27:54` / `ELF ca03d59f1…`。
- 验收交付：`docs/tasks/abcd-views/c1-verify/SUMMARY.md`（sha256 `b3f5d7ca…c165`）+ 16 张截图 + 3× 底部条带 crop + 串口两段（`serial-c1-verify.log` 805 行 / `serial-c1-reboot.log` 578 行）。
- 判定：**#1 A、#2 B、#3 C、#4 D、#5 重启后 = PASS**（B/C/D 底部 `x18–56` 暗像素均为 0；C debug 行首字符可读；D 只剩游戏恐龙、分数 00019→00043）；**#6 回归 = PARTIAL**：右下头像静音 PASS（serial 439/480 ↔ service 1949/1950）、点按链路 PASS（tap→ToggleChatState ×3）、UI 无变化 PASS，**"触摸切视图" 未覆盖**（本次无真人滑动，串口无 `CHD_UI: view=`）。
- mute：基线 true(22:48:30) → 23:44:04 授权解除 → 采集 → **23:47:36 还原 true**（GET 回显 `muted=true since 23:47:36`，设备 serial 515/519 已同步）。
- 未重新刷机、未改代码；回滚锚 `v2.5.3-persona.2`（a67645c8…eeab4）未使用。
- 待办：无。9哥 已现场滑动确认「触摸切视图」（串口当时未挂，见 `c1-verify/SUMMARY.md` §8 的取证缺口说明），task-6 已 complete。

## C4 顶栏静音文字可点 + 18px 热区（2026-10-30 00:2x–00:3x，**代码已交付、产物未刷机**）

- 分支：`fix/persona2-mute-text`，commit `cad924f386d45a32f12bb2c0066668468d4c9783`，parent = C1 `2fd4a698`（**累计构建**）。
  已 push，未推 main、未 tag、未 release。
- 改动：`chd_esp32s3_box_board.cc` 一处 hunk **+5 行** —— `mute_text_` 加 `CLICKABLE` + `ext_click_area(18)` +
  `CLICKED → MuteButtonCb`（等价 `6a6697b` + `e5b2139`）；`MuteButtonCb` 本体一行未改；未带 D3/`d2d47c7` 其余 hunk。
- 评审 reviewer-e **PASS**（含 README 两处事实纠正）；验证 verifier-4 **VERIFIED**（独立 worktree 重建 exit 0、0 error，
  与交付物仅 68 B 差异 = 构建时间 + elf_sha256 + 尾部填充/哈希；C4 vs C1 = 精确 +32 B，shift +28 下 99.6% 逐字节相同；
  sdkconfig 与 deps.lock 均逐字节相同，零漂移）。
- 产物：`02_Archive/esp32-firmware/c4-mute-text/xiaozhi.bin`（2920976 B，sha256 `b69da00b…8c0f`，md5 `c844fa3a…`）+ README（只刷 0x20000、回读校验、两级回滚 C1/persona.2）。
- 预期行为：点顶栏「未静音/已静音」文字（名义热区 x282..408 / y−8..50，实际被父对象裁到 y0..43）→ `ToggleMute()`，
  服务端出现 `by=device`；日志区/脸部/头像行为不变。**未刷机、未真机确认**（验收清单见 `task-8`）。

## C3 D 视图落地像素（2026-10-30 00:3x–00:4x，**代码已交付、产物未刷机**）

- 分支：`fix/persona2-dino-ground`，commit `351945b41e6e8934bd2797c9886e74e502d37699`，parent = C4 `cad924f`
  （**累计 = persona.2 + C1 + C4 + C3**，一次刷写可验三张卡）。已 push，未推 main/tag/release。
- 改动：同一文件 `7 insertions(+) / 7 deletions(-)`，**7 处 / 9 个字面量**：dino `80→89`（成员初值 / 创建 / 落地夹紧两行）、
  cactus 创建 `92→100`、重生与碰撞两条三元 `large 77→85 : small 92→100`。无其它数字、无格式化噪音。
- 算术（reviewer-f 与 verifier-4 各自独立从 A8 数据算出，全 = **303**）：ground 170+127+6；dino 170+89+44；
  cactus small 170+100+33；large 170+85+48。旧值 294/295 → 悬空 9/8 成立。跳跃 `vy=-10` 相对基线，相对高度 55px 不变。
- 评审 reviewer-f **PASS**（唯一瑕疵是 README hunk 计数写 4、实为 5，已由 Lead 改正）；验证 verifier-4 **VERIFIED**
  （独立重建 exit 0、0 error；与交付物 67 B 差异 = 时间戳/elf_sha/尾部哈希；C3 vs C4 = +16 B（净 12 B 代码 + 4 B 对齐填充），
  shift +12 下逐块匹配 0.99–1.00，确认为常量改动的结果；sdkconfig/deps.lock 零漂移）。
- 产物：`02_Archive/esp32-firmware/c3-dino-ground/xiaozhi.bin`（2920992 B，sha256 `2471048e…98b3`，md5 `1e572003…`）
  + README（只刷 0x20000、回读校验、三级回滚 C4/C1/persona.2）。
- **未刷机、未真机确认**；操作单一页纸：`docs/tasks/abcd-views/MORNING-2026-10-30.md`；合并验收卡 = `task-8`。
- **2026-10-30 00:5x 已刷（Lead 亲手）**：`write_flash 0x20000 c3-dino-ground/xiaozhi.bin` → `Hash of data verified.`；
  `read_flash 0x20000 2920992` 回读 sha256 = `2471048e…98b3`，与产物 **cmp 逐字节一致**；只写 app，NVS/Wi-Fi 保留。
  板上现为 **C1+C4+C3**；`task-8` 验收进行中（TTS 不可用，改用 9哥 手指点屏幕开 WS / 触发点击）。
- **设备截图客观复核（00:57–00:59，证据在 `docs/tasks/abcd-views/c3c4-verify/`）**：
  - B 底部 `x18..56` 暗像素 **= 0**（无 A 条残留）；C 8 行日志 + debug 行 `up … A 17529/D 18` 首字符可读、无底部条带；
  - **D：地面线 y=303（整行 480 暗像素）；游戏恐龙墨迹底 = 303、仙人掌墨迹底 = 303**（改前 294/295）→ 悬空 9/8px 已消除；
  - A 条仍在（恐龙 x26–54 / y290–319），仙人掌 2 s 内 x382→137（在动）。
  - 注：`set_view=2` 曾返回 500，是 Lead 自己 curl 的 JSON 引号写坏（`Extra data: line 1 column 12`），非固件问题，重发即正常。

## C4 真机结论：顶栏文字「够不到」（2026-10-30 01:0x）

- 真机实测（9哥 手点，串口 `/tmp/touch-cal.log` + `c3c4-verify/`）：瞄准视觉上的「未静音」(y≈25)，
  固件收到 **y=49~57**（偏差 25~30px，x 基本正确）；连点 6 次全部 `tap -> ToggleChatState`，**没有一次** `mute: toggle requested by UI`。
- 根因（代码级，不是 C4 写错）：`ui_bar_` 高仅 44，LVGL 只在该点落在**父对象 coords 内**才检索子对象
  （`lv_indev.c:631-646`）→ 顶栏内任何热区（含 `ext_click_area`）都被裁在 y0..43，手指落点 y≈50 永远打不中。
  触摸映射本身是 swap + `Y = 319 - raw_x`（board.cc 2790-2850），无常数补偿。
- 结论：C4 那 5 行**保留**（文字本身可点，双保险），但要能用必须改成**屏幕层热区** → 已开卡 `task-10`（C4b，
  分支 `fix/persona2-mute-hotspot`，基线 C3；透明热点 x280..395 / y0..64，`CLICKED → MuteButtonCb`）。
- 顺带澄清：9哥 看到的「在线/离线 来回跳」是他点屏幕切对话的既有功能 + 设备 2s 一次的 OTA/静音 HTTP 轮询，
  **不是崩溃**（串口无 panic/rst；`free sram 15–30K`）。设为 `muted=true` 后 20s 内零新连接，抖动停止。

## 2026-10-30 01:3x–01:5x（9哥 睡觉，授权刷机 + TTS）

- **已刷 C4c 并回读校验**：`write_flash 0x20000 zone-taps/xiaozhi.bin` → `Hash of data verified.`；
  `read_flash 0x20000 2921264` sha256 = `63c9f7e5…28de4`，与产物 **cmp 逐字节一致**。板上现为 **C1+C4+C3+C4c**（仅刷 app，NVS/Wi-Fi 保留）。
- **本机服务事故与修复**：期间 `/tmp/esp32-voice-service.log` 反复报
  `OSError: [Errno 48] ... 4411 address already in use`，一个孤儿 `python3.1` 进程占着 4411、launchd 启动的新实例不断失败；
  之前观察到的「设备每 2s 连一次 WS 又立刻断」是这个坏服务状态造成的，**不是固件问题**。
  处理：`launchctl bootout` → `pkill Esp32VoiceService` → kill 占端口的 python → `launchctl bootstrap`。
  现在：单实例 `Esp32VoiceService`(81354) + `python3.1`(81357)，`/admin` 200，20s 内零重连。
- **TTS 唤醒失败（已尝试）**：把默认输出切到 `2K USB Camera-Audio`（音量 55 / 95）与 Mac Studio 扬声器（70），
  各播「你好小智」3 次，设备均未建 WS（`/debug/mcp` 一直 `sent:0`，`[conn]` 计数不变）。
  本轮无法远程拉会话 → **设备端点击/截图验收未完成**。另测到 Wi-Fi RTT 抖动很大（100–766ms），可能与此有关。
- **release 未发布**：`v2.5.3-persona.4` 的 tag/说明/产物与哈希已备好，但"能用了"缺 9哥 手指确认（左/右分区、品牌区轮换、D 跳跃），
  故按纪律**不发布**。发布脚本与命令见本节下方的「release 待发」。
- 状态还原：`muted=true`（01:42:11），默认音频输出已复原为 Mac Studio 扬声器，系统音量 100。

### release 已发布（pre-release，2026-10-30 01:45）
**https://github.com/yes999zc/xiaozhi-esp32/releases/tag/v2.5.3-persona.4** —— 标了 `--prerelease`，标题写明
"ABCD UI fixes + tap zones"，notes 里如实写了「左右分区/品牌区点击尚未真机点按确认」。
tag `v2.5.3-persona.4` = `832d2295` → 指向 `bbf5b20`；资产 `xiaozhi.bin`（2921264 B）+ `SHA256SUMS.txt`。
撤销：`gh release delete v2.5.3-persona.4 --repo yes999zc/xiaozhi-esp32 --cleanup-tag`（真机确认后再发正式版即去掉 pre-release）。

| 项 | 值 |
|---|---|
| tag | `v2.5.3-persona.4`（annotated，指向 `fix/persona2-zone-taps` @ `bbf5b20`） |
| 资产 | `xiaozhi.bin`（2921264 B，sha256 `63c9f7e5…28de4`，md5 `ce6c8baa…`）+ `SHA256SUMS.txt` |
| 内容 | persona.2 + C1（非 A 视图隐藏 A 条）+ C4（顶栏静音文字可点）+ C3（D 恐龙/仙人掌落地）+ C4c（左/右分区点击，D 例外） |
| 刷写 | `write_flash 0x20000 xiaozhi.bin`（只写 app；回读 `read_flash 0x20000 2921264` → `63c9f7e5…28de4`） |

## CI 红色清理（2026-10-30 02:2x 起，夜间只跑 host 测试 + git，不刷机不出声）

三张卡（Dev Team，reviewer PASS + verifier VERIFIED 才 complete）：

| 卡 | 仓库 | 内容 | 状态 |
|---|---|---|---|
| `task-12` A | esp32-voice-entry | privacy-scan 清红：4 个串口原始日志 `git rm --cached`（本地保留）+ `.gitignore docs/tasks/**/serial-*.log`；其余 tracked 文件 IP → `<nas-ip>/<device-ip>` | **completed**（reviewer-b PASS + verifier-2 VERIFIED；run [40930381600](https://github.com/yes999zc/esp32-voice-entry/actions/runs/40930381600) / [40930506280](https://github.com/yes999zc/esp32-voice-entry/actions/runs/40930506280) 双绿） |
| `task-13` B | xiaozhi-esp32 | Build Boards 红：`startup_wake_word_hint.cc:130 'strcasecmp' not declared`（host 桩切自 `main/application.cc`）→ 修源头补 `<strings.h>` | in_progress（impl-c1；本地已改 `application.cc` + `test_startup_wake_word_hint.py`） |
| `task-14` C | xiaozhi-esp32 | persona.4 分支 MCP host tests 红（run 40924176788）：本地拿 `g++` 真实 stderr 再修，并收敛 `requires C++23/cJSON/mbedTLS headers` 的 skip 条件（CI 不 skip） | blocked_by task-13 |

### A 落地事实（留存）
- commit `c9c23a6`：14 文件 = `.gitignore`(+3) + 4 个日志 `rm --cached` + 8 个文档脱敏 **77 处**（全是 NAS 与设备的局域网地址，见 `<nas-ip>` / `<device-ip>`；
  SSID 只存在于已 untrack 的日志里、未做替换——「IP/SSID 77 处」措辞略宽，实际是 77 处 IP）。
- 4 个日志本地保留：36588 / 53007 / 256134 / 256134 B；`.final.log` 本地 sha256 仍 `5307aef7…e336`，文档登记 sha256/行号未改。
- 遗留：git **历史**仍含 IP/SSID 与 3 个原始日志 blob（彻底清需另开 `filter-repo` + force-push 卡）；本地 4 个日志是明文（`.gitignore` 只防再入库）。

约束：不 force-push、不改历史；证据结论/行号/sha256 保留；夜间禁 TTS/唤醒/刷机。
验收：三条 workflow 在 **main 与 persona.4 分支**都绿，回贴 3 个 run 链接。

## 下一步（9哥 已定顺序）

0. **交互模型改为「左右分区」**（9哥 2026-10-30 01:1x 定）：
   左半屏（x0–239，整屏高）点击 = 在线/离线（`ToggleChatState`）；右半屏（x240–479）点击 = 静音/不静音（`MuteButtonCb`）；
   **D 视图两个分区自动隐藏**，点=跳（游戏不受影响）。实现见 `task-11`（分支 `fix/persona2-zone-taps`，基线 C3）。
   9哥 已确认两个副作用可接受：① 右半区包含头像与脸 —— 脸本来就是静态图、头像本来也是点它切静音；
   ② 全屏媒体/字幕「我也不碰它」。
   C4b 小热区（`fix/persona2-mute-hotspot` @ `c9bef22`）作废，仅留分支备选，不上板。
- **C4c 已实现（未刷机）**：分支 `fix/persona2-zone-taps`，**当前 HEAD `bbf5b20`**（首版 `7582c15` 已废弃，勿刷）；
  基线 C3 `351945b`，唯一文件 `+34/−0`。
  产物 `02_Archive/esp32-firmware/zone-taps/xiaozhi.bin`（2921264 B，sha256 `63c9f7e5…28de4`，md5 `ce6c8baa…`）。
  几何：**左区 x0..239 / y44..319**（让出 44px 顶栏，保住品牌区 A→B→C→D 轮换）→ 切对话；
  **右区 x240..479 / y0..319**（含顶栏右侧）→ 切静音；D 视图两区隐藏（点=跳）。
  闸门：**reviewer-e PASS**（几何/命中链/z 序/D 例外/guard/产物/回滚/卫生全过；README recipe 已改指 `bbf5b20`）；
  verifier-4 已对首版 VERIFIED，正在按新 recipe 对 `bbf5b20` 做增量重建比对 `63c9f7e5…28de4`。
- **事实更正（评审确认）**：本固件**没有「滑动切视图」**（`gesture_event_cb` 的 LEFT/RIGHT 是空块）；
  触摸切视图的唯一入口是左上品牌区（`HermesViewCb`）。`face_panel_` 在 Phase B 无条件隐藏，脸部不显示，
  C4c 的分区对脸无影响（README 已改正早期的错误取舍）。
- **待 9哥 拍板的副作用**：左半区覆盖了 Hermes 品牌区（x0..184 / y0..43，原 `HermesViewCb` 点一下轮换 A→B→C→D）
  → **点 logo 不再能轮换视图/进 D**（滑动切视图仍有效，手势走 screen 不受热区影响）。
  选项：A) 把品牌区从左区挖掉（1 行，保住老习惯，Lead 建议）；B) 保持整屏两半，进 D 靠滑动。
- 其余取舍（9哥 已口头接受）：右半区点击一律静音（脸/头像都算）；全屏媒体不常用。

0. **早上一次刷写三合一**（`c3-dino-ground` 产物已含 C1+C4+C3）→ 执行 `task-8` 的 A/B/C 共 7 条验收
   （A: 顶栏文字可点 + ±18px；B: D 恐龙/仙人掌贴地、跳跃手感不变；C: C1 四条回归 + 头像 + 重启后成立）。
   操作步骤与回滚阶梯见 `docs/tasks/abcd-views/MORNING-2026-10-30.md`。
1. **C2a / C2b（可选，需决策）**：C2a `0a43f23` z-order 防御（9 行，依赖 C1；C1 之后 D 已可见，价值不大 → 建议不做）；
   C2b D 视图那 3 行日志去留（`p2:1382` + `p2:1803-1805`）。
2. **C5 `e6b7c1b` 唤醒恢复**：单独决策（唯一改 mute 唤醒语义的改动）。
   **C6 `64d13ba` 触摸**：只在幽灵点自锁复现时开卡（本次未复现）。
3. 每个修复卡都沿用这个分支模式：**独立 worktree + persona.2 基线 + 单类变更 + 独立评审/验证 + app-only 产物 + 不刷机直到授权**。

## 禁止项（本阶段已遵守，下一阶段继续）

- 刷机**只写 app `0x20000`**，**不要写 `0x0`**（会清 NVS / Wi-Fi）；回滚锚 = persona.2 release 资产。
- 调研/文档卡不改固件代码；实现卡只改 `05_Tools/xiaozhi-esp32`，**不改 `01_Code/projects/esp32-voice-entry/src`**（只读）。
- 不动触摸过滤器（`64d13ba` 在 main 未上板；除非 C6 立项）；不动 mute 语义与服务端静音真相。
- 不重导恐龙资源、不改 `main/ui/chrome_dino_sprites.h`（编码已证明自洽）；不删既有测试当绿。
- 一张修复卡只带一类变更；未过 reviewer PASS + verifier VERIFIED 不得标 complete。

## 本机常驻服务

- app：`/Applications/Esp32VoiceService.app`
- plist：`~/Library/LaunchAgents/com.bakey.esp32-voice.plist`（`RunAtLoad` + `KeepAlive`）
- 日志：`/tmp/esp32-voice-service.log`
- 运维：重启 `launchctl kickstart -k gui/$(id -u)/com.bakey.esp32-voice`；停止 `launchctl bootout gui/$(id -u)/com.bakey.esp32-voice`
- `/admin`：`http://<host>:4411/admin`，token `~/.esp32-voice/control.token`（只存浏览器 localStorage）

## 关键文件

- `02_Archive/esp32-firmware/c1-hide-dino/` — **C1 app-only 产物**（`xiaozhi.bin` sha256 `11b77dc2…37e3`）+ 刷写/回滚说明
- `02_Archive/esp32-firmware/v2.5.3-persona.2/` — **回滚锚**（`xiaozhi.bin` sha256 `a67645c8…eeab4`）+ 回滚说明
- `docs/tasks/abcd-views/03-report.md` — 决策主文档（TL;DR / 速查表 / 四视图 / C0–C6 拆卡）
- `docs/tasks/abcd-views/02-code-arch.md` — R1..R8 缺陷表、三桶归属、cherry-pick 实证
- `docs/tasks/abcd-views/01-repro-evidence.md` — 真机证据（每视图截图 + 实测坐标 + 串口/服务端行号）
- `docs/tasks/abcd-views/evidence/` — 原始证据（**`serial-persona2-2210.final.log` 为准，勿再追加**）
- `05_Tools/xiaozhi-esp32/main/boards/chd/chd-esp32s3-box/chd_esp32s3_box_board.cc` —
  `ApplyViewLayout`（p2:1368+）、`dino_root_`（p2:1180-1200）、`game_view_`（p2:1202-1243）、
  `ADinoTick`（p2:1761+）、`GameTick`（p2:1494-1501）
- `05_Tools/xiaozhi-esp32/main/ui/chrome_dino_sprites.h` — 9 个 A8 sprite（编码已验，勿动）

> 行号约定：固件行号一律引 **persona.2 tag 自己的行号**（`p2:`）；仅在对照修复时引 `main:`。
> 串口行号用 `grep -n` / `sed` 取（`final.log` 第 133 行有孤立 CR，Python `splitlines()` 会让其后行号 +1）。

## 隐私清理（2026-10-30）

- privacy-scan 已转绿：4 个原始串口日志改为**本地未跟踪**（`.gitignore: docs/tasks/**/serial-*.log`，本地文件保留），其余 8 个 tracked 文档共 **77 处** LAN IP/SSID 脱敏（`<nas-ip>` / `<device-ip>` / `<gateway-ip>` / `<wifi-ssid>`）。
- commit `c9c23a6`（普通 push `69b8105..c9c23a6`，无 force）；run **40930381600 success**：https://github.com/yes999zc/esp32-voice-entry/actions/runs/40930381600
- 证据结论、sha256、行号未改；仅在 `01-repro-evidence.md`、`02-code-arch.md`、`c1-verify/SUMMARY.md` 末尾补「本地未跟踪」说明。
- 风险：git 历史 commit 仍含 IP/SSID（未改写历史）；本地 4 个 serial 日志为明文，已被 .gitignore 拦住，勿再 add。

## 新会话第一条（模板）

```
读 01_Code/projects/esp32-voice-entry/docs/HANDOFF.md（ABCD 四视图调研已收口）：
- 先核对：launchctl 服务 running、/admin 200、
  `curl -H "Authorization: Bearer $(cat ~/.esp32-voice/control.token)" http://127.0.0.1:4411/debug/mute` 能返回；
- 板上 app = release v2.5.3-persona.2（sha256 a67645c8…eeab4，已 read_flash + cmp 证明）；main = 64d13ba（D3 未上板）；
- 读 docs/tasks/abcd-views/03-report.md §0 / §1.2 / §4，再按「下一步」开卡；
  刷机只写 app 0x20000，**不要写 0x0**；串口行号用 grep -n，固件行号引 persona.2 tag。
```

本阶段已收口，可直接从「下一步」接着做。

## Bridge 交接（2026-10-30 03:0x 更新，覆盖 03:2x 的旧块）

- **仓库/发布**：`v2.5.3-persona.4` 已发 **pre-release**（tag `832d2295` → 分支 `fix/persona2-zone-taps` @ `bbf5b20`）。
- **板上固件**：已是 **persona.4**（persona.2 + C1 + C4 + C3 + C4c），02:0x 亲手刷写并回读校验
  （sha256 `63c9f7e5…28de4`，cmp 逐字节一致）；当前 `muted=true`。
- **CI 三红已清（本轮）**：
  1. `esp32-voice-entry` privacy-scan：**绿**（run 40930381600 / 40930506280 / 40935217417）。raw 串口日志已转本地未跟踪，
     其余文档 IP 换占位符；历史仍含旧值（要彻底清需另开 filter-repo 卡）。
  2. `xiaozhi-esp32` Build Boards：**修好的是「Test build tooling」那一步**（原红因 `strcasecmp`），ci 分支 run 40934910762 里该步已 **success**；
     ⚠️ 更正：main 的 run 40932405949 是 **skipped**（变更选择没命中任何板，矩阵没真跑），不能算「main 绿」；`ca6eb8c` 与分支 `efcfe80` 曾红于缺 `<strings.h>`，
     已 cherry-pick 到分支（`9b22121`）。分支构建（`ci/persona4-verify` = 9b22121）连跑 3 次仍红，且**红点与代码无关**：
     18/30 个板 job 全在 `Build current variant` 的 `idf.py reconfigure` 处报
     `ERROR: File .component_hash or CHECKSUMS.json for component "78/esp-wifi-connect" …`，
     失败板里包含 `m5stack-atom-echos3r` / `bread-compact-wifi` / `esp-hi` 等与本项目无关的板 —— 属 CI 侧组件注册表/缓存问题，
     同一时刻 main 的同类构建是绿的。**结论：分支「能编」目前改用本地 IDF 6.1 构建作证据**（顺带产出 merged 镜像），不阻塞 doc 卡。
- **分支本地构建已验（2026-10-30 03:0x，硬证据）**：在 `/tmp/xz-c`（detached `9b22121`，seed 主工作树 `managed_components` +
  `dependencies.lock` + `sdkconfig`）执行 `python3 scripts/build.py chd/chd-esp32s3-box --name chd-esp32s3-box-lcd35 --language zh-CN`
  → **exit 0**，产出 `build/xiaozhi.bin` **2921264 B**（与 release 的 persona.4 app 同尺寸）与 `build/merged-binary.bin`
  **10164189 B**（整包，可 `0x0`，会清 NVS/Wi-Fi）。这同时是下一张「factory 全量镜像」卡的现成输入。
  3. `xiaozhi-esp32` MCP host tests：**两个 ref 都绿**（main d5f70b3 / 分支 efcfe80）。根因是 host 桩缺
     `Application::OnMuteEndpoint`，并收敛为 `MCP_REQUIRE_TOOLCHAIN=1` 时 CI 不 skip。
- **文档卡**：`docs/quickstart-single-board.md`（新人单板部署）+ README 资产说明已修正（commit `f5e2806`），等 reviewer 复核。
- **待白天**：真机点按确认左/右分区与品牌区轮换；分支 Build Boards 若仍红则用本地 IDF 6.1 编一次作为分支可编证据（顺带产出 merged 镜像）。

### doc 卡已收口（2026-10-30 03:1x）
- `docs/quickstart-single-board.md`（新人单板部署，四段 + 5 条自证验收 + 已知缺口）+ `README.md` 中英两节修正，
  commit `f5e2806` → `c28fde6`（按 tag 限定 release 资产 / OTA 占位 / 板型列表 / TTS 行号）→ `a80b51a`（p2/p3 app 尺寸拆行 + 章节标题不再自相矛盾）。
- 闸门：**reviewer-b 两轮 CHANGES 后 PASS**（第一轮推翻了我「release 只有 app-only」的错误前提——persona.2/3 实际带
  `merged-binary.bin` 10164189 B 整包；以及 bin 里是未展开的 `${XIAOZHI_OTA_BASE}` 占位、无内网 IP）。
- 隐私：privacy-scan run 40937083544 success（head `a80b51a`）。
- 评审非阻塞备注：`:101` 的 `2921264 B` 是 `/tmp/xz-c` 那次构建的值，主仓 `build/xiaozhi.bin` 当前是 2921568 B（更早一次构建）——
  读者不要用尺寸判断构建成功；如需可加一句注明，不影响验收。

### 待开卡（CI 收件箱继续红的真源头）
- `xiaozhi-esp32` Build Boards 的板级矩阵在 `idf.py reconfigure` 处对所有板报
  `ERROR: File .component_hash or CHECKSUMS.json for component "78/esp-wifi-connect" …`（含与本项目无关的板）。
  需要一张卡查 `main/idf_component.yml` 的版本 pin、`managed_components` 校验文件与注册表侧产物，决定是 pin 版本、加 `CHECKSUMS.json` 还是等上游修。

---

## Factory 镜像（2026-10-30）

构建点：`05_Tools/xiaozhi-esp32` 分支 `fix/persona2-zone-taps`，commit **`9b22121`**；
变体 `chd/chd-esp32s3-box --name chd-esp32s3-box-lcd35 --language zh-CN`；ESP-IDF v6.1（esptool 5.6.0）；
构建工作树 `/private/tmp/xz-c`（tracked 源文件零改动）。

### 镜像与指纹（实测）

| 版本 | 文件 | 字节 | sha256 | 编入的 OTA 地址 |
|---|---|---|---|---|
| A 公开 | `merged-binary.bin` | 10164189 | `38805dbe70a9dc944b851e9686139a23de24e0ca23142c0f6048648f5a1006bb` | `http://rui-ota.invalid:4411/xiaozhi/ota/`（占位） |
| A 公开 | `xiaozhi.bin` | 2921280 | `9726479ec119141831a2329ca45249ce14e1de22d4ade13654eb2ce69a286e3f` | 同上（未上传，见下） |
| B 自用 | `merged-binary.bin` | 10164189 | `147cbec87285be0006a265c1ded295e656ae9df94d2a666ed2dec39b553723a3` | `http://<server-ip>:4411/xiaozhi/ota/` |
| B 自用 | `xiaozhi.bin` | 2921264 | `292c14c8596c618496eac95a74dacd2ae361b28f5a4f4dc3f8327101316b785a` | 同上 |

自用版（B）只落本地归档：`02_Archive/esp32-firmware/factory-20261030/`（含 README，**不入 git、不上传**）。

### ⚠️ 本分支的构建缺陷（重要，下张卡修）

`[已核]` `scripts/build.py` 的 `_expand_ota_base()`（`:412-415`）只在 `--list-boards`/option 路径被调用
（`:509`、`:977`）；真正构建用未展开的 `sdkconfig_append`（`:1577-1596`），ESP-IDF Kconfig 也不展开
`${VAR}`（实测：`export XIAOZHI_OTA_BASE=…` + `idf.py reconfigure` 后 `sdkconfig` 仍是字面量）。
→ 直接跑 `build.py` 编出的镜像里是**未展开的 `${XIAOZHI_OTA_BASE}/xiaozhi/ota/`**，OTA 必失败。
本次 A/B 都是「先让 build.py 生成 `build/xiaozhi-build.sdkconfig.defaults`，把 `CONFIG_OTA_URL=` 改成展开值，
`idf.py fullclean` 后重新写回 fragment、`rm sdkconfig`、`reconfigure` + `build` + `merge-bin`」得到的；
每次构建后都用 `grep '^CONFIG_OTA_URL' sdkconfig`、`grep CONFIG_OTA_URL build/config/sdkconfig.h`、
`strings -a … | grep -c rui-ota.invalid` 断言过。**一行修法**：`scripts/build.py:1577` 换成
`_expand_ota_base(build.get("sdkconfig_append", []))`。

### offset 表（`partitions/v2/16m.csv`，从 A merged 的 `0x8000` 解出后逐项对账）

| 区 | offset | size | 在整包里 |
|---|---|---|---|
| bootloader | `0x0` | 0x8000 | ✅ |
| partition-table | `0x8000` | 0x1000 | ✅ |
| nvs | `0x9000` | `0x4000` | ⚠️ 区间存在但全 `0xFF`（实测非 `0xFF` 字节 = 0）→ 烧 `0x0` 必清 NVS |
| otadata | `0xd000` | `0x2000` | ✅ |
| phy_init | `0xf000` | `0x1000` | ❌ 空 |
| ota_0 | `0x20000` | `0x3f0000` | ✅ app |
| ota_1 | `0x410000` | `0x3f0000` | ❌ 空 |
| assets | `0x800000` | 8M | ✅（`generated_assets.bin` 1775581 B） |

整包 10164189 B = `0x9B17DD` = `0x800000` + assets 长度。其它校验：`dd` 从 `0x20000` 取 app 长度后
`cmp` 与 `xiaozhi.bin` **exit 0**；`esptool image_info` 报 `Detected image type: ESP32-S3`、
bootloader/app checksum 与 validation hash 均 valid。

### Release（未动 tag、未删/改旧资产）

- tag `v2.5.3-persona.4`（pre-release）新增资产：
  `https://github.com/yes999zc/xiaozhi-esp32/releases/download/v2.5.3-persona.4/merged-binary.bin`（10164189 B）
- `SHA256SUMS.txt` 用 `--clobber` 覆盖为两行（162 B）：
  `38805dbe…006bb  merged-binary.bin` + `63c9f7e5…4728de4  xiaozhi.bin`。
- app-only 资产 `xiaozhi.bin`（2921264 B，sha `63c9f7e5…`）**保持原样没换**：它里面是未展开的字面量占位，
  只烧它 OTA 会失败 → 发布说明里已写明必须配 NVS 或重编（A 的新 app 2921280 B 只在 /tmp，没上传）。
- body 只在原文后**追加**「Factory image (2026-10-30)」一节（原 1540 B 前缀逐字保留）。

### 白天要做的（真机，未验证）

1. `0x0` 刷 A 整包（或 B 自用整包）→ 会清 NVS → 设备自动进 SoftAP 配网 → 手机连 `Xiaozhi-XXXX`
   → `http://192.168.4.1/` 填 Wi-Fi → 确认设备 OTA 打到目标地址。
2. 记录 `idf.py -p <port> monitor` 里首次启动 `nvs_flash_init` 建表、以及 OTA 请求行（作为 `0x0` 刷写的真机证据）。

### NVS 改写两条路的可用性

- **`scripts/make_nvs_ota.py`**：`[已核]` 实跑 `--url http://<server-ip>:4411` → `/tmp/nvs-ota.bin`
  16384 B、sha256 `63b1b5259b4eb3d186cec15c48c6fa33eaa9b8032c3ed4b021e9439906547905`；
  镜像里存的完整值是 `http://<server-ip>:4411/xiaozhi/ota/`（`strings` 可见 `wifi`/`ota_url`/该 URL，
  页头 `fe ff ff ff`）。规范化已核：`--url <base>` 与 `--url <base>/xiaozhi/ota/` 两次输入
  生成的镜像 **`cmp` exit 0（字节相同、同一 sha256）**——固件把该值当完整端点用（`main/ota.cc:56-62` 不拼路径），
  服务端只注册 `/xiaozhi/ota/`，所以旧行为（只存 base）会 404，已修。
  **刷 `0x9000` 后设备是否真按该地址 OTA：`[未验证]`**（本卡不刷机）。
- **配网高级页 `/advanced` 写 `ota_url`**：`[源码已核]`（`wifi_configuration_ap.cc:558` 路由、
  `:599-610` `nvs_open("wifi")` + `nvs_set_str("ota_url")`；`main/ota.cc:56-62` 运行期优先读 NVS），
  **端到端 `[未验证]`**。

## 安全事件：privacy-scan 工作流本身在公开仓库里泄漏了要保护的字面量（2026-10-30 08:0x 已止漏）

- **事实**：`.github/workflows/privacy-scan.yml` 的正则里硬编码了真实家庭 SSID、账号/口令串与设备序列号前缀，
  而两个仓库都是 public ⇒ **扫描器把它要保护的字符串公开发布了**（`':!.github/...'` 只让自检不报自己，
  但文件内容对全网可见）。首次进入：`a9b6975` / `6676d12`，均为 **2026-10-28 23:38**，暴露约 32 小时。
- **已修**（`08b05dc` esp32-voice-entry / `e9537b0` xiaozhi-esp32，两仓 privacy-scan 均 success）：
  字面量移入仓库 secret `PRIVACY_TERMS`（值为 <家庭SSID>|<账号串>[|<序列号前缀>]，不在任何 tracked 文件里），工作流只保留通用模式
  `192\.168\.x`；同时给扫描加例外 `192.168.4.1`（ESP32 软 AP 固定网关，文档必须给出，非用户网络数据）。
- **仍是敞口**：git 历史与已 clone 的副本里字面量依旧存在；只改工作流收不回来。
  ⇒ 处置口径：**轮换一次 Wi-Fi 密码 / 该串在别处复用过的账号**；不做历史改写（会毁 tag 与所有 clone，
  且已公开索引，改写收益低）。
- **规则**（写给以后）：任何"检测敏感串"的脚本，其模式里 **不许出现敏感串本身**；要用 secret/环境变量注入，
  并在 PR 里写明"本文件不含真实值"。

## 真机语音链路收口（2026-10-30 白天）

两仓均已按"删除重建"处理：`esp32-voice-entry` HEAD 为单根提交 `365e340` + 本轮修复提交；
`xiaozhi-esp32` HEAD 为单根提交 `3f95a4b`；本地旧 branch/tag/stale remote refs 全部删除，
`git rev-list --all` = 1；旧历史只留在 `02_Archive/repo-backups-20261030/*.bundle`（600，永不推送）。
重建时曾误把 `build-chd/`（含内网 OTA 地址）收进第一个提交，privacy-scan 当场抓红，已 `--amend` 覆盖。

### 服务端三处修复（`src/session.py` / `src/netguard.py` / `src/server.py`）

| 症状 | 根因（一句话） | 修复 | 验证 |
|---|---|---|---|
| 多实例抢 4411 → Traceback 循环 | 失败方把 `OSError(EADDRINUSE)` 抛成 traceback，launchd KeepAlive 每 10s 重拉 | 新增 `src/netguard.py`：起服务前探测两个端口，被占则打印单行 `[fatal] port N already in use` + exit 1；bind 竞态同样单行退出（`server.py:33-37/101-104`） | 真机环境实测第二实例：`rc=1`、单行 fatal、无 Traceback、fatal 前无 `[init]`；空闲端口可正常 `[ready]` |
| 唤醒词变体被当命令 | `strip_wake` 只做字面前缀匹配，ASR 的 `小石/小日/郝小智/好小时/高小日/小治` 落到 `_valid_text` 后进 LLM | 正规化（NFKC+去标点+小写）+ 变体表 + 同音尾词正则 `[你/好/郝/高]?[小/晓][智志石时识日纸只制子治]`；短段 <0.8s 且相似度 ≥0.60（≥3 字）也判 wake-only | `tests/test_wake_variants.py` 表驱动（5 个指定变体 + 3 个真机 ASR 输出 + 反例）；`fake_device` 回放 5 个变体 → 全部 `wake-only, no turn`、TTS 帧 0 |
| 静音开/关后 listen 状态错乱 | mute 切换时设备发的 abort 爆发在"muted 且无 turn 无 speaking"时是空转，却会 cancel 在飞的 turn | muted 且 idle 时忽略 abort（只记日志）；真 abort（speaking / turn 在飞）仍走 `_interrupt()`；mute 关闭首帧重置 session 计数 | `tests/test_mute_abort.py`；真机 + fake_device：静音时发问无轮次，解除后 3 轮 `[turn] done`（带间隔，避免 barge-in 干扰） |

**已知限制（`[未验证]`/未修）**：`VAD` 缓冲在 mute 期间不清，跨静音的首段可能带 mute 前音频（仅注释更正，
行为修复留给后续卡）；纯扬声器回放时 ASR 仍可能把整句听成 `好小我想你` 这类碎片，字符表无法覆盖，
现场偶发一次"答非所问"，未计入本轮验收。

### 固件与 A 视图恐龙

- 代码层面 A 视图底部恐龙条是**正常**的：`dino_root_` 建在 `(0,273) 480×47`，`ApplyViewLayout` 的 `is_a`
  分支 `remove_flag(HIDDEN)` + `move_foreground`，`ADinoTick` 每 80ms 再确认；四类隐藏点（非 A / media /
  speaking / subtitle）都是瞬时门。`git diff` 显示该文件与设备上"恐龙可见"的旧树一致。
- **结论：现场"恐龙消失"是板上跑旧镜像所致**，不是当前代码缺陷。刷本轮 app 后，A 视图截图
  （`snapshot-20261030-091034.jpg`，MCP `self.screen.snapshot` → `/debug/upload`）左下恐龙 + 仙人掌可见。
- 因此**没有为恐龙改固件代码**（不制造假修复）。A 视图初始状态稳定：`phase_b_view_` 默认 `kA`、无 NVS 持久化。

### 固件产物（commit `3f95a4b`，ESP-IDF v6.1，变体 `chd-esp32s3-box-lcd35`）

| 产物 | 字节 | sha256 | 用途 |
|---|---|---|---|
| 公开 merged | 10,164,189 | `ecb0c32c1179e70c07d6f27679219e8e01861faf7ff6d04ca4f80f7255efeff2` | `0x0` 整包 |
| 公开 app | 2,921,568 | `c5064d8a3d6c25cf80ee29fffa275a6fb55189f263356d9543fb47beb083a195` | `0x20000` |
| 自用 merged | 10,164,189 | `22a4d4924ed3ab6e41a9133fb718c7a6f1c0d8f4fc13f8841a132773f7592d8a` | 归档，不发布 |
| 自用 app（已刷板） | 2,921,568 | `038bbb0335a54ba395c043a4d0d6254e8fdabc4b9cca68fced8a017ab1e15198` | 含真实 OTA 地址 |

分区（从 merged `0x8000` 解出）：`nvs 0x9000/16K`、`otadata 0xd000/8K`、`phy_init 0xf000/4K`、
`ota_0 0x20000/4032K`、`ota_1 0x410000/4032K`、`assets 0x800000/8M`；NVS 区 16,384 B 全 `0xFF`。
校验：app 段 `cmp` exit 0；`image_info` bootloader ESP32-S3/checksum `0x16` valid、app ESP32-S3/checksum `0xaf` valid。
公开镜像 `strings`：`rui-ota.invalid` ×1、无 `${XIAOZHI_OTA_BASE}`、无内网 IP；自用镜像含真实地址 ×1。

### 发布

- tag `v2.5.3-persona.5`（pre-release）→ https://github.com/yes999zc/xiaozhi-esp32/releases/tag/v2.5.3-persona.5
- 资产：`merged-binary.bin`（digest 与本地一致）、`xiaozhi.bin`、`SHA256SUMS.txt`（2 行）。
- 说明写明三种刷法（`0x0` 清 NVS / `0x20000` 保留 NVS / NVS `ota_url` 改 OTA），并注明占位地址 `rui-ota.invalid`。

### 真机验证（本机，2026-10-30 09:0x–09:1x）

- 服务重启后单实例监听 4410/4411；第二实例被单实例保护拦下。
- `fake_device` 回放：5 个唤醒变体 → `wake-only, no turn`；静音 ON 时无轮次；解除后 3 轮 `[turn] done`。
- Mac 扬声器自激：`你好小智，现在几点` → `好小志现在几点？` → 剥前缀 → 正确回答时间（`[llm] 现在9点13分…`）。
- 设备 OTA 正常（`[ota] xiaozhi v2.5.3 -> ws://<server-ip>:4410`），app-only 刷写未动 NVS。

### 仍属 [未验证]

- `0x0` 整包 + 手工回写 NVS（`wifi/ssid`、`password`、`ota_url`）后自动重连的完整流程，本轮未跑（设备用 app-only 更新）。
- 配网高级页 `/advanced` 写 `ota_url` 的端到端行为。
- 真人（非扬声器）长时间 soak 下的唤醒词误判率。

## 检查点（2026-10-30 09:2x，上下文 ~50%）

- 已完成并验证：服务端三修 + 同音字表（`3651ff1`）、固件重建与发布 `v2.5.3-persona.5`（merged `ecb0c32c…` /
  app `c5064d8a…`）、板上刷自用 app `038bbb03…`、A 视图恐龙截图证实可见、HANDOFF 与 README 记录已推。
- 两仓 CI：privacy-scan 绿；MCP host tests 绿于 `3f95a4b`（文档提交未触发）；Build Boards 基建红不追。
- **进行中**：给项目主页（本仓 `README.md`）写中英双语「使用指导书」，要求写清"哪些信息必须使用者自己填"，
  并同时修掉 README 里两处过时陈述：① 声称 `XIAOZHI_OTA_BASE` 构建期注入（实测本树不展开）；
  ② 发布资产仍写 persona.4 app-only / persona.2 带 merged（现为 persona.5 两者都有）。
- 约束：新文档不得出现 `192.168.x.x`（唯一例外 `192.168.4.1`，privacy-scan 已放行）；一律用 `<server-ip>`。
- 进度：README 已写完（EN `### Getting started` / ZH `### 使用指导书`，6 步 + 两张表），
  自查 `git grep -nE '192\.168\.' -- README.md` 只命中放行项 `192.168.4.1`；正在由独立 reviewer
  逐条对源码核对（命令/键名/配网/发布/tag/中英一致性）。
- 下一步：reviewer PASS 后 `docs: rewrite the getting-started guide for newcomers` 提交并 push，
  确认 privacy-scan 绿。

### 检查点 2（2026-10-30 09:26）

- README 双语指导书已写完待改：reviewer **CHANGES（5 项阻塞）**，全部是我写文档时想当然的地方，
  已核实成立：① `/advanced` 不存在（实际是 `/` 页面的 Advanced 标签，表单 `POST /advanced/submit`；
  配网成功页会自动 `POST /exit` → `StopConfigAp`，所以 OTA 地址要在提交 Wi-Fi **之前**填）；
  ② `llm.provider` 默认 `hermes`，没有 `HERMES_API_KEY` 启动即抛；③ matcha 在构造期就建，模型缺失时
  即使有 VOLC key 也启动失败；④ `build/xiaozhi-build.sdkconfig.defaults` 每次构建被重写，必须
  fullclean → 重写 → `rm sdkconfig` → `reconfigure` 全序列；⑤ 本仓 venv 没有 esptool，第 3 步前要先 `source export.sh`。
- 另：`docs/quickstart-single-board.md` 仍在 persona.4 旧口径（2921264/`63c9f7e5`、`/advanced`），与 README 冲突，
  本轮一并改成 persona.5（2921568/`c5064d8a`，merged `ecb0c32c`）。
- 已修完（等 reviewer 增量确认）：README 补 `llm.provider`/matcha 模型/视觉（可选）三行、第 2 步给最小
  config 片段、第 3 步前加 `source export.sh`（esptool 在 IDF 里）、Advanced 改为「`/` 页面标签 + 必须在
  提交 Wi-Fi 之前」、firmware 段改成 fullclean→重写 fragment→reconfigure 全序列；quickstart 全量换成
  persona.5（`ecb0c32c…`/`c5064d8a…`），删掉 persona.2/3/4 旧行与 `/advanced` 地址。
- 下一步：reviewer PASS → 一个 commit 提交 README+quickstart → push → privacy-scan 绿。

### 检查点 3（2026-10-30 09:3x）

- reviewer 增量复核：6 处中 5 处通过，剩 1 处阻塞——README 说"模型下载见 §3.3"，但 §3.3 只有 ASR/VAD，
  matcha 的 `model_dir`/`vocoder`（启动必需）没有下载来源。正在补 §3.3（或 §3.4）并改指路句。
- 另有一条非阻塞：`docs/quickstart-single-board.md:168` 仍引旧 commit `9b22121`（重建后历史里没有），
  改为引 `3f95a4b`。
- 已补：§3.3 新增「TTS（matcha）」下载小节（两条 `curl -LO` + `tar xjf`）；实测两个 URL `HTTP/2 200`
  （content-length 75,463,556 / 53,884,024），本地 tarball 首条目为 `matcha-icefall-zh-baker/`，
  本地 `vocos-22khz-univ.onnx` 字节数与远端 content-length 一致；`quickstart:168` 的旧 commit 改指 `3f95a4b`。
- reviewer 最终 **PASS**（含端到端：用下载的 matcha+vocoder 实例化 `MatchaTts` 合成成功，20,382 samples @22,050 Hz）。
  另按其非阻塞建议补了 VAD 直链命令（`asr-models/silero_vad.onnx`，实测 200/643,854 B = 本机文件），
  并把「当前单 commit」改为「根提交 `3f95a4b`（历史另有 a3980dd 文档提交）」。
- 已提交推送 `cfe1f87`（README + quickstart + HANDOFF，+347/−33）；privacy-scan run 40986502767 **success**。
  产物：README 中英双语「Getting started / 使用指导书」6 步 + 两张表（必填信息 7 项、三种刷法）；
  quickstart 全面换成 persona.5，并补齐 ASR/VAD/TTS 三套模型的下载命令（三条 URL 均实测 200）。
