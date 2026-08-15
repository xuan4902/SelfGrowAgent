"""语音对话能力：录音(VAD) → 识别(whisper) → 口语解析 → 朗读(edge/sapi)。

入口在 cli/main.py 的 --mode voice；本包保持可独立测试（Protocol + Mock）。
"""

from selfgrow.voice.asr import MockASR, WhisperASR
from selfgrow.voice.interfaces import ASR, Mic, TTS
from selfgrow.voice.mic import SounddeviceMic
from selfgrow.voice.parser import parse_action, parse_confirm, parse_option
from selfgrow.voice.session import VoiceSession
from selfgrow.voice.tts import AutoTTS, EdgeTTS, NullTTS, SapiTTS

__all__ = [
    "ASR",
    "Mic",
    "TTS",
    "SounddeviceMic",
    "WhisperASR",
    "MockASR",
    "EdgeTTS",
    "SapiTTS",
    "NullTTS",
    "AutoTTS",
    "parse_option",
    "parse_action",
    "parse_confirm",
    "VoiceSession",
]
