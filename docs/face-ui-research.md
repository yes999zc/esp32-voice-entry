# 角色形象与实现路线：现成形象从哪来、三条路线怎么落地

- 日期：2026-10-28（在 2026-10-28 首版「AI Passport × CC usage display」之上**增量修订**，原文全部保留在 §2）
- 触发：9哥 原话「你自己绘制的这个表情太难看了」「千万不要再自己整了，你自己整不了」「抖音上有一个整的是真人形象，他用的 ESP32 设备……哪怕动漫形象也行」
- 目标：**不再自绘**，找到可用的现成形象 + 一条能在 CHD ESP32-S3-BOX（480×320 / 8 MB PSRAM / 16 MB flash / 无 GPU）上跑起来的实现路线
- 硬件事实（已核实，直接采用）：480×320 ST7796 SPI、8 MB PSRAM、16 MB flash（app 分区 0x3f0000 = 4,128,768 B，assets 分区 0x800000 起 8 MB）、FT6336 触摸可用、WiFi 正常、无 GPU/无硬件 JPEG 解码
- 固件事实（本机源码核实，`05_Tools/xiaozhi-esp32`）：上游 `78/xiaozhi-esp32` 分支，LVGL 显示层 `main/display/lcd_display.cc`；CHD 板在 `main/boards/chd/chd-esp32s3-box/chd_esp32s3_box_board.cc` 里把官方 emoji 槽换成了自绘 kawaii 面板
- 纪律：只读调研 + 写这一个文档；不改代码、不刷机。**所有推测标「推测」，查不到写「未找到」**

---

## 1. 结论：三条路线怎么选

> 一句话：**先花 1 人日把现成动漫形象贴上去（路线 C 的 GIF 变体，几乎零固件风险），9哥 点头后再花 3 人日换成 EAF 补满 21 表情；路线 B（服务器推帧）只在「必须是真人视频级」时才做，而且要先修好 WS 保活。**

1. **抖音那条「ESP32 + 真人形象」大概率不是推流，是官方「自定义主题」上传动态表情。** 抖音教程逐字描述了这条流程：小智控制台 → 设备 → 自定义 → 主题设计 → 表情集合（**共 21 个**）→ 上传动态表情图片 → 生成配置文件 → 数据线刷入（[视频页](https://www.douyin.com/shipin/7618753167249164351)）。官方工具 `78/xiaozhi-assets-generator` 的 README 与之一致：21 个表情槽、支持 **GIF 或透明 PNG**、统一尺寸且不得大于屏幕分辨率。**触发这条链路的是「素材」，不是「固件」**——这正是 9哥 要的「不要再自己整」。
2. **我们现在的固件已经能播 GIF 表情，不用改代码。** `main/display/lcd_display.cc:1229-1250` 里 `SetEmotion()` 判断 `image->IsGif()` 后创建 `LvglGif` 控制器，逐帧 `lv_image_set_src()`。唯一的拦路石是 CHD 板把官方 emoji 槽替换成了自绘脸（`chd_esp32s3_box_board.cc:251` 起「replace the stock centered emoji with the kawaii face」）。**把这段换回去 = 换脸完成**，代价 0.5–1 人日（含素材压缩与真机验证），不动协议、不动音频。
3. **观感上限与工作量是反序的。** 同素材下观感：**B 推流（真人视频级）> C-EAF ≈ C-GIF（动漫 Live2D 级）> A 本地帧序列（受 8 MB 限制，只能短片）> 自绘脸（当前，9哥 已否决）**；工作量：**C-GIF 1 人日 < C-EAF 3 人日 ≈ A 3 人日 < B 6 人日**。所以先用 C-GIF 拿到「观感判决」，再决定要不要为 +半档观感付 3–6 人日。
4. **存储是真正的硬约束，不是算力。** assets 分区 8 MB，当前只用了 0.27 MB（`build-chd/generated_assets.bin` = 269,881 B），可支配约 8.1 MB。本机实测 480×320 JPEG：**真人照片质感 q75/4:2:0 = 22.7 KB/帧**，q60 = 16.8 KB，q85 = 31.3 KB；扁平 UI/卡通截图 q75 = 9.5–13.9 KB。按 22.7 KB × 15 fps，8 MB 只够 **约 24 秒**单角色动画；21 个表情各 3 秒需要 21 MB，**装不下**。
5. **GIF 也吃空间，但比帧序列好。** 同源实测（另一项目 Baji_Rtc_Toy）：Live2D 半身 209×360 GIF 高质量无 lossy = **2.3 MB/个**，`--colors 128` 约 500 KB–1 MB，64 色约 120–200 KB。我们 8.1 MB ÷ 21 表情 ≈ **385 KB/表情**，意味着只能放 **6–10 个高质量表情 + 其余复用同一支动画**（官方 20 个逻辑名本来就有 11 个是复用：thinking→confused、surprised→Happy 等）。
6. **EAF 是唯一能在 8 MB 里放下「21 表情 × 2–4 秒」的格式。** 本机实测官方 `emoji_large`：10 个 EAF 合计 **1.18 MB**，单个 `Happy.eaf` = 81,645 B / **43 帧** / 125×160 / 8-bit 调色板；社区项目里 209×360 的 Hiyori GIF 是 2.3 MB，而它的 EAF 数字人包只有 450–505 KB（量级约 1/4–1/5；两者不是同一段动作，只作量级参考）。按 480×228 换算，单表情 100–250 KB，21 个表情 **2–5 MB，放得下**。
7. **官方 EAF 的观感是「玩具级可用」，不是产品级。** 硬指标：`emoji_large` 只有 **125×160**（在 480×320 屏上要放大 2–3 倍）、8-bit 调色板、43–89 帧。风格是日系卡通圆脸（EchoEar/ESP-VoCat 那套脸）。它比自绘脸强一个档次，但**不是** 9哥 说的「抖音上那个真人形象」。**这条只能当「兜底现成资产」，不能当终局。**
8. **路线 B 技术上完全可行，瓶颈在网络不在解码。** `esp_new_jpeg` 官方基准（ESP32-S3）：480×320 解码 **36.29 fps**（4:2:0 → RGB565_LE），4:2:2 也有 32.27 fps；12 fps 只占单核约 1/3。带宽 22.7 KB × 12 = **272 KB/s ≈ 2.2 Mbps**，2.4 GHz WiFi 余量充足。**但**当前设备静置 RTT 789–840 ms、建立 WS 后数十秒被断（`docs/HANDOFF.md` 2026-10-28 记录，仍在查）——**在这条链路修好前做推流是给自己挖坑**。
9. **官方 emote 引擎变体已经存在，但不建议当主线。** `chd-esp32s3-box-lcd35-emote`（EAF + `esp_emote_expression`，`xiaozhi.bin` 2,590,384 B，assets 2.7 MB）已能编译，代价是：官方布局只有 320_240/360_360/1024_600，**没有 480×320**，`320_240/layout.json` 的 `eye_anim` 是写死像素，480 宽屏上表情偏左上、右侧约 160 px 空白；而且 emote 引擎接管 panel + flush_cb，**字幕条和状态栏会消失**。它只能做对照实验。
10. **落子顺序（建议 9哥 直接批这个）：**① 今天：下载一套现成动漫形象 GIF（Live2D 免费模型 Hiyori/Haru 导出，或社区现成表情包），压到 480×228、6–8 个表情，走 assets-generator → 刷 assets → 真机截图给 9哥 判（**1 人日**）；② 判过：接 `esp_lv_eaf_player` 换成 EAF，补满 21 表情、降 CPU（**3 人日**）；③ 只有 9哥 明确要「真人视频级」才启动 B。

| 路线 | 观感上限 | 工作量 | 存储 | 风险 | 改固件 | 建议 |
| --- | --- | ---: | --- | --- | --- | --- |
| **A 本地帧序列**（JPEG 帧 + 自写播放器） | 中高（可放真人短片，但只有 20 余秒） | 3 人日 | 22.7 KB/帧，8 MB≈24 s@15fps | 中（要自写播放器/打包链路） | 是（中） | 不推荐，除非只要一段循环短片 |
| **B 服务器推帧** | **最高（真人视频级）** | 6 人日 | 0（走 PSRAM） | **高（WS 链路当前不稳）** | 是（中） | 只有「必须真人」才做，先修保活 |
| **C 官方 EAF/emote 变体** | 中（现成动漫脸，125×160 拉伸） | 1（GIF）→ 3（EAF） | 100–250 KB/表情，21 个≈2–5 MB | 低（官方格式，社区验证过） | **GIF 变体几乎不用改** | **先做这个** |


---

## 2. 两个原定项目（AI Passport × CC usage display）

> **本节是首版调研的原文，全部保留**（只把标题降了一级、加了 2.x 编号，正文一字未改）。它回答的是「角色该怎么做动、怎么交互」，与本轮「形象从哪来、走哪条技术路线」互补：**§1 定路线，§2 定表情语法与交互细节**。
>
> 原文元信息（保留）：
> - 日期：2026-10-28
> - 对象：① FoloToy **AI Passport**（含其 plays 生态里的角色类玩法）② **CC usage display**（Claude Code 用量展示，候选见 §2.3）
> - 目标设备：480×320、ESP32-S3、触摸、8 MB PSRAM、LVGL 自绘 kawaii 脸（228 px）+ 两行字幕条 + 顶部状态文字
> - 方法：本地仓库检索（无同名项目）→ 官网/仓库源码/文档逐条核对 → 只写能指到文件行或页面的事实；推断一律标「推测」
> - 可行性标签：**直接可做** / **降级可做**（要改做法或牺牲效果）/ **做不了**（硬件或架构不允许）
>
> 下文出现的「§3 #10」等编号是**原文编号**，对应本文的 `### 2.4` 小节内的行号。

### 2.1 结论摘要：每条都对应一个动作（原文 §0）

1. **角色感来自「眼形 × 眉角 × 嘴宽 × 身体倾斜」的离散组合，不来自贴图。** Tamagezi 的设计文档明确写「表情只依赖眼、嘴、眉和身体倾斜」，48×48 精灵 3× 最近邻放大到 144×144。→ 我们下一步不做新素材，先把 6 个状态扩成一张参数表（眼高/眼距/眉角/嘴宽/倾斜），**0.5 人日，零新增 flash**。
2. **「像活的」最便宜的手段是 1–2 px 的不对称微动。** Codex Buddy 的视线每 200 ms tick 漂移 1 px，庆祝时每 2 个 tick 只跳 2 px。→ 加「注视漂移 1 px + 随机眨眼 2–5 s」，**0.5 人日**，不需要 60 fps。
3. **5 fps 就够，关键是节拍而不是帧率。** AI Passport 的动画跑在 200 ms tick、用 `lv_anim_path_step` 离散换帧（眨眼 70 ms 闭合 / 70 ms 睁开 / 停 1700 ms）。→ 我们按 80/150/500/2000 ms 四档节拍表设计动效，禁止追连续插值，**0 人日（设计约束）**。
4. **状态要有「入场反应 + 尾帧」，不能只换一张脸。** 失败 = X 眼 + 屏幕转红，完成 = 蹦跳 + 3 px 彩点，等待 = 双臂抬起。→ speaking / thinking / 完成 / 失败各补一个 ≤300 ms 的入场或收尾动作，**1 人日**。
5. **审批不是一个表情，是一个模式。** Codex Buddy 用底部抽屉 + 棋盘格压暗 + 固定 footer，锁定后显示「正在发送…／发送失败」。→ confirm-pending 从 confused 脸改成「脸缩到上半 + 底部两枚按钮（允许/拒绝）+ 30 s 超时回落」，**1.5 人日**，这是当前最像「同事」的一步。
6. **等待必须给出「还在动」的证据。** busy 时角色胸口小屏有 2×2 的点每 tick 移 4 px；用量屏用「更新中 / 数据较旧」文字区分新鲜度。→ thinking 加 3 点脉冲或 600 ms 眉抬循环，别只停在静态表情，**0.5 人日**。
7. **信息屏的美学是「纸 + 墨 + 两个品牌色 + 分段条」。** FoloToy Usage：纸底 `#F4F3EA`、墨 `#202B2D`、Claude 红 `#B64231`、Codex 蓝 `#225A81`、10 段刻度条（缝 3 px）。→ 若做用量页就照抄这套色与条，**常驻脸上不显示数字**，**1 人日**（二级页）。
8. **底部条要当成「动作栏」来管，而不是字幕容器。** AI Passport 固定预留 24 px action bar 且永不滚动。→ 我们的 60 px 底条定义三种互斥模式（字幕／审批／静默），任何时刻只有一个 owner，**1 人日**。
9. **不要抄竖屏四段式。** 他们 240×320 把脸压到 41% 高度（132 px）是因为要塞 138 px 信息区；我们 480×320 的卖点就是脸（现在 228 px ≈ 71% 高度）。→ 拒绝「信息优先」布局，信息只进长按/二级页，**0 人日（否决项）**。
10. **不要抄 17 状态和蓝屏梗。** 我们的协议只给 6 个状态，17 态会造出映射空洞；BSOD 会让「同事」看起来坏了。→ 状态表锁死 6 + 2（done / error），其余用字幕表达，**0 人日（范围约束）**。

---

### 2.2 AI Passport：出厂不是角色，而是一张工牌（原文 §1）

#### 2.2.1 身份：一台「可穿戴 AI Agent」，出厂不是角色，而是一张工牌

- 定位原文：**Open Wearable AI Agent**，核心信息 **WEAR · PLAY · CREATE**；WEAR 模式下用小程序经 BLE 下发**姓名、头像、简介、整屏图片**，PLAY 模式装玩法，CREATE 模式自己写固件。([品牌文档](https://github.com/FoloToy/ai-passport/blob/main/docs/brand/brand-and-product.md))
- 形态：60×95×8.5 mm / 50 g / 500 mAh / 透明壳，屏幕与电路板可见。([官网](https://ai-passport.folotoy.cn/en/))
- 硬件：**ESP32-C3、240×320 竖屏 ST7789P3、8 MB Flash、无 PSRAM、三颗 ADC 按键（共用一个 GPIO）、麦克风/扬声器/NFC**。([硬件开发指南](https://github.com/FoloToy/ai-passport/blob/main/docs/hardware-design/AI_HARDWARE_DEVELOPMENT_GUIDE.md))
- 关键结论：**平台本身没有人格形象**。人格全部由 plays 自带：电子宠物（Tamagezi）、蓝屏小精灵（Codex Buddy）、橙色代码小人（码上装忙）、腹黑怪兽（声控怪兽）。同一个 6 态硬件，被不同 play 解释成完全不同的角色。
- 对我们的含义：**把「状态词汇表」和「角色皮肤」解耦**。我们的 6 个状态（idle/listening/thinking/speaking/tool/confirm）应该是协议层的事实，脸只是它的一种渲染；将来换脸、换皮不动状态机。

#### 2.2.2 UI 结构：四个固定横向带，各自有硬裁剪框

Pixel Buddy 的 UI 规范（240×320 竖屏）把屏幕切成四段，每段有显式裁剪矩形，互不侵占：([UI 规范](https://github.com/FoloToy/ai-passport/blob/demo/claude-buddy-port/docs/superpowers/specs/2026-08-12-pixel-buddy-ui-design.md))

| 区域 | 高度 | 占比 | 内容 |
| --- | ---: | ---: | --- |
| 状态栏 | 26 px | 8% | 连接/电量/状态，永远可见 |
| 宠物舞台 | 132 px | 41% | 物种名在上，精灵居中（按实际非透明包围盒居中，不按画布原点） |
| 信息区 | 138 px | 43% | 分页内容，独立裁剪 |
| 动作栏 | 24 px | 8% | 永远预留，滚动内容不得占用 |

叠层规则：先画底页，再画**唯一一个**顶层 overlay；优先级 确认/配对 > 审批 > 菜单；overlay 先用**棋盘格抖动压暗**整页，再画不透明面板；面板覆盖区内的底页文字必须不可见。审批用下半屏，保留状态栏和可辨认的角色剪影，footer 固定。

排版规则：正文用 8 px 像素字，只有页面/弹窗标题用 16 px；**标签左对齐、数值右对齐**；按词换行，超宽词省略号截断而不是溢出。

> 我们的对应：480×320 横屏没有「四段」的必要，但**「动作栏永远预留、滚动内容不得侵占」这条要抄**——现在字幕条是 `LV_SIZE_CONTENT` 高度，长文本会往上长，审批按钮将来会被挤。

#### 2.2.3 交互：三键 + 浏览器刷机，没有触摸

- 全局键位：`UP/DOWN` 移动选项，`OK` 单击确认，`OK` 长按返回上一级（首页长按进系统菜单），有明确需求时 `OK` 双击直达最相关入口。([Tamagezi 设计文档 §9](https://github.com/FoloToy/ai-passport/blob/demo/tamagezi/docs/TAMAGEZI_GAME_AND_CHARACTER_DESIGN.md))
- 安装方式：浏览器 WebSerial 直接烧写，装新玩法会覆盖当前玩法；设备端没有「应用列表」概念。([玩法页](https://ai-passport.folotoy.cn/plays/186/))
- Codex Buddy 的按键分工是**把审批做成肌肉记忆**：待确认页 `OK` = 单次允许，`DOWN` = 拒绝，`UP` = 滚动长参数；发送后整页锁定。([Codex Buddy README](https://github.com/zhangsan2000w-art/ai-passport-codex-buddy))
- 省电交互：**60 秒无按键自动息屏，息屏时任何键只唤醒、不顺带触发操作**。([同上](https://github.com/zhangsan2000w-art/ai-passport-codex-buddy))
- 对我们的含义：触摸屏不该复刻「UP/DOWN 翻页」。但「息屏后第一下只唤醒」这条对桌面设备同样成立，且比按键设备更重要（防止误触批准）。

#### 2.2.4 角色处理：三个可对标的个案

#### A. Tamagezi（官方原创电子宠物）——把「表情语法」写成了规范

- 精灵 **48×48 px 源图，3× 最近邻放大到 ≈144×144**；每只 5–7 色（含统一暖黑描边）；**纯黑剪影也能区分**（叶耳、火苗、方壳、星冠……）。
- **「表情只依赖眼、嘴、眉和身体倾斜，避免大量高分辨率面部贴图。」**
- 首页角色占屏 **35%–45%**，需求图标不得遮脸；首页不同时显示 5 条数值条，只显示表情 + 环境 + 最多 2 个需求图标，完整数值进 `STATUS` 页。
- 每个状态 2–4 帧即可：Idle/Blink/Sleep/Sick 各 2 帧，Walk/Eat/Celebrate 各 4 帧；4-bit 索引色、逐帧解码到小 RGB565 缓冲；12 只宠物约 **0.5–0.7 MB** flash。
- 五维需求（饱腹/心情/清洁/健康/精力）各有**身体语言**：摸肚子、背对玩家、打喷嚏、打哈欠——不是弹一个图标。

来源：[Tamagezi 玩法与形象设计](https://github.com/FoloToy/ai-passport/blob/demo/tamagezi/docs/TAMAGEZI_GAME_AND_CHARACTER_DESIGN.md) §8、[设备验收](https://github.com/FoloToy/ai-passport/blob/demo/tamagezi/docs/TAMAGEZI_DEVICE_ACCEPTANCE.md)

#### B. Codex Buddy（蓝屏小精灵）——把「编程 Agent 状态」演成表情

这是我找到的**与我们场景最接近**的实现：桌面状态桥把 Codex 的「开始 / 工具执行 / 等待授权 / 完成 / 失败」经 BLE 推到卡片，卡片用一只 CRT 显示器小精灵表达。([play 96](https://ai-passport.folotoy.cn/plays/96/)、[源码](https://github.com/zhangsan2000w-art/ai-passport-codex-buddy))

表情语法（源码级，`main/buddy_sprite.c`）：

| 状态 | 眼 | 嘴 | 身体/附加 |
| --- | --- | --- | --- |
| sleep | 两条 6×1 横线（闭眼） | — | 屏幕变暗 |
| idle | 3×7 竖眼，**每 tick 水平漂移 −1/0/+1 px**（`tick%3-1`） | 3×1 | 腮红 5×3 |
| busy（工具执行） | 3×7 竖眼 | 3×1 | **胸口小屏一个 2×2 亮点，每 tick 右移 4 px（3 个位置循环）** |
| attention（等授权） | 2×7 竖眼 + 2×2 高光（瞪大） | — | **双臂抬起**，无腮红 |
| celebrate（完成） | `^ ^` 折线眼 | 6×1 + 4×1（张嘴） | **每 2 个 tick 整体上跳 2 px**，四角 3×3 彩点，额头爱心 |
| dizzy（失败） | `X` 眼（两条对角线） | 6×1 + 两个嘴角像素 | **屏幕转红**、双臂抬起 |
| heart | 额头画爱心 | — | 腮红 |

- **角色是一个「屏幕脸」**：小精灵本身是一台 CRT，脸画在它的屏幕上——概念本身就是笑点（AI 硬件长了一张蓝屏脸），比画工更省力也更记得住。
- 状态帧是 **2 帧交替**：busy/attention/dizzy/heart/celebrate 每 500 ms 换一次，sleep 每 1000 ms 换一次（睡/做梦）；`buddy_ui_tick()` 用 `elapsed_ms / 200` 当 tick，即 **5 fps**。([buddy_character.c](https://github.com/FoloToy/ai-passport/blob/demo/claude-buddy-port/main/buddy_character.c)、[buddy_ui.c](https://github.com/FoloToy/ai-passport/blob/demo/claude-buddy-port/main/buddy_ui.c))
- 审批态是**独立模式**：收到审批心跳自动切页，显示工具名 + 参数提示；`OK` 允许、`DOWN` 拒绝；发送后页面锁定并显示 `正在发送…` / `发送失败`；**30 秒无有效心跳就清掉审批并回到离线**，每个审批 ID 只接受一次决定。
- 音效分工：授权 = 短促双音，完成 = 上行三音，音量五档（0/25/50/75/100%）。

#### C. 码上装忙（橙色代码小人）——17 状态的「陪伴感」上限

- 「会眨眼、张望、动手写代码，报错时发愁，被打断后抬手回应，完成了还会庆祝」；终端风格随机切项目，覆盖思考、搜索、读取、修改、测试、等待、恢复等 **17 种状态**；上键打断/继续，下键换项目，确定互动，长按确定看陪伴记录。
- 彩蛋：连续快速按七次触发「虚构账户封禁」，申诉一半概率通过，十秒后恢复——**用虚构叙事把设备的限制变成性格**。([play 186](https://ai-passport.folotoy.cn/plays/186/))

> 这条对我们最有价值的是「被打断后抬手回应」：**中断也要有反应**。我们现在说话被打断，脸只会回到 idle，缺一个「被噎住」的 200 ms 尾帧。

#### D. 声控怪兽——把「听」变成可见的

- 会随声音大小换表情、跳动、抖动；挑战「悄悄话 / 持续发声 / 三连拍」，规则下一回合可能反转；完全离线。([play 524](https://ai-passport.folotoy.cn/plays/524/))
- 这证明**麦克风输入可以直接驱动脸**（而不是先识别成文字）。我们已经有 VAD/ASR 链路，音频包络是现成的；标**降级可做**（需要确认板级能拿到实时音量，推测可行）。

#### 2.2.5 动效细节：时长、缓动、节拍（源码级）

| 动作 | 参数 | 来源 |
| --- | --- | --- |
| 眨眼（LVGL 版） | 闭眼 70 ms → 睁眼 70 ms → 停 **1700 ms**，`lv_anim_path_step`（无插值，直接切帧） | [ui_pixel.c](https://github.com/FoloToy/ai-passport/blob/demo/tamagezi/main/ui_pixel.c) L113–127 |
| 眨眼（帧函数版） | 2000 ms 周期，**1650–1800 ms 闭眼**（150 ms） | [ui_pixel_math.c](https://github.com/FoloToy/ai-passport/blob/demo/tamagezi/main/ui_pixel_math.c) |
| 跳一下 | 上 110 ms（−5 px）→ 下 140 ms，`step` | ui_pixel.c L130–143 |
| 跳一下（帧序列） | 5 帧位移 `{0, −3, −5, −3, 0}` | ui_pixel_math.c |
| 状态帧交替 | 500 ms（busy/attention/…）、1000 ms（sleep） | buddy_character.c |
| 整体跳动（庆祝） | `tick % 4 < 2` 时 −2 px，即 2 px / 400 ms 的方波 | buddy_sprite.c |
| 视线漂移 | 每 tick ±1 px，3 相位 | buddy_sprite.c |
| 进度点 | 2×2 px，3 个位置，间隔 4 px，每 tick 前进 | buddy_sprite.c |

**能得出什么：**

- **闭眼只要 150 ms**，再长就像困了；**睁眼比闭眼慢一点**（70 vs 70 是特例，跳起落回是 110 vs 140）——**下落/回位比出发慢**，这是「有重量」的关键。
- **所有缓动都是 `step`**，即离散换帧。所谓「低帧率也成立」不是妥协，而是这类像素角色的原生语言。
- **固定 1700 ms 眨眼会机械**。他们两处实现都是固定周期；这是我们可以做得更好的地方（见 §3 #3）。
- **60 fps 级别的细节**（连续缩放呼吸、跟随手指的眼神、粒子物理）在这个硬件上既做不到也没必要；AI Passport 用 5 fps 就做出了「活」。**低帧率成立的前提是：动作幅度 1–2 px、节拍稳定、有随机性。**

#### 2.2.6 信息层级与留白

- 舞台 132 px（41%）是「主视觉」，但**信息区 138 px（43%）更大**——它本质是一台信息设备，角色是情绪化的状态指示灯。
- 状态栏 26 px 只放最必要的连接/电量；标题 16 px、正文 8 px，**层级靠字号和字重，不靠颜色数量**。
- 对比靠**纯色块**：审批面板用红/蓝实心 header + 白字，底页压暗用棋盘格（每像素隔一个置 15），既省 CPU 又保留底图轮廓。
- 留白策略：**每个区域有自己的裁剪框**，宁可截断也不越界；角色按实际包围盒居中，避免「看起来偏了」。

#### 2.2.7 反馈节奏（用户等待时看到什么）

| 时刻 | AI Passport 做法 |
| --- | --- |
| 开始工作 | 状态帧切到 busy，胸口的点开始走；不弹「加载中」 |
| 工具执行中 | 同上，点循环本身就是进度 |
| 等待授权 | **切模式**：底部抽屉 + 工具名 + 参数提示 + 双臂抬起；有短促双音 |
| 已按下允许 | 页面锁定，`正在发送…`；失败 → `发送失败`，不假装成功 |
| 完成 | `^ ^` + 蹦跳 + 彩点 + 上行三音，然后回 idle |
| 失败 | X 眼 + 屏幕转红，双臂抬起（求助姿态），不是弹错误码 |
| 断连 | 30 s 心跳超时 → 清审批 → 离线态（sleep） |
| 久置 | 60 s 无按键息屏；第一下只唤醒 |

**核心节奏观：状态切换是「瞬间 + 尾帧」，不是淡入淡出。** 唯一的长动画是「庆祝」和「睡觉」。

---

### 2.3 CC usage display：先把候选摊开，再判断是哪一个（原文 §2）

#### 2.3.1 先把候选摊开：哪个才是 9 哥说的

本地已确认**没有**同名项目：`ls ~/AI_Workspace/01_Code/*/` 无 `*passport*` / `*usage*`；`projects/` 下 45 个目录也没有 CC usage 相关仓库。所以只能按网络候选判断。

| # | 候选 | 是什么 | 像「CC usage display」的理由 | 不像的理由 | 判定 |
| --- | --- | --- | --- | --- | --- |
| A | **FoloToy Usage**（[repo](https://github.com/cfrs2005/folotoy-usage) / [上手文](https://www.80aj.com/2026/09/07/ai-passport-dashboard/)） | AI Passport 独立固件，240×320 LVGL，显示 Claude/Codex 的 5h/7d 额度、重置倒计时、今日/累计 Token、API 估算费用 | 与 AI Passport **同一块硬件**、同为 LVGL 小屏、中文界面、名字直译就是「用量显示」；和第一个调研对象天然成对 | 它自称「用量仪表盘 / UsageHub display」，不叫 CC usage | **最可能（中高可信）** |
| B | **Vibe Passport / Vibe Note**（[V2EX](https://global.v2ex.co/t/1239813)、`vibe-usage-esp32`） | 同一套 VibeUsage 看板的两个 ESP32 固件：Passport（ESP32-C3 彩屏 LVGL、自动背光）、Note（ESP32-S3 墨水屏、局部刷新） | 名字、形态、内容都是「把 CC 用量搬到小屏」 | 社区热度低，没找到公开仓库页面；9 哥更可能看到的是 A | 次选（低中可信） |
| C | **Claude Code Usage Monitor**（[repo](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor)） | 终端 Rich TUI：实时进度条、burn rate、耗尽预测、reset 感知、JSON/状态文件 | 英文里最常被叫「CC usage monitor/display」的桌面工具 | 是终端 TUI，不是「display 设备」；与 face UI 无直接关系 | 若 9 哥指桌面工具，则是它（中可信） |
| D | **ccusage**（[repo](https://github.com/ccusage/ccusage)，≈1.9 万 star） | CLI/statusline：日报、月报、session 报告、`--live`、`--breakdown` | 「CC usage」这个名字最正 | 它是命令行报表，没有「display」的视觉设计可调研 | 最不可能（若是它，9 哥要的是数据口径不是 UI） |

**我的判断**：9 哥说的是 **A（FoloToy Usage）**，因为两个调研对象被放在一起，最自然的解释是「同一块 AI Passport 上的两类玩法：角色陪伴 + 用量仪表」。**但这只是推断**——如果 9 哥指的是桌面工具，§2.5 的 C/D 两条仍然成立（节奏与预报），A 的像素级结论则作废。建议开新会话前用一句话跟 9 哥确认。

> 排除项：Devpost 上的 "AI Passport — Agent Border Control" 是 hackathon 的 HTML mockup，与硬件无关；各类「AI passport / 数字身份护照」项目是身份认证主题，均排除。

#### 2.3.2 身份与 UI 结构（以 A 为准，源码级）

它**没有人格形象**，身份靠「头像 + 名字 + 大时钟」建立——是一块**安静的桌面仪表**，不是同事。([usage_ui.c](https://github.com/cfrs2005/folotoy-usage/blob/main/main/usage_ui.c)、[预览图](https://github.com/cfrs2005/folotoy-usage/blob/main/docs/images/folotoy-usage-preview.png))

| 元素 | 尺寸/位置（240×320 基准） | 说明 |
| --- | --- | --- |
| 头像 | 40×40 @ (10,10) | 可换成用户头像；未同步时显示首字母 |
| 名字 | 78 px 宽 @ (60,9) | 左对齐 |
| 时钟 | 91 px 宽，右对齐 @ (139,5) | **全屏最大字号**，比额度百分比还大 |
| 日期 | 112 px @ (60,34) | muted 小字 |
| 页码 | 45 px @ (188,34) + 右侧两条 2×10 px 刻度 | 「额度 / 用量」，刻度当 page indicator |
| 卡片 ×2 | 224×119，y=65 / y=193 | Claude 在上、Codex 在下 |
| 卡片 header | 224×25 实心色条 | 白字 16 px 品牌名；右侧 94 px 状态字（8 px） |
| 两列 | x=10 / x=121，各 98–99 px | 「5 小时 / 7 天」 |
| 大数字 | 103 px 宽 @ y=45 | `25%` / `1.2M` / `$3.20` |
| 刻度条 | 98×7 @ y=89 | **10 段，缝 3 px**，用 `LV_EVENT_DRAW_MAIN` 画，不额外建 40 个对象 |
| 底部行 | y=101 | 「3时00分重置」/「API估算 $3.20」 |

色彩（全部源码常量）：纸底 `#F4F3EA`、墨 `#202B2D`、次级 `#536264`、Claude `#B64231`、Codex `#225A81`、轨道 `#DCDDD3`。
字体：数字用 **IBM Plex Mono**（等宽，防跳动），中文标签用 **Noto Sans SC 子集**，两者都按 240×320 单独渲染。

**信息层级读数**：时钟（最大）→ 百分比/Token（次大）→ 品牌色条（分组）→ 重置倒计时（小字）→ 页码/日期（最小）。**没有装饰、没有阴影、没有渐变**；对比全靠「纸 vs 墨」和两条品牌色。

#### 2.3.3 交互与反馈节奏

- 翻页：`UP/DOWN` 在「额度 / 用量」两页间切；**没有底部菜单**。
- 额度页按 `OK`：在「已用 / 剩余」之间切换（同一组数字换视角，不换布局）。
- 长按 `OK`：主动刷新；用量页单按 `OK` 也刷新。
- **自动刷新 60 s**；重置倒计时在设备端自己走（不靠云端每秒推）。
- 缺数据 → `--`（**不伪装成 0**）；网络错误 → 保留内存里最后一份快照；**超过 3 分钟或云端标记 stale → 卡片右上角显示「数据较旧」**；离线 → 「离线缓存」；未配对 → 「需要配对」；刷新中 → 页头「更新中」。
- 额度和 Token 的**新鲜度分开判断**（一个旧了不影响另一个）。
- 代价口径写死：「API 估算」不是订阅账单。

**节奏观**：这是一块「1 分钟心跳」的设备。除了倒计时数字在变，屏幕**几乎不动**；所有「在动」都是为了让用户知道数据新不新，而不是为了可爱。

#### 2.3.4 桌面同族（C/D）里值得拿的两点

- **C（Usage Monitor）**：10 s 刷新、burn rate、耗尽预测、`--once` 退出码 `10 = 接近上限 / 11 = 已触顶`、以及 **provenance 标签**（`official` / `local_estimate` / `experimental` / `unknown`）。→ 对我们的启示不是 UI，而是**「数字要带可信度」**：我们的字幕/状态文字同样应该区分「确定」和「估算」。
- **D（ccusage）**：`--live` 实时面板 + 日/月/会话报表 + `--breakdown` 分模型。→ 只取「按窗口分组」（5h / 7d）这个信息结构，不取终端表格。

#### 2.3.5 对我们的价值判断

用量屏和「角色脸」是**两种产品**：一个靠数字密度，一个靠表情。硬把用量塞进脸旁边，会同时毁掉两者。**用量只适合做长按进入的二级页**（或干脆不做）。真正可搬的是它的**状态标签体系**与**新鲜度表达**（见 §3 #10）。

---

### 2.4 可直接搬到我们这边的清单（原文 §3）

> 代价按「1 人日 ≈ 一个实现者一天（含自测）」估；flash 影响指 assets 分区。
> **本轮更正（2026-10-28）**：原文写的「当前余量 26%」与实测不符——assets 分区 8 MB 里目前只用了 **269,881 B**（`build-chd/generated_assets.bin`，约 3%），26% 更可能是 app 分区（`ota_0` 4,128,768 B，固件 2,435,152 B）的余量。原文保留不改，此处以实测为准；各路线体积测算见 §4。
> 文件位置依据 `docs/HANDOFF.md` 记载（`main/boards/chd/chd-esp32s3-box/chd_esp32s3_box_board.cc` 内的 `MoveFaceTo` / 字幕条 / `face_animation_init`）；**本次只读调研，未改任何代码，也未逐行读该文件**。

| # | 他们的做法（来源） | 我们的对应改动 | 代价 | 判定 |
| --- | --- | --- | --- | --- |
| 1 | 表情只靠眼/嘴/眉/身体倾斜，做成离散组合（Tamagezi §8） | 建一张 `state × (eye_h, eye_w, eye_gap, brow_angle, mouth_w, mouth_curve, tilt)` 参数表，6 个状态各一行；现有对象改属性，不换素材 | 0.5 人日；flash 0 | 直接可做 |
| 2 | 视线每 tick 漂 1 px（BSOD `tick%3-1`） | idle/listening 时眼睛整体 `x += {-1,0,1}`，600 ms 一步；说话时锁死 | 0.5 人日；CPU 可忽略 | 直接可做 |
| 3 | 眨眼 150 ms 闭合、周期 2 s（两处实现都是固定周期） | 闭眼 120–150 ms；间隔改 **2000–5200 ms 随机**，**8% 概率连眨两下**；说话/思考时抑制 | 0.5 人日 | 直接可做（改进项） |
| 4 | 下落比出发慢（110 ms 上 / 140 ms 下）；庆祝每 2 tick 跳 2 px | 现有 160 ms 位移改成「去 140 ms ease-out / 回 200 ms ease-in」；完成时加 2 px × 2 次的蹦跳 | 0.5 人日 | 直接可做 |
| 5 | 失败 = X 眼 + 屏幕转红；完成 = `^ ^` + 彩点（buddy_sprite.c） | 新增 `error` / `done` 两个瞬时态（各 800 ms），error 时脸后加 8% 红色蒙版，done 时四角 3 px 彩点 + 嘴角上扬 | 1 人日（含状态机接线） | 直接可做 |
| 6 | 审批 = 模式：底部抽屉 + 压暗 + 固定 footer + 锁定文案（buddy_ui.c） | confirm-pending：脸缩到上半（≈160 px）+ 底部条切成两枚按钮「允许 / 拒绝」；按下后条内显示「正在处理…」；30 s 无操作回落 idle | 1.5 人日 | 直接可做 |
| 7 | 棋盘格压暗（隔像素置暗），不建蒙版层 | 审批/菜单时对底页做棋盘格 dim（LVGL 里可用 1 个 50% 棋盘 pattern 或直接半透明矩形） | 0.5 人日 | 直接可做（若用半透明矩形更省事，效果略平） |
| 8 | busy 时胸口 2×2 点每 tick 移 4 px（进度内嵌在角色身上） | thinking/tool-running：在嘴下方 24 px 处放 3 个 4 px 点，600 ms 依次点亮；代替静态「思考脸」 | 0.5 人日 | 直接可做 |
| 9 | 底部 action bar 固定预留、永不滚动（UI 规范） | 底部 60 px 定为「bar」，三种互斥模式：字幕 / 审批 / 静默；高度固定 60 px，长文本内部滚动而非撑高 | 1 人日（要改现有 `LV_SIZE_CONTENT` 逻辑） | 降级可做（会牺牲「单行时收窄」的现有观感） |
| 10 | 状态标签带新鲜度：`--` / `数据较旧` / `离线缓存` / `需要配对` / `更新中` | 顶部状态文字从「聆听中/说话中」扩成「状态 + 可信度」两段：`思考中` / `思考中（重连）` / `已离线` | 0.5 人日 | 直接可做 |
| 11 | 息屏后第一下只唤醒（Codex Buddy） | 触摸：息屏/暗屏后首次点击只唤醒并吞掉事件；二次点击才生效 | 0.5 人日 | 直接可做 |
| 12 | 完成/授权用不同提示音（双音 vs 上行三音） | 加两个 ≤300 ms 的短音效（完成 / 待确认） | 1 人日（音频通道要避让 TTS） | 降级可做（可能与 TTS 抢通道，需实测） |
| 13 | 用量屏的纸/墨/双品牌色/10 段条 | 长按状态栏进入「用量」二级页，照抄配色与段条；数字用等宽字体子集 | 1 人日 + ~40–80 KB 字体 | 降级可做（要先有数据源） |
| 14 | 声控怪兽用音量直接驱动表情（play 524） | listening 时按输入包络改嘴宽/眼高（0–3 档），无需等 ASR | 1 人日（需板级暴露实时音量） | 降级可做（**推测**可行，未核实 API） |
| 15 | 12 只宠物、每只 0.5–0.7 MB 精灵 | 多角色换肤 | — | 做不了 / 不必（assets 分区余量撑不住，且与「一个同事」定位冲突） |
| 16 | 240×320 竖屏四段式（26/132/138/24） | 横屏 480×320 复刻四段 | — | 做不了（比例不对，且会把脸压到 41%） |

---

### 2.5 AI Passport 里不该抄的（原文 §4）

| 做法 | 为什么不适合我们 |
| --- | --- |
| **竖屏四段式布局**（状态 26 / 舞台 132 / 信息 138 / 动作 24） | 它把 43% 的屏幕给了信息区。我们是「桌上的同事」，脸就是产品；照抄会把 228 px 的脸压到 130 px 左右，瞬间失去辨识度。 |
| **三键导航层级**（UP/DOWN 选项、OK 确认、长按返回、双击直达） | 我们有触摸。把按键语义硬映射到触摸会造出「能点但不知道为什么要点」的界面；触摸应该直接点对象，只保留「长按 = 二级」。 |
| **1-bit / I4 像素风 + ASCII 四行脸**（`buddy_character.c` 的 `( o.o )`） | 那是 240×320、无 PSRAM 的省内存妥协。我们 480×320 + PSRAM + RGB565，做 1-bit 会显得糙；ASCII 脸更是过渡实现。 |
| **蓝屏 / BSOD / 故障梗** | 对开发者是笑点，对「同事」是误导：用户第一眼会以为设备坏了。同理，`X` 眼 + 红屏只适合真错误，不要用于「确认中」。 |
| **17 种状态** | 协议只给 6 个状态；17 态必须有 11 个靠猜，最后会变成「随机变脸」。状态越多，映射越不可测。 |
| **固定 1700 ms 眨眼** | 两处参考实现都是固定周期，2 秒一次像节拍器；人眼对周期性极敏感。我们要随机化（§3 #3）。 |
| **常驻大时钟 + 头像身份卡** | 那是「工牌」的产品逻辑（AI Passport 的 WEAR 模式）。桌上同事不需要时刻告诉你现在几点、你是谁。 |
| **每 60 s 刷新的数字墙** | 角色脸一旦被数字占位，就变成仪表盘；而且我们没有稳定的 CC 用量数据源。要做就进二级页。 |
| **完成音效盖过 TTS** | 我们的音频通道正在播语音；参考实现的「上行三音」是在无 TTS 的设备上成立的。若加，必须做 ducking 或只在无语音时播。**（推测：需实测通道占用）** |
| **「未验证/估算」也画成实心进度条** | Usage Monitor 的 provenance 标签值得学，反面教训是：把估算画得和官方一样实，会误导。我们的状态文字应显式区分「确定/推测」。 |

---

### 2.6 现状对照（480×320 真机截图测量）与下一步（原文 §5）

以 `docs/face/blink-01.jpg`（2026-10-27 22:09，最新）为样本，±2 px：

| 元素 | 现状 | 对照参考后的问题 |
| --- | --- | --- |
| 状态文字 | 顶部居中，约 20 px 高，纯黑 | 对比够，但只有「聆听中…」，缺可信度/连接态 |
| 眉毛 | 两条 ~96×3 px 长条，距眼上缘 ~10 px | 太长太直，读作「装饰线」而非眉；参考实现用短折线/角度表达情绪 |
| 眼睛 | 84×84 圆角方块 + 白色高光豆 | 图形感强、生物感弱；参考的竖长眼（3×7 @ 小屏）更像「看」 |
| 嘴 | ~58×24 圆角矩形，纯色 | 无弧度、无开合；参考用 3–6 px 的横线/张口组合表达 6 种情绪 |
| 面部留白 | 嘴下缘到字幕条约 60 px | 留白偏大，脸的重心偏上；但也给了「加身体/加动作」的空间 |
| 字幕条 | 464×34（单行），深灰 60% + 白字 | 高度随内容变（`LV_SIZE_CONTENT`），与「动作栏固定预留」冲突 |

**最值得先做的 2 件（含代价）：**

1. **表情参数表 + 微动包**（§3 #1 + #2 + #3 + #4）：把 6 个状态写成参数行，加 1 px 注视漂移、随机眨眼、去/回不对称位移。**合计 ≈ 1.5 人日，零 flash**。这是「像活的」投入产出比最高的一步，且不改协议、不新增素材，风险最低。
2. **把 confirm-pending 做成审批模式**（§3 #6 + #9）：脸缩到上半、底部 60 px 切成「允许 / 拒绝」、30 s 超时回落、按下后显示处理中。**≈ 2.5 人日**（含底条模式机）。这是唯一一个「现在的 confused 脸让用户不知道该干什么」的真实可用性缺口；做完之后，设备才真的能当「同事」用。

> 不建议现在做：用量二级页（§3 #13）——数据源未定；声控表情（#14）——要先确认板级音量 API；多角色（#15）——与定位冲突。

---

### 2.7 检索记录与来源（原文 §6）

**本地检索**：`ls ~/AI_Workspace/01_Code/*/`、`find 01_Code -maxdepth 2 -iname "*passport*" -o -iname "*usage*"` → 无同名仓库；`projects/` 45 个目录无 CC usage 相关项。故全部走网络。

**搜过的关键词**：`"AI Passport" desktop device AI companion`、`AI Passport FoloToy plays`、`site:ai-passport.folotoy.cn 用量`、`ccusage Claude Code usage display`、`Claude Code usage monitor TUI`、`FoloToy AI Passport 屏幕 分辨率`。

**取不到的内容**：微信公众号《一张胸牌被玩成了什么》（`mp.weixin.qq.com` 返回「环境异常」验证页），未引用其正文；Devpost 的 AI Passport mockup 已排除；`vibe-usage-esp32` 未找到公开仓库页，仅引用 V2EX 帖。

#### 主要来源

- AI Passport 官网：<https://ai-passport.folotoy.cn/en/>
- 品牌与产品定义：<https://github.com/FoloToy/ai-passport/blob/main/docs/brand/brand-and-product.md>
- 硬件/显示/LVGL 约束：<https://github.com/FoloToy/ai-passport/blob/main/docs/hardware-design/AI_HARDWARE_DEVELOPMENT_GUIDE.md>
- Tamagezi 角色设计规范：<https://github.com/FoloToy/ai-passport/blob/demo/tamagezi/docs/TAMAGEZI_GAME_AND_CHARACTER_DESIGN.md>
- Tamagezi 眨眼/跳跃实现：<https://github.com/FoloToy/ai-passport/blob/demo/tamagezi/main/ui_pixel.c>、<https://github.com/FoloToy/ai-passport/blob/demo/tamagezi/main/ui_pixel_math.c>
- Pixel Buddy UI 规范（四段布局/叠层/字体）：<https://github.com/FoloToy/ai-passport/blob/demo/claude-buddy-port/docs/superpowers/specs/2026-08-12-pixel-buddy-ui-design.md>
- Buddy 状态帧与 tick：<https://github.com/FoloToy/ai-passport/blob/demo/claude-buddy-port/main/buddy_character.c>
- Codex Buddy（BSOD 小精灵）源码：<https://github.com/zhangsan2000w-art/ai-passport-codex-buddy>（表情绘制见 `main/buddy_sprite.c`，审批 UI 见 `main/buddy_ui.c`）
- 玩法页：<https://ai-passport.folotoy.cn/plays/96/>（Codex Buddy）、<https://ai-passport.folotoy.cn/plays/186/>（码上装忙）、<https://ai-passport.folotoy.cn/plays/524/>（声控怪兽）
- FoloToy Usage：<https://github.com/cfrs2005/folotoy-usage>（UI 常量见 `main/usage_ui.c`，预览见 `docs/images/folotoy-usage-preview.png`）
- 上手与网络/新鲜度细节：<https://www.80aj.com/2026/09/07/ai-passport-dashboard/>
- Vibe Passport / Vibe Note：<https://global.v2ex.co/t/1239813>
- Claude Code Usage Monitor：<https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor>
- ccusage：<https://github.com/ccusage/ccusage>
- LVGL 动画与缓动函数：<https://docs.lvgl.io/master/main-modules/animation.html>
- 上游 Hardware Buddy 协议（经 port README 引用，未独立核）：<https://github.com/anthropics/claude-desktop-buddy>

---

## 3. 形象资产盘点

### 3.1 抖音/短视频里那个「ESP32 + 真人形象」设备

**结论：最可能是「官方自定义主题上传动态表情」这条链路，不是服务器推流，也不是 Live2D 运行时。** 判定依据（按可信度排序）：

| 证据 | 内容 | 可信度 |
| --- | --- | --- |
| 抖音教程（[shipin/7618753167249164351](https://www.douyin.com/shipin/7618753167249164351)） | 「打开小智控制台 → 管理设备 → 点自定义直接进入主题设计 → 选择表情集合。这里可以看到**一共有二十一个表情**可以设置……快速上传一下动态表情图片……生成配置文件……准备数据线连接电脑」 | 高——逐字描述了官方链路 |
| 官方工具 `78/xiaozhi-assets-generator`（[README](https://github.com/78/xiaozhi-assets-generator)） | 21 个表情槽（neutral/happy/laughing/funny/sad/angry/crying/loving/embarrassed/surprised/shocked/thinking/winking/cool/relaxed/delicious/kissy/confident/sleepy/silly/confused）；「需要设置统一的图片大小 width×height，**不能大于屏幕分辨率**」；「选择**动态图片（GIF）**或静态透明背景图片（PNG）」；浏览器本地生成 `assets.bin`，USB 刷入 | 高——工具即证据 |
| 我们的固件源码 | `lcd_display.cc:1229` `if (image->IsGif())` → `LvglGif`；依赖 `txp666/otto-emoji-gif-component` | 高——本机核实 |
| B 站教程（[BV18LrgB7Ee6](https://www.bilibili.com/video/BV18LrgB7Ee6/)） | 「小智 AI 2.0 以上版本支持自由配置风格主题……下个视频教你快速制作 gif 动图表情并配置小智 ai」 | 中高 |

**它到底怎么跑（据上述链路推断，标「推测」）**：GIF 文件整段放进 assets 分区（SPIFFS），运行时 LVGL 用 `LvglGif` 逐帧 LZW 解码到 RGB565，再 `lv_image_set_src()` 刷帧。**没有服务器推帧、没有 Live2D 运行时、没有硬解**——所谓「真人形象」就是一段 10–30 帧的真人/GPT-SoVITS 风格 GIF 循环。

**另外两种可能的解释，以及为什么判为次要**：

- *服务器推流/WebRTC 数字人*：TEN-Agent + Trulience 这类方案确实存在（[介绍文](https://www.uied.cn/posts/95835)），TEN 也确实跑在 ESP32-S3 Korvo 上——但**跑在板子上的是语音链路，数字人画面是在浏览器/手机端渲染的**。要让 480×320 屏自己显示推流画面，需要设备端 MJPEG/JPEG 解码 + 长连接，这在开源小智生态里**未找到**成品。
- *本地帧序列 + 自写播放器*：社区有人做（`Baji_Rtc_Toy` 的 sprite_pack 方案），但它明确记录「直写 GRAM 与 LVGL 竞争 → 320×320 时 SPI 队列溢出 → 弃用」，最终回到 GIF。**这条路径的坑已被别人踩完，不值得重走。**

**未确认点（不编造）**：我没能看到那条抖音视频本身（Douyin 页面需要登录/风控），无法 100% 确认 9哥 看到的是哪一条。「21 表情 + 上传动态图」是目前唯一能被公开资料逐条对上的流程，故按高可信推测处理。**若 9哥 能给出视频里角色的样子（真人/动漫、是否有背景、是否在动嘴），判定可以从「推测」升级为「确认」。**

### 3.2 官方 EAF 表情包：画质到什么水平

**实测（本机解包 `managed_components/espressif2022__esp_emote_assets/emoji_large/`）**：

| 项 | 数值 | 怎么得到的 |
| --- | --- | --- |
| EAF 文件数 | 10 个（Happy/Sad/angry/confused/cry/listen/neutral/shocked/sleep/winking） | `ls` |
| 总体积 | **1.18 MB**（10 个合计） | 文件大小求和：81645+177137+98391+211666+89412+100609+161063+64963+184689+12698 |
| 单文件 | `Happy.eaf` 81,645 B；`Sad.eaf` 177,137 B；`confused.eaf` 211,666 B | 同上 |
| 帧数 | Happy **43 帧**、neutral **89 帧**、confused **78 帧** | 解析 EAF 头 `EAF_NUM_OFFSET=4`（`gfx_eaf_dec.h:22`） |
| 分辨率 | **125×160**（`emoji_small` 是 62×80） | 按 `gfx_eaf_dec.c:31-37` 的头偏移解出 width/height，并用 `height == blocks × block_height` 交叉校验（160 = 5×32） |
| 色深 | **8-bit 调色板（256 色）**，`blocks=5`、`block_height=32` | 同上；`EAF_COLOR_DEPTH_8BIT`，调色板 4 B/色（BGRA） |
| 编码 | 支持 RLE / Huffman+RLE / **JPEG** / Huffman-direct / heatshrink / raw（`gfx_eaf_dec.c:386-396`） | 读注册表 |
| 平均压缩率 | 81,645 B ÷ 43 帧 ≈ **1.9 KB/帧**（未扣表头/调色板） | 计算 |

**观感判断（诚实版）**：

- 125×160 的源图放到 480×320 屏上，要放大 **2.4–3.8 倍**。即便用最近邻/双线性，边缘也会糊，**达不到「像抖音上那样精致」**。
- 但它是**成体系的角色**：一套脸覆盖 21 个情绪，眨眼/呼吸/眉毛都有原生动画（43–89 帧不是 2 帧交替），比现在的自绘 kawaii 脸（两只方块眼 + 眉毛 + 小嘴）高一个档次——9哥 说的「太简单」在 EAF 上基本能解决，「难看」则取决于他对这种日系圆脸的接受度。
- **一句话：EAF 官方资产 = 玩具级里做得好的那档，可用、不丢人，但不是产品级。** 想更好只有两条：换更大的 EAF 源（自己拿 Live2D 渲 480×228 再转 EAF，观感直接上一个台阶），或走 B。
- 顺带：本项目 HANDOFF 已记录「官方布局只有 320_240/360_360/1024_600，没有 480×320；`eye_anim` 写死像素 → 480 宽屏右侧约 160 px 空白」，**这是布局问题，不是画质问题**，两条解法见 §4C。

### 3.3 EchoEar（小智回声耳 / 喵伴）

- 硬件：**1.85 英寸 360×360 QSPI 圆形触摸屏**、双麦阵列、ESP32-S3、离线唤醒 + 声源定位（[乐鑫开发套件文档](https://documentation.espressif.com/esp-dev-kits/zh_CN/latest/esp32s3/esp-dev-kits-zh_CN-master-esp32s3.pdf)）。
- 形象：**圆屏就是「脸」**，双麦是耳朵、扬声器是嘴，屏幕上一双会眨的眼睛；外壳是猫形（半球 + 猫耳），64×64×47 mm（[上手文](http://mp.weixin.qq.com/s?__biz=MzkwODgwMDY5Mg==&mid=2247493924&idx=1&sn=e7dbf539e947c41622ba510e2a5cae8b)）。
- **关键事实：EchoEar 用的就是官方 `USE_EMOTE_MESSAGE_STYLE` + EAF 资源**（`main/boards/echoear` 的配置说明：「表情动画风格（Emote animation style）- 推荐 - 配置选项：USE_EMOTE_MESSAGE_STYLE - 使用自定义的 EmoteDisplay 表情显示系统」；上游 PR #1203 也记录了 EchoEar 的 emote display 改为按名加载 assets）。
- **对我们的含义**：我们 assets 里的 `wn9_nihaoxiaozhi_tts-font_puhui_common_20_4-echoear.bin` 只是**按 EchoEar 配置打出来的字体+唤醒词包**，不含形象。EchoEar 的「脸」没有独立资产可抄——它就是 EAF 那 10 个文件 + 圆形裁切。**所以「抄 EchoEar」= 走路线 C，不是另一条路。**

### 3.4 其他开源桌宠 / 产品

| 项目 | 形态 | 屏幕/形象方案 | 观感 | 我们能拿什么 |
| --- | --- | --- | --- | --- |
| **Stack-chan**（M5Stack） | 舵机头 + 方盒身 | CoreS3 **320×240**；表情是**程序化绘制 + 精灵**，官方固件有 AI Agent、ESP-NOW 遥控、OTA；社区工具 `tegnike/stackface-maker` 专门做 320×240 表情资源 | 中上：动作（转头/点头）补足了屏幕的简陋 | 「表情资源制作工具链」的思路；**它的可爱一半来自舵机**，我们没有舵机 |
| **Moflin**（Casio） | 毛绒、无屏 | **完全没有屏幕**，靠头部微动、振动、声音表达 | 高（毛绒 + 行为），但不可借鉴到屏 | 反面印证：**没有屏也能有角色感**，靠的是行为而不是画工 |
| **Petoi**（机器狗） | 四足 | 无屏（部分型号小 OLED 只显示状态） | — | 不适用（形态差太远） |
| **AI Pin**（Humane） | 胸牌、激光投影 | 无屏，激光投影到手掌 | 争议大，已失败 | 不适用；但「不给自己加屏幕」的克制值得记一笔 |
| **ESP-SparkBot**（乐鑫/立创，开源） | 桌面小车 | ESP32-S3 + 屏，表情为固件内绘制的眼睛 | 中：工程 demo 级 | 只能当硬件参考 |
| **Bruffik 桌面机器人**（立创开源） | 1.83" 240×284 ST7789P | 「显示眼睛、口型与情绪表情；未连电脑时显示待机脸」 | 中 | 口型跟随（RMS 驱动嘴型）的做法可抄，见 §5 |
| **Baji_Rtc_Toy**（社区，火山 RTC + 电子吧唧） | 360×360 QSPI | **Live2D Hiyori → GIF → SPIFFS**；后期做 EAF 数字人包（`hiyori_m06.eaf` 505 KB / `m07.eaf` 450 KB） | **高**（真 Live2D 渲染，9哥 要的「动漫形象」就是这档） | **最有价值的参考**：它把「Live2D→GIF→设备」和「Live2D→EAF」两条链路都跑通了，并记录了 8 个坑（见 §6） |

### 3.5 现成素材从哪来（不自绘的关键）

| 来源 | 内容 | 授权/门槛 | 适配我们 |
| --- | --- | --- | --- |
| **Live2D Cubism 免费模型**（Hiyori / Haru / Natori） | 官方 sample，自带 8–26 套动作，Cubism Editor 可导出 GIF/PNG 序列 | Hiyori：普通用户+小企业免费；Haru/Natori：SDK 授权（**商用需读条款**） | ★★★ 480×228 GIF/EAF 的直接来源；观感就是「抖音那档」 |
| **`tegnike/stackface-maker`** | 本地 Web 应用，编辑/生成 320×240 表情资源 | 开源 | ★★ 改目标尺寸即可产出我们的帧序列 |
| **官方 Twemoji 32/64** | assets-generator 内置预设（21 个 emoji） | CC-BY 4.0 | ★ 只有图标级，太小，不适合当「形象」 |
| **社区表情包**（B 站/抖音教程配套） | 现成 21 套 GIF，多为 AI 生成或二创动漫 | **授权不明，商用有风险** | ★★ 拿来给 9哥 看效果可以，进产品前要换 |
| **自建**（Live2D 定制角色） | 找画师做 moc3，再渲成 GIF/EAF | 钱 + 周期（1–3 周） | 终局方案，但要等 |

---

## 4. 三条路线详表

> 统一口径：assets 可用 **8.1 MB**（8 MB − 当前 0.27 MB 字体/唤醒词）；真人质感 JPEG = **22.7 KB/帧**（480×320 q75 4:2:0，本机实测），卡通/扁平 = **9.5–13.9 KB/帧**（本机 480×320 真机截图实测）。

### 4.1 路线 A：本地帧动画（assets 里放 JPEG/raw 帧序列）

| 项 | 数 |
| --- | --- |
| 单帧体积 | 22.7 KB（真人）/ 12 KB（卡通）/ 307 KB（RGB565 raw，不用） |
| 15 fps 一秒 | 340 KB（真人）/ 180 KB（卡通） |
| 8.1 MB 能放多久 | **约 24 秒**（真人 15 fps）/ 约 45 秒（卡通 15 fps）/ 约 67 秒（卡通 10 fps） |
| 21 表情 × 3 秒 @15fps | 真人 **21.4 MB**（✗）/ 卡通 **11.3 MB**（✗）/ 卡通 10 fps **7.6 MB**（勉强 ✓，但要砍帧率） |
| 解码 | 需自写 JPEG 解码循环（`esp_new_jpeg` 已在依赖里，480×320 可跑 36 fps） |
| **观感上限** | 中高：可以放真人短片，但只有 20 余秒且**不能有 21 套** |
| **工作量** | **3 人日**（打包脚本 1 + 播放器/状态机 1 + 素材转码与调参 1） |
| **风险** | 中：帧序列要自己管内存/预取；assets 分区会被撑满，以后换字体没地方；无 OTA 增量（整包重刷） |
| **是否改固件** | 是（新增播放器组件 + 板级接线） |
| 适用 | 9哥 只想要「一段好看的循环动画」，不要求 21 种情绪 |

### 4.2 路线 B：服务器推帧（JPEG over WS/UDP）

| 项 | 数 |
| --- | --- |
| 分辨率/帧率 | 480×320 @ 12 fps（建议），上限可到 20 fps |
| 单帧 | 22.7 KB（q75）/ 16.8 KB（q60） |
| 带宽 | 22.7 × 12 = **272 KB/s ≈ 2.2 Mbps**；q60 则 1.6 Mbps |
| 编码端 CPU | 服务端 `esp_new_jpeg` 编码 480×320 = **24.35 fps**（S3 基准，PC 上更快）；用 ffmpeg/PIL 更省 |
| 设备解码 | **36.29 fps**（480×320、4:2:0→RGB565_LE，S3 官方基准）→ 12 fps 占单核 **约 33%** |
| 单帧延迟 | 编码 20–40 ms + 网络 20–40 ms（同网段）+ 解码 28 ms + flush 15 ms ≈ **80–120 ms** |
| PSRAM | 双缓冲 2 × 307,200 B = **600 KB**（8 MB 里完全够） |
| 流量 | 12 fps 连续跑 1 小时 ≈ 980 MB（仅内网，可接受；公网要限时） |
| **观感上限** | **最高**：真人视频级，可做口型同步、眼神跟随、真实表情迁移 |
| **工作量** | **6 人日**（服务端推流管线 2 + 固件解码显示 2 + 兜底/自适应 1 + 联调 1） |
| **风险** | **高**：① 当前 WS 静置 RTT 789–840 ms、数十秒断连（HANDOFF 已记录，未修完）；② 长连接 + 视频流会放大掉线影响；③ 服务端要 7×24 跑；④ 断电/断网要有兜底画面 |
| **是否改固件** | 是（新增 JPEG 帧接收 + canvas blit + 与 LVGL flush 的互斥） |
| 适用 | 9哥 明确要「真人」，且接受「必须联网才有脸」 |

**最小可行实现清单见 §5。**

### 4.3 路线 C：官方 EAF / emote 变体（零自绘）

路线 C 其实有**三种落地形态**，成本差 3 倍，必须分开看：

| 形态 | 做法 | 观感 | 工作量 | 改固件 | 保留字幕/状态栏 | 判断 |
| --- | --- | --- | ---: | --- | --- | --- |
| **C1 GIF 主题** | assets-generator 上传 480×228 GIF（6–8 个表情）→ 生成 assets.bin → 刷入；把 CHD 板的自绘面板关掉，回到官方 emoji 槽 | 动漫 Live2D 级（取决于素材） | **1 人日** | **几乎不用**（改板级开关 ≈ 30 行） | ✅ | **先做这个** |
| **C2 EAF + LVGL 控件** | 引入 `espressif/esp_lv_eaf_player`（LVGL v8/v9 的 `lv_eaf` 控件），GIF/PNG 序列经 `esp32-gif.espressif.com` 转 EAF，放 assets；我们自己的布局（480×228 + 字幕条） | 同 C1，但**体积 1/4、CPU 更低、可放满 21 表情** | **3 人日** | 是（新增组件 + 控件 + 资源管线） | ✅ | 判过 C1 后升级 |
| **C3 官方 emote 引擎变体** | 已存在：`chd-esp32s3-box-lcd35-emote`（`CONFIG_USE_EMOTE_MESSAGE_STYLE=y` + `FLASH_EXPRESSION_ASSETS=y`） | 官方那张 125×160 圆脸 | 0.5 人日（已编好，只需刷） | 已改 | ❌ 字幕/状态栏消失 | **只作对照实验**，不推荐 |

C1 的技术依据（本机核实）：

- `lcd_display.cc:1229-1250`：`SetEmotion()` → `emoji_collection->GetEmojiImage(emotion)` → `image->IsGif()` → `LvglGif(image->image_dsc())` → 每帧回调 `lv_image_set_src(emoji_image_, gif_controller_->image_dsc())`。
- `assets.cc:338-365`：从 `index.json` 的 `emoji_collection[]` 读 `name`/`file`，`LvglRawImage(ptr, size)` 入集合；**带 `eaf` 字段的条目在这条路径里被跳过**（`NULL == eaf` 才 AddEmoji）——所以别把 EAF 塞进 LVGL 主题，会静默丢图。
- `lcd_display.cc:915-929`：`emoji_box_` 是 `LV_SIZE_CONTENT` 居中容器，`emoji_image_` 居中——**480×228 的 GIF 天然居中，不用改布局**。
- 依赖已有 `txp666/otto-emoji-gif-component`（`main/idf_component.yml`），**不需要开 `CONFIG_LV_USE_GIF`**（当前是 `# CONFIG_LV_USE_GIF is not set`）。
- 需要改的只有一处：CHD 板 `chd_esp32s3_box_board.cc:251` 起把官方 emoji 槽换成自绘面板的那段（`face_panel_` / `face_animation_init`），加一个 `#if` 开关即可 A/B，**不改协议、不改音频**。

**C1 的三个必须实测的风险点**（都不是阻塞级，但要真机确认）：

1. **GIF 逐帧 LZW 解码的 CPU**：参考项目实测「每帧 LZW 解码与 Opus 解码争 CPU，音频卡顿」（Baji_Rtc_Toy §1.2）。480×228 比它的 360×360 小一半，风险降低但**未实测**，标「推测：可用，需真机看 TTS 有无卡顿」。
2. **GIF 体积**：8.1 MB ÷ 6–8 表情 ≈ 1–1.3 MB/表情，够放「256 色、无 lossy」的 Live2D 半身动画（社区实测 209×360 高质量 2.3 MB，我们尺寸更小、可以砍到 1 MB 上下）。
3. **授权**：社区表情包多为二创，**产品化前必须换成自有或授权素材**（见 §3.5）。

### 4.4 三条路线横向对比（拍板表）

| 维度 | A 本地帧序列 | B 服务器推帧 | C1 GIF 主题 | C2 EAF+LVGL | C3 官方 emote |
| --- | --- | --- | --- | --- | --- |
| 观感上限 | 中高 | **最高（真人级）** | 高（素材决定） | 高（素材决定） | 中 |
| 8 MB 放得下多少 | 24 s 单角色 | 不限（走 PSRAM） | 6–8 表情 | **21 表情** | 21 逻辑名（10 文件复用） |
| CPU（12 fps） | 解码 36 fps 能力内，占 33% | 同左 | LZW 较重（推测 30–50%） | 轻（RLE/Huffman） | 轻 |
| 联网依赖 | 无 | **强**（断网没脸） | 无 | 无 | 无 |
| 首帧延迟 | 无 | 80–120 ms | 无 | 无 | 无 |
| 改固件 | 中 | 中 | **极小** | 中 | 已改好 |
| 工作量 | 3 人日 | 6 人日 | **1 人日** | 3 人日 | 0.5 人日 |
| 风险 | 中 | **高** | 低 | 低 | 布局/丢字幕 |
| **推荐** | 备选 | 仅「必须真人」 | **第一步** | **第二步** | 对照 |

---

## 5. 若走 B：最小可行实现清单

> 只在 9哥 明确要「真人视频级」时启动。**前置条件：WS 保活先修到「静置 10 分钟不掉」**（HANDOFF 里 task-25 / 心跳 30/90 那组参数验证通过）。

### 5.1 固件要改的点（文件级）

| # | 位置 | 改动 | 工作量 |
| --- | --- | --- | --- |
| 1 | 新组件 `main/display/avatar_stream/`（`avatar_stream.cc/.h`） | 接收帧消息 → 解 JPEG（`esp_new_jpeg`，YCbYCr/4:2:0 → RGB565_LE）→ 写 PSRAM 双缓冲 | 1 人日 |
| 2 | `main/display/lvgl_display/lvgl_display.h/.cc` | 新增 `lv_image_dsc_t` + 一个全屏 `lv_image`（`LV_IMG_CF_TRUE_COLOR`），`data` 指向双缓冲；`SetAvatarFrame(const uint8_t*, size_t)` 在 `DisplayLockGuard` 内换指针 | 0.5 人日 |
| 3 | `main/boards/chd/.../chd_esp32s3_box_board.cc:251` | 与 C1 同样的 `#if` 开关：走流式时隐藏 `face_panel_`，把 `emoji_box_`/`avatar_image_` 顶到最前 | 0.5 人日 |
| 4 | `main/application.cc`（`OnIncomingJson` 旁） | 新增消息类型 `{"type":"avatar","seq":N,"fmt":"jpeg","w":480,"h":320,"data":"<base64>"}`；**base64 比二进制多 33%**，若走 WS 文本帧先用 base64，跑通再换二进制帧 | 0.5 人日 |
| 5 | 同上 | 断流检测：3 s 无新帧 → 回落到本地 EAF/GIF 兜底脸（**必须有**） | 0.5 人日 |
| 6 | `main/Kconfig.projbuild` | `CONFIG_AVATAR_STREAM`（默认 n） | 0.1 人日 |

**关键约束（别人踩过的坑）**：**不要用 `esp_timer` 任务直接 `esp_lcd_panel_draw_bitmap()` 绕过 LVGL**——`Baji_Rtc_Toy` 实测 320×320 时 SPI 队列溢出、屏幕闪烁，最终弃用（其文档坑 8）。必须走 LVGL 的 image 对象，让 flush 在自己的节奏里跑。

### 5.2 服务端要做什么

| 项 | 做法 |
| --- | --- |
| 编码 | 480×320、JPEG q70–75、4:2:0、**baseline（不能 progressive）**；`esp_new_jpeg` 不支持 progressive，LVGL/我们的解码器同样只吃 baseline |
| 帧率 | 12 fps 起（不是 30）。人眼对「嘴动 + 眼神」的容忍下限约 10 fps，12 fps 足够「像视频」 |
| 口型 | 用 TTS 的 PCM 包络（RMS，3 档）驱动口型图，而不是等 ASR/字时间戳——参考 Baji 的 `sprites_set_mouth(level)` 做法 |
| 推送 | 只在「speaking / listening / thinking」推；idle 停推并让设备放本地循环脸（省带宽 + 断网无感） |
| 编码预算 | PC 上 480×320 q75 编码 < 5 ms/帧，单核可跑 100+ fps，**不是瓶颈** |
| 缓存 | 同一表情的短循环（2–3 s）预编码成 24–36 帧，循环推同一组，避免每帧重编码 |

### 5.3 PSRAM / 带宽 / 延迟估算

```
单帧 RGB565        = 480 × 320 × 2      = 307,200 B
双缓冲             = 614,400 B          (8 MB PSRAM 的 7.3%)
JPEG 输入缓冲      = 32 KB × 2
解码工作区         = ~40 KB（esp_new_jpeg 常量 10 KB DRAM + 行缓冲）
────────────────────────────────────────
合计              ≈ 720 KB PSRAM

带宽 = 22.7 KB × 12 fps = 272 KB/s = 2.2 Mbps
（2.4 GHz 802.11n 实测 TCP 常见 5–15 Mbps → 余量 2–7×）

解码 = 1/36.29 s = 27.6 ms/帧 → 12 fps 占单核 33%
显示 = 307 KB/帧 DMA 到 SPI（40 MHz ≈ 5 MB/s）→ 61 ms/帧 ← **这才是真瓶颈**
```

**注意最后一行**：SPI 40 MHz 刷一整屏 307 KB 要 ~61 ms，理论上限 **16 fps**。所以 12 fps 是这条链路的**物理上限附近**，不要再往上加。若想更高，只能缩小画面区域（例如只传脸部 320×228 = 146 KB/帧，可到 30 fps），这也是「半身像 + 纯色背景」比「全屏视频」更现实的原因。

### 5.4 断网兜底（必须有，否则设备变砖头）

1. 帧超时 3 s → 切本地 EAF/GIF 脸（C1/C2 的资产仍在 assets 里，**两条路线可共存**）。
2. 顶部状态文字加「（离线）」后缀——沿用本项目已有的「状态 + 可信度」写法。
3. 恢复推流时**不闪白**：新帧先写后台缓冲，解码成功再交换指针。

### 5.5 验收判据（可检验）

- [ ] 连续推流 10 分钟，`free_heap` 不单调下降（无泄漏），PSRAM 占用稳定在 720 KB ± 50 KB
- [ ] 端到端延迟（服务端时间戳 → 屏幕可见）< 150 ms，用高速摄影/拍屏计时验证
- [ ] TTS 播放期间无卡顿、无破音（与 Opus 解码共存）
- [ ] 拔网线 3 s 内回到本地脸，插回 2 s 内恢复推流
- [ ] 静置 10 分钟 WS 不掉（**这条不过，整个 B 不成立**）

---

## 6. 不该抄的（形象与资产部分）

> 与 §2.5「AI Passport 里不该抄的」互补：那一节讲交互，这一节讲**形象与实现路径**。

| 不该做 | 为什么 | 证据 |
| --- | --- | --- |
| **继续自绘/参数化画脸** | 9哥 已明确否决两次（「太难看了」「你自己整不了」）。自绘的天花板是「图形感强、生物感弱」，而现成 Live2D 素材的下限就比它高 | 9哥 原话 + §2.6 的现状截图测量（眼睛是 84×84 圆角方块） |
| **把 EAF 塞进 LVGL 的 `emoji_collection`** | `assets.cc:348` 只处理 `NULL == eaf` 的条目，带 `eaf` 字段会被静默跳过，**图不显示还不报错** | 本机源码 `main/assets.cc:343-356` |
| **用 `esp_timer` 直接 `esp_lcd_panel_draw_bitmap()` 绕 LVGL** | 与 LVGL flush 抢 SPI，320×320 就队列溢出、黑屏闪烁 | Baji_Rtc_Toy 文档「坑 8」 |
| **用 PIL 处理透明 GIF** | `Image.quantize()` 丢 alpha，且动画 GIF 只有首帧带 transparency → 从第二帧起黑底 | Baji_Rtc_Toy「坑 1」 |
| **`gifsicle --colors 64 --lossy=80`** | 锯齿明显、色带断层；为了省空间把观感做没了，与本任务目标相反 | Baji_Rtc_Toy「坑 5」+ §18.6 画质表 |
| **只按第一帧算包围盒裁剪** | 动作中人物会移出裁剪框，切换表情时「跳一下」 | Baji_Rtc_Toy「坑 6」 |
| **21 套高清 GIF 全量塞 8 MB** | 2.3 MB × 21 = 48 MB。要么砍表情数，要么换 EAF，要么复用 | §4.1/§4.3 的体积计算 |
| **直接上 C3 官方 emote 变体当主线** | 官方布局无 480×320，`eye_anim` 写死 → 偏左上 + 右侧 160 px 空白；且接管 flush 后**字幕和状态栏消失**，等于退回「只会做表情的音箱」 | `docs/HANDOFF.md` 2026-10-27「布局风险」段 |
| **为了「真人」先做推流、后修保活** | 当前静置 RTT 789–840 ms、数十秒断连；视频流会把这个问题放大成「脸一直卡住」 | `docs/HANDOFF.md` 2026-10-28 |
| **抄 Moflin 的「无屏」路线** | 它靠毛绒 + 微动 + 声音成立，我们已经有屏且 9哥 要的是「屏上有个形象」 | §3.4 |

---

## 附：本轮来源与实测命令

### 实测（本机，2026-10-28）

```bash
# EAF 资产：数量/体积
ls -l 05_Tools/xiaozhi-esp32/managed_components/espressif2022__esp_emote_assets/emoji_large/*.eaf
# → 10 个，合计 1.18 MB；Happy.eaf 81,645 B

# EAF 头：帧数 / 分辨率 / 色深（按 gfx_eaf_dec.h 的偏移解析）
python3 -c "..."   # EAF_NUM_OFFSET=4；frame: bd@9, w@10, h@12, blocks@14, block_h@16
# → Happy 43 帧 125×160 8-bit；neutral 89 帧；confused 78 帧

# JPEG 单帧体积（480×320）
python3 - <<'EOF'  # PIL, quality=75, subsampling=2(4:2:0), optimize
# 真人照片 22,705 B；q60 16,794 B；q85 31,335 B
# 真机截图（扁平 UI）9,499–13,937 B
EOF

# assets 现状
ls -l 05_Tools/xiaozhi-esp32/build-chd/generated_assets.bin   # 269,881 B
```

### 本机源码依据

- `05_Tools/xiaozhi-esp32/main/display/lcd_display.cc:1229-1250`（GIF 表情播放）
- `05_Tools/xiaozhi-esp32/main/assets.cc:338-365`（`emoji_collection` 解析，`eaf` 条目被跳过）
- `05_Tools/xiaozhi-esp32/main/display/lcd_display.cc:915-929`（`emoji_box_` / `emoji_image_` 居中）
- `05_Tools/xiaozhi-esp32/main/boards/chd/chd-esp32s3-box/chd_esp32s3_box_board.cc:251+`（自绘脸替换官方 emoji 的位置）
- `05_Tools/xiaozhi-esp32/main/boards/chd/chd-esp32s3-box/config.json`（`chd-esp32s3-box-lcd35-emote` 变体）
- `05_Tools/xiaozhi-esp32/partitions/v2/16m.csv`（`ota_0` 0x3f0000 / `assets` 0x800000 8M）
- `05_Tools/xiaozhi-esp32/managed_components/espressif2022__esp_emote_gfx/src/lib/eaf/gfx_eaf_dec.{h,c}`（EAF 格式与编码）
- `01_Code/projects/esp32-voice-entry/docs/HANDOFF.md`（emote 变体实测 2,590,384 B、布局风险、WS 抖动）

### 外部来源

- 小智自定义 Assets 工具（21 表情 / GIF / PNG）：<https://github.com/78/xiaozhi-assets-generator>
- 抖音自定义主题教程（21 表情、上传动态图、生成配置、数据线刷入）：<https://www.douyin.com/shipin/7618753167249164351>
- EAF 在线转换工具（GIF → EAF）：<https://esp32-gif.espressif.com/>
- `esp_lv_eaf_player`（LVGL v8/v9 的 EAF 播放控件，Apache-2.0）：<https://components.espressif.com/components/espressif/esp_lv_eaf_player>
- 乐鑫 GUI 优化方案（EAF/emote_gfx/expression 定位与适用场景）：<https://documentation.espressif.com/projects/esp-iot-solution/zh_CN/latest/display/lcd/gui_solution.html>
- `esp_new_jpeg` 性能基准（S3：480×320 解码 36.29 fps / 编码 24.35 fps）：<https://github.com/espressif/esp-adf-libs/blob/89aa3c39/esp_new_jpeg/README.md>
- ESP32-S3 无硬件 JPEG/GIF 解码、PIE 128-bit SIMD 与带宽估算：`Baji_Rtc_Toy`《数字人表情渲染方案》<https://gitea.airlabs.art/Rdzleo/Baji_Rtc_Toy/>
- Live2D → GIF 全流程与 8 个坑（含 `hiyori_m06.eaf` 505 KB）：同上文档 §十八
- EchoEar 硬件（1.85" 360×360 圆屏、双麦、ESP32-S3）：<https://documentation.espressif.com/esp-dev-kits/zh_CN/latest/esp32s3/esp-dev-kits-zh_CN-master-esp32s3.pdf>
- EchoEar 使用官方 emote/EAF（`USE_EMOTE_MESSAGE_STYLE`）：上游 PR #1203 <https://github.com/78/xiaozhi-esp32/pull/1203>、`main/boards/echoear` 配置说明
- Stack-chan 官方固件与表情：<https://docs.m5stack.com/zh_CN/StackChan>
- Stack-chan 表情资源制作工具（320×240）：<https://github.com/tegnike/stackface-maker>
- Moflin（无屏、毛绒、行为表达）：<https://www.notebookcheck-cn.com/Moflin.1082426.0.html>
- TEN-Agent + Trulience 数字人（浏览器侧渲染，非设备侧）：<https://www.uied.cn/posts/95835>
