# 卡｜ABCD 四视图问题调研（ESP32 桌面小智）

- 日期：2026-10-29
- 类型：调研卡（不直接改代码；结论经 9哥 认可后再开修复卡）
- 板上固件：`v2.5.3-persona.2` release 资产（sha256 `a67645c8…eeab4`，app 0x20000，NVS/Wi-Fi 保留）

## 背景

9哥 已要求把板子从最新版（persona.3 / D3）回滚到**上一版 release `v2.5.3-persona.2`**；回滚后设备可用（静音/触摸正常），但 **ABCD 四个视图有问题**。

已知线索（git 核对）：`v2.5.3-persona.2` **不含** persona.3 的三个 UI 修复，也不含静音后唤醒恢复：

- `d2d47c7` hide dino outside A、guard config tap、route label taps
- `175056b` A 视图标题改用 CJK 字体
- `0a43f23` D 游戏视图抬到 B1 图层之上
- `e6b7c1b` 解除静音后无条件恢复唤醒词

## 交接入口（新会话第一步）

1. 先读 **`01_Code/projects/esp32-voice-entry/docs/HANDOFF.md`**（板上固件=persona.2、D3 在 main 未上板、回滚锚、禁止项、接续模板都在里面）。
2. 再读 **本卡**：`01_Code/projects/esp32-voice-entry/docs/tasks/2026-10-29-abcd-views-investigation.md`（本文件是权威版；聊天里的粘贴版只是摘要）。
3. 再建/领任务卡开工；进度以团队任务板 + HANDOFF 为准，不靠聊天记忆。

## 编程方式（必须，9哥 指定）

- 用我们自己做的团队编程插件：**预设「Dev Team · 单仓库」**（`dev-team`，位于 `01_Code/tools/dsh-dev-team/`）。
  新会话创建时选这个预设，不要用标准单 agent 硬干。
- 角色：Lead（拆卡/派工/读关键 diff/集成/最终验收）+ implementer + reviewer + verifier；
  评审者 ≠ 实现者；任务未过 reviewer PASS + verifier VERIFIED 不得 complete。
- 单仓：本卡所有代码改动只在 `05_Tools/xiaozhi-esp32`（固件仓）；**不改 `01_Code/projects/esp32-voice-entry` 的代码**
  （只允许读它和写本卡/HANDOFF 记录）。
- 开工顺序：任务板建卡（含背景/目标/验收/write_scopes/blocked_by/评审者/证据要求）→ 派工 → 评审 → 验证 → commit。
- 阶段收口：更新 `01_Code/projects/esp32-voice-entry/docs/HANDOFF.md`（版本与契约 / 已完成 / 下一步）+ phase-close 标记。
- Lead 必须亲自看关键 diff 和真实命令输出，不能只看队友总结。

## 现象（真机，persona.2）

9哥 反馈：**ABCD 四个视图都有问题，主要问题在「谷歌小恐龙」的配置**。逐视图待复现：

- A：底部恐龙条（`dino_root_`）—— 是否显示/位置/缩放/颜色不对
- B：不应出现恐龙（persona.3 修过 `d2d47c7` hide dino outside A）—— 是否残留/遮挡
- C：同上（不应出现恐龙）
- D：恐龙游戏视图（`game_view_`）—— 是否被压层/不可见、地面/仙人掌/翼龙/分数/帧序列配置不对

## 要调研并产出

1. 逐视图 A/B/C/D 真机复现：截图（`/admin` 截屏或相机）、串口日志、服务端日志；
2. 每个视图列：现象 → 期望 → 是否 persona.2 回滚丢失（对照上面 4 个 commit）→ 建议修法/工作量；
3. 每个恐龙缺陷标注：**编码问题**（A8 cf/stride/尺寸/data_size）还是**配置问题**（位置/缩放/recolor/可见性/层级/GameTick）；
4. 判断 persona.3 的 UI 修复能否**单独重做到 persona.2**，且不引入 D3 触摸回归、不动 mute 逻辑；
5. 输出修复顺序建议（可拆卡），并标出哪些属于 persona.2 自身缺陷、哪些是回滚丢失。

## 写范围（调研阶段）

- 只读：`05_Tools/xiaozhi-esp32`（main 现为 `64d13ba`，但板上是 persona.2）、`src/`、`docs/`；
- 如需落文档：`01_Code/projects/esp32-voice-entry/docs/`。

## 禁止

- 调研卡**不刷机、不改固件代码**；确需刷机复现时只刷 app `0x20000`，**不要写 0x0**（会清 NVS/Wi-Fi）；
- 不动触摸过滤器（D3 `64d13ba` 在 main 但未上板；当前 persona.2 触摸正常，别碰）；
- 不动 mute 语义与服务端静音真相；不碰两个桥仓；不删既有测试当绿。

## 证据要求

- 每视图 ≥1 张真机截图 + 复现步骤 + 关键串口/服务端日志行；
- 对照命令：`git log --oneline v2.5.3-persona.2..v2.5.3-persona.3`；
- 结论区分「回滚丢失」/「persona.2 自身缺陷」/「新问题」。

## 验收

- 四视图各一条：现象可复现、根因/归属清楚、修复建议具体到 commit/文件/函数；
- 9哥 认可调研结论后，再开修复卡（一张卡只带一类变更，刷机只写 app 0x20000）。
