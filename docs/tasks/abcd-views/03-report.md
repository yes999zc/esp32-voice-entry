# T3 四视图根因报告与修复拆卡建议（persona.2 视角）

- 任务卡：`task-3`（T3 汇总；本卡只写文档，不改代码、不刷机）
- 输入：T1 `01-repro-evidence.md`（325 行，真机证据，已评审 PASS）+ T2 `02-code-arch.md`（458 行，代码归因，已评审 PASS）
- 基线：板上固件 = release `v2.5.3-persona.2`（tag `81b3b20`，app sha256 `a67645c8…eeab4`）；对照 `v2.5.3-persona.3 = 0a43f23`；`main = 64d13ba`（未上板）
- 写法约定（全篇统一）：
  - `<board.cc>` = `05_Tools/xiaozhi-esp32/main/boards/chd/chd-esp32s3-box/chd_esp32s3_box_board.cc`
  - 固件行号一律为 **`v2.5.3-persona.2` tag 自身行号**（例 `p2:1420-1422`）；仅在对照修复时引 `main:`。
  - 串口行号一律引 `evidence/serial-persona2-2210.final.log`（3781 行，sha256 `5307aef7…e336`，`grep -n` 口径）。
  - 结论标记：`[事实]` = T1/T2 原文或本次复核命令输出；`[判定]` = 基于事实的归因；`[未证]` = 现有证据不足以判定。

---

## 0. TL;DR（给 9哥，7 行）

1. **总判**：恐龙**不是编码问题**——9/9 sprite 的 `w/h/stride/data_size/初值个数` 全部自洽（本次独立复核），四视图能看见的问题全是**配置**：可见性/层级（R1/R3）与 `y` 常量没算 sprite 的透明 padding（R4/S2）。
2. **A**：恐龙条正常显示，唯一可测缺陷是恐龙脚底裁 1.3px、仙人掌裁 2.1px（肉眼不可辨）；CJK 标题正常，`175056b` 在 persona.2 上**没有可见效果**（被 `ApplyPhaseBFonts` 覆盖，见 §1.1）。
3. **B**：A 条恐龙 + **冻结的**仙人掌残留在 B（`d2d47c7` 的 hide 没上板）；仙人掌不动的直接原因是 `ADinoTick` 非 A 视图早退，不是隐藏失败。
4. **C**：同 B 的残留，外加 C 的 debug 行被残留恐龙压住（`05:24…` 前半截不可读）；残留一消失，重叠自然消失。
5. **D**：游戏本身正常（分数 00001→00165、27–28fps），两个真缺陷：A 条小恐龙叠进游戏区 =「两只恐龙」（R1）；游戏恐龙悬空 9px、仙人掌悬空 8px（R4，三版本同款、persona.3 至今没修）。D 的 3 行日志在 y44–143，**在游戏区（y≥170）之上，不构成遮挡**（见 §1.1）。
6. **动作与顺序**：C0 先备好可回滚的 persona.2 二进制（本机未保留副本）→ C1 隐藏 A 条（约 8 行，一次修好 B/C/D）→ C4 顶栏静音文字可点 → C3 D 视图落地像素（7 处 / 9 个字面量）→ C2a/C2b（可选：z-order / D 日志去留） → C5 唤醒恢复单独决策；D3 触摸只在幽灵点复现时开卡。
7. **不要做**：不要重导恐龙资源、不要为「恐龙显示不对」改 `chrome_dino_sprites.h`、不要把 R4 当成 persona.3 已修的问题。

---

## 1. 结论速查表

### 1.1 先修正三处口径（与 T1/T2 不完全一致，均以代码/像素为准）

| # | 原口径 | 本次复核 | 影响 |
|---|---|---|---|
| M1 | T1 §4.6：persona.2 可点静音目标有 `mute_hit_`、`hermes_avatar_`、`mute_button_` **三处** | `[事实]` `mute_hit_` 虽带 `CLICKABLE`，但构建末尾 `p2:1053` 直接 `HIDDEN`，全仓无**清除 `HIDDEN`** 的 `remove_flag`（`p2:1044`/`p2:2013` 只清 `SCROLLABLE`）；`mute_button_` 在 `p2:1308-1310` 被隐藏，全仓也无再显示；**persona.2 实际只有右下头像一个可点静音入口**（`p2:1268-1269`），且在 D 视图被隐藏（`p2:1445-1446`） | 9哥 说的「右上角不响应」不是触摸失灵，而是**顶栏根本没有可点对象**；R5 的证据更强 |
| M2 | T2 §3.1(b)：`175056b` 改前「中文标题无字形（空白/tofu）」 | `[事实]` `p2:1136` 确实用 `small_font`（montserrat_14），但 `SetupPhaseB` 末尾 `p2:1313` 调 `ApplyPhaseBFonts(ActiveTextFont())`，其中 `p2:1639` 把 `a_metric_titles_` **全部改回主题 CJK 字体**；主题字体每次刷新还会再覆盖（`p2:2238`）。A 截图 `crops/A-metrics-3x.png`（本次已看）标题 CJK 完整，无 tofu | `175056b` 在 persona.2 上是**代码一致性修复、无可见效果**；R2 不再是「用户可感知的回滚丢失」 |
| M3 | 任务背景：「3 行日志仍占据 D 上部」 | `[事实]` D 的日志 `count=3`（p2:1382）、`y0=44`（p2:1383）、`line_h=33`（p2:1384），最后一行底 = 44+2×33+33 = **143**；`game_view_` 顶 = **170**（`p2:1203`）→ 日志整体在游戏区之上，`view-D-extra5`（本次已看）也显示日志与分数/恐龙不重叠 | 这是**设计取舍**，不是图层缺陷；C2b 从「修 bug」降级为「9哥 要不要全屏游戏」的决策 |

> 另有两条**澄清**（非冲突）：
> - T2 §3.2 说 `e5b2139` 前像 0/1、需 `6a6697b` 先上——本次实测按序 `git apply` **两段都 clean**；落地 blob 是 `e54a7649` 而不是 `5424c59`，因为基线只有 persona.2（缺少另外 3 个 UI commit），属预期，不是冲突。
> - T2 §8 写「`6a6697b e5b2139` 需 ⑥（D3）才有效」：过强。T1 已证 persona.2 正常点按能产生 CLICKED（15 次 tap、串口 `Application: mute: toggle requested by UI` **6 次**，其中 4 次与 mute 变更毫秒级一一对应）；只有落入**幽灵点自锁**时 CLICKED 才根本不产生。B1 顶栏静音入口与 D3 无编译依赖，功能依赖仅在 R6 复发时成立。

### 1.2 速查表（视图 × 缺陷 × 归属 × 编码/配置 × 修法 × 工作量）

| # | 视图 | 缺陷（可观测） | 归属桶 | 编码 / 配置 | 修法（commit / 位置 / 函数） | 工作量 |
|---|---|---|---|---|---|---|
| S2-A | A | 恐龙脚底裁 1.3px、仙人掌裁 2.1px（T1：墨迹止于 y=319） | **persona.2 自身且 persona.3 未修**（R4/S2） | 配置：`y` 按「左上锚定」算，未计中心 pivot | 新补丁 `p2:1191`（dino y 9→7）、`p2:1197`（cactus y 18→15）；建议值，需像素复核 | XS（2 个常量） |
| T-A | A | 截图时刻无仙人掌 | 非缺陷（时序） | — | `ADinoTick` 80ms/5px 从 x=480 进入（`p2:1318`、`p2:1785-1789`） | 0 |
| R2-A | A | CJK 标题（未复现） | **不成立**（M2） | 配置（字体指针，已被覆盖） | 可选 `175056b`，无可见收益 | 0 |
| R1-B | B | A 条恐龙（x26–54/y290–317）+ 仙人掌（x452–464/y295–319）残留 | **回滚/未回移**（R1，`d2d47c7`） | 配置：可见性（`ApplyViewLayout` 只 `move_foreground`，不 `HIDDEN`） | `d2d47c7` 的 `ApplyViewLayout` dino 分支（第 3 个 `@@`；`p2:1420-1422` 加 else 分支 `HIDDEN`） | S（约 8 行） |
| R1-B2 | B | 仙人掌冻结 | R1 的衍生（门控） | 逻辑：`ADinoTick` 非 A 早退（`p2:1761-1762`） | **不单独修**：C1 卡隐藏后 B/C/D 不再显示；A 内动画保留 | 0 |
| R1-C | C | 同 R1-B 的残留 | **回滚/未回移**（R1） | 配置 | 同 R1-B | 含于 C1 卡 |
| R1-C2 | C | debug 行被恐龙压住（`up…` 可读、`05:24…` 被盖） | R1 衍生 + z-order | 配置：`dino_root_` 在 A 每 80ms 被 `move_foreground`（`p2:1778`），切走后仍是顶层 | R1 修好即消失；如需保险可对 `debug_line_` 加 `move_foreground`（`p2:1412-1414`） | 含于 C1 卡 |
| R1-D | D | 两只恐龙：A 条小恐龙（354 暗像素）叠在游戏地面带上 | **回滚/未回移**（R1） | 配置：`dino_root_` 273..319 与 `game_view_` 170..319 重叠 | 同 R1-B | 含于 C1 卡 |
| R4-D | D | 游戏恐龙悬空 9px、仙人掌悬空 8px | **persona.2 自身且 persona.3 未修**（R4） | 配置：`y` 未计 ground 顶部 6 行、sprite 底部 2 行透明 padding | 新补丁 7 处 / 9 个字面量：dino 4 个字面量（`p2:494/1224/1576/1577`，各 1 个 80→89）；cactus 3 处 5 个字面量（`p2:1229` 的 92→100、`p2:1501` 的 77→85 与 92→100、`p2:1532` 的 77→85 与 92→100） | S（改 9 个字面量 + 像素验收） |
| R3-D | D | 「游戏被完全压层」（未复现） | **回滚/未回移但无可见证据**（R3） | 配置（z-order，防御） | 可选 `0a43f23`（`ApplyViewLayout` + `GameTick` 各加 `move_foreground`） | XS（9 行） |
| LOG-D | D | 3 行日志占上部 | **设计取舍**（M3） | 配置 | 可选：`p2:1382` 与 `p2:1803-1805` 同时把 D 的 count 改 0 | XS（2 行，需决策） |
| R5-X | 全部 | 顶栏「未静音/已静音」不可点；顶栏无可点热区 | **回滚/未回移**（R5） | 配置：缺 `CLICKABLE` + 缺扩展热区 | `6a6697b` + `e5b2139`（`p2:980-981` 区域；实测定点见 §3.2） | S（5 行） |
| R6-X | 全部 | 幽灵点自锁 → 全屏点击失效（间歇，本次未复现） | **persona.2 自身且 persona.3 未修**（R6） | 驱动/策略 | `64d13ba`（`p2:~2893-2915` 的 D2 触摸 HOLD 策略） | M（条件卡） |
| R7-X | 全局 | unmute 后唤醒词不恢复 | **回滚/未回移**（R7） | 逻辑（状态机条件） | `e6b7c1b`（`main/application.cc` `HandleMuteStateChanged`） | S（7 行 + 语义评审） |
| R8-X | — | 恐龙成色块/花屏 | **不成立**（R8，编码证伪） | — | 无需修，不要重导资源 | 0 |
> 归属桶统计：**回滚/未回移** = R1、R3、R5、R7（R2 因 M2 不计入用户可见缺陷）；**persona.2 自身且 persona.3 未修** = R4/S2、R6；**新问题 = 0**（R8 是证伪行）。

---

## 2. A / B / C / D 逐视图

### 2.1 A 视图（view=0）

**现象**（T1 §4.2；`evidence/view-A-20261029-221214.jpg`，sha256 `bf10712f…be1ec`）
- `[事实]` 恐龙正常出现：墨迹 bbox **x 26–54 / y 290–319**（319 是屏幕最后一行），深色近黑；`[事实]` 无仙人掌：右下 (440–480, 273–320) 暗像素 = 0，因为截图瞬间仙人掌仍在 x≈480 屏外（T1 §4.2、§7#6）。
- `[事实]` 标题栏「● Hermes 在线 已静音 22:12」、指标「状态/空闲、内存/17K、帧/1987」CJK 完整（`crops/A-titlebar-3x.png`、`crops/A-metrics-3x.png`，本次已看后者）；7 行日志 y≈44 起、行距 33；`baseline_` 1px @y=276 极淡（T1 §4.2）。

**期望**：A 条内恐龙完整落在 47px 条带（y 273–319）内；仙人掌按 tick 从右侧进入；CJK 正常。

**归属**：S2-A = **persona.2 自身且 persona.3 未修**；T-A = 非缺陷；R2-A = 不成立（M2）。

**根因**（S2-A，R4/S2）
- `[事实]` 条带 `dino_root_` (0,273) 480×47（`p2:1180-1182`）；恐龙 44×47 @(18,9)、`scale 186`（`p2:1188-1193`）；仙人掌 17×35 @(480,18)、`scale 210`（`p2:1194-1199`）。
- `[判定]` LVGL 缩放以**中心**为 pivot（T2 §4.2 引 `lv_image.c:690`），对象框仍是 44×47。按 `186/256=0.7266` 算：垂直居中偏移 (47−34.1)/2 = 6.43；墨迹行 2..44 → **顶部 289.9、底部 320.4**；父对象 273..319 默认裁剪 → 脚底裁 **1.3px**，与 T1 实测「墨迹止于 319」一致（我按同一算式复算：x 左 = 18+6.02+2×0.7266 = 25.5 → 26，右 = 53.8 → 54，与实测 x 26–54 吻合）。
- 仙人掌：210/256=0.8203，墨迹行 1..33 → **294.9..321.1** → 裁 **2.1px**（T1 实测底 319）。
- 这是**配置**问题：`y=9/18` 是照「未缩放、左上锚定」写的（T2 §5.1）。资源本身自洽（§3.1）。

**修法**（可选，优先级最低）
- 新补丁，只改常量：`p2:1191` `9 → 7`、`p2:1197` `18 → 15`（按上面算式，底部落到 ~318.4，留 1 行余量）。**建议值，需刷机后按墨迹实测微调**。
- 不要改 `chrome_dino_sprites.h`，不要改 scale（scale 与代码注释 "~33x35"/"~14x29" 吻合，T2 §5.1）。
- **工作量**：2 个常量；可与 C3 同卡（同为「按墨迹行校正 y」）。

---

### 2.2 B 视图（view=1）

**现象**（T1 §4.3；`view-B-20261029-221217.jpg`，`eece52fd…ce0e5`）
- `[事实]` 6 张卡 + 3 行日志 + 橙色 ECG（`0xE2703A`，y≈276–320，`crops/B-dino-strip-3x.png`）正常。
- `[事实]` **A 条恐龙仍在**：x 26–54 / y 290–317；**A 条仙人掌仍在**：x 452–464 / y 295–319，且 B/C 与 D 首帧/次帧四帧**像素级同位**（T1 §4.3、§4.5）。

**期望**：B 只应有 6 卡 + 3 行日志 + ECG；A 条 47px 条带整体不可见。

**归属**：**回滚/未回移**（R1）。

**根因**（R1）
- `[事实]` `dino_root_` 构造时是 `HIDDEN`（`p2:1200`），但只在 A 视图被 `ADinoTick` 取消隐藏并提到顶层（`p2:1777-1778`）。
- `[事实]` `ApplyViewLayout` 对 `dino_root_` 只有 `if (is_a …) { lv_obj_move_foreground(dino_root_); }`——**没有 else 分支去 `HIDDEN`**（`p2:1420-1422`，persona.2 原文）。`PhaseBTick` 也不碰 `dino_root_`（`p2:1792-1830`）。
- `[判定]` 因此离开 A 后它一直可见且仍在顶层；"残留"不等于"没动画"：仙人掌冻结的**直接原因**是 `ADinoTick` 在 `phase_b_view_ != kA` 时 `return`（`p2:1761-1762`），即使不隐藏也不会动。两件事必须分开写（本报告 R1-B2 单列）。

**修法**
- `d2d47c7` 的 **`ApplyViewLayout` dino 分支**（git 第 3 个 `@@`，`p2:1417-1428` 区域；即 T2 的逻辑 hunk 2）：改成
  ```c
  if (dino_root_ != nullptr && lv_obj_is_valid(dino_root_)) {
      if (is_a) { lv_obj_remove_flag(dino_root_, LV_OBJ_FLAG_HIDDEN);
                  lv_obj_move_foreground(dino_root_); }
      else      { lv_obj_add_flag(dino_root_, LV_OBJ_FLAG_HIDDEN); }
  }
  ```
- 保留 `ADinoTick` 的 `kA` 门控（`p2:1761-1762`）不动——A 条动画只在 A 跑，符合设计。
- **注意**：`d2d47c7` 整 commit 共 **4 个 hunk**：① include `<ssid_manager.h>`（第 1 个 `@@`）、② `ScreenClickCb` 点按路由（第 2 个，`p2:656-658`）、③ `ApplyViewLayout` dino 分支（第 3 个）、④ `HandleTap` 配网误触（第 4 个，`p2:3268-3271`，T2 §3.1(a)）。若一卡一类变更，**只取第 3 个 hunk**；整 commit 的副作用见 §3.3，且 include 随之不需要。
- **工作量**：约 8 行；1 次构建 + 1 次刷机 + 4 视图截图验收。

---

### 2.3 C 视图（view=2）

**现象**（T1 §4.4；`view-C-20261029-221220.jpg`，`9d8ac333…7b99`）
- `[事实]` 8 行日志（x=8、行距 27、宽 400）+ 56×64 头像 @(416,212) 正常。
- `[事实]` A 条恐龙 + 仙人掌残留（同 B）。
- `[事实]` 底部 `debug_line_`（y=288）文字 `05:24 heap 17K A 1987/D 18` 被小恐龙压住：可视部分只剩 `up…0:05:24 …`（`crops/C-dino-strip-3x.png`，本次已看，行首被恐龙覆盖）。

**期望**：C = 8 行日志 + 小头像 + 一行 debug；底部无恐龙。

**归属**：**回滚/未回移**（R1），重叠是衍生。

**根因**
- 残留同 R1-B。
- `[事实]` `dino_root_` 在 A 内每 80ms 被 `move_foreground`（`p2:1318`、`p2:1778`），切到 C 后仍是**最后一个子对象**（最顶层）；`debug_line_` 创建于 `p2:1254-1260`，在 C 被显示（`p2:1412-1414`），但**没有被提到顶层**。dino 墨迹 y 290–317 与 debug 行 y 288+ 重叠 → 文字被盖。
- 该重叠**不是独立缺陷**：dino 一隐藏，debug 行完整可见（无需改 `debug_line_`）。若想双重保险，可对 `debug_line_` 加 `move_foreground`（`p2:1412-1414`），属可选。

**修法**：同 R1-B（C1 卡）。**工作量**：0（含于 C1）。

---

### 2.4 D 视图（view=3）

**现象**（T1 §4.5；`view-D-second-20261029-221223.jpg`（22:12:46，分数 00001，跳跃中）、`view-D-extra5-20261029-221650.jpg`（22:16:54，分数 00165，落地）；sha256 见 T1 §4.5）
- `[事实]` 游戏**可见可跑**：4 分 8 秒分数 00001→00165；8 条采样 5×`fps=28` + 3×`fps=27`，`dirty≈8.4–9.0k px`（serial 1887/2123/2287/2583/2928/3215/3425/3632）。
- `[事实]` 地面：y=303 全宽实线 + y≈306–308 点状带（T1 §4.5）。
- `[事实]` 游戏仙人掌一大一小轮换（`chrome_cactus_large/small`），两帧位置不同，证明重生循环在跑（`p2:1494-1501`）。
- `[事实]` **A 条小恐龙**（x 25–54 / y 290–317，暗像素 354）与 **A 条仙人掌**（x 452–464 / y 295–319）同屏 → 画面「两只恐龙」，小恐龙脚部与地面带重叠（`view-D-extra5` 已看：大恐龙在中左、小恐龙在左下）。
- `[事实]` 3 行日志在 y≈44–143，位于 `game_view_`（170–319）之上，不重叠（M3）。
- `[事实]` 第一帧标题栏「同步失败」= 静音同步网络超时（serial 1706–1707/1742），与渲染无关（T1 §4.5）。

**期望**：D 只应有 `game_view_` 一个图层组；恐龙/仙人掌脚底贴地面墨迹；日志区按设计取舍处理。

**归属**：
- R1-D（两只恐龙）= **回滚/未回移**（R1）。
- R4-D（悬空 9/8px）= **persona.2 自身且 persona.3 未修**（R4）——`[事实]` 恐龙/game 配置块在 persona.2、persona.3、main **逐字节相同**（见 §3.1 复核）。
- R3-D（被压层）= **未复现**，只保留 `0a43f23` 作为防御性 z-order（R3）。
- LOG-D（3 行日志）= **设计取舍**，不是缺陷。

**根因**

R1-D：`dino_root_` (0,273) 480×47 与 `game_view_` (0,170) 480×150 在 **y 273–319 重叠**（`p2:1180-1182`、`p2:1202-1204`）；R1 使 A 条常驻 → 叠进游戏区。`GameTick` 的 `move_foreground` 修复（`0a43f23`）只提升 `game_view_`，不隐藏 `dino_root_`，**不能替代 d2d47c7**。

R4-D：`[事实]` ground 对象 y=127（`p2:1214`/`p2:1219`），sprite 600×12 的墨迹只在**第 6..11 行**（T2 §4.1）→ 可见地面 abs **303..308**。游戏恐龙 y=80（`p2:1224`）、不缩放、墨迹行 2..44 → abs **252..294** → 与地面差 **9px**。仙人掌小 17×35 @y=92（`p2:1229`）、大 25×50 @y=77（`p2:1501`），两者墨迹底都是 **295** → 悬空 **8px**。`GameTick` 的碰撞盒用同一批常量（`p2:1529-1532`），所以「模型贴地」与「碰撞贴地」是绑定的，改 y 必须同时改碰撞常量。

R3-D：`[事实]` 逐对象排除后，D 视图 y≥170 区域没有后创建的可见同级对象：`cards_` 非 B 隐藏（`p2:1372-1381`）、`ascii_scope_` 恒隐藏（`p2:1252`）、`debug_line_` 非 C 隐藏（`p2:1412-1414`）、`hermes_avatar_` 在 D 隐藏（`p2:1445-1446`）、`idle_wave_` 仅 B、`log_labels_` 最后一行底 143 < 170、`baseline_` 在 D 隐藏（`p2:1423-1425`）。`[判定]` `0a43f23` 的 `move_foreground` 是**防御性保证**（幂等、不改几何），静态找不到必然遮挡物，与 T1 未复现一致。

LOG-D：`count = is_d ? 3 : …`、`y0 = is_b ? 180 : 44`（`p2:1382-1383`）、`line_h` 在 `p2:1384`；`PhaseBTick` 的 count 公式**没有 D 分支**（`p2:1803-1805`，D 落进 else 的 7），但 `ApplyViewLayout` 只显示 3 行 → 另外 4 行在写隐藏 label（不可见、逻辑不一致）。

**修法**
- R1-D：C1 卡（同 R1-B）。
- R4-D：C3 卡，7 处 / 9 个字面量（初值，刷机后按墨迹复核）：
  - dino `80 → 89`，4 个字面量：① `p2:494`（`game_dino_y_` 初值）② `p2:1224`（`set_pos` 的 y）③ `p2:1576`（`>= 80` 落地夹紧）④ `p2:1577`（`= 80` 复位）——**漏改会把落地基线拉回 80，跳一次就下沉 9px**。
  - cactus，3 处 5 个字面量：⑤ `p2:1229` 的 `92 → 100` ⑥ `p2:1501` 的 `77 → 85`（大）⑦ `p2:1501` 的 `92 → 100`（小）⑧ `p2:1532` 的 `77 → 85`（碰撞 `cy` 大）⑨ `p2:1532` 的 `92 → 100`（碰撞 `cy` 小）——**两行三元表达式各改两个值，缺一即错位**。
  - 对齐目标：三者墨迹底 = 303（地面墨迹首行）。若想留 1px 视觉间隙，统一再 −1（dino 88 / cactus 99/84）。
  - `ptero` 不动（飞行物，与地面无关，`p2:1239`/`p2:1514`）。
  - A 条 S2 可同卡附带（C3 可选段）：`p2:1191` 9→7、`p2:1197` 18→15。
- R3-D：C2a 卡（可选），`0a43f23`（它依赖 d2d47c7 的上下文，必须排在其后）。
- LOG-D：C2b 决策；若采纳「D 无日志」，需同时改 `p2:1382` 与 `p2:1803-1805`。

**工作量**：R1-D 含于 C1；R4-D 7 处 / 9 个字面量 + 1 轮像素验收（0.5–1 人日，预留 2 次刷机微调）；R3-D 9 行；LOG-D 2 行。

---

## 3. 逐条回答

### 3.1 恐龙缺陷是编码还是配置？

**判定：配置（可见性/层级 + y 常量），不是编码。** 依据四条，均可复现：

1. **资源自洽 9/9**（本次独立复核，非直接抄 T2）：`python3` 解析 `git show v2.5.3-persona.2:main/ui/chrome_dino_sprites.h`，逐数组比对声明长度与初始化值个数——
   ```
   chrome_dino_idle_a8 2068/2068; run1 2068/2068; run2 2068/2068;
   duck1 1475/1475; duck2 1475/1475; cactus_small 595/595;
   cactus_large 1250/1250; ground 7200/7200; ptero 1840/1840
   → 9/9 declared == initializers == w*h; distinct values = {0,255}
   ```
   且 `stride == w`（`sprites.h:57` 等 9 处 header）。C 语言里 `uint8_t arr[N] = {…}` 若初值不足会补 0（会产生「半截精灵」），本例 9/9 都精确等于 N，排除截断。
2. **A8 语义**（T2 §4.2）：A8 是 mask，颜色来自 `recolor`（`0x202B2D`，`p2:1192/1198`），`recolor_opa` 对 A8 无效但无害；`scale 186/210` 是 0.727/0.820 倍（256=100%），与代码注释 "~33x35"/"~14x29" 吻合（T2 §5.1 S4），**不是百分比误用**。
3. **真机症状只表现为剪影+位置**：T1 的逐像素复核记录四张图里恐龙都是纯深色剪影、无花屏/色块/整块黑矩形（T1 §4.2–4.5）；本次另看过 `view-D-extra5` 全图、`crops/C-dino-strip-3x.png`、`crops/A-metrics-3x.png`，与 T1 描述一致。若编码/stride 错，会表现为斜切、花斑或整块矩形（T2 §4.3 的反证条件）。
4. **配置块三版本逐字节相同**：本次用 `diff` 复核 `p2:1180-1244` vs `p3:1191-1255` vs `main:1196-1260` → 两次都为空；`ADinoTick` p2 vs p3 也逐字节相同（`diff` 空）；`GameTick` p2 vs p3 只差 `+ lv_obj_move_foreground(self->game_view_);` 一行。**结论：persona.3 没有修恐龙配置**（R4 至今存在），「回滚才出现恐龙问题」只对 R1/R3 成立，不对 R4 成立。

**因此**：不需要重导资源、不需要改 `chrome_dino_sprites.h`、不需要动 `scale`；要改的是 `ApplyViewLayout` 的可见性分支和 **7 处 / 9 个字面量**的 `y` 常量（清单见 C3 卡）。

### 3.2 persona.3 的 UI 修复能否只重做到 persona.2？

**判定：能（YES），三条 UI commit 全部可干净重做；不改 mute 语义；不需要捎带 D3 触摸修复。** 前置条件与边界如下。

**（1）可行性（本次独立复核，不只是引 T2）**
- `git log --oneline v2.5.3-persona.2..main` = 8 条（`64d13ba e5b2139 6a6697b e6b7c1b 0a43f23 175056b d2d47c7 15e05fa`），`15e05fa` 仅 README（2 文件，非代码）。
- 板级文件 blob：`v2.5.3-persona.2` = `15e05fa` = `edc3037f…`（逐字节相同）→ `d2d47c7 175056b 0a43f23` 依次 `git apply` 到 persona.2 文件，三段都 **clean**，落地 blob = **`42fe3283065c301be2ccd2501bee198ebe7e8d64`**，与 `v2.5.3-persona.3:<board.cc>` **完全相等**。命令与输出见 §6。
- 顺序硬约束：`0a43f23` 的**第一个 hunk**（`ApplyViewLayout`，`@@ -1425,8`）尾部上下文就是 `d2d47c7` 新增的 dino 分支 → **必须先落 C1**；`175056b` 可独立（1/1 命中）。
- `6a6697b → e5b2139` 同样可**独立**应用到 persona.2（实测两段 clean，落地 `e54a7649…`；因基线没有另外 3 个 UI commit，不等于 persona.3 基线的 `5424c59…`，属预期）。
- `e6b7c1b` 只改 `main/application.cc`，persona.2 的该文件 blob 恰为其**前像** `89138d6…`，应用后 = `335b7925…`（实测 clean），与 board.cc 完全解耦。
- `64d13ba` 单独应用到 persona.2 也 clean（落地 `de2852f4…`），5/5 hunk 上下文命中（T2 §3.2）。

**（2）前置条件**
- `d2d47c7` 的 `HandleTap` hunk（第 4 个）引入 `SsidManager::GetSsidList()`，include 是独立的第 1 个 hunk：`v2.5.3-persona.2:main/idf_component.yml:27` 已依赖 `78/esp-wifi-connect: ~3.3.1`，组件在 `managed_components/`（**不进 git**）→ 本机能编；换干净环境需确认同名组件版本（T2 §7 Q3）。
- 若只取 dino 分支（第 3 个 hunk，推荐给 C1），不引入 `SsidManager` 依赖，也不改点按路由。
- 刷机只写 app 分区（见 §4.0）；assets 不动。

**（3）不能打包票的部分**
- `[未证]` 重编译后的固件不保证与 persona.3 二进制相同（编译期时间戳进镜像：串口 31–33 行 `Compile time: Oct 28 2026 23:36:05`），所以「blob 相等」只证明**源码等价**，不证明二进制等价。
- `[未证]` `0a43f23` 的真实遮挡物静态不可定位（T2 §3.1(c) 注 + 本报告 R3-D），保留它只是防御。

### 3.3 重做是否引入 D3 触摸回归 / 改 mute 语义？

**判定：三条 UI commit 不引入 D3 回归、不改 mute 语义；但 `d2d47c7` 整 commit 含点按路由变更，`e6b7c1b` 改 mute 相关行为，必须分开决策。**

| 变更 | 触 TouchPointFilter？ | 触 mute 代码？ | 行为影响 | 结论 |
|---|---|---|---|---|
| `d2d47c7` dino 分支（第 3 个 hunk，仅显隐） | 否 | 否 | B/C/D 不再显示 A 条；A 内动画不变 | **安全**，C1 |
| `d2d47c7` 的 `ScreenClickCb` hunk（第 2 个，`p2:656-658`） | 否（过滤器在 `p2:~2780+`） | 否 | **所有**非 clickable 子控件上的点按会穿透到 talk toggle（T2 §7 Q3 要求真机确认「点日志不误触发对话」） | 有 UX 变更，**建议 C1 不取**；若要取，单独验收 |
| `d2d47c7` 的 `HandleTap` hunk（第 4 个，`p2:3268-3271`） | 否 | 否 | 只有「无已保存 SSID」的启动期点按才进配网 | 安全，但与本问题无关 |
| `175056b` | 否 | 否 | 无可见效果（M2） | 可选 |
| `0a43f23` | 否 | 否 | 仅 z-order 提升（幂等） | 安全，C2a |
| `6a6697b`/`e5b2139` | 否 | **新增入口**，不改状态机 | 顶栏文字变可点；热区外扩 18px | C4 |
| `e6b7c1b` | 否 | **改**：unmute 后无条件恢复唤醒词（去掉 `state==kDeviceStateIdle` 前提） | speaking/listening 中 unmute 的唤醒并发行为变化 | **C5 单独决策**，不与 UI 混提 |
| `64d13ba` | **是**（D3：2.5s 强释放 + ghost lock） | 否 | 静止点 >2.5s 强制释放；锁定点 ±30px 内丢点击，抬指/移动 >30px 解锁 | **C6 条件卡**，仅在 R6 复现时上 |

补充（本次实测/复核）：
- `[事实]` persona.2 的过滤策略仍是 D2 触摸策略「stale 保持 pressed，不释放」（`p2:2893-2915`），`s_forced_releases` 无递增路径 → **R6 的代码基础仍在**；T1 这次 133 条心跳 `stale=0/ghost=0/forced=0`（本次复核 `grep -c 'post-frame heartbeat'` = 133，全部 `stale=0`），**没有覆盖幽灵点路径**，不能写「已修复」。
- `[事实]` persona.2 顶栏的 `mute_hit_` 被隐藏（`p2:1053`），`mute_button_` 被隐藏（`p2:1308-1310`）→ **C4 之前，persona.2 在 D 视图没有任何静音入口**（头像在 D 隐藏，`p2:1445-1446`）。这是 9哥「右上角不响应」的完整解释。

---

## 4. 修复顺序与拆卡建议

### 4.0 共同约定（每张卡都适用）

- **写范围**：`05_Tools/xiaozhi-esp32/main/boards/chd/chd-esp32s3-box/chd_esp32s3_box_board.cc`（C1、C2a/C2b、C3、C4、C6 全部同文件 → **必须串行**，同一时间只允许一个实现者）；C5 只写 `main/application.cc`（可与 board.cc 卡并行，但要独立评审）。
- **刷机范围**：**只写 app 分区 `0x20000`（`ota_0`，size `0x3f0000`）**；不动 `0x800000` assets（8M）、不动 nvs/otadata。分区依据：`partitions/v2/16m.csv`（`ota_0, app, ota_0, 0x20000, 0x3f0000`）。
  - **风险**：若 otadata 当前指向 `ota_1`，直接写 `0x20000` 不生效。刷前用 `esptool read_flash 0xd000 0x2000`（或 `idf.py` 输出）确认 boot 分区；必要时刷后显式设 boot 分区。**不要**用整包 `merged-binary.bin` 覆盖（会连带写 assets/nvs）。
- **回滚锚**：release `v2.5.3-persona.2`，tag `81b3b20`，app sha256 **`a67645c88da005ee48a913eb89d6cefca8786c6a0efbf71364eff7309e2eeab4`**（`build/SHA256SUMS-persona.2`）。
  - `[事实]` **板上身份已闭环**：verifier 用 `read_flash 0x20000 2920928` 读回板上 app，sha256 = release 资产 `a67645c8…eeab4`，`cmp` 逐字节一致（T1 §2、§8 第 3 条）。
  - `[事实]` **本机未保留该资产副本**：`build/xiaozhi.bin` 是 persona.3 的 `56d96d7d…`（10-29 21:52 重编译覆盖）；`xiaozhi_flashed.bin` = `96247ffb…`、`merged-binary.bin` = `d86b1bc4…`，均不匹配。→ C0 需重新下载并复核 sha256。
- **验收基线**：每次刷机后按 T1 §4.1 的 `self.screen.set_view` + `self.screen.snapshot` 抓 A/B/C/D 四图；D 视图失败率高（T1 §6：9 次 2 成功），**D 的验收必须允许 ≥5 次重试**，且以「分数在增长」作为游戏在跑的判据。

### 4.1 候选卡

#### C0（建议前置，无代码）回滚兜底：取回 persona.2 app 二进制

- **目标**：把 `a67645c8…eeab4` 对应的 app 二进制放回本机（发布渠道下载，或按 tag `81b3b20` 重建后记录新哈希），确保任何一张卡出问题都能回到「板上现状」。
- **写范围**：无源码改动；产物放 `05_Tools/xiaozhi-esp32/build/`（不进 git）或 `04_Docs/` 归档。
- **验收**：`shasum -a 256 <file>` = `a67645c8…eeab4`（若为重建，记录重建哈希并注明非字节等同）。
- **刷机范围**：不刷机。
- **风险**：按 tag 重建**不能保证**字节等同（编译时间戳进镜像）；若发布资产不可得，回滚只能靠「重建 + 真机四视图复验」。
- **回滚锚**：C0 本身就是回滚物质；若只能重建，把重建哈希与 `a67645c8…eeab4` 并列登记，回滚验收改为「四视图复验通过」。
- **工作量**：0.5h（下载）或 1 次构建（重建）。

#### C1 隐藏 B/C/D 的 A 条恐龙（R1）

- **写范围**：`<board.cc>` `ApplyViewLayout` 的 `dino_root_` 分支（`p2:1420-1422` 区域，约 8 行）；**只取 d2d47c7 的第 3 个 hunk（`ApplyViewLayout` dino 分支）**；不取 include（第 1 个）、`ScreenClickCb`（第 2 个）、`HandleTap`（第 4 个）。
- **验收**：
  1. A 视图：恐龙仍出现并在 A 内跑动（`ADinoTick` 未改，`p2:1761-1762` 保留）。
  2. **B**：`y 273–319` 内无 A 条恐龙特征（x 26–54，灰度 <90 的暗像素 ≤5，与 T1 暗像素口径一致）；`x 452–464/y 295–319` 无 A 条仙人掌（同阈值 ≤5）。
     **C 本项不做像素计数**，以第 3 条「debug 行首字符可读」为唯一验收——debug 行颜色 `0x6B7372` 亮度≈113，且与恐龙区域 x26–54/y288 重叠，阈值口径不同会误判。
     **D 不做固定 x 区间检查**——游戏仙人掌从 x=480 每 25ms −6px（`p2:1494`），会经过 452–464，修复正确时该区间也会出现 >5 暗像素。
  3. C：debug 行 `XX:XX heap … A …/D …` **首字符完整可读**（3× 放大截图）。
  4. **D**：画面只有一只恐龙；A 条恐龙特征（x 26–54 / y 290–319）消失——若游戏恐龙本帧覆盖 x≥52（其对象在 x=50、墨迹从 x=52 起），则以 x 26–48 子区间与修复前同视图/同区域对比（可用 `view-D-extra5` 作前像）；游戏仙人掌当前 x 记入截图说明、不按固定区间判定；游戏仍可跳、分数增长（≥2 帧或 `DINO 60s fps=` 行）。
  5. 串口无新增 `CHD_UI` 错误；切换 A→B→C→D→A 一个来回，A 条能重新出现（验证 unhide 路径）。
- **刷机范围**：app `0x20000`。
- **风险**：`dino_root_` 隐藏后，B 的 ECG 波形与 C 的 debug 行会“露出来”成为唯一底部内容（属预期）；若误取 `ScreenClickCb` hunk（第 2 个），会改变全屏点按路由。
- **回滚锚**：§4.0。
- **工作量**：0.5 人日（8 行 + 1 次构建/刷机 + 4 视图验收）。

#### C2a（决策卡）D 视图 z-order 防御（R3，独立 commit）

- **目标**：由 9哥 决定是否保留 `0a43f23`（两处 `lv_obj_move_foreground(game_view_)`）。
- **写范围**：仅 `<board.cc>`：`ApplyViewLayout` D 分支（`p2:1416-1419` 区域）由 2 行改为 if/else 并加 `lv_obj_move_foreground(game_view_)`（+6/−2），`GameTick`（`p2:1491` 后）加 1 行 —— 合计 **+7/−2（9 行）**；**一个 commit，不掺日志改动**。
- **依赖**：必须在 C1 之后（`0a43f23` 第一个 hunk 的尾部上下文就是 C1 落地后的 dino 分支；本次实测单独应用到 persona.2 会 patch failed）。
- **验收**：D 视图在 subtitle/speaking/media 结束后游戏仍然可见（A→D 切换 + 视觉核）；无几何变化；`fps`/`dirty` 与 C1 后基线一致。
- **刷机范围**：app `0x20000`。
- **风险**：R3 从未复现，属零收益保险；若 C1 未先落地则补丁无法应用（已实测）。
- **回滚锚**：§4.0。
- **工作量**：0.2 人日。

#### C2b（决策卡）D 视图日志去留（LOG-D，独立 commit）

- **目标**：由 9哥 决定 D 是否保留 3 行日志（现状 y44–143，在游戏区之上，不遮挡）。
- **写范围**：仅 `<board.cc>`：`p2:1382`（`count = is_d ? 3 : …`）与 `p2:1803-1805`（`PhaseBTick` 的 count 公式）**同时**改成 D=0；**一个 commit，不掺 z-order 改动**。
- **验收**：D 截图 `y 44–143` 无日志文字；`PhaseBTick` 不再向隐藏 label 写文本（临时日志或代码检查）；A/B/C 日志行数保持 7/3/8。
- **刷机范围**：app `0x20000`。
- **风险**：游戏区只有 150px 高，去掉日志后上部留白更多，观感需 9哥 拍；只改 `p2:1382` 会留下「隐藏 label 仍被填充」的不一致。
- **回滚锚**：§4.0。
- **工作量**：0.2 人日。

#### C3 恐龙/仙人掌落地像素（R4 + 可选 S2）

- **写范围**：`<board.cc>` **7 处 / 9 个字面量**，逐处核对：
  - dino `80→89`（4 个字面量）：`p2:494`、`p2:1224`、`p2:1576`、`p2:1577`；
  - cactus（3 处 5 个字面量）：`p2:1229` 的 `92→100`；`p2:1501` 的 `77→85`、`92→100`；`p2:1532`（碰撞 `cy`）的 `77→85`、`92→100`——**两行三元表达式各两个值，缺一即错位**；
  - 可选 A 条：`p2:1191`（9→7）、`p2:1197`（18→15）。
- **验收**（像素级，crop 3×）：
  1. D：恐龙墨迹底与地面墨迹首行（y=303）差 ≤1px；仙人掌小/大墨迹底同样 ≤1px。
  2. **跳跃 3 次后**再测：落地基线不回落到旧值（防漏改 `p2:494/1576-1577`）。
  3. 碰撞体感：跳起时与仙人掌的判定与改前一致（同 dx/cw/chh，仅整体 +9/+8 平移）；撞死后分数归零仍工作（`p2:1546-1554`）。
  4. D 帧率 ≥26fps（60s 采样），`dirty` 不显著上升。
  5. （若做 A 条）A 视图墨迹底 ≤319，且恐龙/仙人掌视觉高度不变。
- **刷机范围**：app `0x20000`。
- **风险**：9 个字面量分散在初始化、重生、落地夹紧、碰撞四处，**漏一处就会跳一次下沉 9px**；`p2:1501/1532` 的三元表达式各含两个值，最容易漏；像素验收预留 2 轮刷机微调。
- **回滚锚**：§4.0。
- **工作量**：0.5–1 人日。

#### C4 顶栏静音文字可点 + 热区（R5）

- **写范围**：`<board.cc>` `mute_text_` 创建段（`p2:973-981`）：cherry-pick `6a6697b`（`CLICKABLE` + `MuteButtonCb`）→ `e5b2139`（`ext_click_area` 18），实测两段 clean。
- **验收**：
  1. 顶栏「未静音/已静音」文字点击 → 串口 `Application: mute: toggle requested by UI` + `Mute: sync ok: muted=…`，服务端 mute 变更毫秒级对应。
  2. 文字右侧/上下 18px 扩展区同样触发。
  3. 右下头像静音仍可用（不回归；T1 §4.6 的 `toggle requested by UI` 共 6 次，其中 4 次已与 mute 变更逐一对应）。
  4. **D 视图**顶栏文字可点（D 无头像）。
  5. 点击日志文字/卡片文字不应触发静音（`ScreenClickCb` 未改，仅文字标签可点）。
- **刷机范围**：app `0x20000`。
- **前置**：`time_label_` 非 clickable 的判断基于 LVGL 9.5.0（`managed_components/lvgl__lvgl/lv_version.h:9-11`，本机工作树；该目录不进 git）。若评审/CI 环境无该源码，先在真机做一次点击路由实测（点 `time_label_` 区域看是否触发静音）再定热区边界。
- **风险**：`mute_text_` 位于 x300 宽 90（右对齐到 390），`ext_click_area=18` → 热区右缘 408；`time_label_` 在 x400..472（`p2:982-984`），**400–408 这 8px 重叠**：按 LVGL 命中测试（`time_label_` 非 clickable），点时钟左缘 400–408 会落到 `mute_text_` 的扩展热区并触发静音。若在意，改成左/上/下扩 18、右扩 8（或把文字区右移）。另：`mute_text_` 与 `mute_hit_`（隐藏）无冲突。
- **回滚锚**：§4.0。
- **工作量**：0.5 人日（5 行 + 1 次刷机 + 4 视图点击验收）。

#### C5（独立决策）unmute 后唤醒词恢复（R7）

- **写范围**：`main/application.cc` `Application::HandleMuteStateChanged`（`e6b7c1b`，+4/−3）；persona.2 前像 blob `89138d6…` → 应用后 `335b7925…`（实测 clean）。
- **验收**：
  1. 构造「speaking 中 unmute」路径：解静音后串口出现 `mute: server-confirmed unmuted, wake word restored`，且随后唤醒词可用。
  2. 对照：重做前同一路径唤醒词不可用（复现基线）。
  3. 不改 mute on/off 协议与 `MuteStatus` 同步逻辑。
- **刷机范围**：app `0x20000`。
- **风险**：语义变更——任何状态 unmute 都恢复唤醒词，speaking 中唤醒词恢复会与 TTS 播放并发，行为需真机实测；需独立评审 + 至少 3 次重复。
- **回滚锚**：§4.0。
- **工作量**：0.5 人日 + 独立评审。

#### C6（条件卡，仅 R6 复现时）D3 触摸：stale 强制释放

- **写范围**：`<board.cc>` `TouchPointFilter`（`p2:~2780-3000`，`64d13ba` +65/−7；实测 clean，落地 `de2852f4…`）。
- **验收**：复现幽灵点（静止点 >2.5s）→ 串口出现 `reason=ghost-release (held=… ms) -> forced release + ghost lock`；同点继续被丢弃时出现 `ghost lock: raw(…) stays dropped until release`；心跳 `ghost=` / `forced=` 计数递增。抬指后或移动 >30px 后点击恢复（CLICKED 重新产生）；正常长按 <2.5s 不被误释放。
- **刷机范围**：app `0x20000`。
- **风险**：改变所有视图的点击投递；锁定点 ±30px 内的点击会被丢弃（抬指或移动 >30px 即解锁，`kPointStalePx`）；与 C1/C4 无编译依赖，但**必须先有 R6 复现**再开卡。
- **回滚锚**：§4.0。
- **工作量**：0.5 人日 + 幽灵点复现实验（时间不确定）。

### 4.2 建议执行顺序

```
C0（回滚兜底）→ C1（B/C/D 残留，收益最大，8 行）
              → C4（顶栏静音，回应 9哥 第二个抱怨）
              → C3（D 落地像素，7 处 / 9 个字面量，需像素验收）
              → C2a / C2b（决策，可跳过；各自独立 commit）
              → C5（唤醒恢复，独立评审）
              → C6（仅 R6 复现时）
```

- **C1 与 C4 可以同一次构建/刷机验收**（两个独立 commit、两张卡各自的评审），以减少刷机次数；**提交必须分开**，便于单独回滚。
- **不要并行**：C1、C2a/C2b、C3、C4、C6 都写同一个 `.cc`；同一文件范围同一时间只允许一个实现者。
- **每张卡刷机前**先做 C0 的哈希核对；刷机后**先跑触摸冒烟**（顶栏、头像、滑动切视图）再跑四视图截图，避免把「刷机失败」误判成「视图回归」。

---

## 5. 风险与未覆盖

1. **D 视图 snapshot 成功率 2/9**（T1 §6）：7 次失败为设备侧 HTTP（`Transmit failed` ×5、`connect_failed, native=12` ×2），伴随 `Mute: … Connection timed out`。属取证可靠性问题，不是渲染缺陷；但 D 的任何验收都必须允许重试，且「分数增长」比单帧更可靠。
2. **回滚资产未留存**：板上身份已由 verifier 闭环（`read_flash 0x20000 2920928` + sha256 + `cmp` 与 release 资产 `a67645c8…eeab4` 逐字节一致，T1 §2/§8 第 3 条）；但本机未保留该资产副本，回滚前需重新下载并复核 sha256（见 C0）。
3. **R6 幽灵点路径未覆盖**（T1 §4.6）：本次 133 条心跳 `stale=0/ghost=0/forced=0`，最长静止间隔 46.9s 也没锁死；只能说明「正常点按可用」，不能说明「自锁已修」。C6 开卡前需要可复现路径。
4. **27fps 与 `dirty≈8.4–9.0k px` 没有基线对照**：只有 8 条 60s 采样（5×28 + 3×27），未与 persona.3/main 对比，不能判定性能回归；C3 只设「≥26fps 不退化」的下限。
5. **单会话、单帧**：每视图只有 1 帧（D 2 帧），A 的仙人掌因时序未入镜；「A 无仙人掌」不是缺陷（§2.1）。任何「偶发」类结论都需要第二轮采集。
6. **M2（175056b 冗余）依赖主题字体已挂载**：`ApplyPhaseBFonts(ActiveTextFont())` 在 `ActiveTextFont()` 返回 `LV_FONT_DEFAULT` 时也会执行；若某次启动 assets 未挂载且默认字体是 montserrat_14（ASCII），A 标题会回到 tofu 形态。此路径未在真机验证，C1 不必捎带 175056b，但保留它作为低成本一致性修复是合理的。
7. **R3 静态不可定位**：找不到必然盖住 `game_view_` 的对象（§2.4 R3-D）；`0a43f23` 是防御性修复，**没有证据**表明它能修掉一个本次未复现的症状。
8. **刷机只写 app 的生效前提**：otadata 必须指向 `ota_0`；写错槽位会「刷了但没变」，容易被误判成修复无效。
9. **回滚物质缺位**：本机无 `a67645c8…` 副本（已核对 4 个候选，verifier 下载的资产也未留存），且重建不保证字节等同；C0 未完成前不建议开始刷机类改动。
10. **构建环境漂移**：`managed_components/`、`sdkconfig` 不进 git（T2 §1），persona.2 构建时的 LVGL/SsidManager 版本无法用 git 证明；C1 只取 dino 分支不依赖 `SsidManager`；若额外取 `HandleTap`（第 4 个）并同时取 include（第 1 个）才会引入该依赖，需 CI 复核；`ScreenClickCb`（第 2 个）不涉及 `SsidManager`，但有全局点按路由 UX 变更（§3.3）。

---

## 6. 证据索引

### 6.1 结论 → 指针

| 结论 | 证据指针 |
|---|---|
| 9/9 sprite 自洽（编码合格） | T2 §4.1 表；本次复核：`git show v2.5.3-persona.2:main/ui/chrome_dino_sprites.h` → 9 个数组 declared==initializers==w*h，distinct={0,255}（§3.1 粘贴输出）；`sprites.h:57/113/169/203/237/281/340/361/409` header `stride=w` |
| A8 颜色/缩放/裁剪语义 | T2 §4.2（`lv_draw_image.c:53`、`lv_draw_sw_img.c:240-250/486-491`、`lv_image.c:690`、`lv_image.h:158-163`） |
| 配置块三版本相同 | 本次 `diff`：`p2:1180-1244` vs `p3:1191-1255` vs `main:1196-1260` 两次均空；`ADinoTick` p2/p3 空；`GameTick` 仅多 1 行 |
| R1 残留根因 | `p2:1200`（初始 HIDDEN）、`p2:1420-1422`（只 move_foreground）、`p2:1761-1762`（非 A 早退）、`p2:1777-1778`（A 内 unhide+foreground）；T1 §4.3/§4.4/§4.5 截图坐标 |
| R4 悬空 9/8px | `p2:1214/1219`（ground y=127）、`p2:1224`（dino y=80）、`p2:1229`（cactus 92）、`p2:1501`（77）、`p2:1529-1532`（碰撞 cy）；T2 §5.2 算式；T1 §4.5 地面 y=303/仙人掌 y 263–295 |
| A 条裁切 1.3/2.1px | `p2:1191`（y=9）、`p2:1197`（y=18）、`p2:1190/1196`（scale 186/210）；T1 §4.2 墨迹 x26–54/y290–319；T2 §5.1；本次算式复核 |
| C debug 重叠 | `p2:1254-1260`（debug y=288）、`p2:1412-1414`（C 显示）、`p2:1778`（dino 顶层）；T1 §4.4 + `crops/C-dino-strip-3x.png`（本次已看） |
| D 日志不遮游戏（M3） | `p2:1382-1384`（count=3/y0=44/line_h=33）、`p2:1203`（game_view y=170）；`view-D-extra5`（本次已看）；T1 §4.5 |
| M1 顶栏无可点对象 | `p2:973-980`（`mute_text_` 无回调）、`p2:1053`（`mute_hit_` HIDDEN）、`p2:1308-1310`（`mute_button_` HIDDEN）、`p2:1268-1269`（头像可点）、`p2:1445-1446`（D 隐藏头像）；T1 §4.6 实测点都在头像区 |
| M2 175056b 冗余 | `p2:1136`（small_font）→ `p2:1313` 调 `ApplyPhaseBFonts(ActiveTextFont())` → `p2:1639` 覆盖为 `font`；`p2:2238` 再次覆盖；`crops/A-metrics-3x.png`（本次已看，CJK 正常） |
| R5 修法可应用 | `6a6697b`（+4）、`e5b2139`（+1）；本次 `git apply` 两段 clean，落地 `e54a7649…`；T2 §3.2（1/1 + 0/1 → 需 6a6697b 先上） |
| 三条 UI commit 可重做 | 本次 `git log --oneline v2.5.3-persona.2..main`（8 条，§6.2）；blob：p2=`15e05fa`=`edc3037f…`；依序 apply 后 = `42fe3283…` = p3；T2 §3.2 表 |
| 不触 TouchPointFilter/mute | 本次对 p2→p3 的 `<board.cc>` diff 逐个符号检索：`TouchPointFilter`、`MuteButtonCb`、`HandleMuteStateChanged`、`ToggleMute`、`mute_text_`、`mute_hit_` —— **全部无匹配** |
| R6 仍是 D2 触摸策略 | `p2:2893-2915`（stale → HOLD，注释「Never write a release timestamp here」）；T1 §4.6（133 条心跳全 0）；T2 §6 R6 |
| R7 改 mute 相关行为 | `git show e6b7c1b -- main/application.cc`（去掉 `state==kDeviceStateIdle` 前提，+4/−3）；p2 前像 `89138d6…` → `335b7925…`（本次 apply clean） |
| D3 触摸可独立应用 | 本次 `git apply 64d13ba` → clean，落地 `de2852f4…`；T2 §3.2（5/5） |
| 回滚锚与板上身份 | `build/SHA256SUMS-persona.2`（`a67645c8…eeab4`）；verifier `read_flash 0x20000 2920928` + `cmp` 逐字节一致（T1 §2/§8 第 3 条）；本次 `shasum -a 256` 核对本机 `build/xiaozhi.bin`=`56d96d7d…`、`xiaozhi_flashed.bin`=`96247ffb…`、`merged-binary.bin`=`d86b1bc4…`（均非 persona.2，资产需重新下载） |
| 分区 0x20000 | `partitions/v2/16m.csv`（`ota_0, app, ota_0, 0x20000, 0x3f0000`；`assets, data, spiffs, 0x800000, 8M`） |
| 证据文件完整性 | 本次 `shasum -a 256 view-*.jpg` 与 T1 §4.2–4.5 逐个一致；`serial-persona2-2210.final.log` = `5307aef7…e336`，3781 行 |

### 6.2 本次实际执行过的复核命令（verifier 可重跑）

```sh
cd 05_Tools/xiaozhi-esp32
git status --porcelain=v1 -b
git log --oneline v2.5.3-persona.2..main
git rev-parse v2.5.3-persona.2 v2.5.3-persona.3 main
git rev-parse v2.5.3-persona.2:<board.cc> 15e05fa:<board.cc> d2d47c7:<board.cc> \
                175056b:<board.cc> 0a43f23:<board.cc> main:<board.cc>
#   → edc3037f  edc3037f  170849ef  b54ff87a  42fe3283  ee40e247
git diff -U0 v2.5.3-persona.2 v2.5.3-persona.3 -- <board.cc> | grep '^@@'   # 7 hunks

# 1) 三条 UI commit 重做到 persona.2（不写仓库，只在 /tmp 验证）
mkdir -p /tmp/applytest/main/boards/chd/chd-esp32s3-box
git show v2.5.3-persona.2:<board.cc> > /tmp/applytest/<board.cc>
git show v2.5.3-persona.2:main/application.cc > /tmp/applytest/main/application.cc
for c in d2d47c7 175056b 0a43f23 64d13ba 6a6697b e5b2139; do
  git format-patch -1 --stdout $c -- <board.cc> > /tmp/applytest/$c.patch; done
git format-patch -1 --stdout e6b7c1b -- main/application.cc > /tmp/applytest/e6b7c1b.patch
cd /tmp/applytest && for p in d2d47c7 175056b 0a43f23; do git apply $p.patch; done
git hash-object <board.cc>     # → 42fe3283065c301be2ccd2501bee198ebe7e8d64 (= persona.3)
# 单测：64d13ba → de2852f4；6a6697b+e5b2139 → e54a7649；e6b7c1b → 335b7925（均 clean）

# 2) 配置块三版本等价
git show v2.5.3-persona.2:<board.cc> | sed -n '1180,1244p' > /tmp/p2.cfg
git show v2.5.3-persona.3:<board.cc> | sed -n '1191,1255p' > /tmp/p3.cfg
git show main:<board.cc>             | sed -n '1196,1260p' > /tmp/main.cfg
diff /tmp/p2.cfg /tmp/p3.cfg && diff /tmp/p2.cfg /tmp/main.cfg   # 两次都空

# 3) sprite 自洽（python3）
git show v2.5.3-persona.2:main/ui/chrome_dino_sprites.h > /tmp/sprites.h
# 逐数组解析 declared[N] 与初始化值个数：9/9 相等，distinct={0,255}

# 4) 证据完整性
cd 01_Code/projects/esp32-voice-entry/docs/tasks/abcd-views/evidence
shasum -a 256 view-*.jpg serial-persona2-2210.final.log
grep -c 'post-frame heartbeat' serial-persona2-2210.final.log       # 133
grep -c 'tap -> ToggleChatState' serial-persona2-2210.final.log     # 15
grep -c 'reason=stale\|ghost-release\|ghost lock' serial-persona2-2210.final.log  # 0
grep -c 'indev state: pressed=1 points=1' serial-persona2-2210.final.log         # 167
sed -n '1325p;1328p' serial-persona2-2210.final.log   # UI toggle → sync ok muted=0
```

### 6.3 文档内引用图（均已存在并核对 sha256）

| 文件 | sha256（前 8） | 用途 |
|---|---|---|
| `evidence/view-A-20261029-221214.jpg` | `bf10712f` | A：恐龙条、CJK |
| `evidence/view-B-20261029-221217.jpg` | `eece52fd` | B：残留 dino/cactus、ECG |
| `evidence/view-C-20261029-221220.jpg` | `9d8ac333` | C：残留 + debug 重叠 |
| `evidence/view-D-second-20261029-221223.jpg` | `7e9e86c0` | D 首帧：分数 00001、跳跃 |
| `evidence/view-D-extra5-20261029-221650.jpg` | `1b188c4d` | D 次帧：分数 00165、两只恐龙 |
| `evidence/crops/C-dino-strip-3x.png` | `8be23ee4` | C debug 被压 |
| `evidence/crops/A-metrics-3x.png` | `ff6d81d1` | A CJK 标题正常 |
| `evidence/serial-persona2-2210.final.log` | `5307aef7` | 串口冻结快照（3781 行） |

---

## 附：交接块

- **目标**：给 9哥 一份可决策的四视图根因报告 + 拆卡建议；本卡不实现修复。
- **已定决策**：不重导恐龙资源；不把 R4 算作 persona.3 已修；D3 触摸不默认纳入；C1 只取 d2d47c7 的 `ApplyViewLayout` dino 分支（第 3 个 hunk）。
- **涉及文件**：本文件（`03-report.md`）为唯一写范围；01/02、`evidence/`、`05_Tools/xiaozhi-esp32`、`src/` 均未改。
- **下一步**：9哥 认可后按 §4.2 顺序开卡；先做 C0（重新下载回滚资产并复核 sha256），再 C1。
- **验收命令**：§6.2 全部；评审者可逐条重跑。
- **未覆盖/未证**：§5 的 10 条（重点：D snapshot 失败率、R6 未复现、回滚资产未留存、重建非字节等同、D fps 无基线对照）。
