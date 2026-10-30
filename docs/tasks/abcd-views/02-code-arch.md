# T2 代码考古：persona.2 vs persona.3 归因 + 恐龙编码核实

- 任务：task-2（impl-arch）。只读考古，不改固件、不刷机。
- 基线：固件仓 `05_Tools/xiaozhi-esp32`，工作树干净，`main = 64d13ba`。
- 对照：`v2.5.3-persona.2 = 81b3b20`（板上 app）↔ `v2.5.3-persona.3 = 0a43f23`。
- 生成时间：2026-10-29 22:10–22:20；修订 22:2x（按 reviewer-b CHANGES 5 条改引用与措辞）。

---

## 0. 结论摘要（TL;DR）

1. **恐龙资源编码没有缺陷**。9 个 A8 sprite 的 `cf/stride/data_size/初始值个数` 与声明尺寸全部自洽（`stride == w`，`data_size == w*h`），LVGL 9.5 对 `LV_IMAGE_SRC_VARIABLE` 不校验 `header.magic`，A8 不放 `recolor` 也默认画成**黑色剪影**（`lv_draw_image.c:53`）。所以「恐龙显示不对」**不是编码问题**，不需要重导资源。
2. **配置确实有可量化缺陷，且集中在 D 视图**：恐龙/仙人掌的 `y` 把「对象框底边」当成「脚下地面」，但 ground sprite 自身顶部有 6 行空白（ink 只在 sprite 第 6..11 行），dino sprite 底部还有 2 行空白 → **D 视图恐龙悬空 9px、仙人掌悬空 8px**（算式见 §5.2）。这条在 persona.2 / persona.3 / main **完全相同**，persona.3 的三个 UI 修复**没有修它**。
3. persona.2 缺的**不止 1 个** commit：`persona.2..persona.3` 有 4 个（1 文档 + 3 UI），`persona.3..main` 还有 4 个（唤醒 + 静音可点 + 静音热区 + D3 触摸）。共 8 个，逐条见 §2。
4. 三条 UI commit 可以**干净地重做到 persona.2**，**不需要**捎带 `64d13ba`，也**不触碰 mute 语义**：`persona.2` 的板级文件 blob 与 `d2d47c7^`(=15e05fa) **逐字节相同**（同为 `edc3037`），`d2d47c7 175056b 0a43f23` 依序 cherry-pick 后板级文件 blob 恰好等于 `persona.3` 的 `42fe328`。hunk 级匹配见 §3.2。
5. **但**：`64d13ba`（D3）单独 cherry-pick 到 persona.2 同样可行（5/5 hunk 上下文命中），且它是**唯一**能让「幽灵点自锁 → 所有点击失效」不再发生的东西。若板上仍复现点击全失效，UI 修复不会生效——因为 CLICKED 根本没产生。它是触摸驱动器层的修复，**不改 mute 语义**。

---

## 1. 基线与方法（只读）

```sh
cd 05_Tools/xiaozhi-esp32
git status --porcelain=v1 -b     # ## main...upstream/main [ahead 52, behind 5]（无文件变更）
git rev-list -n1 v2.5.3-persona.2  # 81b3b20909b8150448e14a012d71bb6aeac22cc5
git rev-list -n1 v2.5.3-persona.3  # 0a43f238a1eaf676fe77a19bfe3e7556137fd5a0
git merge-base --is-ancestor v2.5.3-persona.3 main   # → persona.3 是 main 的祖先
```

读代码一律用 `git show <tag>:<path>`，不用 checkout。**未执行** checkout/reset/stash/commit/edit，未刷机。

**证据边界（必须说明）**：LVGL 源码与 `sdkconfig` 位于工作树（`managed_components/`、`sdkconfig` 均被 `.gitignore`），**不受 tag 控制**。本文的 LVGL 语义来自当前工作树 `lvgl 9.5.0`（`managed_components/lvgl__lvgl/lv_version.h:9-11`）+ `CONFIG_LV_DRAW_SW_SUPPORT_A8=y`（`sdkconfig:5038`）。persona.2 构建时用的是同一目录，但这一点**无法用 git 证明**；若要绝对严谨，需在 persona.2 构建产物里核对（本次未做）。

---

## 2. 提交清单（persona.2 → main 的全部 8 个）

`git log --oneline v2.5.3-persona.2..main`：

| # | commit | 类型 | 文件 | 函数/位置 | 行为变化 | 影响 ABCD 视图？ |
|---|--------|------|------|-----------|----------|------------------|
| 1 | `15e05fa` | **文档（非代码）** | `README.md`, `README_UPSTREAM.md` | — | 双语首页 | 否 |
| 2 | `d2d47c7` | UI | `chd_esp32s3_box_board.cc` (+22/−5) | `ScreenClickCb` / `ApplyViewLayout` / `HandleTap` | ①子控件之外的点按穿透到 talk toggle ②非 A 视图隐藏 A 条带恐龙 ③只有在**没有已保存 SSID** 时启动期点按才进配网 | **是**（A 条带 + 全视图点按路由） |
| 3 | `175056b` | UI | 同上 (+1/−1) | `kAMetrics` 标题字体 | `small_font`(montserrat_14) → `font`(CJK 主题字体) | **是**（A 视图中文标题） |
| 4 | `0a43f23` | UI | 同上 (+7/−2) | `ApplyViewLayout` + `GameTick` | D 视图 `lv_obj_move_foreground(game_view_)` 两处 | **是**（D 视图层级） |
| 5 | `e6b7c1b` | 音频 | `main/application.cc` (+4/−3) | `Application::HandleMuteStateChanged` | 取消 `state == kDeviceStateIdle` 前提，任何状态 unmute 都恢复唤醒词 | 否（但**改 mute 语义**） |
| 6 | `6a6697b` | UI | board.cc (+4) | `mute_text_`（顶栏「未静音」） | 加 `LV_OBJ_FLAG_CLICKABLE` + `MuteButtonCb` | 否（B1 静音入口） |
| 7 | `e5b2139` | UI | board.cc (+1) | 同上 | `lv_obj_set_ext_click_area(mute_text_, 18)` | 否（B1 静音热区） |
| 8 | `64d13ba` | **触摸驱动** | board.cc (+65/−7) | `TouchPointFilter` | D3：静止点 >2500ms 强制释放 + ghost-lock，抑制假 CLICKED | 间接（**全部**视图的点按都依赖它不再自锁） |

> 任务卡只点了 `15e05fa/d2d47c7/175056b/0a43f23 + e6b7c1b`，实际 `persona.2..main` 是 **8** 个；`6a6697b`/`e5b2139`/`64d13ba` 也是板上没有的。这条差异本身是归因表的一部分（见 §6 的 R5/R6）。

**为什么 persona.2 会缺这些 —— 必须分两个层面说，别混成一句**：

- **git 血统**：`15e05fa..64d13ba` 全部在 `persona.2` **之后**线性提交（`git log --oneline v2.5.3-persona.2..main` 无分支）⇒ `v2.5.3-persona.2` 这个 tag **从未包含**这些修复。就代码血统而言，是「**修复未回移**」。
- **设备层面**：回滚前板上跑的是 `e5b2139` 构建 —— `docs/HANDOFF.md:25-26` 的 read_flash 回读记录（「板上 app 回读 md5 = `0f72fd…` = HEAD `e5b2139` 构建…即已含 `6a6697b` + `e5b2139` + `e6b7c1b`」），加上 persona.3 三个 UI commit 在 `0a43f23` 内，可见回滚前的 app 已带全部这些修复；`HANDOFF.md:15` 记「板上 app = 上一版 release `v2.5.3-persona.2`（2026-10-29 21:58 按 9哥 要求回滚）」⇒ 21:58 回滚后，这些修复在**设备上确实丢了**。所以对用户可见的「回滚后变差」，归属是「**回滚/未回移**」，而不是「新冒出来的 bug」。

---

## 3. 三条 UI commit 的关键 diff 与「单独重做」可行性

### 3.1 diff（行号为 persona.2 侧，即各 commit 的 `-` 侧）

**(a) d2d47c7 — 三件事挤在一个 commit 里，三个 hunk 互相独立**

Hunk 1 `persona.2:656-658`（`ScreenClickCb`，屏幕级点按路由）:

```c
         if (lv_event_get_target(e) != lv_event_get_current_target(e)) {
-            return;  // bubbled from a child; the child owns this interaction
+            lv_obj_t* target = static_cast<lv_obj_t*>(lv_event_get_target(e));
+            if (self->face_panel_ != nullptr &&
+                (target == self->face_panel_ || lv_obj_get_parent(target) == self->face_panel_)) {
+                return;
+            }
+            if (lv_obj_has_flag(target, LV_OBJ_FLAG_CLICKABLE)) {
+                return;
+            }
         }
```

Hunk 2 `persona.2:1416-1421`（`ApplyViewLayout`；前 3 行 `game_view_` 是上下文，本 commit 不改它）:

```c
         if (game_view_ != nullptr && lv_obj_is_valid(game_view_)) {
             if (is_d) lv_obj_remove_flag(game_view_, LV_OBJ_FLAG_HIDDEN);
             else lv_obj_add_flag(game_view_, LV_OBJ_FLAG_HIDDEN);
         }
-        if (is_a && dino_root_ != nullptr && lv_obj_is_valid(dino_root_)) {
-            lv_obj_move_foreground(dino_root_);
+        if (dino_root_ != nullptr && lv_obj_is_valid(dino_root_)) {
+            if (is_a) {
+                lv_obj_remove_flag(dino_root_, LV_OBJ_FLAG_HIDDEN);
+                lv_obj_move_foreground(dino_root_);
+            } else {
+                lv_obj_add_flag(dino_root_, LV_OBJ_FLAG_HIDDEN);
+            }
         }
```

Hunk 3 `persona.2:3268-3269`（`HandleTap`，配网误触保护）:

```c
-        if (state == kDeviceStateStarting && GetNetworkType() == NetworkType::WIFI) {
-            ESP_LOGI("CHD_UI", "tap -> EnterWifiConfigMode (state=starting)");
+        if (state == kDeviceStateStarting && GetNetworkType() == NetworkType::WIFI &&
+            SsidManager::GetInstance().GetSsidList().empty()) {
+            ESP_LOGI("CHD_UI", "tap -> EnterWifiConfigMode (no saved SSID)");
```

外加一条 include：`+ #include <ssid_manager.h>`（persona.2 可用：`managed_components/78__esp-wifi-connect/include/ssid_manager.h:28` 提供 `GetSsidList()`，且 `v2.5.3-persona.2:main/idf_component.yml:27` 已要求 `78/esp-wifi-connect: ~3.3.1`，该组件目录不进 git）。

**(b) 175056b — `persona.2:1136`（`kAMetrics = {"状态","内存","帧"}` 在 1130 行）**

```c
-            lv_obj_set_style_text_font(a_metric_titles_[i], small_font, 0);
+            lv_obj_set_style_text_font(a_metric_titles_[i], font, 0);
```

`small_font = &lv_font_montserrat_14`（`main:925`，纯 ASCII），`font = ActiveTextFont()`（主题 CJK 字体，`main:2242-2248`）→ 改前中文标题无字形（空白/tofu），改后正常。**这是 persona.2 tag 从未包含的修复**（归属见 §6 R2=回滚/未回移；设备回滚后丢失见 §2 的「设备层面」）。

**(c) 0a43f23 — 两处 `move_foreground`**

```c
// ApplyViewLayout，D 分支
-            if (is_d) lv_obj_remove_flag(game_view_, LV_OBJ_FLAG_HIDDEN);
-            else lv_obj_add_flag(game_view_, LV_OBJ_FLAG_HIDDEN);
+            if (is_d) {
+                lv_obj_remove_flag(game_view_, LV_OBJ_FLAG_HIDDEN);
+                lv_obj_move_foreground(game_view_);
+            } else {
+                lv_obj_add_flag(game_view_, LV_OBJ_FLAG_HIDDEN);
+            }
// GameTick，每 25ms 的显示路径
         lv_obj_remove_flag(self->game_view_, LV_OBJ_FLAG_HIDDEN);
+        lv_obj_move_foreground(self->game_view_);
```

> 说明：静态代码里**找不到**一个必然盖住 `game_view_` 的同级对象。逐个排除（`cards_` 非 B 即隐藏 `main:1388-1396`；`hermes_avatar_`/`subtitle_bar_`/`idle_wave_`/`debug_line_`/`ascii_scope_` 在 D 全隐藏；`face_panel_` 已在创建时 `lv_obj_move_to_index(...,1)` `main:1942`；`mute_overlay_` 是 `face_panel_` 的子对象 `main:2058`）。因此这条按「**防御性 z-order 保证**」定性：不改几何、幂等、无副作用，但**静态不可复现其触发条件**；结论以真机观测为准。真机记录要分开引：D 视图层级本身见 `docs/HANDOFF.md:96`（「D 视图游戏恢复…实测 `set_view=3` 可见恐龙、仙人掌和分数」，属开发期记录）；`HANDOFF.md:29` 的 21:25/21:33 记的是「整包回刷 persona.3 后仍能用右下角切静音」，是**静音入口**的可用性，不能当成 D 视图层级的证据。

### 3.2 能否单独重做到 persona.2 —— 逐 hunk 实测

方法：把每个 commit 的 hunk 拆成「上下文 + 删除行」，逐段在 `v2.5.3-persona.2:<board.cc>` 的文本里做**逐字匹配**（不写仓库、不 checkout）：

```
64d13ba (D3 touch):  hunks=5  pre-image matches in persona.2: 5/5
0a43f23 (D raise):   hunks=2  pre-image matches in persona.2: 1/2   ← 需 d2d47c7 先上
175056b (CJK font):  hunks=1  pre-image matches in persona.2: 1/1
d2d47c7 (dino hide): hunks=4  pre-image matches in persona.2: 4/4
6a6697b (mute click):hunks=1  pre-image matches in persona.2: 1/1
e5b2139 (mute area): hunks=1  pre-image matches in persona.2: 0/1   ← 需 6a6697b 先上
```

再加一条硬证据（板级文件 blob）：

| rev | blob |
|---|---|
| `v2.5.3-persona.2` | `edc3037f…` |
| `15e05fa`（= `d2d47c7^`） | `edc3037f…`（**相同**） |
| `d2d47c7` | `170849ef…` |
| `175056b` | `b54ff87a…` |
| `0a43f23` = `v2.5.3-persona.3` | `42fe3283…`（**相同**） |
| `main` | `ee40e247…` |

→ `git cherry-pick d2d47c7 175056b 0a43f23` 在 persona.2 上按序应用后，板级文件 hash 恰好落到 `42fe3283`（persona.3 原样），无冲突、无手工解冲突。
**触碰面**：三个 commit 只改这一个 `.cc` 的三段（点按路由 / A 标题字体 / D 层序），**不进入** `TouchPointFilter`（`main:2900+` 区域，属 64d13ba）也**不进入** `MuteButtonCb` / `HandleMuteStateChanged` / `ToggleMute`。
`0a43f23` 单独上不行（hunk 1 的上下文含 d2d47c7 的新增行），必须先 `d2d47c7`；`175056b` 可单独上。

---

## 4. 恐龙资源编码核实（`main/ui/chrome_dino_sprites.h`）

### 4.1 逐 sprite 自洽性

用脚本对数组做「初始化值个数 / 字节数 / 声明 w、h」核算（源文件 412 行，未逐行抄入）：

| sprite | 声明 | cf | stride | data_size | 初始化值个数 | 应等于 w*h | 结论 |
|---|---|---|---|---|---|---|---|
| `chrome_dino_idle_a8` (7, dsc 56-60) | 44x47 | A8 | 44 | sizeof=2068 | 2068 | 2068 | ✅ |
| `chrome_dino_run1_a8` (63, dsc 112-116) | 44x47 | A8 | 44 | 2068 | 2068 | 2068 | ✅ |
| `chrome_dino_run2_a8` (119, dsc 168-172) | 44x47 | A8 | 44 | 2068 | 2068 | 2068 | ✅ |
| `chrome_dino_duck1_a8` (175, dsc 202-206) | 59x25 | A8 | 59 | 1475 | 1475 | 1475 | ✅（但**全仓未引用**） |
| `chrome_dino_duck2_a8` (209, dsc 236-240) | 59x25 | A8 | 59 | 1475 | 1475 | 1475 | ✅（同上未引用） |
| `chrome_cactus_small_a8` (243, dsc 280-284) | 17x35 | A8 | 17 | 595 | 595 | 595 | ✅ |
| `chrome_cactus_large_a8` (287, dsc 339-343) | 25x50 | A8 | 25 | 1250 | 1250 | 1250 | ✅ |
| `chrome_ground_a8` (346, dsc 360-364) | 600x12 | A8 | 600 | 7200 | 7200 | 7200 | ✅ |
| `chrome_ptero_a8` (366, dsc 408-412) | 46x40 | A8 | 46 | 1840 | 1840 | 1840 | ✅ |

`grep -rn 'duck' main/ --include=*.cc --include=*.h | grep -v chrome_dino_sprites.h` → 空：**duck1/duck2 是死资源**（不影响显示，只占 flash）。

墨迹包围盒（判断 "裁剪是否印错/错位"）：

```
chrome_dino_idle_a8    44x47  ink x[2..41]  y[2..44]  740px (35.8%)
chrome_dino_run1_a8    44x47  ink x[2..41]  y[2..44]  726px
chrome_dino_run2_a8    44x47  ink x[2..41]  y[2..44]  724px
chrome_cactus_small_a8 17x35  ink x[1..15]  y[1..33]  249px
chrome_cactus_large_a8 25x50  ink x[1..23]  y[1..48]  527px
chrome_ground_a8       600x12 ink x[0..599] y[6..11]  655px   ← 关键：顶部 6 行全透明
chrome_ptero_a8        46x40  ink x[2..43]  y[8..37]  384px
```

ground 的前 6 行、dino 的上下各 2 行、ptero 顶部 8 行都是**设计内的透明 padding**（Chromium atlas 里就是这样），本身不是错误——但**下游 `y` 配置没有把它们算进去**，见 §5.2。

### 4.2 LVGL 9.5 对该格式的绘制要求（逐条查源码）

| 问题 | 事实 | 证据 |
|---|---|---|
| `header.magic` 要不要填 `0x19`？ | 对 `LV_IMAGE_SRC_VARIABLE` **不校验**；magic 只在 `magic != MAGIC` 时清掉 `PREMULTIPLIED` 标志 | `lv_bin_decoder.c:120-123`（拷 header）、`:143-146`（仅文件源做 legacy 兼容）、`:172-174` |
| `data_size` 怎么用？ | `stride*h > data_size` 才报 `Data size too small` 并 INVALID；相等可以 | `lv_draw_buf.c:218-229` |
| A8 没颜色，颜色从哪来？ | 画笔颜色 = `draw_dsc->recolor`，默认 `lv_color_black()`；**不看 `recolor_opa`**（A8/L8 强制 `do_recolor=false`，只把数据当 mask） | `lv_draw_image.c:53`；`lv_draw_sw_img.c:240-250`（未变换路径 `blend_dsc.color = draw_dsc->recolor`）、`:486-491`（`if(cf==A8){color=recolor; do_recolor=false;}`） |
| 必须显式开 `image_recolor_opa` 吗？ | **不需要**（A8 上它不影响颜色，只影响 L8/RGB 混合路径）。板上对每个 sprite 都设了 `LV_OPA_COVER`，属冗余但无害 | 同上；`main:1209/1215/1232/1237/1242/1247/1257` |
| `lv_image_set_scale(186)` 是 0.73 还是 186%？ | **256 = 100%**，186 = 0.727x，210 = 0.820x | `lv_image.h:158-163`（注释原文：256 or LV_SCALE_NONE: no zoom / 128: half） |
| 缩放绕哪个点？ | 构造函数把 pivot 设为 `LV_PCT(50), LV_PCT(50)`（**默认中心**）；对象尺寸仍是 `w×h`——`LV_EVENT_GET_SELF_SIZE` 直接回报 `img->w/h`，**不随 scale 变**，缩放后的墨迹在框内**居中** | `lv_image.c:690`（pivot 默认值）、`:120-121`（`width_def/height_def = LV_SIZE_CONTENT`）、`:786-789`（self size = img->w/h） |
| A8 能不能被缩放？ | 头文件注释说 "indexed and alpha only images can't be transformed"（`lv_image.h:168`），但**实现支持**：`transform_a8()` 存在且本 build 打开（`CONFIG_LV_DRAW_SW_SUPPORT_A8=y`），变换分支命中 | `lv_draw_sw_img.c:223-224`（`transformed = rotation!=0 || scale_x!=LV_SCALE_NONE ...`）、`lv_draw_sw_transform.c:259-261` → `:887`；`sdkconfig:5038` |
| antialias 要显式开吗？ | 默认 `LV_COLOR_DEPTH > 8 ? 1 : 0`，本板 16bpp → **默认开** | `lv_draw_image.c:57`、`sdkconfig:4954` |
| 子对象会被父对象裁掉吗？ | 会。`LV_OBJ_FLAG_OVERFLOW_VISIBLE` **默认不设** → 用 `obj->coords` 裁剪 | `lv_obj.h:70`、`lv_refr.c:142-147` |

**缺省时的"预期观感"**（对应任务卡的问题）：
- A8 + **不设 recolor** → 画成**纯黑剪影**，背景色从透明像素透出；不会消失、不会花屏。若想要墨绿（`0x202B2D`）必须显式 `image_recolor`（板上已设）。
- A8 + **不设 scale** → 1:1 原尺寸（44x47）；D 视图正是这样，所以 D 视图对尺寸的假设成立。
- A8 + **scale≠256 且不设 pivot** → 以中心为锚缩放，**墨迹在 44x47 框内居中**（左右各缩进约 6px、上下各约 6.5px @0.727x）。与"以左上角为锚"的直觉差 6px 级，这是 §5.1 裁切/悬空的根因之一。
- A8 + **无 AA**（若 `LV_COLOR_DEPTH==8`）→ 缩放后边缘硬阶梯；本板 16bpp，AA 默认开。

### 4.3 结论

**编码合格，问题不在资源**。可证伪的检查全部通过（stride=w、data_size=w*h、初值个数精确、magic 非必需、A8 上色/缩放/AA 语义清楚）。若真机出现"恐龙变成色块/花屏/整块黑矩形"，才可能是编码或对齐问题；按现有代码，A8 只可能表现为**黑色剪影 + 位置/裁切偏差**。

---

## 5. 配置常量核实（`chd_esp32s3_box_board.cc`）

行号：**main(64d13ba)** 为当前文件行号；括号内给 persona.2 行号（该块 persona.2 与 main 差 16 行）。屏幕 `480x320`（`main:373` 注释；串口启动段实测 `CHD_TOUCH: ranges: display=480x320 touch=480x320 MATCH`，位于 `evidence/serial-persona2-2210.final.log` 文件头第 77-78 行 —— 文件头段不随追加漂移，`01-repro-evidence.md` 的「串口启动原文」处亦引同一段）。

### 5.1 A 视图（A 条带 = `dino_root_`）

| 项 | 值 | 位置 | 判断 |
|---|---|---|---|
| `dino_root_` pos/size | `(0,273)` `480x47` → 273..319 | `main:1196-1198`（p2:1180-1182） | ✅ 与 320 高屏严丝合缝（319 是最后一行） |
| dino 精灵 | 44x47 @ `(18,9)`，`scale 186` | `main:1204-1207`（p2:1188-1191） | ⚠️ 对象框 282..328 超出条带底 319；缩放后墨迹 289.7..320.3 → **脚底被裁 ~1.3px** |
| cactus | 17x35 @ `(480,18)`，`scale 210` | `main:1210-1213`（p2:1194-1197） | ⚠️ 墨迹 294.9..321.1 → **底部裁 ~2.1px**；`x=480` 在 t=0 完全在可视区外，但 5px/80ms 走，**第一个 tick（80ms）就进画面**，属正常 spawn，不是缺陷 |
| 缩放语义 | 186/256=0.7266 → 44×0.727=**32.0** 宽、47×0.727=**34.1** 高；210/256=0.8203 → **13.9x28.7** | 代码注释 "~33x35" / "~14x29" | ✅ **与注释吻合 → 不是把 256 当 100 的百分比误用**。若按 1.86x 理解，44x47→82x87，47px 窗口只剩上半身，与注释矛盾，可排除 |
| 上色 | recolor `0x202B2D` + `OPA_COVER` | `main:1208-1209/1214-1215` | ✅（对 A8 而言 `OPA_COVER` 冗余，见 §4.2） |

**A 条带的真实风险不是编码也不是 scale，而是 `y=9/18` + 中心 pivot**：作者按「未缩放、左上锚定」摆位，实际缩放后墨迹在框内居中下沉约 6.5px，于是脚底压到条带边界外 1~2px。肉眼约 1~2 行像素，属**轻微**，单独不足以解释"四视图问题"。

### 5.2 D 视图（`game_view_`）

| 项 | 值 | 位置 | 判断 |
|---|---|---|---|
| `game_view_` | `(0,170)` `480x150` → 170..319 | `main:1218-1220`（p2:1202-1204） | ✅ 底部对齐屏幕 |
| ground A/B | `(0,127)`、`(600,127)`，600x12 | `main:1228-1237`（p2:1212-1221） | ⚠️ 见下「悬空」与「死对象」 |
| game dino | 44x47 @ `(50,80)`，**不缩放** | `main:1238-1240`（p2:1222-1224） | ⚠️ 见下 |
| cactus | 小 17x35 @ `(480,92)`；大 25x50 换源时 `set_y(77)` | `main:1243-1245`、`main:1524-1527`（p2:1227-1229） | ✅ 两个尺寸的框底都=127，与 `y` 自洽 |
| ptero | `(480,75)` 隐藏；激活时 `y∈{90,75}` | `main:1253-1258`、`main:1540` | ✅ 轻微：y=90 时框底 129 落入 ground 带 3px（ground 带那段是透明 padding，无可见重叠） |
| score | `(8,8)` | `main:1248-1252` | ✅ |
| GameTick | `25ms`（40Hz）；cactus `-6px/tick`=240px/s；score `+1/tick`（每 3 tick 刷文本） | `main:1260`、`main:1520-1534` | ✅ 自洽，无矛盾 |
| 碰撞盒 | `dx=50, dy=game_dino_y_`，仙人掌 `cw/chh` 与 `cy` 按大/小切换 | `main:1555-1558` | ✅ 与摆位自洽（注意：碰撞盒用的是**声明尺寸**，与实际墨迹差 2px，属可接受误差） |

**算式（关键缺陷：D 视图整体悬空 8~9px）**

```
game_view_ 顶 = 170（abs）
ground 对象   : y=127 → 对象行 297..308
ground 墨迹   : sprite 第 6..11 行 → 可见地面线 abs 303..308   ← 顶部 6 行是透明 padding
dino 对象     : y=80 → 行 250..296
dino 墨迹     : sprite 第 2..44 行 → abs 252..294            ← 底部 2 行是透明 padding
⇒ dino 脚底 294  vs  地面线 303  ⇒  悬空 9 px
cactus 小墨迹 : sprite 1..33 → abs 263..295  ⇒  悬空 8 px
cactus 大墨迹 : sprite 1..48 → abs 248..295  ⇒  悬空 8 px
```

**算式（死对象）**

```
ground B x=600..1199；game_view_ 内容宽 480（列 0..479），默认裁剪（lv_obj.h:70）
⇒ 地面 B 自始至终一个像素都画不出来；且 ground 已"静态化"（main:1518-1519 注释），
  不存在滚动把它带进画面 ⇒ 7200B rodata + 每帧一次被裁掉的绘制调用，纯负担
```

**ground 间距 600 与滚动逻辑是否匹配**：地面 A 宽 600，若滚动，下一块应在 x=600（相邻无缝）——数值上**正确**；但当前实现已改为静态地面，`600` 只是历史残留，导致 B 块永远不可见。这不是视觉缺陷，是**死配置**。

**cactus 起始 x=480 是否在可视区外**：是（列 480..496 全部 > 479），但它是「刚出屏右侧的 spawn 点」，`GameTick` 每 25ms 左移 6px，**第一帧后就有像素进入**；`x<-30` 时重置回 480，同样只黑 1 帧。**判定：不是缺陷**（任务卡的这个怀疑点可以排除）。

### 5.3 可疑配置值汇总（含算式）

| # | 值 | 位置 | 算式/推理 | 判定 |
|---|---|---|---|---|
| S1 | D 视图 dino `y=80`、cactus `y=92/77` 相对 ground `y=127` | `main:1240/1245/1527` | 127−(80+47)=**0**（框底贴地）但墨迹底 44/47 → 地面墨迹在 sprite 第 6 行 ⇒ 127+6−(80+44)=**9px 悬空** | **确定缺陷（可见）**，persona.3/main 同款未修 |
| S2 | A 条带 dino `y=9`、cactus `y=18`（条带高 47） | `main:1207/1213` | 9+47=56 > 47；缩放后墨迹 320.3 > 319 ⇒ 裁 1.3px；cactus 321.1 ⇒ 裁 2.1px | **轻微缺陷**（1~2 行像素），根因=按左上锚定算 y |
| S3 | ground B `x=600` | `main:1235` | 480 宽窗口 + 默认裁剪 ⇒ 永不可见 | **死配置**（非视觉缺陷） |
| S4 | `scale 186 / 210` | `main:1206/1212` | 186/256=0.727→32.0x34.1（注释 "~33x35"）；210/256=0.820→13.9x28.7（注释 "~14x29"） | **正常**，非百分比误用 |
| S5 | cactus spawn `x=480` | `main:1213/1245/1539` | 列 480..496 vs 0..479 ⇒ t=0 在屏外，1 tick 后进入 | **正常 spawn 约定** |
| S6 | GameTick `25ms` | `main:1260` | 40Hz；6px/tick=240px/s；score 40/s，每 3 tick 刷新 | **正常** |
| S7 | game_view_ 底 11px 空白（ground 墨迹止于 308，窗口到 319） | `main:1219-1220` | 319−308=11 | **风格问题**，非缺陷 |

---

## 6. 缺陷 → 归因表

> 编号用 **R1..R8**（report defect）；代码里触摸链的 **D1/D2/D3** 是另一套标签（D1=去 ghost anchor、D2=长按保持、D3=2.5 s 强制释放），两者不要混读。
> 「归属」只用三桶：**回滚/未回移**（persona.3 或 main 有、persona.2 tag 没有，且回滚前板上曾有过）/ **persona.2 自身且 persona.3 未修**（三个版本都错的配置/策略）/ **新问题**（本次新引入）。R8 是证伪行，不落桶。

| # | 缺陷（可观测） | 编码/配置 | 归属 | 证据 file:line |
|---|---|---|---|---|
| R1 | A 条带恐龙在 B/C/D 视图**残留**（persona.2 上 ADinoTick 一旦取消隐藏就再没人隐藏它） | 配置/逻辑 | **回滚/未回移**（`d2d47c7` 修；p2 tag 从未包含，板上 e5b2139 曾有） | persona.2 `ApplyViewLayout` 只有 `if (is_a …) move_foreground(dino_root_)`（`git show v2.5.3-persona.2:<board.cc>` 1420-1422）；修复后 `main:1440-1446` |
| R2 | A 视图中文标题（状态/内存/帧）不显示 | 配置 | **回滚/未回移**（`175056b` 修） | p2:1130（`kAMetrics`）、p2:1136（`small_font`）→ main:1146/1152（`font`）；`small_font = &lv_font_montserrat_14` main:925 |
| R3 | D 游戏视图被更高层对象盖住 | 配置（z-order） | **回滚/未回移**（`0a43f23` 修） | 修复只加 `lv_obj_move_foreground(game_view_)`：main:1435、main:1517；**触发它的具体遮挡物静态不可定位**（见 §3.1(c) 注） |
| R4 | D 视图恐龙/仙人掌**悬空 8~9px** | 配置 | **persona.2 自身且 persona.3 未修**（配置三版本逐字节相同） | main:1230（ground y=127）、main:1240（dino y=80）、main:1245（cactus y=92）；`chrome_dino_sprites.h:360-364`（ground ink 从第 6 行开始）；算式 §5.2 |
| R5 | B1 顶栏「未静音」文本不可点 | 配置 | **回滚/未回移**（p2 从未有过，板上 e5b2139 曾有） | `6a6697b`（main:994 加 `LV_OBJ_FLAG_CLICKABLE` + `MuteButtonCb`）、`e5b2139`（main:995 加 `lv_obj_set_ext_click_area(mute_text_, 18)`） |
| R6 | 幽灵点自锁 → 全屏点击失效（含静音）；**间歇复现，T1 本次会话未复现**（`reason=stale`/`ghost-release`/`ghost lock` 均 0 条） | 驱动/策略 | **persona.2 自身且 persona.3 未修**（D2 策略 `68f0f06` 在 p2 与 p3 内；修复 `64d13ba` 只在 main） | `git merge-base --is-ancestor 68f0f06 v2.5.3-persona.2` → 在；persona.2 只有 `reason="stale"` 保持 pressed（p2:2901-2912），无 force-release；`main:2841`（`kPointStaleForceMs=2500`）、`main:2947`/`2964-2985`（`stale_too_long` → `ghost-release` + `lv_indev_wait_release`，分支体首末行）为 D3 |
| R7 | unmute 后唤醒词不恢复 | 配置（状态机条件） | **回滚/未回移**（`e6b7c1b` 修） | `e6b7c1b`：`application.cc` 去掉 `state == kDeviceStateIdle` 前提 |
| R8 | 「恐龙显示成色块/花屏」类 | **编码** | **不成立**（编码假设，证伪；不落桶） | §4.1/§4.2：9/9 sprite 自洽；A8 语义完整 |

**新问题：无** —— 本次全部缺陷都落在「回滚/未回移」与「persona.2 自身且 persona.3 未修」两桶；R8 只是编码假设的证伪行。

**对 9哥 判读的回应**：「ABCD 四视图问题主要是谷歌小恐龙的**配置**问题」——**代码层面支持这个判断**，但要修正两点：
- 配置问题里**最确定**的是 R4（悬空 9px）与 R1（A 条带越界残留）；`scale 186/210`、`cactus x=480`、`GameTick 25ms` 这三项经核算**没有问题**（不是百分比误用、不是屏外死摆）。
- **这些配置值在 persona.2 / persona.3 / main 三个版本里逐字节相同**（`git diff v2.5.3-persona.2 v2.5.3-persona.3 -- <board.cc>` 的 38 行内不含 1180-1260 区域；`GameTick`/`ADinoTick` 除 `0a43f23` 加的一行外相同）→ **persona.3 并没有修复恐龙配置**。所以「四视图问题**全部由回滚造成**」不成立——R4（悬空/裁切）在三版本同款、属 persona.2 自身；而 R1/R2/R3 确属回滚/未回移（见 §6）。

---

## 7. 风险结论（重做 persona.3 UI 修复到 persona.2）

**Q1：必须捎带 `64d13ba`（D3 触摸）吗？**
**A：编译/合并上 = 不必须；功能上 = 若板上复现"点击全失效"，则必须有，但应作为独立的一次 cherry-pick。**

理由：
- 三个 UI commit 与 `TouchPointFilter` 无交集；`0a43f23` 需要 `d2d47c7` 先上（hunk 上下文），与 64d13ba 无关。
- `64d13ba` 的 5 个 hunk 上下文在 persona.2 中 **5/5 命中** → 可独立 cherry-pick 到 persona.2（其目标函数自 persona.2 起未被其它 commit 改过）。
- 功能耦合是"上游"的，但**有前提**：D3 之前，静止点会 `reason="stale"` 永远保持 LVGL pressed（p2:2901-2912 + `s_forced_releases` 恒为 0：p2:2784 定义、p2:3002 打印）；**只有碰上 21:47 那种持续 stale 的幽灵点**（HANDOFF:32-40）才会自锁、CLICKED 完全不产生。正常点按在 persona.2 上**确实产生 CLICKED**（T1 采集 15 次，见 §10）——一旦落入自锁形态，`ScreenClickCb` 的新路由逻辑与 `mute_text_` 的 CLICKABLE 才全都无从触发。

**Q2：会改动 mute 语义吗？**
**A：三条 UI commit = 不会。`e6b7c1b` = 会（且是本次唯一改动 mute 语义的提交），不要与 UI 混提。**

- `d2d47c7`/`175056b`/`0a43f23`：只碰 `ScreenClickCb`、`ApplyViewLayout`、`HandleTap`、A 标题字体、`move_foreground`。`MuteButtonCb`/`HandleMuteStateChanged`/`ToggleMute` 一字未动。
- `6a6697b`/`e5b2139`：**新增**一个静音入口（顶栏文本 +18px 热区），不改静音状态机，属"增强"而非"改语义"。
- `e6b7c1b`：把"仅在 idle 恢复唤醒词"改成"任何状态都恢复"——这是**行为语义变更**，需要独立评审（它会影响 speaking/listening 时 unmute 的唤醒并发行为）。

**Q3：还有别的副作用吗？**
- `d2d47c7` 的 `HandleTap` 改动引入了对 `SsidManager` 的依赖；persona.2 的 `main/idf_component.yml:27` 已含 `78/esp-wifi-connect: ~3.3.1`，`managed_components` 目录共享 → 能编过。**但**该目录不进 git，若 CI 用干净环境重拉，版本可能与现场不同（`GetSsidList()` 自 3.3.x 起存在，风险低）。
- `d2d47c7` 的 `ScreenClickCb` 改动会改变**所有**非 clickable 子控件上的点按行为（现在会穿透到 talk toggle）。这在 A/B/C/D 全视图生效，属预期修复，但需在真机上确认"点日志文字不会误触发对话"——这是 reviewer 无法静态覆盖的部分。

---

## 8. 建议的重做顺序（供 T3/后续任务参考，本卡不改代码）

```
① git cherry-pick d2d47c7        # A 条带越界残留 + 点按路由 + 配网误触（persona.2 可独立应用）
② git cherry-pick 175056b        # A 视图 CJK 标题
③ git cherry-pick 0a43f23        # D 视图层序（依赖 ①）
   —— 以上三步后板级文件 blob 应为 42fe3283（= persona.3 原样）
④ （独立决策）git cherry-pick 6a6697b e5b2139   # B1 静音入口，需 ⑥ 才有效
⑤ （独立决策）git cherry-pick e6b7c1b           # 唤醒词恢复，改 mute 语义
⑥ （独立决策，若真机点击仍失效）git cherry-pick 64d13ba   # D3，5/5 hunk 可独立应用
⑦ 恐龙配置修复（R4/S2）需新写补丁：ground/精灵的语义 y 应按"墨迹行"校正，
   建议在 board.cc 内加常量而不是改资源（资源本身是对的）
```

---

## 9. 交接块

- **目标**：给出「每个已知缺陷 → 编码/配置 → 归属（`回滚/未回移` / `persona.2 自身且 persona.3 未修` / `新问题`）」的代码级证据表，并核实恐龙资源编码。
- **已定决策**：
  - 只读，以 tag 为基线（`git show`），未 checkout/commit。
  - `15e05fa` 是文档提交，不计入代码差异。
  - D3（`64d13ba`）不在板上，视为**不可用基线**；其可用性已单独验证（5/5 hunk 可独立应用到 persona.2）。
  - 编码结论以「LVGL 9.5 源码 + sdkconfig」为准，不以头文件注释为准（注释与实现不一致处已注明）。
- **涉及文件**：
  - `05_Tools/xiaozhi-esp32/main/boards/chd/chd-esp32s3-box/chd_esp32s3_box_board.cc`
  - `05_Tools/xiaozhi-esp32/main/ui/chrome_dino_sprites.h`
  - `05_Tools/xiaozhi-esp32/main/application.cc`（仅 `e6b7c1b`）
- **下一步**：T3 汇总（把 §6 归因表与 §7 风险结论并入总报告/决策）。
- **验收命令**（评审者抽查用）：
  ```sh
  git log --oneline v2.5.3-persona.2..main                    # 8 条
  git show d2d47c7 -- main/boards/chd/chd-esp32s3-box/chd_esp32s3_box_board.cc
  git show 175056b -- 同上 ; git show 0a43f23 -- 同上 ; git show e6b7c1b -- main/application.cc
  git show v2.5.3-persona.2:<board.cc> | sed -n '1180,1245p'  # 配置常量（与 main 1196-1260 同值）
  git rev-parse v2.5.3-persona.2:<board.cc> 15e05fa:<board.cc> # 同为 edc3037f…
  sed -n '1,412p' main/ui/chrome_dino_sprites.h | grep -n 'header = \|data_size'
  ```
- **未做/不能证明**：真机观感；§3.1(c) 的具体遮挡物（静态不可定位）；persona.2 构建时 `managed_components` 是否与当前工作树完全同版本（该目录不进 git）。

---

## 10. 附：实际执行过的验证命令与输出摘要

```sh
# 1) 拓扑与范围
$ git log --oneline v2.5.3-persona.2..main
64d13ba fix(touch): release and lock a stale point instead of holding LVGL pressed
e5b2139 fix(ui): enlarge mute status tap target
6a6697b fix(ui): make B1 mute status text clickable
e6b7c1b fix(audio): restore wake word after unmute in any state
0a43f23 fix(ui): raise D game view above B1 layers
175056b fix(ui): use CJK font for A-view metric titles
d2d47c7 fix(ui): hide dino outside A, guard config tap, route label taps
15e05fa docs: add bilingual persona fork homepage
$ git merge-base --is-ancestor v2.5.3-persona.3 main && echo yes    # → yes（persona.3 是 main 祖先）

# 2) 逐 commit 的文件面
$ git show --stat --format='' 15e05fa   # 仅 README.md / README_UPSTREAM.md
$ git show --stat --format='' d2d47c7   # board.cc +22/−5
$ git show --stat --format='' 175056b   # board.cc +1/−1
$ git show --stat --format='' 0a43f23   # board.cc +7/−2
$ git show --stat --format='' e6b7c1b   # main/application.cc +4/−3
$ git show --stat --format='' 6a6697b   # board.cc +4
$ git show --stat --format='' e5b2139   # board.cc +1
$ git show --stat --format='' 64d13ba   # board.cc +65/−7

# 3) persona.2 与 d2d47c7 的父提交是否同一份板级文件
$ git diff --stat v2.5.3-persona.2 15e05fa -- main/boards/chd/.../chd_esp32s3_box_board.cc
（空 → 逐字节相同）

# 4) persona.2→persona.3 的全量代码差异只有 7 个 hunk / 38 行
$ git diff --stat v2.5.3-persona.2 v2.5.3-persona.3
 README.md | 258 +++--- ; README_UPSTREAM.md | 174 +++ ; chd_esp32s3_box_board.cc | 38 ++-
$ git diff -U0 v2.5.3-persona.2 v2.5.3-persona.3 -- <board.cc> | grep '^@@'
@@ -12,0 +13 @@ @@ -657 +658,11 @@ @@ -1136 +1147 @@ @@ -1417,2 +1428,6 @@
@@ -1420,2 +1435,7 @@ @@ -1491,0 +1512 @@ @@ -3268,2 +3289,3 @@

# 5) 恐龙/游戏配置与两个 Tick 在三个版本上的等价性
$ diff <(git show v2.5.3-persona.2:<board.cc> | sed -n '/dino_root_ = lv_obj_create/,/game_timer_ = lv_timer_create/p') \
       <(git show v2.5.3-persona.3:<board.cc> | sed -n '/dino_root_ = lv_obj_create/,/game_timer_ = lv_timer_create/p')   # → 空（相同）
$ diff <GameTick p2> <GameTick p3>     # → 仅多一行 lv_obj_move_foreground(self->game_view_);
$ diff <ADinoTick p2> <ADinoTick p3>   # → 空

# 6) 资源自洽性（脚本核账，见 §4.1 表）
$ python3 …   # declared 与 initializer 个数逐数组比对 → 9/9 match=True；distinct values = {0,255}

# 7) LVGL 语义抽查
$ grep -n 'LV_IMAGE_HEADER_MAGIC' managed_components/lvgl__lvgl/src/libs/bin_decoder/lv_bin_decoder.c
$ sed -n '240,250p;486,491p' managed_components/lvgl__lvgl/src/draw/sw/lv_draw_sw_img.c
$ sed -n '53p;56p' managed_components/lvgl__lvgl/src/draw/lv_draw_image.c
$ sed -n '690p' managed_components/lvgl__lvgl/src/widgets/image/lv_image.c      # pivot 默认 50%/50%
$ grep -n 'CONFIG_LV_DRAW_SW_SUPPORT_A8\|CONFIG_LV_COLOR_DEPTH_16' sdkconfig    # 均 =y

# 8) D3 是否在板上基线
$ git merge-base --is-ancestor 68f0f06 v2.5.3-persona.2 && echo yes   # D2 策略在
$ git merge-base --is-ancestor 64d13ba v2.5.3-persona.2 || echo no    # D3 不在

# 9) 串口证据 —— 只引 T1 的冻结快照，不引活文件的瞬时尾巴
#    快照：docs/tasks/abcd-views/evidence/serial-persona2-2210.final.log
#    采集区间 22:06:57–22:21:05，3781 行 / 256134 bytes
#    （见 01-repro-evidence.md 的「采集记录」与「文件清单」两节；该文档仍在增补，不锁行号）
#    sha256 由 T1 收尾冻结时给出，登记在 01-repro-evidence.md；行号以该 final 快照为准
$ grep 'display=480x320' <final.log>                  # 分辨率 480x320 MATCH
$ grep -n 'tap -> ToggleChatState' <final.log>        # 15 条，行号区间 1204..2973
$ grep -c 'reason=stale\|ghost-release\|ghost lock' <final.log>   # → 0
```

> **事实更正（reviewer-b 复核意见，2026-10-29）**：本文初稿在 22:10 引用的是**仍在追加的活文件**（当时 710 行 / 134 s，`raw_points` 恒 0），那个瞬时尾巴**不能**支撑任何结论，初稿据此写的「无法证明或否证 R6」已作废。
> 按 T1 收尾后的完整采集（`serial-persona2-2210.final.log`，3781 行 / 256134 bytes，22:06:57–22:21:05；本文核对时的停采版 md5 `668d8be6…`，正式 sha256 见 `01-repro-evidence.md`）：
> - persona.2 上**产生了 CLICKED**：`CHD_UI: tap -> ToggleChatState` **15** 条（第 1204 行起，末条第 2973 行）。口径澄清：review 时的 **16** 是 `grep 'tap'` 的**宽匹配**——15 条 `tap -> ToggleChatState` + 1 条 `CHD_UI: tap ignored: 170 ms after a swipe`（final:3009）；精确匹配为 **15** 条（2472 行中间态是 14 条），且相邻 `indev state: pressed=1/0` 正常成对；其中 **11/15** 条的后续 1~3 行是 `mute: dialogue/wake path blocked while muted`（当时设备处于 muted；另 4 条不是），故只作多数观察、不作全量因果；
> - `state=PRESSED` 出现 56 次（正常按压/心跳），而 `reason=stale`、`ghost-release`、`ghost lock` 均为 **0** 条。
> ⇒ **R6（幽灵点自锁）是间歇复现，本次会话未复现**；不能把它写成「板上必然如此」。R6 的代码依据仍为 `68f0f06` 的 D2 策略（静止点保持 pressed）+ `64d13ba` 的 D3 修复（2.5 s 强制释放 + ghost-lock）+ HANDOFF 21:47 的**另一次**串口实证（那次出现 `reason=stale → HOLD`、heartbeat 长期 `pressed=1 act=0`）。


---

## 证据可访问性（隐私清理，2026-10-30）

原始串口日志 `docs/tasks/abcd-views/evidence/serial-persona2-2210.final.log` 已改为**本地未跟踪**（`.gitignore` 规则 `docs/tasks/**/serial-*.log`），仓库内不再包含；本文引用的行号区间（如 `1204..2973`）与结论不变，复算需在本机同一份本地文件上执行。
