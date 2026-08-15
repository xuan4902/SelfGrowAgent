"""语音合成：edge-tts(在线自然音) / SAPI(离线中文，需中文语音包) / Null 兜底。

AutoTTS 双后端自动切换：socket 快探联网（会话内缓存）→ 有网 edge，离线 SAPI；
两者都失败降级 NullTTS（纯文字，界面不中断）。
"""

from __future__ import annotations

import asyncio
import io
import socket
from typing import Any

from selfgrow.voice.interfaces import TTS

EDGE_HOST = "edge.microsoft.com"
_EDGE_VOICE = "zh-CN-XiaoxiaoNeural"


class EdgeTTS:
    """在线自然中文女声（需联网；mp3 → miniaudio 解码 → sounddevice 播放）。"""

    def __init__(self, voice: str = _EDGE_VOICE, rate: str = "+10%"):
        self._voice = voice
        self._rate = rate

    def speak(self, text: str) -> None:
        mp3 = asyncio.run(_edge_bytes(text, self._voice, self._rate))
        _play_audio(mp3)

    @property
    def name(self) -> str:
        return "edge"


async def _edge_bytes(text: str, voice: str, rate: str) -> bytes:
    from edge_tts import Communicate

    buf = io.BytesIO()
    async for chunk in Communicate(text, voice, rate=rate).stream():
        if chunk["type"] == "audio":
            buf.write(chunk["data"])
    return buf.getvalue()


def _play_audio(audio_bytes: bytes) -> None:
    """解码音频字节并用 sounddevice 播放（阻塞至读完）。"""
    import miniaudio
    import numpy as np
    import sounddevice as sd

    decoded = miniaudio.decode(audio_bytes, output_format=miniaudio.SampleFormat.FLOAT32)
    samples = np.frombuffer(decoded.samples, dtype=np.float32).reshape(-1, decoded.nchannels)
    sd.play(samples, decoded.sample_rate)
    sd.wait()


class SapiTTS:
    """Windows 系统语音（离线中文需先安装中文语音包 Language.Speech zh-CN）。"""

    def __init__(self):
        self._voice = None

    def speak(self, text: str) -> None:
        import win32com.client

        sp = win32com.client.Dispatch("SAPI.SpVoice")
        if self._voice is None:
            self._voice = _pick_chinese_voice(sp)
        if self._voice is not None:
            sp.Voice = self._voice
        sp.Speak(text)

    @property
    def name(self) -> str:
        return "sapi"


def _pick_chinese_voice(sp: Any) -> Any | None:
    """优先选中文(zh-CN)语音；找不到返回 None（用默认音）。"""
    try:
        zh = sp.GetVoices("Language=804")  # 0x0804 = zh-CN
        if zh.Count > 0:
            return zh.Item(0)
    except Exception:
        pass
    return None


class NullTTS:
    """兜底：不发声（纯文字模式）。"""

    def speak(self, text: str) -> None:
        return None

    @property
    def name(self) -> str:
        return "null"


def _probe_online(host: str = EDGE_HOST, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, 443), timeout=timeout):
            return True
    except OSError:
        return False


class AutoTTS:
    """双后端自动切换：有网 edge / 离线 sapi / 都失败 null。结果会话内缓存。"""

    def __init__(self, edge: TTS | None = None, sapi: TTS | None = None):
        self._edge = edge or EdgeTTS()
        self._sapi = sapi or SapiTTS()
        self._null = NullTTS()
        self._online: bool | None = None

    def _is_online(self) -> bool:
        if self._online is None:
            self._online = _probe_online()
        return self._online

    def speak(self, text: str) -> None:
        if self._is_online():
            try:
                self._edge.speak(text)
                return
            except Exception:
                self._online = False  # 本次降级，后续会话内不再重试 edge
        try:
            self._sapi.speak(text)
        except Exception:
            self._null.speak(text)

    @property
    def name(self) -> str:
        if self._online is None:
            return "auto"
        return "edge" if self._online else "sapi"
