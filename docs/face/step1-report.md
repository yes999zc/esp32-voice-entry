# M7 Step 1 真机验收证据（face_check.py）

- 时间：2026-10-27 11:01:33 CST
- 脚本 PID：94299；服务端 PID：79386
- 服务端：http://127.0.0.1:4411；板子侧地址：http://<mac-lan-ip>:4411
- token 来源：~/.esp32-voice/control.token
- 探活 `sent`：1

## 截图

| 文件 | 字节 | 推送 emotion | sent |
| --- | --- | --- | --- |
| `docs/face/step1-neutral.jpg` | 15733 | neutral | 1 |
| `docs/face/step1-happy.jpg` | 23046 | happy | 1 |
| `docs/face/step1-thinking.jpg` | 18544 | thinking | 1 |
| `docs/face/step1-confused.jpg` | 19072 | confused | 1 |

## 预览回显一击

- `preview_image` URL：http://<mac-lan-ip>:4411/screen/face-check-preview.png
- 设备回执：true
- 停止预览 6 s 后：`docs/face/step1-after-preview.jpg`（20218 bytes）
- 为什么预览的是生成的 PNG：设备快照只出 JPEG，而固件只编译了 PNG 解码器
  （`CONFIG_LV_USE_LODEPNG=y`，无 TJPGD）；预览 JPEG 会报 invalid，5 s 定时器
  不会启动，也就测不到 emoji 回显。

## 请人工确认

请人工确认：四张表情各不相同；after-preview 的脸中央仍是 kawaii 脸而不是小智 emoji。

## 备注

- 设备完全 Idle 时 WS 会话不存在，`/debug/emotion` 和 `/debug/tool` 都到不了板子；
  本报告只有在会话窗口内跑完才有效。
- 只调用了 `/debug/emotion`、`self.screen.snapshot`、`self.screen.preview_image`，
  没有调用任何破坏性工具。
