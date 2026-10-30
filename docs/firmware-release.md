# 固件发布/回滚校验（2026-10-28 收口）

仓库：`05_Tools/xiaozhi-esp32`，分支 `feat/persona-face`。
- `origin` = `https://github.com/yes999zc/xiaozhi-esp32.git`（fork，ssh 推送）
- `upstream` = `https://github.com/78/xiaozhi-esp32.git`（保留，不推）
- `gh auth status`：`yes999zc` 已登录；**未使用 force / force-with-lease**。

## 远端同步（2026-10-28 19:1x 核对）

```text
git rev-list --count HEAD                      -> 19
git rev-list --count origin/feat/persona-face  -> 19
git ls-remote origin refs/heads/feat/persona-face
  68f0f060127a...
git status -b --short
  ## feat/persona-face...origin/feat/persona-face   (ahead/behind 0/0)
```

HEAD `68f0f06 fix(touch): remove ghost anchor and keep long-press held`；`d6efc16`、`9f99d88`、`b7d1d7c`、`68f0f06` 均在远端。

## bin ↔ commit（归档即回滚权威）

| 目标 | commit | 大小 | md5 | `image_info` 编译时间 | 归档 |
|---|---|---|---|---|---|
| **D1/D2（板上）** | `68f0f06` | 2,884,288 B | `d70389dfa3b9e130d465b9e15a584f35` | Oct 28 2026 16:51:03（`image_info`；bin mtime 19:02） | `xiaozhi-b7d1d7c-touch-d1d2-md5-d70389df.bin` |
| C1（回滚） | `b7d1d7c` | 2,884,656 B | `51b4f24fc084e3b723674972d1d479fe` | Oct 28 2026 16:51:03 | `xiaozhi-b7d1d7c-c1-md5-51b4f24f.bin` |
| B2 | `9f99d88` | 2,884,560 B | `d68b6db8fd2bb0e1b8ef0a7bc54b97d1` | Oct 28 2026 15:12:45 | `xiaozhi-9f99d88-b2-md5-d68b6db8.bin` |
| B2 前 | `d6efc16` | 2,872,128 B | `7e159681c3e10a2722d1560de6366d43` | （历史归档） | `xiaozhi-d6efc16-b2pre-md5-7e159681.bin` |

四者 `Project name: xiaozhi / App version: 2.5.3 / ESP-IDF v6.1`，checksum valid。D1/D2 bin 与板上读回 md5 一致。

**可复现性边界**：ESP-IDF 会把编译时间写进 app 镜像，重新构建同一 commit 不保证 md5 相同；上表 md5 以**归档 bin / 板上读回**为准，不用“重编一次”冒充同一镜像。B2 bin 是刷 C1 前从板上读回的原始 app（不是重编）。

## Secret 扫描（18 个提交，`origin/main..HEAD`；分支共 19 个）

方法：`git log -p --format= origin/main..HEAD > /tmp/fw-18commits.patch`（425,214 B），按真实凭证形状搜：
`ghp_…` / `sk-…` / `AKIA…` / `Bearer <20+>` / `BEGIN … PRIVATE KEY` / `*.env` 文件。

结果：**0 命中**（0/0/0/0/0/0）。  
`token` 字样全部是代码标识符/日志（`mute_controller_->SetEndpoint(vision_url, token)`、`mute token refresh` 等），不是明文凭证。没有 `.env`、私钥或云 key 进入历史。

## 状态

- D1/D2 新 commit `68f0f06` 已 push；bin `d70389df…` 已归档并与板上读回一致；fork 19/19、ahead/behind 0/0。
- task-8 的 fork/bin/secret 三项已收口；后续每次触摸/UI 刷机后按同表更新 commit→bin md5。

回滚命令见 [firmware-rollback](firmware-rollback.md)。

---

# 如何产出 factory 镜像（`0x0` 一次烧）

构建点：`05_Tools/xiaozhi-esp32` 分支 `fix/persona2-zone-taps`，commit **`9b22121`**；
变体 **`chd-esp32s3-box-lcd35`**（板型目录 `main/boards/chd/chd-esp32s3-box/`，
变体声明 `config.json:12-21`）。ESP-IDF `release/v6.1`。

## 1. 命令

```bash
source <esp-idf>/export.sh
cd <xiaozhi-repo>
python3 scripts/build.py chd/chd-esp32s3-box \
  --name chd-esp32s3-box-lcd35 --language zh-CN --zip
# 产物：build/xiaozhi.bin（app）、build/merged-binary.bin（整包）、
#       releases/v2.5.3_chd-esp32s3-box-lcd35.zip（zip 内只有 merged-binary.bin）
# ⚠️ 本分支这条命令编出来的是未展开占位 CONFIG_OTA_URL（export XIAOZHI_OTA_BASE 不生效），
#    要带自己的地址必须再走下面「`9b22121` 上的已知缺陷」里的 fragment 展开做法。
```

`scripts/build.py` 的参数以 `--help` 为准（`board` 位置参数 + `--name/--language/--wake-word/--zip`）；
变体名可用 `python3 scripts/build.py --list-boards | grep -i chd` 核对。

### ⚠️ `9b22121` 上的已知缺陷：`XIAOZHI_OTA_BASE` 不生效

`[已核]` `scripts/build.py` 的 `_expand_ota_base()`（`:412-415`）只在
`--list-boards` / option 定义路径被调用（`:509`、`:977`）；真正构建用的 `sdkconfig_append`
是未展开的原样（`:1577-1596`，`_configure_build()` 在 `:1429-1460` 把字符串直接写进
`build/xiaozhi-build.sdkconfig.defaults`）。ESP-IDF 的 Kconfig 也**不会**展开 `${VAR}`
（实测：`export XIAOZHI_OTA_BASE=...` 后 `idf.py reconfigure`，`sdkconfig` 仍是字面量
`"${XIAOZHI_OTA_BASE}/xiaozhi/ota/"`，编出的镜像里也是这个字面量）。

结果就是三种可能：

| 做法 | `sdkconfig` 里的 `CONFIG_OTA_URL` | 镜像可用性 |
|---|---|---|
| 直接跑 `build.py`（带不带 `XIAOZHI_OTA_BASE`） | `${XIAOZHI_OTA_BASE}/xiaozhi/ota/` 字面量 | 设备回落到这个坏 URL → OTA 必失败 |
| 手工把展开值写进生成的 fragment 后 reconfigure | `http://<server-ip>:4411/xiaozhi/ota/` | 正常（本次发布的 A 版即此法） |
| 不改镜像，改 NVS | 镜像里仍是占位，NVS `wifi/ota_url` 优先（值是完整端点，见下） | 正常（`scripts/make_nvs_ota.py`） |

可复现的展开做法（**不改任何 tracked 源文件**）：正常跑一次 `build.py` 让它生成
`build/xiaozhi-build.sdkconfig.defaults`，把其中 `CONFIG_OTA_URL=` 一行替换为展开后的地址，
然后重新配置并构建：

```bash
# 1) 让 build.py 生成 fragment（这一步产物可以丢弃）
python3 scripts/build.py chd/chd-esp32s3-box --name chd-esp32s3-box-lcd35 --language zh-CN
# 2) 把 generate 出来的占位行改成真实地址（例：sed -i '' 's#\${XIAOZHI_OTA_BASE}#http://<server-ip>:4411#' ...）
# 3) 干净重配 + 全量构建（fullclean 会删 build/，所以 fragment 要在 fullclean 之后写）
source <esp-idf>/export.sh
idf.py fullclean
#    重新写回展开后的 build/xiaozhi-build.sdkconfig.defaults
rm -f sdkconfig
idf.py -DIDF_TARGET=esp32s3 \
  -DSDKCONFIG_DEFAULTS="sdkconfig.defaults;build/xiaozhi-build.sdkconfig.defaults" \
  -DBOARD_NAME=chd-esp32s3-box-lcd35 reconfigure
idf.py build && idf.py merge-bin
```

构建后**先断言再打包**（不满足就别发布）：

```bash
grep -n '^CONFIG_OTA_URL' sdkconfig                                  # 期望展开后的地址
grep -n 'CONFIG_OTA_URL' build/config/sdkconfig.h                    # 期望同上
strings -a build/xiaozhi.bin | grep -c 'XIAOZHI_OTA_BASE'            # 期望 0
strings -a build/xiaozhi.bin | grep 'xiaozhi/ota'                    # 期望 http(s)://<真实或占位域名>
```

彻底修法（下一张卡）：让 `scripts/build.py:1577` 取 `_expand_ota_base(build.get("sdkconfig_append", []))`，
一行改动，之后 `export XIAOZHI_OTA_BASE=...` 就按文档生效。

## 2. 分区与 offset 表（`sdkconfig.defaults:14-16` → `partitions/v2/16m.csv`）

| 区 | offset | size | 是否在 `merged-binary.bin` 里 |
|---|---|---|---|
| bootloader | `0x0` | 0x8000（csv 外隐式） | ✅ 起始 |
| partition-table | `0x8000` | 0x1000（`sdkconfig.defaults:16` `CONFIG_PARTITION_TABLE_OFFSET=0x8000`） | ✅ |
| nvs | `0x9000` | `0x4000` | ⚠️ 区间在，但内容全是 `0xFF`（=擦除） |
| otadata | `0xd000` | `0x2000` | ✅（`ota_data_initial.bin`） |
| phy_init | `0xf000` | `0x1000` | ❌ 未写（空） |
| ota_0（app） | `0x20000` | `0x3f0000`（4032 K） | ✅ |
| ota_1 | `0x410000` | `0x3f0000` | ❌ 空（`0x410000 = 0x20000 + 0x3f0000`，csv 里 offset 留空由工具算） |
| assets（spiffs） | `0x800000` | `8M` | ✅（`generated_assets.bin`） |

`[已核]` `build/flash_args` 实际写入顺序：
`0x0 bootloader.bin` / `0x8000 partition-table.bin` / `0xd000 ota_data_initial.bin` /
`0x20000 xiaozhi.bin` / `0x800000 generated_assets.bin`；`merge_bin()`（`build.py:81-83`）用
`esptool merge-bin -f raw @flash_args` 合成，间隙填 `0xFF`。整包长度 = `0x800000 + assets 长度`
（本次 10164189 B = `0x9B17DD`）。

**NVS 不在整包里**：`0x9000`–`0xD000` 这 16384 B 实测非 `0xFF` 字节数为 **0**，即整包把 NVS 擦成空白；
设备首次启动由 `nvs_flash_init()` 建表（`wifi/ota_url` 也是运行期才写）。所以刷 `0x0` 必然丢 Wi-Fi 凭据。

## 3. 校验方法（发布前逐条跑）

```bash
# a) 三份文件的指纹
shasum -a 256 merged-binary.bin xiaozhi.bin ; stat -f%z merged-binary.bin xiaozhi.bin

# b) 从整包里解出分区表（0x8000 起 0x1000 字节）
dd if=merged-binary.bin of=/tmp/pt.bin bs=1 skip=32768 count=3072
python3 $IDF_PATH/components/partition_table/gen_esp32part.py --flash-size 16MB /tmp/pt.bin
#   逐行对 partitions/v2/16m.csv：nvs/otadata/phy_init/ota_0/ota_1/assets 的 offset+size 应完全一致

# c) 整包里的 app 段必须与 xiaozhi.bin 逐字节相同
APP=$(stat -f%z xiaozhi.bin)
dd if=merged-binary.bin of=/tmp/app-seg.bin bs=1 skip=131072 count=$APP    # 131072 = 0x20000
cmp /tmp/app-seg.bin xiaozhi.bin && echo "app segment identical"

# d) 镜像头/校验和（esptool 5.6.0；`image_info` 已 deprecated，等价 `image-info`）
python3 -m esptool image_info build/bootloader/bootloader.bin   # Detected image type: ESP32-S3
python3 -m esptool image_info xiaozhi.bin                       # Checksum / Validation hash valid

# e) OTA 地址断言（A 版应为占位域名；B 版为真实地址）
strings -a merged-binary.bin | grep -c 'rui-ota.invalid'                 # 期望 1
strings -a merged-binary.bin | grep -c '192\.168\.'                      # 期望 0（192.168.4.1 以分拆 octet 形式存在，见下）
strings -a xiaozhi.bin | grep -c 'XIAOZHI_OTA_BASE'                      # 期望 0
```

> `[已核]` `strings | grep '192\.168\.'` 命中 **0**：镜像里没有明文 LAN IP；
> SoftAP 的固定 `192.168.4.1` 在源码里是拆成 octet 的（`IP4_ADDR(..., 192, 168, 4, 1)` 和
> `std::to_string(192) + "." + ...`），所以字符串扫描不到——这是**正常**的，
> 不代表 SoftAP 地址缺失。

## 4. 为什么要用占位地址

公开镜像必须能给别人用，而服务端地址因人而异：把某个内网 IP 编进去，对别人就是死地址，还会泄露
作者的内网结构（历史镜像里没有明文内网 IP，这个约束要继续保持）。所以公开镜像编
`http://rui-ota.invalid:4411/xiaozhi/ota/`（`.invalid` 是 RFC 2606 保留域，永远不会解析），
设备侧再通过两条**不需要改源码**的路子修正：

1. 重编时展开成自己的地址（见 §1 的缺陷说明与「彻底修法」）；
2. 保持镜像不动，把 `ota_url` 写进 NVS —— `scripts/make_nvs_ota.py` 刷 `0x9000`
   （脚本会把 base 规范化成 `<base>/xiaozhi/ota/`：固件把该值当**完整 URL** 用、不做拼接，服务端只注册该路由），
   或配网高级页 `/advanced` 直接填（`docs/quickstart-single-board.md` §3.5 第 6 条）。

自用版（真实地址）镜像**不入 git、不上传 release**，只落本地归档
（`02_Archive/esp32-firmware/factory-<日期>/`）。

