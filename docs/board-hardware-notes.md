# CHD ESP32-S3-BOX (V2.0) — 硬件事实表

> 目标：给固件/驱动决策提供**可依赖**的硬件事实，每条结论标注证据来源与置信度。
> 调研日期：2026-10-28　调研范围：`~/Downloads/CHD/` 全部资料（只读）
>
> **置信度标记**
> - **【确认】** 厂家文档明写，或 DXF 几何连通性实测到 0.00mm 重合（两网络共享同一焊盘）
> - **【强推断】** 由 BOM + 网络名 + 拓扑排除法导出，未直接测通断
> - **【推测】** 有间接迹象，需实测
> - **【不足】** 资料不足以判定，已给出最省的实测方法
>
> ⚠️ DXF 是 PADS 导出的 **PCB 图形 + 网络名 linetype**，**不是网表**。"存在某网络名" ≠ "该网络连到了某器件"。
> 本文所有连通性结论都来自"网络铜箔端点与焊盘中心重合（<0.06mm）"的几何判定，并已用已知案例校验（见 §7 方法说明）。

---

## 0. 一句话结论

| 问题 | 结论 |
|---|---|
| USB-A 是什么 | **纯供电口（充电口），没有数据通路到 MCU**。ESP32 唯一 USB PHY 的数据对接到了 **Type-C** |
| 能否插 U 盘 / UVC 摄像头到 USB-A | **不能**。无 D+/D- 到 MCU，板上也无 HUB/切换芯片，出厂固件无 `usb_host` |
| TF 卡是 SDMMC 还是 SPI | **1-bit SDMMC**（CMD=IO0 / CLK=IO43 / D0=IO44），**无 CS、无 CD**。SPI 方案不成立 |
| TF 卡座供电 | **硬连 +3V3，没有 GPIO 开关**。所以 `ESP_FAIL` 与"没上电"无关 |
| 我们 1-bit SDMMC 方案对不对 | **对，且是唯一选项**（DAT1/2/3 未引到 MCU）。`ESP_FAIL` 要往别处查，见 §2.3 |
| 摄像头 | **8-bit DVP / OV2640**，PWDN 与 RESET **未接 GPIO**（NC），无法软复位 |
| 和 TF 抢引脚的是谁 | **不是摄像头**，是 **PZ 扩展排针**（外加 IO0 的 BOOT 键、IO43/44 的 UART0） |
| 空闲 GPIO | **没有**。PZ 排针 14 个脚全部与摄像头或 TF 复用 |

---

## 1. USB-A / Type-C 拓扑（重点问题 1）

### 1.1 直接证据链

**网表层面**（DXF linetype → 网络名，共 193 个网络，见 §7）：

- ESP32 侧的 USB 网络只有 `IO19` 和 `IO20` 两个，与引脚配置表 `IO19=USB_DN / IO20=USB_DP` 一致（`CHD-ESP32-S3-BOX_引脚配置表.pdf`，V2.0 段第 13–14 行）。
- `IO19` / `IO20` 各自**只有 2 个焊盘**，全部位于 `(43.66, 75.76)-(46.99, 75.77)` / `(43.66, 74.49)-(46.99, 74.50)` 一带 → 一端在模组、一端在串联件上。
- 与它们 1.0mm 串联相邻的是 **`USB_D-`（y=75.76）和 `USB_D+`（y=74.49）**，间隙 1.0mm = 0402 串联件。
- `USB_D+` / `USB_D-` 走到 `(5.5, 34.5)` / `(5.5, 32.5)`，那里是一个 **2 列 × 3 行、2.0mm 间距**的焊盘块，逐行连通关系（距离 0.00mm）：

  | 行 | 左焊盘 | 右焊盘 | 丝印 |
  |---|---|---|---|
  | y = 30.50 | `DGND` | `DGND` | `G` |
  | y = 32.50 | `USB_D-` | `USB_DN` | `DP` |
  | y = 34.50 | `USB_D+` | `USB_DP` | `DN` |

  → 这是一个 **3 位烙铁跳线/排针块**（丝印 `G` / `DP` / `DN` 在 x≈3.43）。它把"MCU 侧"和"连接器侧"的 USB 数据对分开，可跨接也可断开。
- `USB_DP` / `USB_DN` 向下走到 **`(11.88, 11.09)` / `(11.88, 12.23)`**，落在一个 **2 列 × 7 行、1.14mm 间距**的细间距焊盘阵列上；同一阵列里还有 `VBUS_IN`（(10.92,15.70)、(14.70,15.88)）和大量 `DGND`，其余引脚是**未命名网络**（`$$$7416` / `$$$7417` / `$$$31858` / `$$$31872`）——典型的 **Type-C 的 CC1/CC2/SBU** 这类未使用引脚。
  → 该阵列是 **J_TYPE-C-12**（BOM 有 `J_TYPE-C-12`，DXF 有 `SYM_NAME 'J_TYPE_C_12'`）。

**结论：ESP32-S3 的 USB D+/D- 物理上接在 Type-C 上，不接 USB-A。**

### 1.2 USB-A 到底接了啥

- BOM 里 USB-A 是 `J_USB-A-M_USB-A`，封装名写 `直插USB-A型母插座-90°`（母座、直插、90°），**物理形态是主机口**（器件插进来那种）。
- 但 **BOM 里没有 USB HUB、没有 USB 切换/mux、没有 USB-UART 桥**。全部 IC 只有：
  `ESP32-S3-WROOM-1` / `BL8028`（DC-DC 降压）/ `ME6211C`（LDO）/ `TP4057`（锂电充电）/ `NS4150B`（功放）/ `ES7210` / `ES8311` / `ICM42607` / `MSM381A3729`（MEMS 麦）/ 若干 PMOS、LBSS138、SS34。
- 出厂固件 `chd-esp32s3-box-esp-claw_1.0.0.bin` 里 `usb_host_install`、`usb_host_lib`、`usb_host` 命中数 **全为 0**（`strings` 实测），驱动字符串是 `ili9341`(13) / `gt911`(20) / `es7210` / `es8311` —— 即 **原封不动的 esp_box_3 BSP**，完全没有 USB 主机栈。

**【强推断】USB-A = 纯 5V 供电口（充电口）。** 理由：唯一的 USB PHY 数据对已被 Type-C 占用；板上无 HUB/mux 可分配；固件无主机栈。它对外输出 5V（这就是"插 USB 灯会亮"的原因），但 D+/D- 要么悬空、要么按 DCP 短接，与 MCU 无关。

### 1.3 5V 是否常通、有没有 load switch

- **没有 load switch。** 板上唯一的电源开关类器件是 `S_SWITCH_MSK-22D4-3`（拨动开关，丝印 `ON`）与 `Q_AO3415-PMOS`。
- `BL8028` 经查证是 **1.5A / 2MHz 同步降压 DC-DC**（SOT-23-5，2.6–5.5V 输入），**不是** USB 限流开关 — [Belling 官方 datasheet](https://www.belling.com.cn/media/file_object/bel_product/BL8028/datasheet/BL8028_V4.0_en.pdf)、[产品页](https://www.belling.com.cn/product_info.html?id=164)。
- **板上没有任何升压电路**（无 boost IC，也无 charge-pump）。BL8028 只能降压、ME6211C 只是 LDO。
- 网络：`VBUS_IN`（Type-C 进来）→ `PWR_IN` / `+5V` → `5V_USB` → 一路去 **PZ 扩展排针的 5V 脚**（`5V_USB` 铜箔终止于 `(4.50, 60.65)` / `(6.50, 60.65)`，丝印在该处印 `5V`）。
- `PWR_CTR` 是与 `+5V` 相邻（0.023mm）的控制网络，接 `Q_AO3415` 栅极一类位置 —【推测】电源保持/软开关。

**【强推断】5V 是常通的（受拨动开关 ON/OFF 控制），不是 GPIO 使能。**而且因为板上没有升压：
> **只用电池供电时，USB-A 和排针的 5V 应该是没有输出的。** 这是一个可以立刻验的判据。

### 1.4 Type-C 的一个坑（值得单独记）

Type-C 的 CC 引脚落在**未命名网络**上，而 **BOM 里没有任何 5.1kΩ 电阻**（电阻只有 0/10/100/1.5K/2K/10K/100K/200K）。
**【推测】该 Type-C 没做 CC 下拉，属于"哑电源口"**：A-to-C 线能供电（主机强制给 5V），**C-to-C 线配 PD 充电器很可能不供电**。
实测方法：用 C-to-C 线接 PD 充电头，看是否能开机；再换 A-to-C 复测。

---

## 2. TF 卡（重点问题 2）

### 2.1 接法：1-bit SDMMC，已定死

`CHD-ESP32-S3-BOX_引脚配置表.pdf` V2.0 段：

| 引脚号 | IO | SD 卡列 |
|---|---|---|
| 27 | IO0 | `SD_CMD`（同时是 `boot` 键） |
| 36 | IO43 | `SD_CLK`（同时是 `TXD0`） |
| 37 | IO44 | `SD_DAT0`（同时是 `RXD0`） |

**没有 `SD_CS`，也没有 `SD_CD`** —— 全表无此二者。

DXF 几何把卡座 8+1 个触点全部解析出来（y = 82.92 一排，1.1mm 间距，与 microSD 标准触点序完全对应）：

| x (mm) | 网络 | microSD 脚号 |
|---|---|---|
| 12.80 | `SD_DAT2` | 1 |
| 13.90 | `SD_DAT3` | 2 |
| 15.00 | `SD_CMD` | 3 |
| **16.10** | **`+3V3`** | **4 = VDD** |
| 17.20 | `SD_CLK` | 5 |
| 18.30 | `DGND` | 6 = VSS |
| 19.40 | `SD_DAT0` | 7 |
| 20.50 | `SD_DAT1` | 8 |
| 21.60 | *无网络* | 9 = 卡检测（**悬空**） |

在卡座正上方 1.0mm（= 0402 跨距）有一排焊盘，y = 78.61 / 79.27：
`(14.99, 79.27)=IO0`、`(17.14, 79.27)=IO43`、`(19.43, 79.27)=IO44`，其余为 `+3V3` 与 `DGND`。

**【确认】结论：**
1. **只有 CMD / CLK / D0 三根线有串到 MCU 的通路**；`SD_DAT1/2/3` 只在卡座侧有短桩 + 上拉，**没有引到 MCU** → **4-bit 不可能**，只能 1-bit。
2. **卡座 VDD 硬连 `+3V3`**，没有 GPIO 供电开关 → 别去找"SD 电源使能脚"。
3. **卡检测脚悬空** → 只能按"永久插入"处理（现有代码正是这么做的）。

### 2.2 厂家给的配置是错的，别信

`esp-claw/esp-claw_chd/application/edge_agent/boards/espressif/esp_box_3/board_devices.yaml` 里写着：

```yaml
fs_sdcard:  sub_type: sdmmc   bus_width: 4
            pins: clk:11 cmd:14 d0:9 d1:13 d2:42 d3:12    # ← 全是摄像头脚
sdcard_power: gpio_sd_power pin: 43 active_level: 0        # ← IO43 其实是 SD_CLK
display_lcd:  chip: ili9341 / 320x240                       # ← 实际 ST7796 / 480x320
lcd_touch:    chip: gt911                                   # ← 实际 FT6336
```

这是**原封不动照搬 esp_box_3 的旧值**，与 CHD 板实际接线矛盾（`board_info.yaml` 也写着 `description: ESP-BOX-3 Development Board` / `manufacturer: ESPRESSIF`）。
→ **esp-claw 里的板级 YAML 对这块板没有参考价值**，不要拿它当依据。

### 2.3 那 `ESP_FAIL` 最可能是什么

我们的方案（IO0/43/44 做 1-bit SDMMC）**与硬件完全一致**，所以 "SPI 才对" 这个假设可以彻底排除。剩下按可能性排序：

1. **卡座—MCU 之间的 0402 串联件可能没贴（DNP）** ← 最值得先查
   卡座触点与 MCU 侧网络之间各有一个 0402 位置（§2.1）。DXF 是**光板图**，看不出贴没贴。
   如果这三颗 0Ω 没贴：MCU 侧靠自身/外部上拉读起来仍是高电平（**pin sanity 会"通过"**），但卡根本不在总线上 → 表现就是 `sdmmc_card_init` 失败 / `ESP_FAIL`，且怎么改频率都没用。
   **实测（最省）**：万用表通断档，量卡座焊盘到对应 0402 另一侧焊盘；或直接量卡座 CMD 脚（15.00）对模组 IO0 是否 0Ω。
2. **IO43/IO44 同时是 UART0 TXD/RXD**（引脚表明写 `TXD0`/`RXD0`）。若固件把 console 放在 UART0，IO43 会被 UART 持续驱动，SD_CLK 直接失效。必须 `CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG=y` 或彻底不启 UART0。
   另外 **PZ-6 / PZ-8 就是 IO43 / IO44**，排针上插了 USB-TTL 也会打架。
3. **IO0 是 BOOT 键 + 启动 strap**（引脚表 `boot` 列）。若 BOOT 键电路带消抖电容（100nF 量级），CMD 线的容性负载会让 CMD 时序崩 → 卡初始化失败。这是 S3 上很典型的坑。
   **实测**：示波器看 CMD 波形上升沿；或拆掉/换小该电容试。用万用表量 IO0 对地电容（断电，二极管档/电容档）可粗判。
4. 卡本身：容量/文件系统（exFAT 需要 `CONFIG_FATFS_LFN` + exFAT 支持），或卡在 3.3V 下电流不足。
5. 供电余量：3.5" 屏 + 摄像头 + 喇叭同时工作，Type-C 只靠 5V 直供时压降过大。
6. **卡座是翻盖式（hinge）**：DXF 里 `DECAL TF_CARD_HINGE`，型号名 GBK 解码为 **"TF卡翻式盖卡座_伍尔特"**（Würth 翻盖座）。翻盖没压到底/卡没插到底时，8 个触点全部不接触，症状与"引脚接错"完全一样。
   **实测**：重新插卡并确认盖扣到位，换一张已知良好的卡再试。成本最低，建议排在第 1 位之前先做一遍。

> 注：`boot:0x28 SPI_FAST_FLASH_BOOT` 只说明 strap 正常，**不能**说明 CMD 线信号质量 OK。

---

## 3. 摄像头（重点问题 3）

**8-bit DVP，OV2640。**（`摄像头方向调整说明.txt` 提到 `s->set_hmirror(s, 1); s->set_vflip(s, 0);`，该 API 与 `ov2640` 驱动一致；引脚表 CAMERA 列为 `DVP_Y2..Y9 + PCLK + XMCLK + HREF + VSYNC`）

权威映射（`05_Tools/xiaozhi-esp32/main/boards/chd/chd-esp32s3-box/config.h:103-114`（BSP_* 定义）+ `:119-127`（别名），与引脚表逐条吻合）：

| 信号 | GPIO | 引脚表名 |
|---|---|---|
| XCLK | 39 | `DVP_XMCLK` |
| PCLK | 14 | `DVP_PCLK` |
| VSYNC | 42 | `DVP_VSYNC` |
| HREF | 41 | `DVP_HREF` |
| D0 | 12 | `DVP_Y2` |
| D1 | 10 | `DVP_Y3` |
| D2 | 9 | `DVP_Y4` |
| D3 | 11 | `DVP_Y5` |
| D4 | 13 | `DVP_Y6` |
| D5 | 21 | `DVP_Y7` |
| D6 | 38 | `DVP_Y8` |
| D7 | 40 | `DVP_Y9` |
| PWDN | **NC** | — |
| RESET | **NC** | — |

- `CAMERA_PIN_PWDN` / `CAMERA_PIN_RESET` 均为 `GPIO_NUM_NC`（`config.h:95-96`）。
  DXF 里确有 `CAM_PWDN` / `CAM_RESET` 网络，但它们只在摄像头 FPC 附近起止、不接 MCU。
  → **摄像头无法由软件断电或复位**；想复位只能整板重启。XCLK 16MHz（`CAMERA_XCLK_FREQ`）。
- 摄像头与 TF **引脚不冲突**（IO9-14/21/38-42 vs IO0/43/44，完全不相交）。
  厂商 readme 说的"复用"指的是 **两者都与 PZ 扩展排针复用**，不是彼此复用。
  → 现有 `hardware.md` 里"camera 与 TF 共用引脚、要拔一个"的说法**应更正**。

---

## 4. PZ 扩展排针 GPIO 完整映射（重点问题 4）

`J_CON20_PZ20-DIP2.0`（2×10，2.0mm）+ `J_CON6_PZ6-DIP2.0`（1×6，2.0mm）。

PZ-1..PZ-14 全部来自引脚配置表；与丝印交叉验证一致（丝印直接在排针旁印 GPIO 号）：
丝印一列 `G / 5V / 3V3 / 9 / 11 / 13 / 21 / 38 / 40 / 42`，另一列 `G / 5V / 3V3 / TXD / RXD / 10 / 12 / 14 / 39 / 41`
—— 恰好 14 个 GPIO + 两组 G/5V/3V3，**TXD/RXD 就是 IO43/IO44**。

| PZ | GPIO | 主功能 | 是否"空闲" |
|---|---|---|---|
| PZ-1 | IO42 | DVP_VSYNC | 摄像头占用 |
| PZ-2 | IO41 | DVP_HREF | 摄像头占用 |
| PZ-3 | IO40 | DVP_Y9 (D7) | 摄像头占用 |
| PZ-4 | IO39 | DVP_XMCLK | 摄像头占用 |
| PZ-5 | IO38 | DVP_Y8 (D6) | 摄像头占用 |
| PZ-6 | IO43 | **SD_CLK** / TXD0 | TF + UART0 占用 |
| PZ-7 | IO9 | DVP_Y4 (D2) | 摄像头占用 |
| PZ-8 | IO44 | **SD_DAT0** / RXD0 | TF + UART0 占用 |
| PZ-9 | IO11 | DVP_Y5 (D3) | 摄像头占用 |
| PZ-10 | IO10 | DVP_Y3 (D1) | 摄像头占用 |
| PZ-11 | IO13 | DVP_Y6 (D4) | 摄像头占用 |
| PZ-12 | IO12 | DVP_Y2 (D0) | 摄像头占用 |
| PZ-13 | IO21 | DVP_Y7 (D5) | 摄像头占用 |
| PZ-14 | IO14 | DVP_PCLK | 摄像头占用 |

**没有任何一个 PZ 脚是真正空闲的。** 唯一的"自由度"来自：不装摄像头时，PZ-1..5、7、9..14 共 12 个脚可以自由用（但仍是 3.3V 单端 IO，无专用外设）。

排针电源：`5V` = `5V_USB`（仅外部 5V 在时才有，见 §1.3）；`3V3`；`G`。

**不引出到任何排针的 GPIO**：IO0(SD_CMD/BOOT)、IO1(电池 ADC/EXTRA_BUTTON)、IO2(I2S MCLK)、IO3(CTP_INT)、IO4/5/6/7(LCD)、IO8/18(I2C)、IO15/16/17/45/46(I2S)、IO19/20(USB)、IO47(背光)、IO48(充电状态)。
**IO35/36/37 不可用**（八线 PSRAM 占用，引脚表明确写 `NA`；`sdkconfig` 为 `CONFIG_SPIRAM_MODE_OCT=y`）。

---

## 5. 冲突矩阵（重点问题 5）

|  | 摄像头 | TF 卡 | PZ 排针 | USB(Type-C) | UART0 | BOOT 键 | LCD | 音频/I2C |
|---|---|---|---|---|---|---|---|---|
| **摄像头** | — | **不冲突** | **完全冲突**(PZ-1..5,7,9..14) | 无 | 无 | 无 | 无 | 无 |
| **TF 卡** | 不冲突 | — | **PZ-6 / PZ-8 冲突** | 无 | **IO43/44 = TXD0/RXD0 冲突** | **IO0 = BOOT strap/键 冲突** | 无 | 无 |
| **PZ 排针** | 完全冲突 | PZ-6/PZ-8 冲突 | — | 无 | PZ-6/8 即 UART0 | 无 | 无 | 无 |
| **USB(Type-C)** | 无 | 无 | 无 | — | **单 PHY：USJ console 与 OTG 互斥** | 无 | 无 | 无 |
| **UART0** | 无 | IO43/44 | PZ-6/8 | 与 USJ 二选一 | — | 无 | 无 | 无 |

要点：
1. **摄像头 ↔ TF 不互斥**（这是最反直觉、也最省事的一条：不用为了测 TF 拆摄像头）。
2. **摄像头 ↔ PZ 排针 100% 互斥**：14 个排针脚里 12 个是摄像头信号，插任何东西都得先拆摄像头。
3. **TF ↔ UART0 互斥**：IO43/IO44 就是 console TXD/RXD。用 UART0 打日志 = SD 必坏。这是 `ESP_FAIL` 的第二号嫌疑。
4. **TF ↔ BOOT 键/strap**：IO0 同时是 SD_CMD、BOOT 键、启动 strap。插着卡能开机说明 strap 没被拉死，但 CMD 信号质量仍可能被按键电路拖坏。
5. **USB 单 PHY**：`CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG=y` + `CONFIG_SOC_USB_OTG_PERIPH_NUM=1`。若将来真要做 USB 主机，必须放弃 USJ console。而本板 **USB-A 没有数据线**，所以这条目前只是理论约束。
6. **无 GPIO 可做 SD 电源开关 / 无 GPIO 可做摄像头复位** —— 这两件事在硬件上就不存在，不要写这类代码。
7. **IO43/IO44 还有第三个用途**：`config.h:131-132` 里 `ML307_RX_PIN=44` / `ML307_TX_PIN=43`（Cat.1 4G 模组选配）。本板没装 ML307，但这条定义说明这三个用途（SD / UART0 / 4G）共用同一对脚，任一开启其余必须关。
8. **I2C 用 port 1**（`config.h:99 BSP_I2C_PORT (1)`），与实测"FT6336 在 port1、与 codec 共用"一致。注意 `esp-claw` 的板级 YAML 写的是 `port: 0` —— 又一次证明那份 YAML 不可信。I2C 只是软件外设实例号，GPIO 仍是 IO8/IO18。

---

## 6. 板上有什么（BOM 摘要，用于排除法）

从 DXF `PARTTYPE`（43 种）与 `PART` 位号（约 290 个）提取：

| 类别 | 器件 |
|---|---|
| MCU | `IC_ESP32-S3-WROOM-1`（八线 PSRAM） |
| 电源 | `IC_BL8028`（2MHz 同步降压）、`IC_ME6211C`（LDO）、`IC_TP4057`（锂电充电）、`Q_AO3415-PMOS`、`D_SS34_SMB`、`S_SWITCH_MSK-22D4-3`（ON/OFF 拨动） |
| 音频 | `IC_ES8311`（codec）、`IC_ES7210`（4ch ADC）、`IC_NS4150B`（功放）、`IC_MSM381A3729_4`（MEMS 麦）、`BZ_EMX-7T06SP`（喇叭）、`PJ-342`（3.5mm 座） |
| 传感器 | `IC_ICM42607-14`（6 轴 IMU） |
| 连接器 | `J_TYPE-C-12`、`J_USB-A-M_USB-A`、`J_TF-CARD_HINGE`、`J_FPC24_FPC05-24`、`J_CON20_PZ20-DIP2.0`、`J_CON6_PZ6-DIP2.0`、`J_MX1.25-4PLB`（电池）、`J_JST-ZH-2A` |
| 保护/电平 | `ESD_0402ESDAC30` ×6、`Q_LBSS138LT1G`、`R_0_1-16W_0402` ×N |
| 按键 | `SW_JH-02_KEY-JH-02` ×2（RST / BOOT） |

**明确不存在的**：USB HUB、USB mux/switch、USB-UART 桥（CH340/CP2102 之类）、升压 IC、SD 电源开关、摄像头 LDO 开关。

---

## 7. 方法与可信度说明（重要）

**DXF 怎么读的**：`CHD-ESP32-S3-BOX_PCB_V2.0.dxf` 是 PADS 导出，网络名不在图层上，而是编码在 **linetype 定义**里：
`LTYPE / 2 / SIG_151 / 3 / "USB_D+:=2 0 0"`，共 193 个带网络的 linetype。走线实体通过 group code 6 引用该 linetype，于是"线 → 网络"可还原。

**坐标**：板框 `BOARD_OUTLINE_00` 实测 **78.0 × 99.0 mm**，与图上标注 `78.0mm` / `99.0mm` 一致 → **1 DXF 单位 = 1 mm**；元件/走线坐标在 0..78 × 0..99 的板内坐标系。

**连通性判定**：取每个网络的铜箔端点，与 `PADS_TOP` 焊盘中心比对，**< 0.06mm 记为相接**。
方法自校验：`USB_CMD` 类结果全部给出 0.00mm 且拓扑自洽（IO19/IO20 各 2 焊盘、Type-C 阵列 7 行、microSD 9 触点 1.1mm 间距与标准序一致），可以认为没有系统性错位。

**仍然止步的地方（必须实测）**：
- DXF 是**光板图**，**不包含贴片/装配信息** → 无法知道 0Ω / ESD / 上拉是否贴装。§2.3 的 1 号嫌疑只能靠万用表。
- 无法判定 Type-C 的 CC 电阻是否存在（网络未命名，BOM 无 5.1k）。
- 无法判定 BOOT 键上是否有消抖电容。

---

## 8. "资料不足需实测"清单

按性价比排序，每条都写清"量哪里 / 看什么"。

> **2026-10-28 校准：#0 与 #1 已作废，不用量了。** 卡格成 FAT32 后板子 **mount OK、235 GB 读写通过**
> （HANDOFF §「今天已收口的卡（2026-10-28）」task-30），说明卡座扣到位、0402 串联件是贴装的；
> 当初的 `ESP_FAIL` 根因是 **exFAT 不支持**（IDF 6.1 `FF_FS_EXFAT 0`），不是硬件。

| # | 待判定 | 最省实测方法 | 判据 |
|---|---|---|---|
| ~~0~~ | ~~翻盖卡座是否扣到位 / 卡是否良好~~ | ~~重插卡确认盖扣到底；换一张已知能在别处用的卡~~ | ❌ **已作废（2026-10-28）**：TF 挂载 OK + 235 GB 读写通过，卡座与卡都正常 |
| ~~1~~ | ~~卡座 CMD/CLK/D0 到 MCU 的 0402 串联件是否贴装~~ | ~~万用表通断档：卡座触点 (15.00, 82.92)/(17.20)/(19.40) 对 IO0/IO43/IO44 网络侧焊盘~~ | ❌ **已作废（2026-10-28）**：235 GB 读写通过 = 串联件已贴装；`ESP_FAIL` 真因是 exFAT |
| 2 | BOOT 键是否给 IO0 挂了消抖电容 | 断电，电容档量 IO0 对 GND；或示波器看 SD CMD 上升沿 | 有明显容性（>10nF）/上升沿变缓 = 时序杀手 |
| 3 | Type-C 有无 CC 下拉（能否 C-to-C 供电） | C-to-C 接 PD 头试开机；再 A-to-C 复测 | C-to-C 不开机 = 无 CC 电阻 |
| 4 | USB-A 是否真的只有 5V | 插 U 盘看是否枚举（必然不枚举）；万用表量 USB-A 的 D+/D- 对 GND 电阻 | 数据脚悬空/短接 = 纯供电口 |
| 5 | 5V 在电池供电时是否存在 | 拔掉 Type-C，仅电池开机，量排针 5V / 插 USB 灯 | 无 5V = 印证"无升压、5V 常通但仅外部供电时有效" |
| 6 | 排针 5V 与 USB-A 5V 是否同一路（`5V_USB`） | 通断档量 USB-A VBUS ↔ PZ 的 5V 脚 | 通的 = 同一路，共承受载 |
| 7 | `LCD_RST` 到底由谁驱动（V2.0 引脚表把 IO48 标成"电池充电"，固件 `DISPLAY_RST_GPIO=NC`） | 通断档量 LCD FPC 的 RST 脚 ↔ IO48 / +3V3 | 接 3V3 = RC 复位，固件 NC 正确 |
| 8 | 摄像头 PWDN/RESET 是否被硬拉到有效电平 | 量 FPC 对应脚对 GND/3V3 | 固定电平 = 永远使能，无法软复位 |

---

## 9. 对我们固件的直接影响（结论性建议）

1. **TF 卡：继续用 1-bit SDMMC（IO0/43/44），不要改 SPI。** 硬件只支持这一种；`ESP_FAIL` 请按 §2.3 顺序排查，**先量那三颗 0402**。
2. **必须保证 console 不在 UART0**（`CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG=y`），否则 SD 必失败。
3. **不要为 SD 写"电源使能"代码**，也不要为摄像头写"PWDN/RESET"代码 —— 硬件上没有这两根线。
4. **USB-A 不要规划任何数据功能**（U 盘、UVC、HID 都不行）。要用摄像头只能走 DVP（OV2640）。
5. **`espressif__usb_host_uvc` 这条线在本板上走不通**：单 PHY 且 PHY 已接 Type-C，USB-A 无数据。若确需 USB 摄像头，只能改硬件（把 USB-A 的 D+/D- 飞到 IO19/IO20，并放弃 USJ console）。
6. 若要在 PZ 排针上接外设，**必须先拆摄像头**（12/14 个脚冲突）。

---

## 10. 证据索引

| 结论 | 来源 |
|---|---|
| 引脚功能表（V2.0 / V1.x 两版） | `CHD-ESP32-S3-BOX_引脚配置表.pdf`（`pdftotext -layout`，84 行） |
| 屏幕 320×480 / RGB565 / 4 线 SPI / ST7796U | `3.5寸_亦亚徽E350S030-D显示屏产品规格书.pdf` 第 12、53-57、142 行 |
| 193 个网络名、USB_D±/USB_DP/DN、SD_*、DVP_*、VBUS_IN/5V_USB/PWR_CTR | DXF linetype 表（`SIG_n` → `<net>:=2 0 0`） |
| BOM（43 种 PARTTYPE、约 290 位号） | DXF `PART_ATTR` 层 `PARTTYPE` / `PART` / `Value` / `DECAL` |
| 板框 78×99mm | DXF `BOARD_OUTLINE_00` POLYLINE 顶点 |
| USB 跳线块逐行连通、Type-C 阵列、microSD 9 触点、卡座 VDD=+3V3、CD 悬空 | 焊盘中心 ↔ 网络端点重合分析（<0.06mm，全部 0.00mm） |
| 摄像头 12 根信号 + PWDN/RESET=NC、RST=NC、IO48=充电状态、IO1=EXTRA_BUTTON、I2C port1、ML307 复用 IO43/44 | `05_Tools/xiaozhi-esp32/main/boards/chd/chd-esp32s3-box/config.h:24-25, 36, 95-96, 99, 103-134` |
| 板型选择 esp_box_3、Type-C 供电、屏幕镜像 | `虫洞CHD-ESP32-S3-BOX开发板小智AI适配教程.docx`；`chd_esp_claw固件说明.docx` |
| 摄像头/扩展/TF 复用说明 | `readme(必看).txt` |
| OV2640 镜像/翻转 API | `摄像头方向调整说明.txt` |
| 厂家 SD/显示/Touch 配置是照搬 esp_box_3（错） | `esp-claw/esp-claw_chd/application/edge_agent/boards/espressif/esp_box_3/board_devices.yaml`、`board_info.yaml` |
| 单 USB PHY、HUB 未编译、USJ console、SDMMC 可用 GPIO matrix | `esp-claw_chd/application/edge_agent/sdkconfig`（`CONFIG_SOC_USB_OTG_PERIPH_NUM=1`、`# CONFIG_USB_HOST_HUBS_SUPPORTED is not set`、`CONFIG_SOC_SDMMC_USE_GPIO_MATRIX=y`、`CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG=y`） |
| 出厂固件无 usb_host、只有 ili9341/gt911 驱动 | `strings -a chd-esp32s3-box-esp-claw_1.0.0.bin` |
| BL8028 = 1.5A 同步降压（非 load switch） | [Belling datasheet](https://www.belling.com.cn/media/file_object/bel_product/BL8028/datasheet/BL8028_V4.0_en.pdf)、[产品页](https://www.belling.com.cn/product_info.html?id=164) |
