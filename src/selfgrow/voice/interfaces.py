"""语音模块协议：注入 Mock 保证测试确定性（离线、无硬件依赖）。

三个关键抽象：
- Mic   : 录音（VAD 返回说话段）
- ASR   : 语音 → 文字
- TTS   : 文字 → 朗读
实现放在 mic.py / asr.py / tts.py；CLI 组装真实现，测试注入假实现。
"""

from __future__ import annotations

from typing import Any, Protocol


class Mic(Protocol):
    def record(self, max_seconds: float = 30.0) -> Any:
        """VAD 录音，返回 16k mono float32 音频（numpy 数组，仅说话段）。"""
        ...

    def beep(self, duration: float = 0.12) -> None:
        """播放「叮」提示音（提示用户开始说话）。"""
        ...


class ASR(Protocol):
    def transcribe(self, audio: Any) -> str:
        """把 16k mono float32 音频转成文字。"""
        ...


class TTS(Protocol):
    def speak(self, text: str) -> None:
        """朗读文本（阻塞至读完；失败静默忽略）。"""
        ...

    @property
    def name(self) -> str:
        """后端标识（edge/sapi/null），用于日志与提示。"""
        ...
