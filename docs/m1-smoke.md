# M1 冒烟记录 — 2026-10-26

第一块真板（虫洞 CHD-ESP32-S3-BOX，3.5" + 摄像头）当晚上机。**没有调任何参数**：
唤醒门限、麦阵、AEC、音量区间全部是固件默认值。下面每个数字都来自串口日志或
服务端日志，不是估算。

## 1. 刷机

```
factory image 16 MB        1a54d967…601ea2   (备份，回滚用)
our firmware               98b28de9…27cfa80   chd-esp32s3-box-lcd35_v2.5.3_…
写入 10 164 192 字节 / 20.7 s / 校验通过
```

- 出厂固件其实就是同一块板的官方构建（SKU 相同），只是 OTA 指向
  `api.tenclass.net`。所以「回滚」= 写回 16 MB 备份。
- 写 0x0 会覆盖 NVS，Wi-Fi 凭据必然丢，刷完进配网 AP（`Xiaozhi-<mac-suffix>` @ <ap-ip>）。
- **本次没有手工配网**：老板自己在手机上配好了，板子起来直接拿到 <device-lan-ip>。

启动日志关键行：

```
Project name: xiaozhi      App version: 2.5.3
Board: UUID=6e24e03f-… SKU=chd-esp32s3-box-lcd35
Chd-Esp32s3-Box-Board: chd camera fb get OK
ES8311 slave / ES7210 TDM 4 slot / 4 路麦使能
WifiStation: Got IP: <device-lan-ip> → State: activating → idle
```

## 2. 语音闭环（第一句就成）

```
[conn] <device-lan-ip>
hello sr=16000 frame=60
[listen] start realtime
[asr] 0.07 s  你好，小志。
[llm] 1.16 s  你好，我在呢，有什么可以帮你的？
[asr] 0.07 s  现在几点？
[llm] 0.85 s  现在晚上十一点零四分。     ← 真实时间 23:04:52，答对
```

## 3. 修正后的一轮（唤醒剥离 + 音量 + 首帧计时）

```
[mcp] initialize vision=http://<mac-lan-ip>:4411/xiaozhi/vision
[mcp] set_volume 90
[asr] wake stripped: '你好，小志，几点。' -> '几点。'
[llm] 0.9 s   现在是晚上十一点零八分
[tts] synth 0.21 s → first frame 1.18 s      ← 冷启动
[asr] wake-only, no turn: '你好，小志。'
[tts] first frame 0.83 s                      ← 稳定值
[tts] first frame 0.77 s
[llm] 0.42 s（第三轮）
```

## 4. 摄像头（MCP 触发 → 图像上行 → 本地视觉）

```
[debug] mcp self.camera.take_photo {"question": "画面里有什么？谁在镜头前？"} -> 1 session
[vision] 28451 bytes from 80:b5:4e:cd:0f:64 → photos/20261026-231413.jpg
[vision] -> 手机屏幕反光，旁边有玩具车，没人，纯物象。
[mcp] result {"content":[{"type":"text","text":"{…}"}],"isError":false}
```

链路顺序（这是理解整套东西的关键）：

```
server  --MCP tools/call-->  板子拍照（GC2145，RGB565→JPEG q80）
板子    --HTTP multipart-->  server.vision_url（question + file）
server  --OpenAI vision-->   本机 oMLX Qwen3-VL-4B
server  --MCP result-->      板子（同一条 ws，原样回传文本）
```

`vision_url` 不是配置在固件里的，是我们在 MCP `initialize` 的
`capabilities.vision.url` 里下发的（`mcp_server.cc::ParseCapabilities`）。

## 5. 当晚踩到的坑（都已解决，别再踩）

1. **Homebrew Python 3.15 进程收不到局域网入站。** 表现为 TCP 能连（`nc` 成功）、
   HTTP 永远不回；loopback 完全正常；`socketfilterfw --getappblocked` 说 permitted，
   ALF 列表里也是 allow。同机的 uv 3.13 和 Xcode 3.9 都正常。结论：换解释器，
   不跟它较劲。
2. **opuslib 在 3.13 下找不到 libopus。** 需要
   `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib`。
3. **`python -m src.server` 起不来。** `src/` 里是扁平 import，必须
   `cd src && python server.py`。
4. **重启太快会撞端口。** 旧进程收 SIGTERM 后要几秒才释放 4411，新进程直接
   `[Errno 48] address already in use`；等 3–5 s 再起。
5. **唤醒词会进 ASR。** 设备唤醒后还会多推一点音频，`你好，小志。` 被当问题回答。
   服务端 `strip_wake()` 剥前缀；剥成空串就不开回合。
6. **音量不在最大。** 默认值偏小，握手后发 `self.audio_speaker.set_volume`，
   写进 NVS，重启保持。现在是 90。
7. **会话说完就断。** 小智空闲会关 WS，所以外部随时发指令不可行——这也是 M5
   要把「工具接进回合」而不是靠旁路命令的原因。

## 6. 回滚

```bash
# 板子进下载模式（无串口时：断电 → 按住 BOOT → 上电），然后
python3 -m esptool --chip esp32s3 -p /dev/cu.usbmodemXXXX -b 460800 \
  write-flash 0x0 <factory 16MB dump>
```

## 7. 无人值守复测（同日 23:30，人已离开板子）

现场没人也能跑：用插在 Mac 上的 2K USB 摄像头自带喇叭播 TTS，物理位置就在板子旁边。

```
播「你好小智」                        → 板子被唤醒，WS 重连成功
播「帮我拍张照片，看看桌上有什么」      → [asr] 0.06 s 「有什么？」
                                     → [llm] 1.10 s  tool_calls ['take_photo']
                                     → [mcp] take_photo 1.34 s
                                     → [vision] 21622 bytes → 本地 Qwen3-VL
                                     → [llm] 1.03 s「我看到天花板上两盏亮着的灯…」
                                     → [tts] first frame 3.96 s / 整回合 10.29 s
```

要点：

- 唤醒词模型名就叫 `WN9_NIHAOXIAOZHI_TTS`，训练语料本就是合成语音，所以 TTS 喊得醒。
  输出设备切到 `2K USB Camera-Audio`（`SwitchAudioSource -s` + `afplay`），播完切回。
- 这一段是**模型自己选的工具**：用户只说「拍张照片」，没有外部指令注入。
- 工具回合的真实延迟：工具 1.3 s、二次推理 1.0 s、TTS 首帧 4.0 s（整段 6.6 s 音频一次合成）。
  首帧慢的原因是整段 TTS 而非流式，属于 M6 要解决的。
