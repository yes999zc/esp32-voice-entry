# C1 六状态真机截图（2026-10-28 17:47）

- 固件：`b7d1d7c`（C1 kawaii 六状态），板上 app md5 `51b4f24fc084e3b723674972d1d479fe`
- 变体：`chd-esp32s3-box-lcd35`（kawaii 脸，未切 emote）
- 截图方式：MCP `self.screen.snapshot` → `POST /debug/upload` → `~/.hermes/cache/scratch/esp32-voice/photos/`
- 触发方式：C2 尚未在生产重启，六状态用 `/debug/emotion` / `self.screen.set_emotion` 直接推 emotion；映射与自然状态推送共用同一 `FaceEmotionFromName`。
- 说明：静态截图会撞上眨眼/弹跳帧；`idle.jpg` 已重拍到睁眼帧。`unknown.jpg` 是 `nonsense` 推入后的回落，日志 `nonsense -> 0`，与 idle 同 enum（像素会因眨眼/弹跳有差）。

| 文件 | 状态 | 服务端 emotion | 固件日志 | FACE enum |
|---|---|---|---|---|
| `idle.jpg` | idle | neutral（旧服务端名；C1a 后为 idle） | `neutral -> 0` | NEUTRAL |
| `listening.jpg` | listening | happy | `happy -> 1` | HAPPY |
| `thinking.jpg` | thinking | confused | `confused -> 15` | CONFUSED |
| `speaking.jpg` | speaking | speaking | `speaking -> 14` | EXCITED |
| `working.jpg` | working | angry | `angry -> 13` | WORKING_HARD |
| `confirm-pending.jpg` | confirm-pending | shocked | `shocked -> 4` | SURPRISED |
| `unknown.jpg` | unknown → idle | nonsense | `nonsense -> 0` | NEUTRAL |

人工目视：六张均为 480×320、脸区居中；idle/listening/thinking/speaking/working/confirm 在眉眼、嘴形、汗滴/惊讶纹上可辨；speaking 的 EXCITED 与 listening 的 HAPPY 是同一“笑”族，静态帧接近，动效（快速转眼/弹跳）区分，待 C2 生效后按自然状态复看。
