# 形象资产管线调研：三条路能否在 CHD ESP32-S3-BOX 上跑

- 日期：2026-10-28
- 范围：只读调研 + 本文档。不改固件、不做形象、不刷机、不 commit。
- 前置：`docs/persona-research.md` §7（三队汇总）、`docs/face-ui-research.md`（路线 A/B/C）。
- 前提：项目里**没有「已决定用真人」的记录**（`docs/persona-research.md:282-289`）；9哥 原话是「真人形象……哪怕动漫形象也行」（`docs/face-ui-research.md:4`），**日漫是可接受降级，不是已定档位**；真人程度仍待确认（`docs/persona-research.md:284-285`）。M7 Step 2 不碰选型。
- 本文回答：在 480×320 / 8 MB PSRAM / 16 MB flash / 无 GPU 的板上，`.eaf`、Live2D、分层贴片三条资产管线各自能不能跑、多少 fps、占多少 flash/RAM、许可边界，并给一张后续实现卡。

## 0. 结论表

| 路线 | 本板可跑 | fps（脸区 480×228） | flash（8 表情） | RAM | 许可 | 判断 |
|---|---|---|---|---|---|---|
| 1. `.eaf`（esp_emote / EAF） | ✅ 已验证（官方 320_240 变体可编译） | **15–20**（SPI 上限 22.8） | 3.3–5.0 MB（按 480×228 重制） | ~110–150 KB | manifest 声明 Apache-2.0；未附 LICENSE 文件、素材无专项授权 | 可用，观感受源素材限制 |
| 2. Live2D（Cubism 运行时） | ❌ 0（无可用运行时；无 Xtensa 版、无 GPU） | **0** | — | 纹理解码 4.2–16.8 MB | 商用需签约/署名，烘帧灰区 | 只能当离线作者工具 |
| 3. 分层底图 + 贴片 | ✅ 纯 LVGL，无新组件 | **30（目标/上限，未实测）** | **≤0.3 MB（预算）** | <0.6 MB PSRAM（draw buffer 在内部 SRAM） | 自有/委托最干净 | **推荐管线** |

**一句话**：全屏刷新的物理上限是 16.3 fps（§1.3），所以「整屏动画」类管线在本板都被带宽锁死；在**自有/可商用素材**前提下，只有分层贴片能同时做到「有反应 + 省 flash + 许可干净」。

## 1. 板子与余量（数字来源：build 产物 / 分区表 / sdkconfig）

### 1.1 硬件与显示

| 项 | 值 | 来源 |
|---|---|---|
| MCU / 屏 | ESP32-S3-WROOM-1（八线 PSRAM）；**面板 ST7796、驱动 esp_lcd_new_panel_st7789** | `config.h:86`、`chd_esp32s3_box_board.cc:1933-1934` |
| 分辨率 | 480×320（当前横屏），16 bpp | `config.h:96-101` |
| SPI 时钟 | **40 MHz** | `chd_esp32s3_box_board.cc:1923` |
| CPU | 240 MHz 双核 | `sdkconfig`: `CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ_240=y` |
| PSRAM | 8 MB octal @ 80 MHz | `sdkconfig`: `CONFIG_SPIRAM_MODE_OCT=y`、`CONFIG_SPIRAM_SPEED_80M=y` |
| LVGL 缓冲 | 480×20 px ×2 B = **19,200 B**，单缓冲、DMA 条带，**内部 SRAM（不计入 PSRAM）** | `main/display/lcd_display.cc:173-181` |
| LVGL 其他内存 | heap 1 MB（`CONFIG_LV_MEM_SIZE_KILOBYTES=1024`）；image cache 2 MB PSRAM | `sdkconfig`；`lcd_display.cc:155-160` |

### 1.2 flash 余量（实测文件大小）

| 分区 | 容量 | 当前占用 | 余量 |
|---|---:|---:|---:|
| `ota_0`（app） | 4,128,768 B | `build/xiaozhi.bin` = 2,872,128 B | **1,256,640 B ≈ 1.20 MiB** |
| `assets`（SPIFFS） | 8,388,608 B | `build/generated_assets.bin` = 1,775,581 B | **6,613,027 B ≈ 6.31 MiB** |

- **build 目录消歧**：`build/` 是当前 CHD 产物（`build/config/sdkconfig.h`：`CONFIG_BOARD_TYPE_CHD_ESP32S3_BOX=y`，xiaozhi.bin 2026-10-28 13:06）；`build-chd/` 是 10-27 的另一份产物（其 sdkconfig.h 为 `CONFIG_BOARD_TYPE_BREAD_COMPACT_WIFI`），**不作为本文数字依据**。
- 分区表：`partitions/v2/16m.csv:6-8`；二进制解析 `build/partition_table/partition-table.bin` 一致。
- 已用的 1.78 MB 是字体 ＋ 唤醒模型 ＋ Noto 彩色 emoji PNG（`strings build/generated_assets.bin` 可见 `font_noto_sans_common_20_4.bin`、`srmodels.bin`、`happy.png`），**不是 EAF**；唤醒/字体不能删，所以可用上限就是 6.31 MiB。
- PSRAM 余量：仓库内**没有真机 free PSRAM 记录（未实测）**。按 8 MB 总量、2 MB image cache、1 MB LVGL heap 估算，可安全支配 ≥4 MB。**EAF / 分层贴片 <1 MB，PSRAM 不是瓶颈；Live2D 纹理解码 4.2–16.8 MB，超 8 MB PSRAM（见 §3）。**

**当前渲染是什么（本机源码核实）**：`sdkconfig` 里 `CONFIG_USE_EMOTE_MESSAGE_STYLE` **未开**，CHD 板当前走 `CustomLcdDisplay` ＋ `lvgl_kawaii_face`（480×228 脸 ＋ 底部字幕，`chd_esp32s3_box_board.cc:366-374`）；`ChdEmoteDisplay`（esp_emote `.eaf`）是同一 board 的编译期变体（`chd_esp32s3_box_board.cc:1178-1236, 1958-1962`）。下文把 `.eaf` 当「已可编译的备选管线」，把 kawaii 当「当前回退基线」。

### 1.3 带宽推导（决定 fps 的硬约束）

```
SPI 有效吞吐 = 40 MHz × 1 bit/clk ÷ 8 = 5.0 MB/s
全屏 480×320×2 B = 307,200 B → 61.4 ms/帧 → 16.3 fps（不含命令开销，实际 ≤15）
脸区 480×228×2 B = 218,880 B → 43.8 ms/帧 → 22.8 fps
眼片 120×60：RGB565 14,400 B → 2.9 ms；RGB565A8 21,600 B → 4.3 ms
嘴片  80×50：RGB565  8,000 B → 1.6 ms；RGB565A8 12,000 B → 2.4 ms
```

结论：**任何「每帧重刷整屏」的方案都到不了 20 fps**；只有脏矩形局部刷新（分层贴片/眨眼/口型）才有机会到 30 fps。这是物理约束，不是实现取舍。

## 2. 路线 1：`.eaf`（现有 esp_emote 资产管线）

- **素材/工具链**：`espressif2022/esp_emote_expression ^1.0.2`（`main/idf_component.yml:77`）＋ `esp_emote_assets`＋`scripts/spiffs_assets/build.py`。EAF 由 GIF/PNG 序列转（社区链路 `esp32-gif.espressif.com`）；`320_240/emote.json` 把 **20 个逻辑表情映射到 9 个 distinct src**（磁盘共 10 支 EAF，`listen.eaf` 未被引用），默认 20 fps。
- **分辨率适配**：官方只有 1024_600 / 360_360 / **320_240** 三套 layout，没有 480×320；`320_240/layout.json` 的 `eye_anim` 是 `x=10,y=30` 像素硬编码，宽屏上脸会偏左上（`docs/face-ui-research.md:1-35` 第 9 条）。`emoji_large` 是 **125×160（25:32）竖构图**：按脸区高 228 等比只能显示 **178×228**（放大 1.43×，横向空 302 px），要铺满 480 宽需 3.84× → 高 614 px 超出脸区，必须裁切或重制 480×228 的 EAF。要走通必须自写 `layout.json`。
- **flash 计算**：磁盘 10 支官方 EAF = **9 支 125×160 + `listen.eaf` 100×46**（实测头部均 `block_height=32`），共 1,182,273 B；B/px 换算用 `Happy.eaf`（81,645 B / 43 帧 / 125×160 = 20,000 px）→ **1,899 B/帧 = 0.095 B/px/帧**。换算 480×228（109,440 px）≈ **10.4 KB/帧**；2 s@20 fps（40 帧）≈ 0.42 MB，3 s ≈ 0.62 MB。
  - 8 表情：**3.3–5.0 MB ✓**（<6.31 MiB）；21 表情：**8.7–13 MB ✗**。误差 ±50%，必须真做一支 EAF 实测后再定量。
- **fps/CPU**：SPI 上限 22.8 fps，组件默认 20 fps，官方实测 20 fps（`docs/persona-research.md:264-280`）→ 预计 **15–20 fps**；EAF 调色板展开为 RGB565 的 CPU 占用估 2–5 ms/10 万 px（估算）。
- **RAM**：EAF 按 `block_height=32` 分块解码（`gfx_anim.c:375-381`、`gfx_eaf_dec.c` 头部实测）：缩放后 480×32 RGB565 = **30,720 B/块**，双缓冲 61,440 B；显示条带取组件示例 `buf_pixels = h_res*16`（README）= 480×16×2 = 15,360 B；加调色板/块表/工作区 ≈ **110–150 KB，仍 <1 MB**。
- **许可**：manifest 声明 **Apache-2.0**，但组件目录**未附 LICENSE 文件**，官方 emoji 素材也没有专项授权说明（`persona-research.md:297`）。代码可商用，但需保留 NOTICE/署名；**素材能否随产品分发必须向 Espressif 书面确认**。
- **集成代价**：A) `esp_emote_expression` 接管 panel + flush（`chd_esp32s3_box_board.cc:1958-1962`），字幕条/状态栏消失，且只有编译开关 `CONFIG_USE_EMOTE_MESSAGE_STYLE`；B) `esp_lv_eaf_player` 留在 LVGL 内播 EAF，保留字幕，约 3 人日。
- **失败模式**：放大糊、8-bit 调色板色带、layout 硬编码、接管整屏丢字幕、帧数不足时循环动作假、IDF 6.1 未验证。

## 3. 路线 2：Live2D

- **素材/工具链**：Cubism Editor 建模 → `.moc3`；运行时是 Cubism SDK for Native，**Core 为闭源预编译库**，不提供源码。
- **分辨率适配**：Editor 侧任意分辨率；但运行时依赖 GPU 渲染。
- **能否跑**：官方平台表只有 Windows / macOS / Linux / Android / iOS / HarmonyOS，Native 仅 **64-bit**，渲染引擎 OpenGL / Metal / DirectX / Vulkan（[平台支持](https://docs.live2d.com/en/cubism-sdk-manual/platform/)）。**没有 Xtensa/FreeRTOS 版本，S3 也没有 GPU → 本板无可用运行时（0 fps）。**
- **内存估算**：`.moc3` 0.1–0.5 MB（估）；一张 2048² RGBA 纹理解码 **16.8 MB > 8 MB PSRAM**；降到 1024² 也要 4.2 MB，而脸区只有 480 px，画质收益被抵消。
- **若强行软件光栅化**（仅上限参考，非可行方案）：109k px × 3–5 层 × alpha blend，按 5–10 Mpx/s 估 50–100 ms/帧 → 10–20 fps；**前提是重写闭源 Core，许可不允许**。
- **许可**：SDK Release License 对**年销 <1000 万日元**免费商用，超出需签约（[Live2D 帮助·授权](https://help.live2d.com/tag/tag_-agreement/)）；官方 sample 模型是 Free Material License：**必须署名**、**禁止再分发原始素材**（[Free Material License Agreement §4.1.1](https://www.live2d.com/eula/live2d-free-material-license-agreement_en.html)）、部分联动角色非商用（[sample terms](https://www.live2d.com/eula/live2d-sample-model-terms_en.html)）；把渲染帧烘进商用硬件属衍生物，灰区（`persona-research.md:307`）。
- **集成代价**：本板无直接集成；只能**离线**把 Live2D 渲成 PNG 序列，再转 EAF/分层，或走服务器推帧。
- **失败模式**：Core 无法移植 → 授权链断裂 → 纹理超 PSRAM → 无 GPU 帧率崩。

## 4. 路线 3：分层底图 + 贴片

- **素材/工具链**：一张 480×228 底图 ＋ 眼/嘴/眉/腮红 patch（PNG，RGB565A8），LVGL `lv_image` + 定时器/动画；切图用 Pillow/PS，不需新组件、不改协议。
- **分辨率适配**：1:1 原生 480×228，字幕条 464×84 保持（板级已按 `y 0..228` 脸 + 底部字幕布局，`chd_esp32s3_box_board.cc:366-374`），无缩放损失。
- **flash 计算**：底图 JPEG q80 480×228 ≈ **10–24 KB**（按 `face-ui-research.md` 实测 480×320 真人 22.7 KB、扁平 9.5–13.9 KB 折算）。
  - patch 集：眼 4 套 ×21,600 B（120×60 RGB565A8）= 86.4 KB；嘴 4 套 ×12,000 B（80×50 RGB565A8）= 48 KB；眉 3 套 ×6 KB = 18 KB；腮红 1 套 5,400 B → **12 个核心 patch ≈155 KiB**；再加 8 个备用 ≈25–45 KB → **20 个 patch，raw ≈180–200 KB**，PNG 压缩后 ~100–140 KB。
  - **合计 ≈0.2 MB（预算 ≤0.3 MB）**。
- **fps/CPU（计算见 §1.3）**：眼 4.3 ms、嘴 2.4 ms（RGB565A8）、LVGL 合成 1–3 ms；`CONFIG_LV_DEF_REFR_PERIOD=20` → 上限 50 fps。**目标 30 fps（未实测）**；整脸换表情一次性 43.8 ms（≈20 fps 上限），足够。
- **RAM**：日漫档底图解码 218,880 B ＋ patch cache ≤0.3 MB → **<0.6 MB PSRAM**；半写实底图更大，按 ≤0.9 MB 预算；draw buffer 19 KB 在内部 SRAM，不计入。
- **许可**：自有/委托最干净；CC-BY 需署名（如 `Xiael Tia`）；真人照片高风险（见 §5）。
- **集成代价**：纯 LVGL，不接管 panel，字幕/状态栏保留；现有 `SetEmotion()` 已支持 GIF（`main/display/lcd_display.cc:1229-1250`），分层贴片比 GIF 更省带宽（脏矩形 vs 整图刷新）；1–2 人日代码 ＋ 美术工时。
- **失败模式**：接缝/色差、层序（头发要盖眼）、只有位移无转头、美术质量决定上限、RGB565 无 alpha（用 RGB565A8）、JPEG 边缘彩边（patch 用 PNG）。

## 5. 许可与合规边界

| 素材 | 边界 | 结论 |
|---|---|---|
| 日漫差分立绘（CC-BY） | 商用可，需署名；RPG Maker RTP 明文禁止移植；AI-Vtuber 代码 GPL-3.0 不可进闭源固件 | ✅ 可用，署名进 README/关于页 |
| 委托/自有立绘 | 买断合同覆盖复制、修改、商用 | ✅ 最干净 |
| 真人照片 | 图库许可 ≠ 模特授权；CC0 只放弃版权不放弃肖像权；《民法典》1018–1023 ＋ 深度合成规定要求**单独同意**并标识 | ❌ 不建议 |
| Live2D 官方 sample | Free Material License：署名、禁再分发原素材（§4.1.1）、部分角色非商用；烘帧进硬件灰区 | ⚠️ 仅原型 |
| Live2D SDK | 年销 <1000 万日元免费商用，超出签约；Core 闭源 | ⚠️ 商用前先签约 |
| esp_emote 官方素材 | 组件 manifest Apache-2.0，但未附 LICENSE、素材无专项授权 | ⚠️ 商用前书面确认 |

## 6. 「真人程度」三档：对应管线与代价

| 档位 | 管线 | 本板 fps | flash | 额外代价 | 许可 |
|---|---|---|---:|---|---|
| 照片级·预烘 | 480×228 JPEG 帧序列 | **8–10（解码 100–120 ms/帧，估算）** | 6.31 MiB ÷ ≈16 KB/帧 → ~403 帧；按 8–10 fps 播 ≈40–50 s | 拍摄/修图 ＋ 打包链路 | **最高风险** |
| 照片级·推流 | 服务器 JPEG over WS/UDP | **12（目标码率；官方解码 36 fps@480×320，22.7 KB×12≈272 KB/s）** | 0 | 6 人日；当前 WS 数十秒被断 | **最高风险** |
| 半写实 | Blender/VRM 渲 2D → 分层贴片 | 30（目标） | 0.4–0.6 MB | 3D 建模/绑定 5–10 人日（日漫的 2–3×） | 自有/委托，干净 |
| 日漫·分层 | 差分立绘/CC-BY → 分层贴片 | 30（目标） | ≤0.3 MB（预算） | 美术 2–5 人日 | 最干净 |
| 日漫·EAF | 官方/自渲 EAF | 15–20 | 3.3–5.0 MB | 3 人日 ＋ 素材 | 素材需书面确认 |

**实时照片级在这块板上不存在**：分辨率 × 帧率 × SPI 带宽三者互斥，只能预烘短片或服务器推帧；且推流链路当前不稳。

## 7. 推荐

**推荐管线 = 分层底图 + 贴片**（唯一同时满足 **跑得动 + 保留字幕 + 许可可控** 的路线；EAF 也能跑 15–20 fps，但要么整屏接管丢字幕、要么需额外播放器）。**档位待 9哥 定：**

- **若坚持「像人」→ 半写实**（Blender/VRM 渲成 2D 分层）：+5–10 人日，flash 0.4–0.6 MB，30 fps 目标；许可最干净。
- **若预算优先 → 日漫**（差分立绘/CC-BY 分层）：2–5 人日，≤0.3 MB，30 fps 目标。**这是低成本默认，不是已定档位**——真人程度仍未确认（`docs/persona-research.md:284-285`），本卡不替 9哥 拍板。

理由：

1. 只有分层贴片能在 SPI 40 MHz 下把眼/嘴做到 30 fps 目标（§1.3），整脸换表情仍有 ~20 fps 上限。
2. flash ≤0.3 MB、PSRAM <0.6 MB（draw buffer 在内部 SRAM），给字幕/状态栏留足余量；不动 panel、不动协议。
3. 许可链最短：委托或 CC-BY，署名可控；避开真人肖像与 Live2D 商用灰区。
4. 档位可后置：同一套运行时既能吃日漫立绘，也能吃半写实渲染图，换档只换美术资产。
5. Live2D 只当**离线作者工具**；EAF 可作 2–3 个 hero 动画的补充层，不作主线。

若不接受：**替代方案 = EAF（`esp_lv_eaf_player` 变体）**，保留字幕、15–20 fps、3 人日，但官方素材无专项授权、放大糊，需先确认素材范围。

## 8. 后续实现卡（建议新建 task，不实现）

> **目标**：按 9哥 确认的档位（日漫或半写实），在 CHD 480×320 上接入「分层底图 + 贴片」形象，保留 LVGL 字幕条与状态栏，实现 6 状态 + 眨眼 + 口型；眼/嘴局部刷新 ≥25 fps、整脸切换 ≥15 fps（验收目标）。**体积目标分档：代码 flash 增量 ≤0.4 MB；assets 增量：日漫 ≤0.3 MB / 半写实 ≤0.7 MB；30 min 峰值 PSRAM 增量：日漫 ≤0.7 MB / 半写实 ≤0.9 MB。**
>
> **验收标准**：
> 1. 6 个情绪（neutral/happy/sad/angry/thinking/surprised）真机截图各 1 张，与素材稿一致；切换延迟 <100 ms。
> 2. 眨眼 3–6 s 随机、口型跟随 TTS 播放（RMS 或服务端 viseme 二选一），连续 10 min 无卡死。
> 3. 实测帧率：眼/嘴脏矩形 ≥25 fps（LVGL perf monitor 或帧计数），整脸切换 ≥15 fps。
> 4. 代码体积：`idf.py size` 量 `xiaozhi.bin` 增量 ≤0.4 MB；assets 体积在固件仓用 `stat -f%z build/generated_assets.bin` 的前后差值验收——**日漫 ≤0.3 MB / 半写实 ≤0.7 MB**；30 min 运行峰值 PSRAM 增量——**日漫 ≤0.7 MB / 半写实 ≤0.9 MB**，且 free PSRAM 无单调下降。
> 5. 回退开关：一个宏/设置项切回现有 kawaii 脸，切换后功能不回归。
>
> **写范围**：`05_Tools/xiaozhi-esp32/main/boards/chd/chd-esp32s3-box/persona_layered_face.{h,cc}`（新建）、`05_Tools/xiaozhi-esp32/main/boards/chd/chd-esp32s3-box/chd_esp32s3_box_board.cc`（仅集成点）、`05_Tools/xiaozhi-esp32/main/CMakeLists.txt`（源文件）、`05_Tools/xiaozhi-esp32/scripts/spiffs_assets/build.py`（素材打包）、`05_Tools/xiaozhi-esp32/main/boards/chd/chd-esp32s3-box/persona/`（素材）；文档 `01_Code/projects/esp32-voice-entry/docs/` 内新增实现记录。**不碰**协议、音频、`docs/HANDOFF.md`、`docs/ROADMAP.md`、`docs/persona-research.md`。
>
> **依赖**：① **9哥 确认档位（日漫 / 半写实）——阻塞项，方向依赖它；若选照片级则本卡不适用、另开卡**；② 美术素材 + 授权文件/署名文本（阻塞项）；③ 9哥 在场同意刷机；④ 当前 kawaii 可回退；⑤ 固件仓库写权限（`05_Tools/xiaozhi-esp32` 是另一个 git 仓库）。
>
> **风险**：素材许可（CC-BY 署名必须落到产品可见处）；接缝/色差/层序；PSRAM 碎片；SPI 带宽与字幕刷新抢时序；真机验收需在场；固件仓库与本文档仓库分离，commit 分开做。
>
> **不做**：Live2D 运行时、服务器推帧、照片级、改通信协议、改音频链路。

## 9. 来源

- 硬件/分区/构建（未注明仓的路径均在固件仓 `05_Tools/xiaozhi-esp32/` 下）：`docs/face-ui-research.md:6`；`build/flasher_args.json`；`build/partition_table/partition-table.bin`（解析）；`partitions/v2/16m.csv:6-8`；`build/xiaozhi.bin`、`build/generated_assets.bin` 文件大小；`sdkconfig`。
- 显示/SPI/LVGL：`main/boards/chd/chd-esp32s3-box/config.h:86,96-101`；`chd_esp32s3_box_board.cc:1923`、`:1933-1934`、`:366-374`、`:1958-1962`；`main/display/lcd_display.cc:155-181`、`:1229-1250`。
- EAF 资产：`managed_components/espressif2022__esp_emote_assets/emoji_large/*.eaf`（大小实测）、`320_240/emote.json`（20 逻辑名 / 9 distinct src 实测）、`320_240/layout.json`；`main/idf_component.yml:77`；组件 manifest 声明 Apache-2.0（两组件目录均未附 LICENSE 文件）；`docs/persona-research.md:264-315`。
- Live2D：[平台支持](https://docs.live2d.com/en/cubism-sdk-manual/platform/)（2026-09-29 更新）、[license/年销阈值](https://help.live2d.com/tag/tag_-agreement/)、[Free Material License Agreement §4.1.1](https://www.live2d.com/eula/live2d-free-material-license-agreement_en.html)、[sample model terms](https://www.live2d.com/eula/live2d-sample-model-terms_en.html)。
- 真人照片/合规：`docs/persona-research.md:305-311`（民法典 1018–1023、深度合成规定、CC0 不覆盖肖像权）。
