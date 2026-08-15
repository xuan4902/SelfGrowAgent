"""VAD 录音：能量检测自动判断「开始说话 / 静音结束」，无需按键。

实现：16k mono float32 流式采集；前 ~0.4s 校准噪声底；连续超阈值 0.3s 判定开始；
持续静音 1.2s 判定结束；30s 上限兜底。sounddevice 缺失时抛出 MicError。
"""

from __future__ import annotations

import numpy as np

RATE = 16000
_CHUNK = 1600  # 0.1s @16k
_ONSET_SECONDS = 0.3
_SILENCE_SECONDS = 1.2
_MAX_SECONDS = 30.0
_CALIB_SECONDS = 0.4
_THRESHOLD_MULT = 4.0
_FLOOR = 0.01  # 绝对下限，防全静音环境误触发


class MicError(RuntimeError):
    pass


def _pick_input_device() -> int | None:
    """选第一个有输入通道的设备；找不到返回 None（交给 PortAudio 默认）。"""
    try:
        import sounddevice as sd

        for i, dev in enumerate(sd.query_devices()):
            if dev["max_input_channels"] > 0:
                return int(i)
    except Exception:
        pass
    return None


class SounddeviceMic:
    def __init__(self, device: int | None = None, rate: int = RATE):
        self._device = _pick_input_device() if device is None else device
        self._rate = rate

    def record(self, max_seconds: float = _MAX_SECONDS) -> np.ndarray:
        try:
            import sounddevice as sd
        except ImportError as e:  # pragma: no cover
            raise MicError("缺少 sounddevice，请先 pip install sounddevice") from e

        frames: list[np.ndarray] = []
        speech = False  # 已进入说话段
        onset = 0
        silence = 0
        total = 0
        calib: list[float] = []
        threshold = _FLOOR

        try:
            with sd.InputStream(
                samplerate=self._rate,
                channels=1,
                device=self._device,
                dtype="float32",
                blocksize=_CHUNK,
            ) as stream:
                while total < max_seconds:
                    data, _ = stream.read(_CHUNK)
                    rms = float(np.sqrt(np.mean(np.square(data))))

                    # 前 0.4s 只做噪声底校准
                    if not speech and len(calib) < max(1, int(_CALIB_SECONDS / (_CHUNK / self._rate))):
                        calib.append(rms)
                        continue

                    threshold = max(_FLOOR, (np.median(calib) if calib else 0.0) * _THRESHOLD_MULT)
                    if rms > threshold:
                        onset += 1
                        silence = 0
                    else:
                        silence += 1

                    if not speech and onset >= max(1, int(_ONSET_SECONDS / (_CHUNK / self._rate))):
                        speech = True  # 开始说话

                    if speech:
                        frames.append(data)

                    total += _CHUNK / self._rate
                    if speech and silence >= max(1, int(_SILENCE_SECONDS / (_CHUNK / self._rate))):
                        break  # 静音足够久 → 结束
        except MicError:
            raise
        except Exception as e:  # 设备不可用
            raise MicError(f"录音失败：{e}") from e

        if not frames:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(frames).reshape(-1)

    def beep(self, duration: float = 0.12) -> None:
        """合成 880Hz 短提示音（提示开始说话）。"""
        try:
            import sounddevice as sd
        except ImportError:  # pragma: no cover
            return
        try:
            t = np.linspace(0, duration, int(self._rate * duration), endpoint=False)
            tone = 0.3 * np.sin(2 * np.pi * 880 * t).astype(np.float32)
            sd.play(tone, samplerate=self._rate)
            sd.wait()
        except Exception:
            pass  # 无输出设备时不阻塞
