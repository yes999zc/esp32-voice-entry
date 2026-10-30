"""Device tools exposed to the LLM.

Names here are speech-friendly (`take_photo`), the firmware names are dotted
(`self.camera.take_photo`). Danger tools from the firmware (`reboot`,
`upgrade_firmware`, `set_download_url`, `reconfigure_wifi`) are deliberately
absent: a voice entry point has no confirmation UI, and a mis-wake must not be
able to reboot the board or flash it.
"""

DEVICE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "hermes_info",
            "description": "查询当前后台 Hermes 的版本、模型和连接方式。用户明确问"
                           "「你后台是什么/什么模型/Hermes 版本」时调用；不要猜版本。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "show_screen",
            "description": "截取这台设备当前的屏幕，并把它显示回设备屏幕上。用户说"
                           "「截个屏/把你屏幕上的画面给我看/显示出来」时调用。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "take_photo",
            "description": "用板子上的摄像头拍一张照片，返回画面内容。用户问「你看到什么」"
                           "「帮我看看」「这是啥」时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "想从照片里知道什么，例如「画面里有什么」「念一下纸上的字」",
                    },
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_volume",
            "description": "设置这台设备的音量。用户说太吵、太小声、音量调到几时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "volume": {"type": "integer", "minimum": 0, "maximum": 100},
                },
                "required": ["volume"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_device_status",
            "description": "读取设备当前状态（电量、音量、屏幕、网络）。不知道现状时先调它。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_brightness",
            "description": "设置屏幕亮度，0-100。",
            "parameters": {
                "type": "object",
                "properties": {
                    "brightness": {"type": "integer", "minimum": 0, "maximum": 100},
                },
                "required": ["brightness"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_theme",
            "description": "切换屏幕主题，light 或 dark。",
            "parameters": {
                "type": "object",
                "properties": {"theme": {"type": "string", "enum": ["light", "dark"]}},
                "required": ["theme"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "flip_camera",
            "description": "把摄像头画面上下翻转（拍出来是倒的时候用）。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_aec_mode",
            "description": "设置设备侧回声消除模式。只在调试「它说话时听不见我」时使用。",
            "parameters": {
                "type": "object",
                "properties": {"mode": {"type": "string"}},
                "required": ["mode"],
            },
        },
    },
]

# speech-friendly name -> firmware MCP tool name
DEVICE_NAME = {
    "take_photo": "self.camera.take_photo",
    "set_volume": "self.audio_speaker.set_volume",
    "get_device_status": "self.get_device_status",
    "set_brightness": "self.screen.set_brightness",
    "set_theme": "self.screen.set_theme",
    "flip_camera": "self.camera.set_camera_flipped",
    "set_aec_mode": "self.AEC.set_mode",
}

# Tools whose result is a photo upload round-trip, not a quick RPC.
SLOW_TOOLS = {"take_photo", "show_screen", "preview_image"}
# Tools that make the firmware close the audio channel before replying
# (Application::SetAecMode ends with CloseAudioChannel()), so the MCP result is
# never delivered. Expect the session to drop right after the call.
SESSION_ENDING = {"set_aec_mode"}
DEFAULT_TIMEOUT = 8.0
SLOW_TIMEOUT = 90.0

# ---------------- spoken confirmation (C2/C3) ----------------
# The first confirmation step must restate WHAT will happen, not just ask
# "should I do it". These are the Chinese action names spoken to the user; the
# raw tool name (`self.reboot`) must never be read out. Both the speech-friendly
# aliases and the firmware names are listed because `call_device_tool` accepts
# either (aliases from the LLM, firmware names from /debug/tool).
TOOL_ACTIONS = {
    "take_photo": "拍照",
    "self.camera.take_photo": "拍照",
    "set_volume": "调整音量",
    "self.audio_speaker.set_volume": "调整音量",
    "get_device_status": "读取设备状态",
    "self.get_device_status": "读取设备状态",
    "set_brightness": "调整屏幕亮度",
    "self.screen.set_brightness": "调整屏幕亮度",
    "set_theme": "切换屏幕主题",
    "self.screen.set_theme": "切换屏幕主题",
    "flip_camera": "翻转摄像头画面",
    "self.camera.set_camera_flipped": "翻转摄像头画面",
    "set_aec_mode": "切换回声消除模式",
    "self.AEC.set_mode": "切换回声消除模式",
    "self.reboot": "重启这台设备",
    "self.upgrade_firmware": "升级固件",
    "self.assets.set_download_url": "更换资源下载地址",
    "self.system.reconfigure_wifi": "重新配置 Wi-Fi",
}

# Spoken labels for the argument keys users actually hear. An unmapped key is
# kept verbatim (English key) in parentheses, which is acceptable in the
# restatement; the tool *name* is what must never leak.
ARG_LABELS = {
    "delay": "延迟秒数",
    "volume": "音量",
    "brightness": "亮度",
    "theme": "主题",
    "question": "问题",
    "mode": "模式",
    "url": "地址",
}

# Argument keys whose VALUE must never be spoken or logged (Wi-Fi credentials,
# tokens, secrets). Matched case-insensitively as substrings, so
# `wifi_password` / `api-key` / `accessToken` are covered too. The wire payload
# still carries the real value; only the restatement and the log are redacted.
SENSITIVE_KEY_MARKERS = (
    "password", "passwd", "pwd", "token", "secret", "api_key", "apikey",
    "api-key", "authorization", "bearer", "credential", "private_key",
    "密码", "口令", "令牌", "密钥", "凭证",
)
MASK = "***"


def is_sensitive_key(key) -> bool:
    """True when an argument key names a credential (never speak/log its value)."""
    lowered = str(key).lower()
    return any(marker in lowered for marker in SENSITIVE_KEY_MARKERS)


def redacted_arguments(arguments: dict | None) -> dict:
    """Copy of `arguments` with credential values replaced by `***` (for logs)."""
    if not arguments:
        return {}
    return {key: (MASK if is_sensitive_key(key) else value)
            for key, value in arguments.items()}


def action_name(tool_name: str) -> str:
    """Chinese action name for a tool; never the raw tool name."""
    return TOOL_ACTIONS.get(tool_name, "执行这个操作")


def arguments_summary(arguments: dict | None) -> str:
    """Short audible summary of a tool call, e.g. `音量=60，主题=dark`."""
    if not arguments:
        return ""
    parts = []
    for key, value in arguments.items():
        label = ARG_LABELS.get(key, str(key))
        shown = MASK if is_sensitive_key(key) else value
        parts.append(f"{label}={shown}")
    return "，".join(parts)


def confirm_question(tool_name: str, arguments: dict | None) -> str:
    """Step-one restatement: 「我要<动作>（参数摘要），确认吗？」."""
    action = action_name(tool_name)
    summary = arguments_summary(arguments)
    if summary:
        return f"我要{action}（{summary}），确认吗？"
    return f"我要{action}，确认吗？"


def spec_for(names: list[str] | None = None) -> list[dict]:
    """Tool specs for the LLM; `None` = all."""
    if names is None:
        return DEVICE_TOOLS
    wanted = set(names)
    return [t for t in DEVICE_TOOLS if t["function"]["name"] in wanted]
