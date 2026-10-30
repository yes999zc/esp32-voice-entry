# 字体许可核对：MiSans + JetBrains Mono

- 日期：2026-10-28
- 范围：只做选型与许可记录。**不下载字体到仓库、不提交字体二进制。**
- 结论：中文 **MiSans**（小米）、拉丁/数字 **JetBrains Mono**（SIL OFL 1.1）；备选 IBM Plex Mono。
- 本文所有"官方原文"以 **引用段落 + 链接** 记录；**截图待补**（见 §6），本机无浏览器，不伪造截图。

## 0. 结论表

| 用途 | 字体 | 许可 | 免费商用 | 允许嵌入固件 | 义务 | 状态 |
|---|---|---|---|---|---|---|
| 中文主字体 | **MiSans**（小米） | MiSans 免费商用许可 | ✅ | ✅ | **必须在软件中注明使用了 MiSans** | ✅ 采用 |
| 拉丁/数字 | **JetBrains Mono** | SIL OFL 1.1 | ✅ | ✅ | 保留版权声明与 OFL 文本；不得单独售卖字体 | ✅ 采用 |
| 拉丁/数字（备选） | IBM Plex Mono | SIL OFL 1.1 | ✅ | ✅ | 同上 | 备选，不启用 |
| 中文（已放弃） | 阿里巴巴普惠体 3.0 | 官方许可页难核 | ？ | ？ | — | ❌ 不采用 |

**为什么放弃普惠体**：官方许可页不好核，第三方站点说法互相矛盾（有的说免费商用、有的限制嵌入/派生），
在没有可引用的官方原文前不冒险。**不是**因为已知它收费。

## 1. MiSans（中文主字体）

- 官方 FAQ：<https://hyperos.mi.com/font/faq>
- 官方字体站：<https://hyperos.mi.com/font>
- 许可结论（据 9哥 2026-10-28 转述的官方 FAQ 口径，**待截图**）：

  > MiSans Global 全部字体全球免费商用，任何平台/商业项目可用；可作嵌入式字体，但软件中需特别注明使用了 MiSans 字体。

- **对本项目的含义**：
  1. 可以作为固件内置字体（子集化、bpp=4、编译/打包进 assets）——**允许嵌入**；
  2. **必须署名**：在产品可见处（README / 设备关于页 / OTA 说明）写：
     ```
     Font: MiSans (c) Xiaomi, used under MiSans free commercial license
     ```
  3. 不单独售卖字体本身（卖的是设备，不构成字体售卖）。
- **待核对**：官方 FAQ 是否另有"不得修改/不得子集化"的附加条款；MiSans 各字重（Regular/Medium）许可是否一致。
  子集化（保留字形轮廓）通常属于"嵌入使用"，但需以官方原文为准。

## 2. JetBrains Mono（拉丁/数字）

- 官方许可页：<https://fonts.google.com/specimen/JetBrains+Mono/license>
- 许可：**SIL Open Font License 1.1**
- 版权声明：`Copyright 2020 The JetBrains Mono Project Authors`
- 允许：商用、嵌入、再分发、修改（含子集化）。
- 义务：
  1. 再分发时**保留版权声明与 OFL 1.1 文本**（固件"开源许可"页或随附 LICENSES 文件）；
  2. 不得单独售卖字体；
  3. 若 OFL 声明了 Reserved Font Name，修改版（含子集）需改名 —— **RFN 未核实，列为待核对项**；
     保守做法：子集文件仍以 `jetbrains_mono_*_4.bin` 命名、不宣称是官方原版即可。

## 3. IBM Plex Mono（备选，不启用）

- 许可页：<https://fonts.google.com/specimen/IBM+Plex+Mono/license>
- 许可：SIL OFL 1.1；版权：`Copyright 2017 IBM Corp.`
- 仅在 JetBrains Mono 出现渲染/许可问题时替换；本轮样张与规格均按 JetBrains Mono 写。

## 4. 子集化后的义务（两个字体都适用）

| 事项 | 做法 |
|---|---|
| 版权声明 | 固件"关于/开源许可"页各一行（MiSans 必填，JetBrains Mono 必填） |
| OFL 文本 | JetBrains Mono 需随固件附 OFL-1.1 全文（assets 或文档目录，纯文本 ~4 KB） |
| 字体二进制 | **不入 git**；生成物在 `scripts/fonts/build/fonts/`（已 gitignore） |
| 改名 | 不把子集文件标成"官方 MiSans/JetBrains Mono 原版"；文件名带 `_subset` 或尺寸后缀 |

## 5. 样张字体（重要）

本机**没有安装** MiSans / JetBrains Mono，`docs/face/ui-v2/*.png` 使用：

- 中文：**Hiragino Sans GB W3**（macOS 系统字体，仅用于渲染样张，不嵌入、不分发）
- 拉丁/数字：**SF Mono**（同上）

**样张不是 MiSans，也不是 JetBrains Mono**；字号、行高、栅格、颜色是最终口径，字形只是占位。
最终字体需按 `scripts/fonts/build_fonts.sh` 生成子集后再截图复核。

## 6. 待截图清单（由 9哥 补，本机无浏览器）

| # | 页面 | 要截到的内容 | 用途 |
|---|---|---|---|
| 1 | <https://hyperos.mi.com/font/faq> | "免费商用 / 可嵌入 / 需注明"那一段原文 + 页面 URL 栏 | 证明 MiSans 许可结论 |
| 2 | <https://hyperos.mi.com/font> | 字体名称、版本（MiSans Global）与下载入口 | 证明字体来源 |
| 3 | <https://fonts.google.com/specimen/JetBrains+Mono/license> | SIL OFL 1.1 与 Copyright 2020 The JetBrains Mono Project Authors | 证明 JetBrains Mono 许可 |

> 截图存放建议：`docs/fonts/license-shots/`（尚未创建，等截图到位再建）。
> 在截图补齐前，本文的 MiSans 结论标记为 **"9哥 转述 + 待截图核对"**，不作为最终法务结论。

## 7. 参考

- 固件现有字体链：`managed_components/78__xiaozhi-fonts/README.md`（`lv_font_conv@1.5.3`、CBIN 方案、运行期 glyph push 上限 64 字/64 KiB）。
- 体积与子集规格：`docs/fonts/font-spec.md`。
