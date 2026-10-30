# M7 Step 5 · 固件独立性方案

> 只写方案，不改代码。仓库 `05_Tools/xiaozhi-esp32`，分支 `feat/persona-face` @ `bd396e8`，采样 2026-10-27。
> **结论先行**：走 ① 保持 fork，但把补丁压到 3–4 个上游文件、≤200 行；不建独立 BSP 仓库（②），更不自立（③）。

## 0. 事实基线（可复核）

> **采样时点**：以下数字采样于 `bd396e8`。13:27 之后又合入 `3fc6354`（字幕字体改用运行期 theme 字体，+35/−15），
> 所以当前应为：HEAD `3fc6354`、本地提交 **10** 个（浅克隆可达 11 个，含基线 `04213af`）、`git diff --stat origin/main...HEAD` = 26 文件 **+4131/−35**、
> board **+704/−2**（含 README 与字幕层）、vendored `lvgl_kawaii_face` **+2886**、**工作树 clean**。
> 表中若与上述不一致，以上述为准；P0 的「≈120 行插桩」是估算值，未逐行核。

| 项 | 事实 | 证据 |
|---|---|---|
| 上游 | `origin` = github.com/78/xiaozhi-esp32.git | `git remote -v` |
| 克隆形态 | **浅克隆**，仅 10 个 commit 可达 | `.git/shallow` 存在；`git rev-list --count HEAD`=10 |
| 共同基线 | `04213af`（2026-10-21，上游 PR #2335） | `git merge-base HEAD origin/main` |
| 本地提交 | 9 个（采样时点；范围 `2443e5d`…`bd396e8`） | `git log --oneline origin/main..HEAD \| wc -l`=9 |
| 上游现状 | `c435f99`（2026-10-25），相对我们的基线**领先 89 个提交** | `git ls-remote --heads origin main`；GitHub compare `ahead_by: 89` |
| 上游版本 | 仍是 `2.5.3`（没有可依赖的 release 号） | 上游 `CMakeLists.txt:12` |
| 改动面 | 26 文件 / +4102 −35 | `git diff --stat origin/main...HEAD` |
| 其中 vendored | `components/lvgl_kawaii_face/**` **2886** 行 | 同上 |
| 工作区 | **clean**（采样时点有 2 个未提交，13:27 已全部提交） | `git diff --stat` |

**两个必须纠正的前提**（与任务描述不同）：

1. **CHD 板是上游自带板型**，不是我们新建的。上游已有 `main/boards/chd/chd-esp32s3-box/{README.md,chd_esp32s3_box_board.cc,config.h,config.json,power_manager.h}`（`git ls-tree -r origin/main | grep chd`）；Kconfig 板型在 `main/Kconfig.projbuild:182`，构建选择在 `main/CMakeLists.txt:113-118`。我们的板级代码是**向上游文件追加**。
2. board.cc 相对上游 **0 行删除**(0 deleted lines)，9 个 hunk 全为插入，最大一块 +291 行落在 `CustomLcdDisplay` 类体内（`@@ -148,6 +241,291 @@`）。→ 冲突面仅限"上游改到相邻行"。

## 1. 「独立性」指什么：三种目标

| | 目标 | 收益 | 代价 | 判断 |
|---|---|---|---|---|
| ① | 保持 fork，补丁 rebase 维护 | 上游新板型/协议/语音能力白拿；改动面小 | 每轮 rebase 手工解冲突，补丁会腐化 | **推荐**（配合减面） |
| ② | 板级独立成 out-of-tree 组件/BSP 仓库，上游当依赖 | 板级代码跨仓复用 | 上游**没有**板级插件机制：板型仍需 Kconfig 项（`main/Kconfig.projbuild:182`）+ `BOARD_DIR` elseif（`main/CMakeLists.txt:113-118`）+ 源文件收集（GLOB 只扫 `main/boards/<BOARD_DIR>`，`:937-940`；全仓无 `EXTRA_COMPONENT_DIRS`） | 暂不 |
| ③ | 完全自立 | 不受上游变更影响 | 上游 89 个提交 / 4.5 天（10-21→10-25，≈20/天）全要自担；LVGL/esp-sr/emote 资产自维护 | 否 |

判据：扣掉 vendored 组件、死代码与临时插桩后，扣掉 vendored 组件 2886、死代码 365、插桩约 120 后，自有代码 ≈ **730 行**（含板 README），远小于自立成本。

## 2. 逐文件可分离性

归类口径：**保留**（板级自持）/ **删除** / **跟随上游**（不改）/ **上游化**（提 PR 后从 fork 消失）。
「可分离」= 能不能做成不改上游公共文件的板级覆盖。

| 文件 | 净变更 | 归类 | 可分离 | 处置 |
|---|---|---|---|---|
| `components/lvgl_kawaii_face/**` | +2886 | 保留 | **能** | 已 vendored，`.gitignore:7-8` 放行；可整体外置为独立仓 + `idf_component.yml` git 依赖（代价：多一仓 + 版本 pin） |
| `main/boards/chd/chd-esp32s3-box/chd_esp32s3_box_board.cc` | +483/−0 | 保留 | **半能** | 上游文件、纯追加；把脸+字幕抽到板目录新文件即可（`file(GLOB BOARD_SOURCES …/*.cc)`，`main/CMakeLists.txt:937` 自动编译），板文件只留选型 |
| `…/chd-esp32s3-box/config.json` | +21/−2 | 保留 | **半能** | 上游数据文件；含内网 OTA URL（`:17`、`:28`）；`build.py -c` 支持板目录内自定义文件名（`scripts/build.py:1534`）→ 拆 `config.local.json` |
| `…/chd-esp32s3-box/README.md` | +171 | 保留 | 半能 | 文档追加，冲突概率低 |
| `…/config.h`、`…/power_manager.h` | 0 | 跟随上游 | 能 | 未改，无需处理 |
| `main/Kconfig.projbuild` | +1/−1 | 上游化 | **不能** | `:923` 把 CHD 加进 emote 白名单；理由通用，最适合 PR |
| `main/CMakeLists.txt` | +2 | 上游化/删除 | **不能** | `:20` `matrix_ui.cc`（死代码，删）；`:1154` `lvgl_kawaii_face` REQUIRES（可改走既有 `MAIN_PRIV_REQUIRES_EXTRA` 条件块 `:1101-1125`） |
| `main/application.cc` | +130/−23 | 上游化 + 长期 patch | **不能** | 核心状态机：15 处 `KA_LOG` 临时插桩（`:36` 定义，自标 TEMPORARY）+ 7 处 `IsSocketConnected()`（`:888,920,955,1040,1060,1386,1540`）+ 2 处省电抬升。插桩必须删；语义改动可提 PR，不收则长期 patch |
| `main/protocols/{protocol.h:69, protocol.cc:113-121, websocket_protocol.cc:74, websocket_protocol.h:23}` | +28 | 上游化 | **不能** | `IsSocketConnected` 虚函数 + timeout 只记一次日志，通用能力，PR 首选 |
| `main/display/lvgl_display/lvgl_display.cc` | +8/−6 | 上游化 | **不能** | `:332` 快照字节序是上游 bug；PR 首选 |
| `main/display/matrix_ui.{cc,h}` | +365 | 删除 | 能 | `f1f4ea2` 已 revert 交互，仅剩 `main/CMakeLists.txt:20` 引用 → **死代码** |
| `.gitignore` | +7/−1 | 保留 | 不能 | 只因 vendored 组件而改；组件外置后可还原 |

## 3. 上游升级路径

**节奏**：建议每 2 周一次；命中高冲突文件时立即跟。基线以来（`since=2026-10-21T09:12:10Z`）上游触及我们文件的提交数（GitHub commits API，按 committer date）：
`Kconfig.projbuild` 5、`CMakeLists.txt` 5、`application.cc` 2、`protocols` 0、`lvgl_display.cc` 0、`chd-esp32s3-box/` 0、`idf_component.yml` 0。

```bash
git fetch origin --unshallow          # 一次性：当前是浅克隆
git tag backup/pre-sync-$(date +%Y%m%d)
git switch -c sync/$(date +%Y%m%d) feat/persona-face
git rebase origin/main                # 冲突高发：application.cc / Kconfig / CMakeLists
```

**验证**（构建 + 真机三件套）：

```bash
source <workspace>/05_Tools/esp-idf-6.1/export.sh
python3 scripts/build.py chd/chd-esp32s3-box --name chd-esp32s3-box-lcd35   # 板 README:124
```

真机：① 启动日志无 panic、脸与字幕出现 ② WiFi 连上 + OTA 注册成功 ③ 唤醒→ASR→TTS→打断一轮通过。
（IDF 路径取自 `build/CMakeCache.txt` 的 `CMAKE_TOOLCHAIN_FILE`。）

**回滚**：rebase 失败 `git rebase --abort`；已合并 `git reset --hard "$(git tag -l 'backup/pre-sync-*' | tail -1)"`（`*` 不会被 git 解析成 tag，必须这样取）；设备侧 `write-flash "@flash_args"` 只写 app、保 NVS（HANDOFF:132），整片备份用 `write-flash 0x0 <backup>.bin`（HANDOFF:304）。

## 4. 推荐方案 + 分阶段

目标形态：**上游文件 3–4 个、上游文件改动 ≤ 200 行、单轮 rebase ≤ 半天**（现状 4102 行里 2886 是 vendored 组件、365 是死代码、约 120 是临时插桩）。

- **P0 减面（0.5 天；零**运行时行为**风险，但会先失去 soak 证据）**：
  ⚠️ **前置条件（硬）**：必须等 Step 4 的 **15 min 保活 soak 完成并写进 HANDOFF** 才能删插桩——
  `application.cc:333-341`（idle-heartbeat）与 `:659-662`（rx-while-idle）正是 soak 的判读依据。
  **建议保留三条降级为 `ESP_LOGD`**：idle-heartbeat / rx-while-idle / closed-by-peer。
删 `matrix_ui.{cc,h}` 与 `CMakeLists.txt:20`；删 **17** 处标记：`application.cc` **14 处 `KA_LOG` 调用 + 1 处宏定义** + `board.cc` **2 处电源边沿标记**（只删 `M7-KEEPALIVE-SPIKE-TEMP` 注释会留下调用，所以验收要额外 `grep -r M7KEEPALIVE main/` = 0）；保留 7 处 `IsSocketConnected` 与省电改动。
  验收：`grep -r M7-KEEPALIVE-SPIKE-TEMP main/` = 0（当前 **17** 处：`application.cc` 15 + `board.cc` 2 —— P0 必须**两处都删**，否则验收过不了）；自有 diff（不含组件）≤ 800 行（P0 删的是**整块插桩**含注释/空行约 120 行；只删 15 行调用会到 836 行、过不了这条）；构建通过；真机三件套通过。
- **P1 板级归位（1 天）**：脸+字幕抽到 `main/boards/chd/chd-esp32s3-box/kawaii_face_display.{cc,h}`（GLOB 会自动收集但**没有 `CONFIGURE_DEPENDS`** → 新增文件后必须 `idf.py reconfigure` 或 clean build，否则不进 SRCS）；board.cc 只剩选型几行。
  验收：board.cc 相对上游 diff ≤ 40 行；镜像大小差 ≤ 1 KB；脸/字幕/表情切换截图回归。
- **P2 配置外置（0.5 天）**：`config.local.json` + `-c`，把内网 OTA URL 移出上游 config.json。
  验收：`build.py chd/chd-esp32s3-box -c config.local.json --name chd-esp32s3-box-lcd35` 通过；config.json 相对上游 diff 归零。
- **P3 上游化（1 天 + review 等待）**：按序提 3 个 PR：snapshot 字节序 → `IsSocketConnected`+timeout 日志 → Kconfig 白名单。
  验收：PR 链接回填本文件；上游合并后 `git cherry origin/main feat/persona-face` 确认等价补丁并删本地 commit。

### 需要 9 哥 拍板

1. 维护形态：定 ①（本次推荐），还是启动 ②（独立 BSP 仓库）？
2. 是否允许以我们名义向上游提 PR（代码与提交者身份公开）？
3. 升级节奏 2 周一次可否；是否把「真机三件套通过」定为合并硬门槛？
4. 若上游不收 keepalive 语义改动，是否接受长期 patch（约 30 分钟/轮人工解冲突）？

## 4b. 与 Step 4 的关系（两份文档互相约束）

- Step 4 推荐的**零固件方案 F** 依赖本方案保留的 `IsSocketConnected()` 补丁；本方案 P3 计划把它上游化 → F 的基础更耐久。
- 本方案「上游文件 3–4 个 / ≤200 行」这个目标**只在 9哥 不选 Step 4 的 E/A（改状态机）时成立**；若选了 E/A，需重新基线。
- **时序约束**：P0 删插桩必须排在 Step 4 Step 0 的 15 min soak 之后（见 P0 前置条件）。

## 5. 风险清单

| 风险 | 触发信号 | 处置 |
|---|---|---|
| 上游破坏性变更（协议/显示 API、LVGL 版本） | 构建报错、启动 panic | 2 周窗口 + backup tag + 三件套；先修到可编译再逐条对齐语义 |
| 组件版本漂移 | 干净构建后行为变化 | `dependencies.lock` **被 `.gitignore:16` 忽略、未入库** → 建议纳入版本管理 |
| 我们补丁被上游吸收 | rebase 提示 already applied | `git cherry` / `git patch-id` 检测后删本地 commit |
| 内网信息泄漏 | 提 PR 时 config.json:17,28 | P2 外置配置；PR 前 `grep 192.168.` |
| 临时插桩进发布 | 日志噪音、性能 | P0 删除 + 发布前 `grep M7-KEEPALIVE` 门禁 |
| 浅克隆查不到历史/blame | `git log` 只见 10 条 | 升级前 `git fetch --unshallow` |

## 6. 已知限制 / 未核实

- 本次**未跑构建**：`idf.py` 不在 PATH，未 source `export.sh`；"构建通过"未验证，IDF 路径仅来自 `build/CMakeCache.txt`。
- "落后 89 个提交"来自 GitHub compare API（2026-10-27 采样，**本次未复算**）；同节的 Kconfig/CMake/application churn 读数**同样未复算**，非本地 `git log` 计数（浅克隆）。
- 每文件 churn 数按 committer date 过滤，口径为"上游 main 上触及该路径的提交数"，非行数。
- `build.py -c` 自定义文件名是否影响 CI/OTA 流程**未实测**，只读了 `scripts/build.py:1534` 的路径解析。
- 上游是否接受三个 PR、是否有 release tag 节奏：未联系、未核实。
- 真机三件套判定阈值沿用 `docs/真机验收待办.md` 与 HANDOFF，本文件不重新定义。
