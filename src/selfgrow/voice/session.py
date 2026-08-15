"""VoiceSession：把「录音 → 识别 → 解析 → 确认」编排成统一的 listen_* 方法。

真实实现注入 SounddeviceMic / WhisperASR / AutoTTS；测试注入 Mock（保持确定性）。
语义规则见 parser.py。
"""

from __future__ import annotations

import re
import sys
from typing import Any

from selfgrow.voice.parser import RETRY, parse_action, parse_confirm, parse_option

# 装饰 emoji（角色横幅等）：TTS 朗读会很怪，朗读前剥掉；屏幕显示保留原样
_EMOJI_RE = re.compile(r"[\U0001F000-\U0001FAFF☀-➿️]")


def _print_safe(text: str) -> None:
    """打印文本：GBK 等旧编码控制台对装饰符(emoji)无法编码时兜底，不中断流程。"""
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        print(text.encode(enc, errors="replace").decode(enc))
    except (LookupError, ValueError):  # 非常规编码名
        print(text)


def _voice_text(text: str) -> str:
    """朗读文本：去掉装饰 emoji 与首尾空白，避免 TTS 读出一串符号。"""
    return _EMOJI_RE.sub("", str(text or "")).strip()


class VoiceSession:
    def __init__(self, mic: Any, asr: Any, tts: Any):
        self._mic = mic
        self._asr = asr
        self._tts = tts

    @property
    def tts_name(self) -> str:
        return getattr(self._tts, "name", "?")

    @property
    def asr_name(self) -> str:
        return self._asr.__class__.__name__

    def speak(self, text: str) -> None:
        """只朗读（文字已在界面打印）。"""
        self._tts.speak(_voice_text(text))

    def say(self, text: str) -> None:
        """打印 + 朗读。"""
        _print_safe(f"  🔊 {text}")
        self._tts.speak(_voice_text(text))

    def is_available(self) -> bool:
        """快速探测是否有可用麦克风（无则回落文字交互）。"""
        try:
            import sounddevice as sd

            return any(d["max_input_channels"] > 0 for d in sd.query_devices())
        except Exception:
            return False

    # ---- 内部：一次录音→识别 ----

    def _capture(self) -> str:
        self._mic.beep()
        audio = self._mic.record()
        return self._asr.transcribe(audio).strip()

    # ---- 对外交互 ----

    def listen_goal(self, default: str) -> str:
        """对话入口：听目标诉求（空/未识别则用默认），并回读确认。"""
        text = self._capture()
        _print_safe(f"  🎙 识别：{text or '（未识别到语音）'}")
        if not text:
            self.say("没听清，我先按默认方向开始，你可以随时重新表达。")
            return default
        self.say(f"好的，你的目标：{text}。我们开始吧。")
        return text

    def listen_option(self, question: dict[str, Any], index: int = 1, max_retries: int = 1) -> int:
        """逐题语音作答（全流程语音的关键环节）。

        朗读题干与各选项，听到「叮」后作答；序数/字母精确命中直接通过，
        内容命中则语音「对/重说」确认，最多重试 max_retries 次。
        """
        options = question.get("options", [])
        scenario = question.get("scenario", "")
        _print_safe(f"\n  {index}. {scenario}")
        for oi, opt in enumerate(options, start=1):
            _print_safe(f"     ({oi}) {opt}")
        self.speak(f"第 {index} 题：{scenario}")
        for oi, opt in enumerate(options, start=1):
            self.speak(f"选项{oi}：{opt}")
        self.say("请作答。")

        for _ in range(max_retries + 1):
            text = self._capture()
            parsed, exact = parse_option(text, question)
            if parsed == RETRY:
                self.say("好的，重新听你说。")
                continue
            if parsed is None:
                self.say("没听清你选第几项，请再说一遍。")
                continue
            _print_safe(f"  🎙 识别：{text} → 第 {parsed + 1} 项")
            if exact:
                return parsed  # 序数/字母精确命中 → 直接通过
            if self._confirm(options[parsed]):
                return parsed
        _print_safe("  （多次没听清，默认选第 1 项）")
        return 0

    def _confirm(self, option_text: str) -> bool:
        self.say(f"你选的是「{option_text}」，对吗？")
        ans = self._capture()
        c = parse_confirm(ans)
        if c == "yes":
            return True
        if c == "no":
            return False
        raw = input("  （回车确认 / 输入 1 重说）：").strip()
        return raw == ""

    def listen_action(self, options: list[str]) -> str:
        """从给定动作里选一个（去演练/继续问/复盘）。"""
        for _ in range(2):
            text = self._capture()
            action = parse_action(text, options)
            if action in options:
                _print_safe(f"  🎙 识别：{text} → {action}")
                return action
            self.say("没听清你的选择，请再说一遍。")
        self.say(f"默认进入「{options[0]}」。")
        return options[0]

    def listen_free_text(self, hint: str = "") -> str:
        """自由文本（对线回应 / 复盘反思）：屏幕回显 + 回车确认兜底。"""
        if hint:
            _print_safe(f"  {hint}")
        text = self._capture()
        _print_safe(f"  🎙 识别：{text or '（未识别到语音）'}")
        raw = input("  （回车确认，或输入 1 重说）：").strip()
        if raw == "1":
            text = self._capture()
            _print_safe(f"  🎙 重说：{text or '（未识别到语音）'}")
        return text or "（未回应）"
