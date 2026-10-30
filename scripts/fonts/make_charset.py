#!/usr/bin/env python3
"""Build deterministic glyph subsets for UI v2 fonts.

Output (scripts/fonts/build/, git-ignored):
  charset-800.txt   800 CJK glyphs for MiSans 20px  (primary UI/body font)
  charset-500.txt   first 500 of the same order, for MiSans 14px (detail)
  charset-title.txt  room names + state words, for MiSans 32px (title)
  charset-mono.txt  ASCII printable + a few symbols, for JetBrains Mono

Order = curated high-frequency characters first, then project-doc characters by
frequency. This keeps the 800-set stable even if docs change (only the tail is
affected). No third-party list is downloaded.
"""
import collections
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
BUILD = pathlib.Path(__file__).resolve().parent / "build"

# Curated high-frequency characters (UI + everyday speech). Order matters: the
# 500-set is a prefix of the 800-set, so the most useful glyphs must come first.
CURATED = (
    "的一是不了人我在有他这为之大来以个中上们到说国和地也子时道出而要于就下得可你年生自会那后能对着事其里所去行过家十用发天如然作方成者多日都三小军二无同么经法当起与好看学进种将还分此心前面又定见只主没公从"
    "房间客厅卧室书房厨房阳台玄关洗手间儿童老的书桌沙发灯门窗墙地板温度湿度空气晴雨风雪冷热干舒服开关灯光窗帘空调风扇电视音箱音乐播放暂停继续停止音量大小声快慢"
    "现在几点钟分秒上午下午晚上今天明天昨天本周星期一二三四五六日月份年号天气预报降雨概率最高最低度"
    "你好早上晚安再见谢谢不客气对不起没关系请问请稍等一下可以行好的收到明白知道不知道要不要是不是对不对有没有什么怎么为什么哪里谁几个多少"
    "打开关闭启动暂停取消确认设置调整增加减少调高调低切换返回上一页下一页首页菜单列表详情状态在线离线连接断开网络信号强弱充电电量满低充足"
    "提醒闹钟计时预约日程会议休息吃饭睡觉起床洗漱出门回家上班下班工作学习阅读锻炼散步喝水吃药"
    "播放新闻股票汇率天气路况限号快递外卖订单支付账单记账预算消费收入支出余额"
    "我你他她它们咱大家自己别人朋友家人爸爸妈爷奶奶哥姐弟妹孩子宝宝先生女士老师同学同事领导客户"
    "感觉高兴开心快乐难过伤心生气着急紧张害怕放心担心希望想要需要应该必须可能也许大概差不多"
    "时间地点人物原因结果问题办法事情东西地方时候以后以前现在正在已经还没完成开始结束继续等待处理"
    "红色蓝色绿色黄色白色黑色灰色橙色紫色粉色彩色亮暗深浅大小高矮长短粗细宽窄厚薄轻重快慢远近"
    "第一次第二次左右前后上下里面外面旁边中间附近周围东南西北方向路线距离公里米分钟小时天周月年"
    "语音助手智能回答请问需要帮忙帮助服务功能选项操作使用方法说明提示错误失败成功完成进度加载等待"
    "注意小心危险安全紧急报警求助医院医生身体健康感冒发烧咳嗽疼痛休息睡眠运动饮食营养水果蔬菜米饭面条鸡蛋牛奶咖啡茶"
)

CN_PUNCT = "，。！？、；：“”‘’（）《》〈〉【】…—·～"
TITLE_CHARS = "房间客厅卧室书房厨房阳台玄关儿童洗手间主次在听想说话空闲待机播报确认取消加音量"

def cjk(ch: str) -> bool:
    return "\u4e00" <= ch <= "\u9fff"

def doc_chars() -> str:
    counter = collections.Counter()
    paths = list((ROOT / "docs").rglob("*.md"))
    readme = ROOT / "README.md"
    if readme.exists():
        paths.append(readme)
    for p in paths:
        for ch in p.read_text(encoding="utf-8", errors="ignore"):
            if cjk(ch):
                counter[ch] += 1
    # deterministic: frequency desc, then codepoint asc (stable across machines)
    return "".join(ch for ch, _ in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])))

def dedupe(s: str) -> str:
    seen, out = set(), []
    for ch in s:
        if ch not in seen:
            seen.add(ch)
            out.append(ch)
    return "".join(out)

def main() -> int:
    base = dedupe("".join(ch for ch in CURATED if cjk(ch)))
    if len(base) < 800:
        base = dedupe(base + doc_chars())
    if len(base) < 800:
        print(f"ERROR: only {len(base)} CJK glyphs available, need 800", file=sys.stderr)
        return 1
    set800 = base[:800]
    set500 = base[:500]

    title = dedupe("".join(ch for ch in TITLE_CHARS if cjk(ch)))
    # 95 ASCII codepoints + "°%/·"; "/" and "%" already in ASCII -> 99 codepoints, 97 unique glyphs
    mono = dedupe("".join(chr(c) for c in range(0x20, 0x7F)) + "°%/·")

    BUILD.mkdir(parents=True, exist_ok=True)
    (BUILD / "charset-800.txt").write_text(set800 + CN_PUNCT + "\n", encoding="utf-8")
    (BUILD / "charset-500.txt").write_text(set500 + CN_PUNCT + "\n", encoding="utf-8")
    (BUILD / "charset-title.txt").write_text(title + "\n", encoding="utf-8")
    (BUILD / "charset-mono.txt").write_text(mono + "\n", encoding="utf-8")

    print(f"charset-800: {len(set800)} CJK + {len(CN_PUNCT)} punct")
    print(f"charset-500: {len(set500)} CJK + {len(CN_PUNCT)} punct  (prefix of 800)")
    print(f"charset-title: {len(title)} CJK")
    print(f"charset-mono: 99 codepoints, {len(mono)} unique glyphs")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
