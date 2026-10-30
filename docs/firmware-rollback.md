# 固件回滚锚（ESP32 桌面同事，2026-10-28 收口）

板子：CHD ESP32-S3 Box，默认变体 `chd-esp32s3-box-lcd35`（kawaii 脸，不切 emote）。
串口：`/dev/cu.usbmodem*`（口名会随插拔变，先 `ls /dev/cu.usbmodem*`）。

## 四个可回滚点

| 目标 | 固件 commit | app 大小 | app md5 | 归档文件（`02_Archive/esp32-voice-firmware/`） | 说明 |
|---|---|---|---|---|---|
| **D1/D2（当前板上）** | `68f0f06` | 2,884,288 B | `d70389dfa3b9e130d465b9e15a584f35` | `xiaozhi-b7d1d7c-touch-d1d2-md5-d70389df.bin` | 移除幽灵锚点 + 长按 HOLD；归档名沿用构建时的 `b7d1d7c` 前缀，内容对应 `68f0f06` |
| **C1（回滚）** | `b7d1d7c` | 2,884,656 B | `51b4f24fc084e3b723674972d1d479fe` | `xiaozhi-b7d1d7c-c1-md5-51b4f24f.bin` | B2 + C1 六状态 kawaii 映射 |
| **B2** | `9f99d88` | 2,884,560 B | `d68b6db8fd2bb0e1b8ef0a7bc54b97d1` | `xiaozhi-9f99d88-b2-md5-d68b6db8.bin` | B1 服务端静音 + B2 固件按钮/已静音/停采停传 |
| **B2 之前** | `d6efc16` | 2,872,128 B | `7e159681c3e10a2722d1560de6366d43` | `xiaozhi-d6efc16-b2pre-md5-7e159681.bin` | 无 B2 静音 UI（服务端 B1 静音仍可用） |

> B2 归档来自刷 C1 前从板上读回的 app 镜像（md5 已核对）；不是重新构建产物。D1/D2 归档来自 `68f0f06` 构建（构建时 commit 尚未生成，文件名保留 `b7d1d7c` 前缀），内容 md5 与板上读回一致。

## 回滚命令（只写 app 分区 0x20000）

```bash
source <workspace>/05_Tools/esp-idf-6.1/export.sh
PORT=$(ls /dev/cu.usbmodem* | head -1)
BIN=<workspace>/02_Archive/esp32-voice-firmware/xiaozhi-b7d1d7c-c1-md5-51b4f24f.bin

esptool.py --chip esp32s3 -p "$PORT" -b 460800 write_flash 0x20000 "$BIN"
```

写后读回校验：

```bash
esptool.py --chip esp32s3 -p "$PORT" -b 460800 read_flash 0x20000 0x2c0430 /tmp/readback-c1.bin
md5 -q /tmp/readback-c1.bin   # C1 应为 51b4f24fc084e3b723674972d1d479fe
```

读回长度/期望 md5：
- D1/D2：`0x2c02c0`，`d70389dfa3b9e130d465b9e15a584f35`
- C1：`0x2c0430`，`51b4f24fc084e3b723674972d1d479fe`
- B2：`0x2c03d0`，`d68b6db8fd2bb0e1b8ef0a7bc54b97d1`
- B2 前：`0x2bd340`，`7e159681c3e10a2722d1560de6366d43`

## 注意

- 只回滚 app 分区即可，四个锚点的 bootloader/分区表/assets 未变；若从更早版本（非本表）回滚，必须用完整 `flash_args`。
- 回滚后要重新确认服务端 `/debug/mute` 状态与屏幕是否一致（B2/B1 静音真相在服务端）。
- 一次刷机只带一类变更：B2 / C1 / D1+D2 分三次，不要把补丁混进回滚镜像。
