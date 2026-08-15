"""CLI voice 模式端到端：注入 Mock 语音会话，验证整条接线（无需硬件/网络）。

链路：目标语音收集 → 全流程语音作答 → 角色朗读(on_message) → 战报朗读。
用 MockASR 脚本驱动真实 LangGraph，确定性、离线。
"""

from __future__ import annotations

import argparse
import unittest
from unittest.mock import patch

from selfgrow.cli.main import DEFAULT_GOAL, _run_voice
from selfgrow.cli.render import render_battle_report
from selfgrow.voice.asr import MockASR
from selfgrow.voice.session import VoiceSession, _EMOJI_RE
from selfgrow.competency.loader import load_framework


class MockMic:
    def record(self, max_seconds: float = 30.0):
        import numpy as np

        return np.zeros(0, dtype=np.float32)

    def beep(self, duration: float = 0.12):
        return None


class MockTTS:
    def __init__(self):
        self.spoken: list[str] = []

    def speak(self, text: str):
        self.spoken.append(text)

    @property
    def name(self) -> str:
        return "mock"


def _asr_script():
    """确定性脚本驱动全流程语音。

    队列覆盖已知捕获顺序：目标 → 基线测评（逐题「第二项」序数精确命中，6 核心+追问
    最多 10 题）→ 第 1 周动作/对线/复盘 → 复测（3–5 题，「第二项」余量兜底）→
    第 2 周动作/对线/复盘；此后「去演练」兜底——对 listen_action 必命中，
    对 listen_option 走默认第 0 项，对自由文本可读。
    """
    queue = [
        "我想提升汇报能力",
        *(["第二项"] * 10),  # 基线测评（最多 10 题；不足时余量被动作解析消耗，不影响流程）
        "去演练",  # 第 1 周学习动作
        "结论先行：项目会延期三天，我建议砍掉非核心功能保交付。",
        "这次我该提前同步风险，下周我会及时预警。",
        *(["第二项"] * 6),  # 复测（3–5 题；复盘也会吃一行，给足余量）
        "去演练",  # 第 2 周学习动作
        "这次我会先定优先级再同步。",
        "复盘收获：同步风险要带上方案。",
    ]

    def fn():
        if queue:
            return queue.pop(0)
        return "去演练"

    return fn


class TestCliVoice(unittest.TestCase):
    def setUp(self):
        # 与 cli.main 的 main() 入口一致：Windows 控制台统一 UTF-8（emoji 界面）
        import sys

        for stream in (sys.stdout, sys.stderr, sys.stdin):
            try:
                stream.reconfigure(encoding="utf-8")
            except (AttributeError, ValueError):
                pass
        self.args = argparse.Namespace(
            mode="voice", goal=DEFAULT_GOAL, learner="voice_01", db=":memory:", tts="on"
        )
        self.tts = MockTTS()

    def _session(self) -> VoiceSession:
        return VoiceSession(MockMic(), MockASR(_asr_script()), self.tts)

    def test_voice_mode_runs_full_loop(self) -> None:
        with (
            patch("selfgrow.cli.main._build_voice_session", return_value=self._session()),
            patch.object(VoiceSession, "is_available", return_value=True),
            patch("builtins.input", return_value=""),
        ):
            final = _run_voice(self.args)

        # 全流程跑通：复测完成、周数跑满、战报生成
        self.assertTrue(final["reassess_done"])
        self.assertEqual(final["current_week"], final["plan"]["total_weeks"])
        self.assertEqual(final["llm_mode"], "mock")
        report = final["report"]
        self.assertIn("summary", report)

        # 语音收集了目标诉求
        joined = "\n".join(self.tts.spoken)
        self.assertIn("我想提升汇报能力", joined)

        # 战报摘要朗读
        self.assertTrue(any("恭喜通关" in s for s in self.tts.spoken))

        # 朗读内容已剥掉装饰 emoji（角色横幅等），TTS 不念符号
        self.assertFalse(any(_EMOJI_RE.search(s) for s in self.tts.spoken))

        # 角色叙述（计划/讲解/对线/战报）经由 on_message 朗读过
        self.assertTrue(any("闯关" in s for s in self.tts.spoken) or
                        any("规划" in s for s in self.tts.spoken))

    def test_voice_mode_falls_back_without_mic(self) -> None:
        """无麦克风 → 自动回落 interactive，不抛异常。"""
        with (
            patch("selfgrow.cli.main._build_voice_session", return_value=self._session()),
            patch.object(VoiceSession, "is_available", return_value=False),
            patch("builtins.input", return_value=""),  # 回落 interactive 也要输入
        ):
            final = _run_voice(self.args)
        self.assertIn("report", final)

    def test_render_battle_report_accepts_voice_final(self) -> None:
        """战报渲染与语音返回值兼容（评审/录屏用）。"""
        with (
            patch("selfgrow.cli.main._build_voice_session", return_value=self._session()),
            patch.object(VoiceSession, "is_available", return_value=True),
            patch("builtins.input", return_value=""),
        ):
            final = _run_voice(self.args)
        fw = load_framework("managing_up")
        render_battle_report(final, fw)  # 不抛异常


if __name__ == "__main__":
    unittest.main()
