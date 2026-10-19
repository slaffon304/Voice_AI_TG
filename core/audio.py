"""Shared Core Audio: примитивы, АРУ, шумоподавление и микшеры звука."""

from __future__ import annotations

import contextlib
import wave
from typing import Any

import numpy as np
from pipecat.frames.frames import Frame, InputAudioRawFrame, OutputAudioRawFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

try:
    from pipecat.audio.filters.rnnoise_filter import RNNoiseFilter
except ImportError:
    RNNoiseFilter = None

from core.config import (
    BACKGROUND_ATTEN_DB,
    BACKGROUND_GATE_DB,
    BACKGROUND_HOLD_MS,
    WEB_OUTPUT_SAMPLE_RATE,
    log,
)

# =============================================================================
# PCM-примитивы (быстрые операции со звуком)
# =============================================================================
_audioop = None
try:
    import audioop as _audioop  # type: ignore
except ImportError:
    try:
        import audioop_lts as _audioop  # type: ignore
    except ImportError:
        _audioop = None

if _audioop is None:

    def pcm_rms(data: bytes) -> float:
        if not data:
            return 0.0
        a = np.frombuffer(data, dtype="<i2").astype(np.float32)
        return float(np.sqrt(np.mean(a * a))) if a.size else 0.0

    def pcm_scale(data: bytes, factor: float) -> bytes:
        if not data:
            return data
        a = np.frombuffer(data, dtype="<i2").astype(np.float32) * factor
        return np.clip(a, -32768, 32767).astype("<i2").tobytes()

    def pcm_resample(data: bytes, state: Any, src: int, dst: int) -> tuple[bytes, Any]:
        if not data or src == dst:
            return data, state
        a = np.frombuffer(data, dtype="<i2").astype(np.float32)
        ratio = dst / src
        n_out = max(1, int(len(a) * ratio))
        idx = np.linspace(0, len(a) - 1, n_out)
        out = np.interp(idx, np.arange(len(a)), a)
        return np.clip(out, -32768, 32767).astype("<i2").tobytes(), state

else:

    def pcm_rms(data: bytes) -> float:
        if not data or len(data) % 2:
            return 0.0
        return float(_audioop.rms(data, 2))

    def pcm_scale(data: bytes, factor: float) -> bytes:
        return _audioop.mul(data, 2, factor) if data else data

    def pcm_resample(data: bytes, state: Any, src: int, dst: int) -> tuple[bytes, Any]:
        if not data or src == dst:
            return data, state
        return _audioop.ratecv(data, 2, 1, src, dst, state)


# =============================================================================
# Автоматическая регулировка усиления (InputAGC)
# =============================================================================
class InputAGC:
    """Подтягивает речь звонящего к целевому уровню и приглушает фон."""

    LOOKAHEAD = 3  # кадров по 20 мс

    def __init__(
        self,
        target_dbfs: float = -18.0,
        max_gain_db: float = 24.0,
        min_gain_db: float = 0.0,
        speech_floor_dbfs: float = -45.0,
    ) -> None:
        self.target = 32768.0 * 10 ** (target_dbfs / 20)
        self.max_gain = 10 ** (max_gain_db / 20)
        self.min_gain = 10 ** (min_gain_db / 20)
        self.floor = 32768.0 * 10 ** (speech_floor_dbfs / 20)
        self.gain = min(self.max_gain, max(self.min_gain, 10 ** (8.0 / 20)))
        self.level: float | None = None
        self.peak: float | None = None
        self.applied: list[float] = []
        self.gate_ratio = 10 ** (-BACKGROUND_GATE_DB / 20) if BACKGROUND_GATE_DB > 0 else 0.0
        self.gate_atten = 10 ** (-BACKGROUND_ATTEN_DB / 20)
        self.hold_frames = max(1, int(BACKGROUND_HOLD_MS / 20))
        self._hold = 0
        self._env: float | None = None
        self._queue: list[Any] = []
        self._fg: list[bool] = []
        self.gated_frames = 0
        self.total_frames = 0

    def process(self, data: bytes, adapt: bool = True, attenuate_db: float = 0.0) -> bytes:
        if len(data) < 4:
            return data

        a = np.frombuffer(data[: len(data) // 2 * 2], dtype="<i2").astype(np.float32)
        rms = float(np.sqrt(np.mean(a * a))) if a.size else 0.0
        self.total_frames += 1

        self._env = rms if self._env is None else max(rms, self._env * 0.85)
        foreground = (
            self.peak is None
            or self.gate_ratio == 0.0
            or self._env >= self.peak * self.gate_ratio
        )

        if adapt and rms > self.floor and foreground:
            if self.level is None:
                self.level, self.peak = rms, rms
            else:
                self.level = self.level * 0.93 + rms * 0.07
                self.peak = max(rms, self.peak * 0.985)
            desired = min(self.max_gain, max(self.min_gain, self.target / self.level))
            self.gain += (desired - self.gain) * 0.12
            self.applied.append(self.gain)

        self._queue.append(a)
        self._fg.append(foreground)
        if len(self._queue) <= self.LOOKAHEAD:
            return b""
        a_out = self._queue.pop(0)
        if any(self._fg[: self.LOOKAHEAD + 1]):
            self._hold = self.hold_frames
        elif self._hold > 0:
            self._hold -= 1
        self._fg.pop(0)

        gain = self.gain * (10 ** (-attenuate_db / 20)) if attenuate_db else self.gain
        if self.gate_ratio and self.peak is not None and self._hold == 0:
            gain *= self.gate_atten
            self.gated_frames += 1

        out = a_out * gain
        lim = 0.75 * 32767.0
        over = np.abs(out) > lim
        if over.any():
            out[over] = np.sign(out[over]) * (lim + (np.abs(out[over]) - lim) * 0.2)
        return np.clip(out, -32767, 32767).astype("<i2").tobytes()

    @property
    def average_gain_db(self) -> float:
        if not self.applied:
            return 0.0
        return round(20 * float(np.log10(float(np.mean(self.applied)))), 1)


# =============================================================================
# Шумоподавление (SafeRNNoiseFilter)
# =============================================================================
if RNNoiseFilter is not None:

    class SafeRNNoiseFilter(RNNoiseFilter):  # type: ignore[misc,valid-type]
        """RNNoise, который при первой же ошибке отключается вместо падения."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self._broken = False

        def _disable(self, exc: Exception) -> None:
            if not self._broken:
                self._broken = True
                log.warning("RNNoise отключён из-за ошибки: %s", exc)

        async def filter(self, audio: bytes) -> bytes:
            if self._broken:
                return audio
            try:
                return await super().filter(audio)
            except Exception as exc:
                self._disable(exc)
                return audio

else:
    SafeRNNoiseFilter = None  # type: ignore


# =============================================================================
# Аудиомикшер и Catcher'ы (WebAudioMixer / AudioMixer)
# =============================================================================
class WebAudioMixer:
    """Сводит микрофон (16 кГц) и голос бота (24 кГц) в один WAV 24 кГц моно."""

    def __init__(self, output_path: str, target_rate: int = WEB_OUTPUT_SAMPLE_RATE) -> None:
        self.output_path = output_path
        self.target_rate = target_rate
        self._wav = None
        self._ai_buffer = np.array([], dtype=np.int16)

    def add_ai_audio(self, frame: OutputAudioRawFrame) -> None:
        chunk = np.frombuffer(frame.audio, dtype=np.int16)
        self._ai_buffer = np.concatenate((self._ai_buffer, chunk))

    def add_user_audio(self, frame: InputAudioRawFrame) -> None:
        self._init_wav()
        user = np.frombuffer(frame.audio, dtype=np.int16)
        if len(user) == 0:
            return
        n = int(len(user) * (self.target_rate / max(frame.sample_rate, 1)))
        x = np.arange(len(user))
        x_new = np.linspace(0, len(user) - 1, n)
        user_rs = np.interp(x_new, x, user).astype(np.int16)

        ai = np.zeros(n, dtype=np.int16)
        if len(self._ai_buffer) > 0:
            take = min(n, len(self._ai_buffer))
            ai[:take] = self._ai_buffer[:take]
            self._ai_buffer = self._ai_buffer[take:]

        mixed = np.clip(user_rs.astype(np.int32) + ai.astype(np.int32), -32768, 32767).astype(np.int16)
        self._wav.writeframes(mixed.tobytes())

    def _init_wav(self) -> None:
        if self._wav is None:
            self._wav = wave.open(self.output_path, "wb")
            self._wav.setnchannels(1)
            self._wav.setsampwidth(2)
            self._wav.setframerate(self.target_rate)

    def close(self) -> None:
        if self._wav and len(self._ai_buffer) > 0:
            self._wav.writeframes(self._ai_buffer.tobytes())
            self._ai_buffer = np.array([], dtype=np.int16)
        if self._wav:
            self._wav.close()
            self._wav = None


class WebUserAudioCatcher(FrameProcessor):
    def __init__(self, mixer: WebAudioMixer) -> None:
        super().__init__()
        self.mixer = mixer
        self.muted = False

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, InputAudioRawFrame):
            with contextlib.suppress(Exception):
                self.mixer.add_user_audio(frame)
            if self.muted:
                frame.audio = b"\x00" * len(frame.audio)
        await self.push_frame(frame, direction)


class WebAIAudioCatcher(FrameProcessor):
    def __init__(self, mixer: WebAudioMixer) -> None:
        super().__init__()
        self.mixer = mixer

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, OutputAudioRawFrame):
            with contextlib.suppress(Exception):
                self.mixer.add_ai_audio(frame)
        await self.push_frame(frame, direction)


# Алиасы для единообразия архитектуры
AudioMixer = WebAudioMixer
UserAudioCatcher = WebUserAudioCatcher
AIAudioCatcher = WebAIAudioCatcher
