# UI v2 字体规格：MiSans + JetBrains Mono（bpp=4，≤250 KiB）

- 日期：2026-10-28
- 关联：`docs/fonts/LICENSE-notes.md`（许可）、`docs/face/ui-v2/`（样张）、`scripts/fonts/`（生成脚本）
- 结论：6 个 `lv_font_conv` 位图字体，合计 **240,337 B ≈ 234.7 KiB（估算）**，硬上限 250 KiB，超限脚本直接失败。
- **字体二进制不入 git**；生成物在 `scripts/fonts/build/fonts/`（已 `.gitignore`）。

## 1. 字体与字号

| 用途 | 字体 | 字号 | 行高 | 生成文件 | 字形数 | 备注 |
|---|---|---:|---:|---|---:|---|
| 标题 / 房间名 | MiSans | **32** | 40 | `misans_32_4.bin` | 36 | 房间名 + 状态词（小集） |
| 正文 | MiSans | **20** | 26 | `misans_20_4.bin` | 823 | 800 字 + 23 中文标点 |
| 明细 | MiSans | **14** | 20 | `misans_14_4.bin` | 523 | 500 字（800 的前缀）+ 标点 |
| 明细数字 | JetBrains Mono | 14 | 20 | `jetbrains_mono_14_4.bin` | 97 | 99 码点 / **97 唯一字形**（`/`、`%` 与 ASCII 重复） |
| 正文数字 | JetBrains Mono | 20 | 26 | `jetbrains_mono_20_4.bin` | 97 | 同上 |
| 主数值 | JetBrains Mono | **44** | 52 | `jetbrains_mono_44_4.bin` | 16 | `0-9 . ° % / + -` |

- 全部 **bpp = 4**，`lv_font_conv@1.5.3`，`--format bin --no-compress`（LVGL 9 binfont）。
- 中文标点固定 23 个：`，。！？、；：“”‘’（）《》〈〉【】…—·～`。
- 拉丁/数字**不重复进 MiSans**：混排文本用 MiSans 做主字体、Mono 做 fallback，避免每个尺寸多塞 ~95 个 ASCII 字形。

## 2. 子集范围

| 集合 | 内容 | 生成方式 |
|---|---|---|
| 800 字 | 高频口语 + UI 词（房间/状态/音量/网络/时间/天气/提醒/语音助手…），按人工排序打头，不足时用项目文档高频字补足 | `scripts/fonts/make_charset.py` |
| 500 字 | **800 的前 500 个**（严格前缀，保证小的集合总被大的覆盖） | 同上 |
| 36 字 | `房间客厅卧室书房厨房阳台玄关儿童洗手间主次在听想说话空闲待机播报确认取消加音量` | 同上 |
| ASCII 97 | `0x20–0x7E`（95）+ `°` `·` = **99 码点 / 97 唯一字形**（`/`、`%` 已在 ASCII 内，`make_charset.py` 去重） | 同上 |
| 数字 16 | `0123456789.°%/+-`（44px 主数值专用） | `build_fonts.sh` 内联 |

- 子集**不含**生僻字、繁体、日文假名、emoji；缺失走 §5 回退。
- **CURATED 去重后是 447 个 CJK**（< 500），所以 448–800 位由 `docs/**/*.md` 语料按频次参与排序；
  500/800 集的**尾部由文档语料决定**——`docs/` 内容变化会改变集合，只有同一台机器、同一份语料才字节级一致。
- 排序规则：先 CURATED（人工顺序），再接文档字频（**频次降序、同频按码位升序**），最后取前 800；500 集是 800 的严格前缀。

## 3. 体积预算（含推算过程）

### 3.1 实测锚点（本机固件仓已有 binfont，直接量）

| 文件 | 字节 | 字形数 | B/字形 |
|---|---:|---:|---:|
| `espressif2022__esp_emote_assets/font/font_puhui_common_20_4.bin` | 1,240,332 | 6,845 | **181.2** |
| 同上 `_16_4.bin` | 863,960 | 6,845 | 126.2 |
| 同上 `_30_4.bin` | 2,499,568 | 6,845 | 365.2 |
| `78__xiaozhi-fonts/cbin/font_noto_sans_common_20_4.bin` | 1,287,460 | 6,845 | 188.1 |

> 这些文件都是 **bpp=4 + 6,845 字**（`78__xiaozhi-fonts/charsets/common.json`: `count=6845`），可直接当标尺。

### 3.2 推算模型

```
B(s) ≈ 16 + (181.2 - 16) × (s / 20)²      # CJK 全角，含每字形 ~16 B 描述符
     → 14px ≈ 96.9 B/字形 ; 32px ≈ 438.7 B/字形
等宽 ASCII 按 0.6 倍宽折算：
     14px ≈ 58 B/字形（0.6×96.9，经验值）; 20px ≈ 115 B/字形 ; 44px ≈ 496 B/字形（沿用上一轮核对值）
```

### 3.3 预算表

| 字体 | 字形数 | 估算字节 | KiB | 任务卡口径 |
|---|---:|---:|---:|---|
| `misans_20_4` | 823 | 149,128 | **145.6** | 20px 中文 120–160 ✅ |
| `misans_14_4` | 523 | 50,679 | **49.5** | 14px 60–80（略低，可接受） |
| `misans_32_4` | 36 | 15,793 | **15.4** | 任务卡未列，标题必需 |
| `jetbrains_mono_14_4` | 97 | 5,636 | 5.5 | — |
| `jetbrains_mono_20_4` | 97 | 11,165 | 10.9 | mono 20–30 ✅（三档合计 24.2 KiB） |
| `jetbrains_mono_44_4` | 16 | 7,936 | 7.8 | 主数值 |
| **合计** | **1,592** | **240,337** | **≈234.7** | **≤250 ✅** |

- 估算误差 ±15%（字宽分布、kerning 表、对齐）；`build_fonts.sh` 生成后实测，**>250 KiB 直接 `exit 2`**。
- 若实测超限，按优先级削减：14px 500→400（−9.5 KiB）→ 32px 36→24（−5 KiB）→ 20px 800→700（−18 KiB）。
- 体积上限是**字体总量**；固件 app/ assets 余量见 §6。

## 4. 行高与基线

| 字号 | 行高 | 说明 |
|---:|---:|---|
| 32 | 40 | 标题，单行；房间名 2–4 字 |
| 20 | 26 | 正文/字幕；字幕条单行 48 px 内垂直居中 |
| 14 | 20 | 明细三行，行距 24（视觉行高 = 24） |
| 44 | 52 | 主数值，右对齐，与 20px 标签基线对齐 |

- 全部字体用同一 `line_height` 策略（`lv_font_conv --line-height` 不给则取默认），**以生成后 `lv_font_get_line_height()` 实测为准**，Phase B 在板子上复核一次。

## 5. 未收录字回退

链式 fallback（`lv_font_set_fallback`，LVGL 9）：

```
misans_14_4  → misans_20_4 → font_noto_sans_common_20_4 (assets, 6845 字) → 空白
misans_32_4  → misans_20_4 → font_noto_sans_common_20_4 → 空白
misans_20_4  → font_noto_sans_common_20_4 → 空白
jetbrains_mono_* → （ASCII 全覆盖，不需要回退）
```

> **□ 不是现状**：`sdkconfig:5283` 当前是 `# CONFIG_LV_USE_FONT_PLACEHOLDER is not set`，
> 所以缺字现在渲染成**空白**；要显示 □ 需在 Phase B 打开 `LV_USE_FONT_PLACEHOLDER=y`。

| 场景 | 表现 | 处理 |
|---|---|---|
| 正文出现 800 集外的字 | 用 assets 里现成的 Noto 20px 渲染（**同字号、观感基本一致、flash 零新增**，该字体已随固件发布） | 无需干预 |
| 14px 明细出现 500 集外的字 | 回落 20px；**行距保持样张的 24 px（y184/208/232）不变** | 20px 行盒 26 px 会与相邻行**重叠 2 px**，但重叠落在上下行留白里，**不压字、不裁切**；不改成 26 px 行距 |
| 32px 标题出现 36 集外的字 | 回落 20px（标题变小） | 房间名在设置页改名时限制为常用字；超出则标题降级 |
| 全部回退都失败 | **空白**（当前未开 PLACEHOLDER）；开启 `LV_USE_FONT_PLACEHOLDER=y` 后才显示 □ | 构建期脚本比对 + 真机抽查 |
| emoji | 不在这套字体里；如需要沿用现有 `font_noto_emoji_30_4` 单独 label | 不在本卡范围 |

- **不做**运行期 glyph 动态推送（`78__xiaozhi-fonts` 支持 64 字/64 KiB，但会引入网络与缓存复杂度）；Phase B 如需再评估。

## 6. 放 app 还是 assets

| 方案 | 占用 | 结论 |
|---|---|---|
| 编译进 app（C 数组） | +232 KiB 到 `xiaozhi.bin`（现 2,885,152 B，余 30.12%） | 可行但吃掉 19% 余量 |
| **放 assets（推荐）** | +232 KiB 到 SPIFFS（余 6.31 MiB） | ✅ app 不变，随 assets 打包 |
| 运行期加载 | `lv_binfont_create_from_buffer(ptr, size)`，`ptr` 来自 `Assets::GetAssetData()`（mmap，`main/assets.cc:195-240`） | 与现有 cbin 字体同一套机制 |

- 打包：在 `scripts/spiffs_assets/build.py` 增加 `ui_fonts/` 目录复制（`.bin` 已在 `support_format` 里，`:319`）。
- 内存：binfont 按需解码，单字号常驻 ≤150 KiB PSRAM；四个常用字号全加载 ≈232 KiB，仍 <0.6 MB 预算。

## 7. LVGL 配置要求

| 配置 | 值 | 原因 |
|---|---|---|
| `CONFIG_LV_USE_FONT_PLACEHOLDER` | **现状 n（`sdkconfig:5283` 未开）**；Phase B 建议改 y | 现状缺字为空白（不会崩）；开启后才显示 □ |
| `CONFIG_LV_FONT_FMT_TXT_LARGE` | 视生成结果 | 单字体字形数 <1k，通常不需要 |
| binfont + mmap | — | `LV_BIN_DECODER_RAM_LOAD` 已关，正好直读 flash |

## 8. 生成与验收

```sh
# 1) 字符集（无需字体文件）
python3 scripts/fonts/make_charset.py
#    charset-800: 800 CJK + 23 punct
#    charset-500: 500 CJK + 23 punct  (prefix of 800)
#    charset-title: 36 CJK
#    charset-mono: 99 glyphs

# 2) 字体（需先放 MiSans/JetBrains 源文件，见 scripts/fonts/README.md）
FONT_DIR=scripts/fonts/fonts-src ./scripts/fonts/build_fonts.sh
#    末行打印 total: <bytes> KiB，>250 KiB 则 exit 2

# 3) 样张（占位字体，可随时重跑）
python3 scripts/fonts/render_ui_v2.py
```

验收口径：
1. 6 个 `.bin` 合计 ≤250 KiB（脚本硬校验）。
2. `charset-800.txt` 恰好 800 个 CJK + 23 标点，且 500 集是它的前缀。
3. 板子上每个字号至少 1 张截图（Phase B）：32/20/14/44 各一行中文 + 数字 + 数字/中文混排。
4. 缺字回退：故意在字幕里塞一个 800 集外的字，确认落到 Noto 20px、不是空白（开启 PLACEHOLDER 后才是 □）。

## 9. 未定项

- MiSans 具体字重与版本（建议 Regular 400；官方下载后记录版本号与文件 hash）。
- JetBrains Mono 是否声明 Reserved Font Name（影响子集文件命名）。
- 官方许可页截图（见 `LICENSE-notes.md` §6）。
- 14px 是否值得从 500 扩到 800（+18 KiB，逼近预算上限）。
- 14px 明细在 480×320 上偏小：Phase B 需真机复核可读性；必要时升到 16px，行距 24→28 并重算预算（约 +18 KiB，仍在 250 KiB 内）。
