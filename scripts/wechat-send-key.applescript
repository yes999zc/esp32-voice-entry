-- 步骤 10~11：发送，然后在会话里回读，确认这条真的发出去了
-- 参数: 1=正文
-- 输出: found=yes / found=no
on run argv
	set body to item 1 of argv
	tell application "System Events" to tell process "WeChat"
		set frontmost to true
		delay 0.4
		key code 36
		delay 1.5
		set {wx, wy} to position of window 1
		set {ww, wh} to size of window 1
		click at {(wx + (ww * 0.6)) as integer, (wy + (wh * 0.4)) as integer}
		delay 0.6
		keystroke "a" using command down
		delay 0.4
		keystroke "c" using command down
		delay 0.6
		set got to the clipboard as text
		key code 124
		delay 0.2
		if got contains body then return "found=yes"
		return "found=no"
	end tell
end run
