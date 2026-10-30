# CHD ESP32-S3-BOX 触摸「能初始化、收不到事件」只读调研

- 调研日期：2026-10-28
- 性质：**只读**。未改固件、未刷机、未改动 `~/Downloads/CHD/`。
- 目标：解释 `I (458) Touch panel ft6336` 之后 LVGL 层 35 s 内 0 事件。
- 结论标注：**[事实]** = 有 `file:line` / `strings` / PDF 原文可查；**[推测]** = 由事实推出，未实测。

---

## 0. TL;DR

1. **[事实] 厂商出厂固件只用 GT911**（`0x5D`，备用 `0x14`，`INT=IO3`，无 RST），二进制里 `ft6336` / `ft5x06` 字符串**一个都没有**。
2. **[事实] `esp_lcd_touch_ft5x06` 驱动初始化全程不读芯片 ID**（`0xA3` 只定义不使用），只要 `0x38` 有人 ACK 就"初始化成功" → 这正是「init OK + 0 事件」的成因。
3. **[事实] 我们的 `Touch panel ft6336` 那行日志不是识别结果，是 `i2c_master_probe(0x38)` 的结论**（`xiaozhi-esp32` HEAD `:1353-1356`）。日志名 = 假设，不是实测。
4. **[事实] 这块板只有 `CTP_INT`(IO3) 一根触摸专线**，引脚表和 PCB 网表里都**没有 `CTP_RST`** → `rst_gpio_num = NC` 是对的，不是根因。
5. **根因排序**：① 驱动/地址错配（应为 GT911，不是 FT5x06）→ ② `0x38` 上那个"设备"根本不是触摸 IC（含总线假 ACK）→ ③ GT911 地址锁存成 `0x14` 而我们只探 `0x5D` → ④ INT 缺失（次要，见 §3.2）。

---

## 1. 厂商固件里触摸到底是什么

### 1.1 板级 YAML：GT911 / 0x5D+0x14 / INT=IO3

`~/Downloads/CHD/esp-claw/esp-claw_chd/application/edge_agent/boards/espressif/esp_box_3/board_devices.yaml:107-128`

```yaml
- name: lcd_touch
  chip: gt911
  type: lcd_touch_i2c
  dependencies:
    espressif/esp_lcd_touch_gt911: "*"     # :115
  config:
    io_i2c_config:
      dev_addr: [0x5D, 0x14]               # :119  GT911 双地址
      lcd_cmd_bits: 16                     # :120
    touch_config:
      x_max: 320                           # :126
      y_max: 240                           # :127
      int_gpio_num: 3                      # :128  ← BSP_LCD_TOUCH_INT
```

同目录 `setup_device.c:72-85` 调 `esp_lcd_touch_new_i2c_gt911()`，**没有**任何 ft5x06 分支。
`sdkconfig:613` = `CONFIG_ESP_BOARD_ESP_BOX_3=y`，即这块板走的就是上面这份 `esp_box_3` 配置。

I2C 外设（`board_peripherals.yaml:3-10`）：`port: 0`, `sda: 8`, `scl: 18`。
→ 与我们 `config.h:110-112` 的 `BSP_I2C_PORT 1` + IO8/IO18 只差"实例号"，**GPIO 一致**。I2C 实例号不影响能否找到芯片。

**[推测]** `dev_addr: [0x5D, 0x14]` 是"两个都试"（`esp_board_manager` 源码不在本机缓存，未验证），这解释了为什么厂商固件在地址被锁成 `0x14` 时也能工作。

### 1.2 CHD 对厂商源码的全部改动：只有镜像

```
$ git -C ~/Downloads/CHD/esp-claw/esp-claw_chd status --short
 M application/edge_agent/boards/espressif/esp_box_3/board_devices.yaml

$ git -C ... diff
-      mirror_y: true
+      mirror_y: false
```

**[事实]** 触摸一行没改 → 厂商是靠"原封不动的 BOX-3 BSP"驱动这块屏的触摸。
**旁证**：`chd_esp_claw固件说明.docx` 第 5 段 —— 「用来开发验证，保证与官方代码最小差异，**只需要将屏幕水平镜像即可**」。与 diff 完全一致。

### 1.3 出厂 binary：只有 GT911

```
$ strings -a chd-esp32s3-box-esp-claw_1.0.0.bin | grep -c ...
gt911                 14
GT911                  6
esp_lcd_touch_gt911    7      # 含 esp_lcd_touch_new_i2c_gt911 / touch_gt911_read_cfg / esp_lcd_touch_gt911_read_data
ft6336                 0
FT6336                 0
ft5x06                 0
FT5x06                 0
```

驱动符号级证据（`strings` 行号）：`:11024-11034` `touch_gt911_reset` / `esp_lcd_touch_gt911_read_data` / `esp_lcd_touch_new_i2c_gt911`；
`:1499` `Failed to create gt911 touch driver: %s`；`:6232-6243` `GT911 read error` / `GT911 reset failed` / `GT911 init failed` / `Touch controller GT911 initialization failed`。

→ **[事实] 出厂固件里不存在 FT5x06/FT6336 驱动。**

---

## 2. 硬件事实：只有 INT，没有 RST；面板规格书不含触摸

| 来源 | 结论 |
|---|---|
| `CHD-ESP32-S3-BOX_引脚配置表.pdf`（V2.0 与 V1.0-1.2 两页都一致） | `IO3 = CTP_INT`；`IO18 = I2C_SCL`、`IO8 = I2C_SDA`；**全表没有 CTP_RST** |
| `CHD-ESP32-S3-BOX_PCB_V2.0.dxf`（网表名搜索） | 触摸侧只有 1 个 `CTP_INT` 网络；RST 类网络仅有 `RST` / `MCU_RST` / `LCD_RST`，**没有** `CTP_RST`/`TP_RST` |
| `3.5寸_亦亚徽E350S030-D显示屏产品规格书.pdf` | 3.5" **320×480**、**ST7796U**、4 线 SPI、RGB565；**通篇无 touch/触摸/CTP 字样** |
| `board_devices.yaml:120` | `lcd_cmd_bits: 16` —— GT911 的 16-bit 寄存器寻址（FT5x06 是 8-bit） |

结论：
1. **[事实] 触摸复位不是 GPIO 控制的**（无网络）→ `rst_gpio_num = GPIO_NUM_NC` 正确，**排除「RST=NC 导致面板从未启动」**。GT911 的 RST 应为上电 RC / 与屏共复位。
2. **[推测]** 触摸的 RST 很可能并到 `LCD_RST` 这个网络（`[推测]`：V2.0 引脚表把 IO48 标成"电池充电"，所以 `LCD_RST` 应是上电 RC 复位）。这与我们 `DISPLAY_RST_GPIO = GPIO_NUM_NC`（`config.h:47`）却能正常显示一致 —— 也意味着 **GT911 的地址是在 IO3 悬空时锁定的**，见 §3.2。
3. **[事实] 面板规格书里没有触摸型号** —— CTP 是单独一层/单独 FPC，**资料未给出**其型号。
4. **[推测]** `lcd_cmd_bits: 16` 这条独立佐证厂商 BSP 认的是 GT911 这类 16-bit 寄存器器件。

---

## 3. 为什么「初始化成功」是假阳性（驱动源码级）

### 3.1 FT5x06 驱动压根不校验芯片 ID —— 这是本次故障的机制

`~/AI_Workspace/05_Tools/xiaozhi-esp32/managed_components/espressif__esp_lcd_touch_ft5x06/esp_lcd_touch_ft5x06.c`

- `:69` `#define FT5x06_ID_G_CIPHER (0xA3)` —— **全文件唯一一次出现，从未被读取**。
- `:289-337` `touch_ft5x06_init()` 只做 9 次 `i2c_write`（THGROUP/THPEAK/…/PERIODMONITOR），**不读 0xA3，不做任何 ID 比对**，`return ret`。
- `:318-333` `touch_ft5x06_reset()`：`rst_gpio_num == NC` 时**直接 `return ESP_OK`**，等于没复位。

→ **[事实]** 只要 `0x38` 上有任何器件 ACK 这些写操作，`esp_lcd_touch_new_i2c_ft5x06()` 就返回成功。
→ 于是「初始化成功」+「`read_data` 读 `0x02 TD_STATUS` 永远 0 点」= 我们看到的现象。**init 成功完全不能证明 `0x38` 是触摸 IC。**

对照 GT911 驱动（`managed_components/espressif__esp_lcd_touch_gt911/esp_lcd_touch_gt911.c`）：
- `:168` `touch_gt911_read_cfg()`，失败即 `GT911 init failed` → **GT911 路径是会"硬失败"的**，天生能区分"有没有芯片"。

### 3.2 INT=NC 会不会导致读不到帧？—— 不会（对 GT911 而言）

`esp_lcd_touch_gt911.c`：
- `:221-231` `read_data` 直接 `i2c_read(0x814E, 1)` 轮询状态寄存器，**没有任何 INT 电平判断**。
- `:199-213` `int_gpio_num != NC` 只用于「配成输入 + 注册边沿中断/回调」。
- `:108-146` **地址锁存块要求 `rst` 和 `int` 同时非 NC**；`rst = NC` 时打印 `:145` `I2C address initialization procedure skipped - using default GT9xx setup`，然后 `:147` 调 `touch_gt911_reset()`，而后者在 `rst = NC` 时是空操作。

结论：
1. **[事实] INT 不接，GT911 仍能被轮询读到坐标**（LVGL 的 indev 是定时器轮询）。
2. **[事实] 但 INT(IO3) 同时是 GT911 的上电地址锁存脚**：`rst=NC` 时驱动**无法**主动选地址，只能"相信上电时锁好的那个"。
3. **[推测]** IO3 在我们固件里直到 `InitializeTouch()` 才被配置，上电复位窗口内是悬空态 → 地址可能锁成 `0x14`。**所以必须两个地址都试**，只写 `0x5D` 是赌博。

### 3.3 初始化顺序（display 与 touch 共用总线）

`chd_esp32s3_box_board.cc:1889-1895`：`InitializeI2c() → InitializeSpi() → InitializeDisplay() → InitializeTouch()`，`i2c_bus_` 只 `i2c_new_master_bus` 一次（`:1354`），全程**没有** `i2c_del_bus`。
→ **[事实] 不存在"先触摸后显示"的句柄失效问题；顺序是对的**，可排除。

**但**有一处**待验证隐患**：`InitializeCamera()` 在 `InitializeTouch()` 之后，`sccb_i2c_port = BSP_I2C_PORT`（`:1713`）—— 同一个 port 1 被 ESP32-S3 新 I2C 驱动占着，摄像头驱动再装一次总线会失败。这不解释"0 事件"，但会污染总线/日志，建议顺手确认。

---

## 4. 厂商 vs 我们（对照表）

| 项 | 厂商出厂固件 | 我们（HEAD 提交版） | 我们（当前工作区，未提交） |
|---|---|---|---|
| 驱动 | **GT911**（bin 实证） | FT5x06/FT6336（按 0x38 probe 选） | GT911 强制 |
| I2C 地址 | `0x5D`，备用 `0x14` | `0x38` | 仅 `0x5D` |
| 寄存器位宽 | `lcd_cmd_bits: 16` | 8 | 16 |
| INT | **IO3** | `NC` | IO3 |
| RST | 无（`int` 之外的唯一专线是 INT） | `NC` | `NC` ✅ |
| 频率 | 400 kHz | 400 kHz | 400 kHz |
| 旋转 | `mirror_y` 被 CHD 改成 false | 由 `display_mode` 推导 | 同左 |
| 坐标系 | `x_max 320 / y_max 240` | 480×320 + `swap_xy` | 480×320 + `swap_xy` + x 偏移 +80 |
| I2C 实例 / GPIO | port0 / IO8+IO18 | port1 / IO8+IO18 | 同左 |

> 当前工作区 `config.h:30-38` 与 `.cc:1486-1514` **已被另一路改动**（mtime 2026-10-28 11:25，含 `task-29 follow-up` 注释）：已强制 GT911、INT=IO3、并打印 `0x38/0x5D/0x14` 三点 probe。本调研独立得出同一结论。

---

## 5. 根因排序

| # | 假设 | 一句话证据 | 置信度 |
|---|---|---|---|
| **1** | **用错驱动**：实际是 GT911，我们按 `0x38` 选了 FT5x06 | 出厂 bin 里 `esp_lcd_touch_gt911`×7、`ft5x06/ft6336`×0；BSP YAML `chip: gt911` | 高 |
| **2** | `0x38` 上不是触摸 IC | 板上已知地址只有 ES8311 `0x18`、ES7210 `0x40`、GT911 `0x5D/0x14`、ICM42670 `0x68`，**`0x38` 无出处**；FT5x06 init 不校验 ID，随便谁 ACK 都"成功" | 高（同源） |
| **3** | GT911 地址锁成 `0x14`，而我们只探/只用 `0x5D` | `rst=NC` → 驱动跳过地址选择（gt911.c:145）；IO3 上电悬空 | 中 |
| **4** | INT=NC | 对 GT911 轮询**无影响**（gt911.c:221-231 不看 INT）；仅影响地址锁存与省电中断 | 低（非根因） |
| **5** | RST=NC 导致面板没启动 | 引脚表 + DXF 均无 CTP_RST 网络；`rst` 本就不存在 | 排除 |
| **6** | 触摸/显示初始化顺序 | 总线只建一次，display 先于 touch | 排除 |
| **7** | 坐标范围/旋转不匹配 | 只会让坐标偏或压在边上，不会 0 事件 | 排除 |

---

## 6. 下一步：具体改哪几行

> 当前工作区已改到 GT911 + INT=IO3，所以只需补 §6.1~6.3。

### 6.1 必做：`0x5D` 失败时回落 `0x14`（当前缺口）

`main/boards/chd/chd-esp32s3-box/chd_esp32s3_box_board.cc:1505`

```c
.dev_addr = ESP_LCD_TOUCH_IO_I2C_GT911_ADDRESS,          // 只有 0x5D
```

改成"地址作为参数"，先 0x5D 后 0x14：

```c
// 函数签名：bool InitializeTouch_gt911(uint16_t addr = ESP_LCD_TOUCH_IO_I2C_GT911_ADDRESS)
.dev_addr = addr,
...
// InitializeTouch() 里：
if (InitializeTouch_gt911(ESP_LCD_TOUCH_IO_I2C_GT911_ADDRESS)) return;
ESP_LOGW("CHD_TOUCH", "0x5D failed, retry 0x14");
if (InitializeTouch_gt911(ESP_LCD_TOUCH_IO_I2C_GT911_ADDRESS_BACKUP)) return;
```

依据：厂商 YAML `board_devices.yaml:119` 就是 `[0x5D, 0x14]`；`rst=NC` 时地址不可控（§3.2）。

### 6.2 必做：把 `0x38` 的结论从"日志"降级为"待证"

不要再让 `i2c_master_probe()` 决定驱动。保留现有 `CHD_TOUCH: i2c probe: 0x38=… 0x5D=… 0x14=…` 日志即可（`.cc:1657-1661` 已实现）。

**开机第一件事**：读这行日志。
- `0x5D=ESP_OK` → 就是 GT911，`0x38` 是别的器件，问题到此定性。
- `0x5D=ESP_ERR_NOT_FOUND` 且 `0x14=ESP_OK` → 命中假设 3，§6.1 修好即通。
- 两个都 `NOT_FOUND` → 触摸没上电/被复位拉死/总线有问题，转 §7.1 全总线扫描。

### 6.3 建议：把 `0xA3` 读出来贴日志（一次性排除 FT 系）

现有 `TouchReadRegs()`（`.cc:1215-1260`）已经会读 `0x8140`(GT911 版本) 与 FT 的 `0xA3`。**加一行硬判**：

```
0x38 的 0xA3 ∈ {0x64, 0x36, 0x63, 0x54, 0x55, 0x08} → 真 FT 系
0x38 的 0xA3 == 0xFF / 读失败                        → 不是触摸 IC（假 ACK 或别的器件）
```

（FT6336 的 `0xA3` 应为 `0x64`；**资料未给出**，需实测确认。）

### 6.4 若 GT911 两个地址都 init 失败

1. 确认 IO3 上电电平：`gpio_set_direction(IO3, INPUT_PULLDOWN)` 后**断电重启**再看 `0x5D`。GT911 在 RST 上升沿按 INT 电平锁地址（INT 低→`0x5D`，高→`0x14`）。**[推测]** 这是唯一能不拆机就"选地址"的手段 —— 但 RST 不在 GPIO 上，只能靠**先拉住 IO3 再上电**。
2. 若仍无：量 FPC 上 CTP 的 VDD/RST 是否有 3.3V；`0x5D` 无 ACK 基本就是 CTP 未上电或被复位拉死。

---

## 7. 资料未给出 → 必须实测的项

| 项 | 为什么资料给不出 | 最省实测法 |
|---|---|---|
| **CTP 型号** | 面板规格书（E350S030-D）只写 TFT+ST7796U，无触摸章节；DXF 里触摸 IC 不在板上（COF 在 FPC） | 读 GT911 `0x8140`×4 → 应含 ASCII `"911"`；读 FT `0xA3` → `0x64` |
| **`0x38` 到底是谁** | 无总线扫描日志；`0x38` 不在任何已知器件地址表里 | `for a in 0x08..0x77: probe`；若**大片地址同时 ACK** → SDA 被拉死/假 ACK，不是器件 |
| **CTP 上电锁的是 0x5D 还是 0x14** | 取决于 IO3 上电电平，无原理图 | §6.4 的 PULLDOWN 冷启动对比；或直接两地址都试 |
| **CTP 原生分辨率** | 无 CTP 规格书 | GT911 读 `0x8048`(X) / `0x804A`(Y) 配置寄存器，或点四角看 raw 值 |
| **CTP 是否有独立 RST** | 引脚表/DXF 都只有 `CTP_INT` | 已基本可判定"无"；如要确认，量 FPC 第 N 脚（需 FPC 定义，资料未给） |
| **厂商是否也在 `0x38` 上探测过** | 出厂固件无 ft5x06 代码，无从得知 | 无需 |

---

## 8. 证据复现命令（全部只读）

```bash
# 1) 厂商固件用的是 GT911 还是 FT5x06
strings -a ~/Downloads/CHD/chd-esp32s3-box-esp-claw_1.0.0.bin | grep -icE "gt911|ft5x06|ft6336"

# 2) 厂商板级配置
sed -n '107,130p' ~/Downloads/CHD/esp-claw/esp-claw_chd/application/edge_agent/boards/espressif/esp_box_3/board_devices.yaml

# 3) CHD 对厂商源码的唯一改动
git -C ~/Downloads/CHD/esp-claw/esp-claw_chd diff -- '*board_devices.yaml'

# 4) 引脚表：CTP_INT 与"没有 CTP_RST"
pdftotext -layout ~/Downloads/CHD/CHD-ESP32-S3-BOX_引脚配置表.pdf - | grep -nE "CTP|IO3|I2C_S"

# 5) 面板规格书：无触摸章节
pdftotext -layout ~/Downloads/CHD/3.5寸_亦亚徽E350S030-D显示屏产品规格书.pdf - | grep -icE "touch|触摸|CTP"   # → 0

# 6) FT5x06 驱动不校验芯片 ID
sed -n '289,337p' ~/AI_Workspace/05_Tools/xiaozhi-esp32/managed_components/espressif__esp_lcd_touch_ft5x06/esp_lcd_touch_ft5x06.c
```

---

## 9. 一句话交接

**出厂固件只认 GT911（0x5D，备用 0x14，INT=IO3，无 RST）；我们因为 `0x38` 有 ACK 就选了 FT5x06，而 FT5x06 驱动根本不校验芯片 ID，所以「初始化成功」是假阳性。下一步：读开机那行三地址 probe 日志，并给 GT911 补 0x14 回落。**
