"""AutoTTS 双后端降级测试：全程假对象，不触网、不发声。

- 有网 → edge
- edge 抛错 → 自动落到 sapi（会话内不再重试 edge）
- 都失败 → NullTTS 兜底，不中断
- 离线 → 直接 sapi
"""

import unittest
from unittest.mock import patch

from selfgrow.voice.tts import AutoTTS


class _FakeTTS:
    def __init__(self, name: str, raise_on_speak: bool = False):
        self._name = name
        self._raise = raise_on_speak
        self.calls: list[str] = []

    def speak(self, text: str):
        if self._raise:
            raise RuntimeError(f"{self._name} 故障")
        self.calls.append(text)

    @property
    def name(self) -> str:
        return self._name


class TestAutoTTSFallback(unittest.TestCase):
    def test_online_uses_edge(self):
        edge, sapi = _FakeTTS("edge"), _FakeTTS("sapi")
        engine = AutoTTS(edge=edge, sapi=sapi)
        with patch("selfgrow.voice.tts._probe_online", return_value=True):
            engine.speak("你好")
        self.assertEqual(edge.calls, ["你好"])
        self.assertEqual(sapi.calls, [])

    def test_edge_error_falls_back_to_sapi_once(self):
        edge, sapi = _FakeTTS("edge", raise_on_speak=True), _FakeTTS("sapi")
        engine = AutoTTS(edge=edge, sapi=sapi)
        with patch("selfgrow.voice.tts._probe_online", return_value=True):
            engine.speak("你好")
            engine.speak("再说一遍")  # 第二次不再尝试 edge
        self.assertEqual(sapi.calls, ["你好", "再说一遍"])
        # 降级后会话内缓存为离线
        self.assertEqual(engine.name, "sapi")

    def test_both_fail_uses_null_without_raise(self):
        edge, sapi = _FakeTTS("edge", raise_on_speak=True), _FakeTTS("sapi", raise_on_speak=True)
        engine = AutoTTS(edge=edge, sapi=sapi)
        with patch("selfgrow.voice.tts._probe_online", return_value=True):
            engine.speak("你好")  # 不应抛异常
        self.assertEqual(edge.calls, [])
        self.assertEqual(sapi.calls, [])

    def test_offline_uses_sapi_directly(self):
        edge, sapi = _FakeTTS("edge"), _FakeTTS("sapi")
        engine = AutoTTS(edge=edge, sapi=sapi)
        with patch("selfgrow.voice.tts._probe_online", return_value=False):
            engine.speak("你好")
        self.assertEqual(edge.calls, [])
        self.assertEqual(sapi.calls, ["你好"])
        self.assertEqual(engine.name, "sapi")


if __name__ == "__main__":
    unittest.main()
