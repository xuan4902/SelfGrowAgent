"""语音识别：faster-whisper 本地离线（中文，small 模型已缓存）；MockASR 供测试。

真实实现懒加载模型（首次调用约数秒），之后常驻内存复用。
"""

from __future__ import annotations

from typing import Any, Callable

_MODEL = None
_MODEL_SIZE = "small"


class WhisperASR:
    """faster-whisper 离线识别（16k mono float32 音频 → 中文文本）。"""

    def __init__(self, model_size: str = _MODEL_SIZE):
        self._model_size = model_size

    def transcribe(self, audio: Any) -> str:
        model = _get_model(self._model_size)
        segments, _info = model.transcribe(
            audio, language="zh", vad_filter=True, beam_size=1
        )
        return "".join(seg.text for seg in segments).strip()


def _get_model(model_size: str):
    global _MODEL
    if _MODEL is None:
        from faster_whisper import WhisperModel

        _MODEL = WhisperModel(model_size, device="cpu", compute_type="int8")
    return _MODEL


class MockASR:
    """确定性假识别：按脚本逐条返回文本（测试/演示用）。"""

    def __init__(self, script: list[str] | Callable[[], str] | str):
        if isinstance(script, str):
            script = [script]
        self._script: list[str] | Callable[[], str] = script
        self._idx = 0
        self.calls: list[Any] = []

    def transcribe(self, audio: Any) -> str:
        self.calls.append(audio)
        if callable(self._script):
            return self._script()
        line = self._script[self._idx]
        self._idx = min(self._idx + 1, len(self._script) - 1)
        return line
