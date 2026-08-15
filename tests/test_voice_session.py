"""VoiceSession 编排测试：注入 Mock 麦克风/ASR/TTS，离线确定性。

验证 listen_option（精确直过 / 内容确认 / 重试一次 / 多次未听清默认）、
listen_action、listen_free_text（键盘兜底）全流程。
"""

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from selfgrow.voice.asr import MockASR
from selfgrow.voice.session import VoiceSession

_DATA = Path(__file__).resolve().parent.parent / "data" / "assessments" / "managing_up_questions.json"


def _q_by_id(qid: str) -> dict:
    with open(_DATA, encoding="utf-8") as f:
        for q in json.load(f)["questions"]:
            if q["id"] == qid:
                return q
    raise AssertionError(f"找不到题目 {qid}")


class MockMic:
    """记录调用；录音返回固定 numpy 空数组（ASR 走 Mock，不看音频）。"""

    def __init__(self):
        self.records = 0
        self.beeps = 0

    def record(self, max_seconds: float = 30.0):
        import numpy as np

        self.records += 1
        return np.zeros(0, dtype=np.float32)

    def beep(self, duration: float = 0.12):
        self.beeps += 1


class MockTTS:
    def __init__(self):
        self.spoken: list[str] = []

    def speak(self, text: str):
        self.spoken.append(text)

    @property
    def name(self) -> str:
        return "mock"


def _make_session(script: list[str]) -> tuple[VoiceSession, MockMic, MockTTS]:
    mic = MockMic()
    tts = MockTTS()
    asr = MockASR(script)
    return VoiceSession(mic, asr, tts), mic, tts


class TestListenOption(unittest.TestCase):
    def setUp(self):
        self.q = _q_by_id("q_goal_01")

    def test_exact_ordinal_passes_without_confirm(self):
        session, mic, tts = _make_session(["第二项"])
        self.assertEqual(session.listen_option(self.q), 1)
        self.assertEqual(mic.records, 1)
        # 精确命中不触发「你选的是…对吗？」确认
        self.assertFalse(any("对吗" in s for s in tts.spoken))

    def test_content_match_confirms_yes(self):
        session, _, tts = _make_session(["直接开始做", "对的"])
        self.assertEqual(session.listen_option(self.q), 0)
        self.assertTrue(any("直接开始做，任务都是领导安排的" in s for s in tts.spoken))
        self.assertTrue(any("对吗" in s for s in tts.spoken))

    def test_content_confirmed_no_then_retries(self):
        # 第一遍内容命中但用户说「重说」→ 重录一次 → 第二遍精确命中
        session, mic, _ = _make_session(["直接开始做", "重说", "第二项"])
        self.assertEqual(session.listen_option(self.q), 1)
        self.assertEqual(mic.records, 3)

    def test_repeated_failure_defaults_to_first(self):
        session, _, tts = _make_session(["嗯嗯嗯", "嗯嗯嗯"])
        self.assertEqual(session.listen_option(self.q), 0)
        self.assertTrue(any("没听清" in s for s in tts.spoken))

    def test_unclear_confirm_falls_back_to_keyboard(self):
        # 确认语无法判断（如「？？？」）→ 键盘回车兜底 = 确认
        session, _, _ = _make_session(["直接开始做", "？？？"])
        with patch("builtins.input", return_value=""):
            self.assertEqual(session.listen_option(self.q), 0)

    def test_retry_word_triggers_retry_prompt(self):
        session, _, tts = _make_session(["重说一遍", "选2"])
        self.assertEqual(session.listen_option(self.q), 1)
        self.assertTrue(any("重新听你说" in s for s in tts.spoken))


class TestListenAction(unittest.TestCase):
    def test_pick_practice(self):
        session, mic, _ = _make_session(["演练一下"])
        self.assertEqual(session.listen_action(["去演练", "继续问", "复盘"]), "去演练")
        self.assertEqual(mic.records, 1)

    def test_pick_review(self):
        session, _, _ = _make_session(["总结一下"])
        self.assertEqual(session.listen_action(["去演练", "继续问", "复盘"]), "复盘")

    def test_unrecognized_defaults_to_first(self):
        session, _, tts = _make_session(["随便说说", "随便说说"])
        self.assertEqual(session.listen_action(["去演练", "继续问", "复盘"]), "去演练")
        self.assertTrue(any("没听清" in s for s in tts.spoken))


class TestListenFreeText(unittest.TestCase):
    def test_capture_with_enter_confirm(self):
        session, _, _ = _make_session(["我会先确认交付标准"])
        with patch("builtins.input", return_value=""):
            text = session.listen_free_text()
        self.assertEqual(text, "我会先确认交付标准")

    def test_capture_with_redictate(self):
        session, _, _ = _make_session(["第一遍说得不好", "第二遍说的才作数"])
        with patch("builtins.input", return_value="1"):
            text = session.listen_free_text()
        self.assertEqual(text, "第二遍说的才作数")

    def test_empty_returns_placeholder(self):
        session, _, _ = _make_session([""])
        with patch("builtins.input", return_value=""):
            text = session.listen_free_text()
        self.assertEqual(text, "（未回应）")


class TestSessionBasics(unittest.TestCase):
    def test_say_prints_and_speaks(self):
        session, _, tts = _make_session([])
        session.say("你好")
        self.assertEqual(tts.spoken, ["你好"])

    def test_tts_name_exposed(self):
        session, _, _ = _make_session([])
        self.assertEqual(session.tts_name, "mock")
        self.assertEqual(session.asr_name, "MockASR")


if __name__ == "__main__":
    unittest.main()
