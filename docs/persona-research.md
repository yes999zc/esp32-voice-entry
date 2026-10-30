# 人格层调研：来源、借鉴与硬事实

日期：2026-10-27 · 对应里程碑：`ROADMAP.md` → `## M7 · 人格层（桌上的同事）`

目的：M7 要回答「桌上同事该长什么样、什么时候该开口」。这份文档把参考来源、
每个来源里**借鉴什么 / 抄不抄 / 为什么**、以及从固件源码核实的硬事实写下来，
供 Step 1–5 直接引用，也供后来的人不必重跑一遍调研。

## 0. 结论先行

1. **脸用 `lvgl_kawaii_face` 的引擎，但不用它的萌宠视觉**：眨眼/眼球/嘴型的
   动画状态机直接复用，配色、几何、表情语义由我们定。
2. **状态词表以 rui 的九态命名为基底**（`LED_STATES`）；M7 复用其中四项
   （`off`→idle、listening、thinking、speaking），再加上本项目的 tool-running /
   confirm-pending，映射只允许有一处定义。
3. **主动性 v0 不引入 LLM 判定**：4 类白名单触发 + 6 道确定性闸门；宁可不动，
   不可乱动。ProPerAgent 的「先判断该不该主动」只作为设计原则，不搬它的双 agent
   流水线。
4. **表情推送走 `{"type":"llm","emotion":...}`**，固件在任何设备状态都放行
   （`main/application.cc:683-689`）；`notify` 只在 Idle 接受，且 TTS 结束后设备
   回到 Listening，所以 WS 下主动播报结构不可用（M6-e 已实测）。
5. **设备完全 Idle 时没有可推的会话**，因此「主动开口」不能只靠 emotion 推送；
   是否换 MQTT+UDP 或做端侧保活，交给 Step 4 出结论、9 哥 拍板。
6. **不改分区表**：16 MB 板上 `ota_0` 余量约 1.26 MiB，够 Step 1 用；一旦改分区，
   首次升级必须 USB 迁移，OTA 不行（xiaozhi-robot 的教训，见 §5.3）。

---

## 1. 来源 A：xiaozhi-robot（同源定制固件，MIT）

- 仓库：<https://github.com/malongan/xiaozhi-robot>
- 性质：上游 `78/xiaozhi-esp32` 的定制分支（`avatar-5line`），MIT，保留上游
  LICENSE 与署名；作者在 README 里持续记录版本说明与复盘。
- 关键能力（README，2026-10-27 读取）：
  - 竖屏 240×320 **白色程序化圆脸**：眨眼 / 视线 / 表情 / 睡眠；
  - 6 行分页聊天、卡片式设置页与网络页、BLE HID 键盘、Wi-Fi 传文件、TF 卡笔顺；
  - 16 MB 板自 2026-10-22 起改为 **6 MB app + 4 MB assets** 分区；
  - **首次从旧版升级必须 USB 迁移分区，不能只 OTA**。

**借鉴什么**

- 「脸」是**程序化绘制**而不是位图表情包：同一套几何参数驱动眨眼、视线和表情，
  体积小、可连续插值——这正是 480×320 常驻脸需要的形态。
- UI 替换发生在**显示层**（`display` / board 的 `SetupUI`），不动音频与协议栈；
  与我们「固件只做 BSP，智能在服务端」的边界一致。
- 分区变更的代价被明确写在 README 第一屏——这是一条应该被抄走的**交付纪律**：
  会破坏 OTA 的改动必须提前说，并给出 USB 迁移路径。

**抄不抄**

- **抄**：程序化脸的实现思路、显示层替换位置、分区/升级的教训。
- **不抄**：竖屏 240×320 的版式、6 行聊天记录、设置页、BLE 键盘、TF 卡学习功能。
  我们是 480×320 横屏桌面同事，不是带键盘的随身设备；聊天记录铺屏正是 M7
  明确不要的「卡片/仪表盘式界面」。
- **不抄它的分区表**：6 MB app + 4 MB assets 是为它的功能包服务的；我们现有
  `partitions/v2/16m.csv` 的 `ota_0` = 0x3f0000（4,128,768 B），Step 1 前基线
  `build/xiaozhi.bin` = 2,786,080 B，现测 2,804,624 B（含 face 组件），余量
  ≈1.26 MiB，Step 1 不需要动分区（见 §5.3）。

**为什么**：这个项目证明「在 xiaozhi 固件上换一张常驻脸」是可行的，而且踩过
分区迁移的坑。我们借的是**可行性证据与教训**，不是它的产品形态。

---

## 2. 来源 B：lvgl_kawaii_face（表情组件，MIT）

- 仓库：<https://github.com/0015/lvgl_kawaii_face>
- 组件仓库：<https://components.espressif.com/components/0015/lvgl_kawaii_face>
  （v1.0.0，MIT，archive ≈18.51 KB，17 种情绪，动态眼/嘴/sparkle 动画）
- 引入方式（Step 1 决定）：作为**本地 ESP-IDF component** 放进
  `05_Tools/xiaozhi-esp32/components/lvgl_kawaii_face/`，不走 registry 依赖，
  版本与本地补丁在固件仓库里可见；保留原始 `LICENSE` 与版权头。
- 已核实的工程约束（Step 1 卡片）：
  - LVGL 9 组件，我们用 LVGL 9.5.0，无版本冲突；
  - 编译产物 ≈18.4 KB flash + 114 B 静态 RAM；
  - 运行时 3 个 RGB565 canvas：父对象短边 S 时
    `2×(0.45S)²×2 B + (0.45S)(0.38S)×2 B = 1.152S² B`；S=320 时 **117,965 B**
    （≈115 KiB）。上游默认优先内部 RAM（`lvgl_kawaii_face.c:26-38`）；本仓已打
    PSRAM 优先补丁（`components/lvgl_kawaii_face/LOCAL_PATCHES.md` §1），画布从
    PSRAM 分配，不占 AFE/WakeNet 的内部 RAM 预留。

**借鉴什么**

- 动画状态机（眨眼节奏、眼球跟随、嘴型插值）与 17 个情绪的几何参数；
- 「一个组件、一组枚举、一个 `SetEmotion` 入口」的接口形状——与固件现有的
  `Display::SetEmotion(const char*)` 天然对齐。

**抄不抄**

- **抄**：引擎、状态机、组件化引入方式、表情枚举 → `face_emotion_t` 的映射。
- **不抄**：kawaii 视觉语言本身——爱心眼、腮红、满屏 sparkle、夸张卖萌。
- **要改**：调色板、眼睛/嘴的比例、情绪语义按「克制、可读、像人」重调；
  只保留可作为「同事」的表达（中性、在听、在想、在说、疑惑、被打断）。

**为什么**：这是唯一一个 MIT、LVGL 9、编译体积可接受、且直接提供
`SetEmotion` 语义的现成组件；重写一遍动画状态机没有收益。但 M7 的验收里
「不要萌宠式表情」是硬边界，所以**用引擎不用皮肤**。

---

## 3. 来源 C：OpenDeskBotV2（产品参考，非 MIT）

- 仓库：<https://github.com/tudoom/OpenDeskBotV2>（桌面机器人「小歪」）
- 许可：firmware / service **GPL-3.0**，hardware **CERN-OHL-S-2.0**
  （与本仓库 MIT 不兼容，**只读参考，不抄任何代码或素材**）。
- 关键行为（README，2026-10-27 读取）：
  - 「听见 → 听懂 → 回应 → 表情与动作 → **主动陪伴**」；
  - 表情按待机 / 倾听 / 思考 / 说话成套应用，另有 AI 生成位图表情与「表演」
    （表情 + 动作 + 语音的组合）；
  - 主动陪伴：冷场时主动开口、日常关心可定时、小目标按顺序推进；
  - 设备默认 USB 连本机服务，配网后 Wi-Fi 回连，**USB 始终优先**；
  - 所有服务只绑 `127.0.0.1`，机器人不访问云。

**借鉴什么**

- **状态-表情成套**的产品直觉：待机 / 倾听 / 思考 / 说话四态是用户能立刻读懂的
  最小集合；我们在 Step 2 扩到六态（加 tool-running / confirm-pending）。
- **主动陪伴的触发清单**：冷场、定时关心、小目标推进——可以对照我们的四类白名单
  （任务完成 / 定时提醒 / 问过的事有结果 / 待确认动作超时）检查有没有漏。
- **USB 优先、本机服务、不连云**的部署取向，与我们「服务在 Mac、板子是身体」
  一致；它验证了这条路线的产品可行性。
- 它把「主动」做成可配置场景而不是随机插话——这正是 Step 3 那组闸门（实现为 7 道）要解决的问题。

**抄不抄**

- **抄**：四态表情的产品分层、主动陪伴的触发类别、USB/本机优先的部署原则。
- **不抄**：GPL 代码与素材；舵机头部动作（我们没有舵机）；AI 生成位图表情与
  「表演」编排（Step 1–3 不需要，且会把注意力从「像人」拉到「像玩具」）；
  「冷场就开口」的无闸门策略（会直接违反 Step 3 的误触发 0 次）。
- **不抄**它的客户端形态：一键安装的桌面客户端 + 控制台不是我们的交付物。

**为什么**：它是目前最接近「桌面同事」的完整产品，适合当**行为基准**；
但许可证和硬件都不同，只能借问题清单和取舍，不能借实现。

---

## 4. 来源 D：ProPerAgent（论文，主动性的判断框架）

- 论文：Kaur, Gupta, Gupta, Shah. *PROPER Agents: Proactivity Driven
  Personalized Agents for Advancing Knowledge Gap Navigation.*
  Findings of ACL 2026, pp. 41951–41975.
  <https://aclanthology.org/2026.findings-acl.2082/>
- 代码：<https://github.com/i-kiran/ProPer-Agent>
- 核心：不把「主动」等同于「多说一句」，而是显式建模用户的**知识缺口**——
  DGA 从 query 提取显式维度并生成隐式维度，RGA 选择性整合，产出个性化、
  主动但不越界的回答；评估用 gap-aware rubric（coverage、initiative
  appropriateness、intent alignment）。

**借鉴什么**

- **开口前先判断「该不该主动」**：主动性的失败模式不是「没说话」，而是
  「在不合适的时刻说了不合适的话」。Step 3 的闸门（实现为 7 道）就是这条原则的确定性版本。
- **initiative appropriateness 作为评估维度**：除了「触发了几次」，还要看
  「这几次是否合适」。30 分钟误触发 0 次是下限，不是全部。
- **显式维度**的思路可以借到触发判定：例如「任务完成」要先确认用户是否还在等
  这个结果、是否已经通过别的通道知道了——这就是我们的「问过的事有结果」触发。

**抄不抄**

- **不抄** DGA/RGA 双 agent 流水线：每一步都要额外 LLM 调用，延迟与成本不可接受，
  且 v0 的触发是确定性的四类事件，不需要开放式推断。
- **不抄**它的知识缺口建模与数据集：那是问答/任务完成场景，不是桌面陪伴。
- **抄**判断顺序与评估语言：先问「此刻合适吗」，再问「说什么」。

**为什么**：M7 的主动性必须是**可解释、可复现**的（误触发 0 次是硬指标），
论文给的是判断框架和评估维度，不是可以直接落地的代码。

---

## 5. 硬事实（源码级，固件 `f1f4ea2`）

### 5.1 `{"type":"llm","emotion":...}` 在任何设备状态都放行

`main/application.cc:683-689`：

```cpp
} else if (strcmp(type->valuestring, "llm") == 0) {
    auto emotion = cJSON_GetObjectItem(root, "emotion");
    if (cJSON_IsString(emotion)) {
        Schedule([display, emotion_str = std::string(emotion->valuestring)]() {
            display->SetEmotion(emotion_str.c_str());
        });
    }
}
```

这里**没有设备状态判断**：只要 WS 消息能到，`SetEmotion` 就会执行。未知名字由
显示层忽略/回落（具体回落行为在 Step 1 的真机测试里确认）。

对照 `notify`：`main/application.cc:1183-1184` 明确要求
`GetDeviceState() == kDeviceStateIdle`，否则打印
`Ignoring notify message while device is busy`。而 TTS 结束时设备回到的是
`Listening` 而不是 `Idle`（`main/application.cc:642-650`，非 manual-stop 模式），
所以**会话开着时 notify 永远收不到**——这是 M6-e 的真因，也是 Step 3 选择
「先动脸、走屏幕通道」而不是 `notify` 的原因。

### 5.2 WS 在 Idle 没有可用的会话

WS 这一路是**会话级**的：

- 唤醒/开始对话时才建立音频通道（`main/application.cc:857-880`；
  `ContinueOpenAudioChannel`）；
- 一轮结束、停止监听后设备回到 `Idle`（`main/application.cc:893-908`，
  `SendStopListening()` + `SetDeviceState(kDeviceStateIdle)`）；
- 通道是否「开着」还包含超时判断：`websocket_protocol.cc:70-72`
  的 `IsAudioChannelOpened()` = connected && !error && **!IsTimeout()**。

因此：**设备完全 Idle 待机时，服务端没有一个可推的活跃会话**，
`/debug/emotion` 只能落到 `sent: 0`。表情推送的有效窗口是
Connecting / Listening / Speaking / 工具执行等会话进行中的状态。

M7 的含义：

- Step 1/2 的「推表情」足够用——那时人正在和它交互，会话开着；
- Step 3 的「主动开口」在设备完全待机时不成立，**必须**由 Step 4 回答：
  换 MQTT+UDP，还是端侧保活一条控制通道；
- 在那之前，「主动」只能做到「下一次交互时先动脸」或「排队到下次连上」。

### 5.3 xiaozhi-robot 的分区与「首次升级必须 USB」结论

来源：xiaozhi-robot README 首屏（2026-10-27 读取）：

> 2026-10-22 起 16MB 板改用 6MB app + 4MB assets 分区；首次从旧版升级需
> USB 迁移分区，不能只 OTA。

上游 `78/xiaozhi-esp32` 的 `partitions/v2/README.md` 在「Migration from v1」里
只写了「Flash New Partition Table」；「v1 无法通过 OTA 升到 v2」是我们基于
分区表不兼容的推论——分区表不在应用 OTA 镜像里，必须另烧。

对本案：

- 我们的板子也是 16 MB，分区表在 `partitions/v2/16m.csv`：
  `ota_0` / `ota_1` 各 0x3f0000 = **4,128,768 B**，`assets` 8 MB；
- 当前 `build/xiaozhi.bin`：Step 1 前基线 **2,786,080 B** → 现测 **2,804,624 B**
  （含 face 组件），`ota_0` 余量 ≈ **1.26 MiB**；
- Step 1 只加一个 ≈18.4 KB 的组件 + 一张脸，**不需要改分区表**；
- 结论：**不碰分区 = 不触发 USB 迁移**。将来若确实要改分区（例如 app 超过
  4 MB），必须按「先备份 16 MB → USB 全量烧录 → 再恢复 OTA」的路径做，
  并提前告知 9 哥（这会中断 OTA 升级链）。

---

## 6. 对 M7 各 Step 的直接影响

| Step | 采用的结论 | 来源 |
| --- | --- | --- |
| 1 换脸 | 用 lvgl_kawaii_face 引擎、本地 component + PSRAM 优先补丁（`LOCAL_PATCHES.md` §1）；不改分区 | B、A、§5.3 |
| 2 状态-表情 | 六态映射；词表对齐 rui `LED_STATES`；打断要有 surprised/attentive | 项目内 rui、C |
| 3 主动性 v0 | 4 类白名单 + 6 道闸门；先动脸再动嘴；不用 notify | A、C、D、§5.1 |
| 4 传输层 | 完全 Idle 推不到是结构问题；MQTT+UDP vs 端侧保活二选一，9 哥 拍板 | §5.2 |
| 5 固件独立性 | 显示层改动集中、可裁；上游同步成本按「保留/删除/跟随」分类 | A、本项目固件分支实践 |

## 7. 来源清单

| # | 来源 | 许可 | 用途 |
| --- | --- | --- | --- |
| A | <https://github.com/malongan/xiaozhi-robot> | MIT | 程序化脸、显示层替换、分区迁移教训 |
| B | <https://github.com/0015/lvgl_kawaii_face> · [registry](https://components.espressif.com/components/0015/lvgl_kawaii_face) | MIT | 表情组件（本地 component） |
| C | <https://github.com/tudoom/OpenDeskBotV2> | GPL-3.0 / CERN-OHL-S-2.0 | 产品行为参考（只读，不抄代码） |
| D | <https://aclanthology.org/2026.findings-acl.2082/> · <https://github.com/i-kiran/ProPer-Agent> | 论文/代码各自许可 | 主动性判断框架与评估维度 |
| — | 本地 `01_Code/projects/house-ear`（rui，public `yes999zc/rui`） | MIT | 状态词表、VAD/时序、音效确认、唤醒确认上限、延迟测量方法（详见 README Credits） |
| — | 固件 `05_Tools/xiaozhi-esp32` @ `f1f4ea2` | MIT | 行为事实（emotion / notify / 会话生命周期） |

## 6. 现成表情方案对比（2026-10-27 调研，9哥 要求「找现成包」）

| 方案 | 许可 | flash | RAM | 6 态 | 人日 | 关键风险 |
|---|---|---|---|---|---|---|
| **lvgl_kawaii_face**（已接入 = 我们现在的脸） | MIT | 20–40 KB | 21 KB @135px / 118 KB @320px（内部 RAM 优先） | ✓ 17 种 | 0.5–1 | 320px 时形状偏"敦实"；无口型 |
| **lv_lottie + Noto Animated Emoji** | LVGL/ThorVG MIT；Noto **CC BY 4.0** | ThorVG 150–400 KB（未实测）+ 6 JSON 196 KB | 4×w×h：240² 230 KB / 320² 410 KB | ✓ 6 个 | 2–3 | ThorVG 体积/堆未实测；480×320 帧率低（估 12–18 fps）；需 CC BY 署名 |
| **esp_emote_expression**（官方，已是我们的依赖） | Apache-2.0 | 代码 200–300 KB + EAF 1.2 MB（可放 assets 分区） | ~31 KB 行缓冲 + 解码 40–80 KB | ✓✓ 20 名字→10 EAF，20 fps | 3–5 | **不是 LVGL：接管 panel/flush**；布局按 360×360；IDF 6.1 未验证 |
| lv_animimg（帧序列） | MIT | 128² RGB565 32 KB/帧 × 帧数 | ≈0 | ✓ 取决素材 | 1–2 + 美术 | 全屏 480×320 单帧 307 KB，不可行 |
| lv_gif | MIT | GIF 文件大小 | 25 KB + 3×w×h（480×320 ≈ 486 KB） | ✓ 取决素材 | 0.5–1 + 美术 | 256 色/抖动，解码 CPU |
| RoboEyes | **GPL-3.0** | ~10 KB | ~2 KB | △ 只有眼 | 2–3 移植 | GPL 传染；Arduino 单色 |
| M5Stack-Avatar | MIT | ~30 KB | 2×全屏 sprite 150–300 KB | △ 6 表情 + 口型 | 3–4 移植 | 依赖 M5GFX，非 LVGL |

**决策（2026-10-27）**：先做 **官方 esp_emote_expression 的可切换 spike**（task-12）——
它已在依赖里、有 20 种动画表情、资产可放 8 MB 分区，代价是整屏交给它（放弃 LVGL UI）、
且 IDF 6.1/480×320 未验证。**若半天内不能干净跑通就止损**，改走 **lv_lottie + Noto**（视觉最好、
仍在 LVGL 内、许可干净），自绘 kawaii 保留可切回。
**不要**再花时间在手绘 canvas 的造型上。

## 7. 三队调研汇总（2026-10-27，9哥 要「日漫/真人形象 + 带字幕」）

> **2026-10-28 状态：形象路线仍未拍板。**
> **待确认：真人程度（照片级 / 半写实 / 日漫）未落盘。**
> 「9哥 已决定形象用真人」在本项目里**没有任何记录**（无会议纪要、无 task 卡、无 commit），**不得当已定**。
> 本节真正可用的结论只有两条：**日漫差分立绘推荐**（许可干净、<0.5 MB、能眨眼/口型）；
> **真人照片许可高风险**（图库许可 ≠ 模特授权，CC0 只放弃版权不放弃肖像权）。
> 形象是独立线，M7 Step 2（六状态表情）不碰形象选型。

### 结论表
| 路线 | 素材许可 | 体积（8 表情） | 实时眨眼/口型 | 判断 |
|---|---|---|---|---|
| **2D 差分立绘（日漫）** | CC-BY（商用仅需署名，如 `Xiael Tia`） | **<0.5 MB**（8 底图 + 眼睑 + 3 嘴型） | ✅ 都能 | **推荐：唯一同时满足好看+能反应+许可干净** |
| 半写实 3D 渲染成 2D | 自有/委托版权（最安全） | ≈0.4 MB | ✅ | "像人但不写真"时选，工作量大 |
| 真人照片（静帧+3嘴型） | **高风险**：图库许可 ≠ 模特授权 | ≈0.4 MB | ✅ | 不建议 |
| 官方卡通 EAF | 素材仓库**无 LICENSE** | 0.5–1 MB | ❌ 死帧 | 仅验证管线，不可当产品素材 |

### 硬约束（不是取舍，是物理）
- **320×320 RGB565 × 160 帧 = 32 MB**；240² 也要 17.6 MB → 8 MB 分区装不下全帧动画。
- 240² JPEG q80 × 192 帧 = 1.5–2.0 MB（放得下），但**解码 56–60 ms/帧 → 15–18 fps**；320² 需 100–120 ms → **8–10 fps**。
  → 「真人 24 fps 说话脸」在这块板上做不到。**正确做法是分层**（底图 + 贴片），不是烘帧。
- LVGL 9 **自带 TJPGD**（`LV_USE_TJPGD`），S3 还有 ROM JPEG 解码器 —— 所以问题从来不是"能不能解 JPEG"，是解得太慢。（本项目 sdkconfig 里 TJPGD 当前为 n，需要时打开即可。）

### 颜色/许可雷区（已核实，别再踩）
- **`AvatarSample_A/B` 不是 CC0**：允许营利创作，但**禁止有偿再分发模型内图像数据**（airi 等开源项目内置它，不能照抄素材）。
- **Live2D 官方 sample（Hiyori/Mao/Haru）** 是 Free Material License：年销<1000 万日元可商用、禁止再分发原始素材 → **烘帧嵌入商用硬件属灰区**，仅可做原型。
- **RPG Maker RTP/立绘**明文禁止移植到其他引擎。
- **AI-Vtuber 项目 GPL-3.0**，代码不可进闭源固件。
- Unsplash/Pexels 许可 ≠ 模特授权；CC0 只放弃版权不放弃肖像权。中国《民法典》1018–1023 + 深度合成规定要求单独同意。
- 口型项目：`Wav2Lip`/`Sonic` 非商用；`MuseTalk` MIT 可用；`LivePortrait` MIT 但需替换 InsightFace 检测器；`SadTalker` 名义 Apache-2.0 但旧 checkpoint 含 wav2lip 权重，需审计。

### 字幕（三队一致）
**没有任何项目把字幕画进脸里**，全是「角色层 + 独立文字层」。官方 emote 那版 `emote_display.cc:202` 的 `SetChatMessage` **只打日志、不显示字幕** → 要字幕必须留在 LVGL 变体。
480×320 推荐布局：脸 228 + 底部 464×84 字幕条（30px/4bpp 中文，15 字/行 × 2 行 = 30 字），空闲时脸下移 46 px；打字机 10–12 字/秒；**不做逐字卡拉 OK**（无字级时间戳）。
- `esp_lv_eaf_player` 可在 **LVGL 内**播 EAF 动画（不同于 `esp_emote_expression` 接管整屏）→ 若将来走 EAF 脸，字幕仍可保留。
