-- 步骤 1~9：打开微信 → 搜索收件人 → 打开对话 → 粘正文 → 读回校验
-- 只做键盘 + 剪贴板，不读 AX、不截图、不算坐标。
-- 参数: 1=收件人 2=正文
-- 输出: box=[<输入框里读回来的字>]
on run argv
	set contact to item 1 of argv
	set body to item 2 of argv
	do shell script "open -b com.tencent.xinWeChat"
	delay 2.0
	tell application "WeChat" to activate
	delay 1.0
	tell application "System Events" to tell process "WeChat"
		set frontmost to true
		delay 0.5
		keystroke "f" using command down
		delay 1.0
		keystroke "a" using command down
		delay 0.2
		key code 51
		delay 0.3
		set the clipboard to contact
		delay 0.2
		keystroke "v" using command down
		delay 1.0
		key code 36
		delay 2.0
		key code 53
		delay 0.8
		keystroke "a" using command down
		delay 0.2
		key code 51
		delay 0.3
		set the clipboard to body
		delay 0.2
		keystroke "v" using command down
		delay 1.0
		keystroke "a" using command down
		delay 0.3
		keystroke "c" using command down
		delay 0.5
		set got to the clipboard as text
		key code 124
		delay 0.2
		return "box=[" & got & "]"
	end tell
end run
