"""
Lab Upgrade — GSM Voice Agent
Asterisk AudioSocket  <->  Pipecat  <->  Gemini Live

Переписанная версия. Основные отличия от предыдущей:
  * убран дублирующийся (и сломанный) класс AsteriskWSAdapter
  * audioop-шим для Python 3.13+ (audioop удалён из stdlib, PEP 594)
  * движок характера (personality engine) — из БД в промпт и в параметры VAD
  * per-call корреляция входящего номера (устранена гонка при одновременных звонках)
  * URL-энкодинг всех параметров PostgREST
  * таймауты на всех HTTP-вызовах, параллельная загрузка контекста звонка
  * учёт токенов и себестоимости звонка — уходит в существующий call_logs через n8n
  * лимит одновременных звонков и максимальной длительности
  * structured logging с call_id
  * рабочие часы и таймзона — из БД, а не хардкод

Переменные окружения — см. .env.example в конце AUDIT.md
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import gc
import hashlib
import hmac
import json
import logging
import os
import re
import time
import uuid
import wave
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Response, Security, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from starlette.websockets import WebSocketState
from starlette.websockets import WebSocketDisconnect
import numpy as np

import redis.asyncio as redis
from google import genai
from google.genai import types
from supabase import Client, create_client

try:
    from pipecat.audio.filters.rnnoise_filter import RNNoiseFilter
except Exception:  # зависимость pyrnnoise/PyAV может быть несовместима после пересборки
    RNNoiseFilter = None  # type: ignore[assignment]
from pipecat.frames.frames import (
    CancelFrame,
    Frame,
    InputAudioRawFrame,
    InterruptionFrame,
    LLMRunFrame,
    MetricsFrame,
    OutputAudioRawFrame,
    TranscriptionFrame,
    InterimTranscriptionFrame,
    UserStartedSpeakingFrame,
)
from pipecat.metrics.metrics import LLMUsageMetricsData
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.serializers.base_serializer import FrameSerializer
from pipecat.services.google.gemini_live.llm import GeminiLiveLLMService, GeminiVADParams
from pipecat.services.llm_service import FunctionCallParams
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)
from pipecat.turns.user_turn_strategies import ExternalUserTurnStrategies

# =============================================================================
# 1. КОНФИГУРАЦИЯ
# =============================================================================


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


SUPABASE_URL = (os.getenv("SUPABASE_URL") or "").replace("/rest/v1", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
REDIS_URL = os.getenv("REDIS_URL")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
API_SECRET_TOKEN = os.getenv("API_SECRET_TOKEN")

ASTERISK_ARI_URL = os.getenv("ASTERISK_ARI_URL")
ASTERISK_ARI_USER = os.getenv("ASTERISK_ARI_USER")
ASTERISK_ARI_PASS = os.getenv("ASTERISK_ARI_PASS")
ASTERISK_ENDPOINT_SUFFIX = os.getenv("ASTERISK_ENDPOINT_SUFFIX", "")
ASTERISK_RECORDING_PATH = os.getenv("ASTERISK_RECORDING_PATH", "/var/spool/asterisk/monitor")
ASTERISK_RECORDING_EXT = os.getenv("ASTERISK_RECORDING_EXT", "wav16")
AUDIOSOCKET_HOST = os.getenv("AUDIOSOCKET_HOST", "0.0.0.0")
AUDIOSOCKET_PORT = _env_int("AUDIOSOCKET_PORT", 8085)

N8N_BASE_URL = (os.getenv("N8N_BASE_URL") or "").rstrip("/")
N8N_WEBHOOK_SECRET = os.getenv("N8N_WEBHOOK_SECRET", "")
KOMMO_SUBDOMAIN = os.getenv("KOMMO_SUBDOMAIN")
KOMMO_ACCESS_TOKEN = os.getenv("KOMMO_ACCESS_TOKEN")

# Транк, номер которого нельзя принимать за номер клиента.
TRUNK_NUMBERS = [
    n.strip() for n in os.getenv("TRUNK_NUMBERS", "78001079,078001079").split(",") if n.strip()
]

# Протокол AudioSocket. Вынесено в конфиг, т.к. значения зависят от сборки Asterisk.
AS_TYPE_HANGUP = _env_int("AS_TYPE_HANGUP", 0x00)
AS_TYPE_AUDIO_OUT = _env_int("AS_TYPE_AUDIO_OUT", 0x12)
# Частота, с которой Asterisk отдаёт звук. В диалплане стоит slin16 => 16000.
# Ресемплинг включается ТОЛЬКО если здесь 8000. Раньше код тянул 8->16 по типу
# пакета 0x10, а этот тип Asterisk шлёт для любого аудио — речь растягивалась
# вдвое и распознавание сыпалось.
ASTERISK_INPUT_RATE = _env_int("ASTERISK_INPUT_RATE", 16000)

# Шумодав — улучшение, а не обязательный компонент. Выключается без редеплоя.
ENABLE_RNNOISE = _env_bool("ENABLE_RNNOISE", True)
# Сторож: сколько секунд тишины в пайплайне при живом сокете считать поломкой.
AUDIO_STALL_SECONDS = _env_float("AUDIO_STALL_SECONDS", 10.0)
# Сторож мёртвого эфира: столько секунд без речи с обеих сторон — бот кладёт трубку.
DEAD_AIR_SECONDS = _env_float("DEAD_AIR_SECONDS", 50.0)
# ВРЕМЕННАЯ ДИАГНОСТИКА. Пишет в WAV ровно тот звук, который получает Gemini,
# и кладёт в Supabase рядом с записью разговора. Убрать, когда починим звук.
DUMP_INPUT_AUDIO = _env_bool("DUMP_INPUT_AUDIO", False)

PIPELINE_SAMPLE_RATE = _env_int("PIPELINE_SAMPLE_RATE", 16000)

# АРУ на входе. Проверено экспериментом 02.09: одна и та же чистая фраза
# распознаётся Gemini идеально на -17 dBFS и превращается в испанский мусор
# на -27 dBFS. Голос по GSM приходит на -25..-29. Подтягиваем к цели.
INPUT_AGC = _env_bool("INPUT_AGC", True)
INPUT_TARGET_DBFS = _env_float("INPUT_TARGET_DBFS", -20.0)
INPUT_MAX_GAIN_DB = _env_float("INPUT_MAX_GAIN_DB", 24.0)
INPUT_MIN_GAIN_DB = _env_float("INPUT_MIN_GAIN_DB", 0.0)
# Порог фона. Всё, что тише голоса звонящего на BACKGROUND_GATE_DB, приглушается
# на BACKGROUND_ATTEN_DB перед отправкой в Gemini — голоса на заднем плане
# перестают засчитываться как «клиент заговорил». BACKGROUND_HOLD_MS — сколько
# держать «открыто» после последнего громкого кадра, чтобы не рвать паузы
# внутри слов. 0 в BACKGROUND_GATE_DB выключает порог.
BACKGROUND_GATE_DB = _env_float("BACKGROUND_GATE_DB", 10.0)
BACKGROUND_ATTEN_DB = _env_float("BACKGROUND_ATTEN_DB", 15.0)
BACKGROUND_HOLD_MS = _env_int("BACKGROUND_HOLD_MS", 300)
OUT_CHUNK_SIZE = _env_int("OUT_CHUNK_SIZE", 640)
OUT_VOLUME = _env_float("OUT_VOLUME", 0.75)

DEFAULT_TZ = os.getenv("DEFAULT_TIMEZONE", "Europe/Chisinau")
DEFAULT_LANG = os.getenv("DEFAULT_LANG", "ro")
GEMINI_MODEL = os.getenv("GEMINI_LIVE_MODEL", "gemini-3.1-flash-live-preview")
ARCHIVIST_MODELS = [
    m.strip()
    for m in os.getenv(
        "ARCHIVIST_MODELS",
        "gemini-3.6-flash,gemini-3.1-pro-preview,gemini-3.1-flash-lite,gemini-3.5-flash",
    ).split(",")
    if m.strip()
]

MAX_CONCURRENT_CALLS = _env_int("MAX_CONCURRENT_CALLS", 25)
MAX_CALLS_PER_CLIENT = _env_int("MAX_CALLS_PER_CLIENT", 5)
MAX_CALL_SECONDS = _env_int("MAX_CALL_SECONDS", 900)
# Раньше этого не было: бот принял мусорную расшифровку за прощание и положил
# трубку на 40-й секунде. Ниже этого порога end_call игнорируется.
MIN_SECONDS_BEFORE_END_CALL = _env_int("MIN_SECONDS_BEFORE_END_CALL", 25)
# Значения из исходной рабочей версии, характером не управляются.
VAD_SILENCE_MS = _env_int("VAD_SILENCE_MS", 1500)
# high = рубит реплику на первой паузе, обрывки по 0.5 с, на которых Gemini
# не может определить язык. low = ждёт, пока человек договорит.
VAD_END_SENSITIVITY = os.getenv("VAD_END_SENSITIVITY", "low").strip().lower()
# Детектор НАЧАЛА речи у Gemini. start=low — нужна уверенная речь, а не всплеск;
# prefix_padding — сколько мс речь должна длиться, прежде чем засчитается.
VAD_START_SENSITIVITY = os.getenv("VAD_START_SENSITIVITY", "low").strip().lower()
VAD_PREFIX_PADDING_MS = _env_int("VAD_PREFIX_PADDING_MS", 800)
RECOVERY_DELAY_S = _env_float("RECOVERY_DELAY_S", 2.5)
IDLE_TIMEOUT_SECONDS = _env_float("IDLE_TIMEOUT_SECONDS", 20.0)
PERSONA_CACHE_TTL = _env_int("PERSONA_CACHE_TTL", 60)

# Цены Gemini Live, $ за 1M токенов.
PRICE_TEXT_IN = _env_float("PRICE_TEXT_IN", 0.75)
PRICE_AUDIO_IN = _env_float("PRICE_AUDIO_IN", 3.00)
PRICE_AUDIO_OUT = _env_float("PRICE_AUDIO_OUT", 12.00)

INTERNAL_TOKEN = os.getenv("INTERNAL_TOKEN")  # опционально защищает /get_uuid
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
log = logging.getLogger("gsm")

redis_client = redis.from_url(REDIS_URL, decode_responses=True) if REDIS_URL else None

_call_semaphore = asyncio.Semaphore(MAX_CONCURRENT_CALLS)
_calls_per_client: dict[str, int] = {}
_http: Optional[httpx.AsyncClient] = None


def http() -> httpx.AsyncClient:
    """Общий пул соединений. Создаётся в lifespan."""
    global _http
    if _http is None:
        _http = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=3.0))
    return _http


def sb_headers() -> dict[str, str]:
    return {"apikey": SUPABASE_KEY or "", "Authorization": f"Bearer {SUPABASE_KEY or ''}"}


def tz_for(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or DEFAULT_TZ)
    except Exception:
        return ZoneInfo("UTC")


def estimate_tokens(text: str) -> int:
    """Оценка токенов с поправкой на кириллицу (латиница ~3.8 симв/токен, кириллица ~2.2)."""
    if not text:
        return 0
    cyr = sum(1 for ch in text if "\u0400" <= ch <= "\u04ff")
    lat = len(text) - cyr
    return int(cyr / 2.2 + lat / 3.8) + 1


# =============================================================================
# 2. АУДИО-ПРИМИТИВЫ (audioop удалён в Python 3.13 — здесь шим)
# =============================================================================

_audioop = None
try:  # Python <= 3.12
    import audioop as _audioop  # type: ignore
except ImportError:  # pragma: no cover
    try:  # бэкпорт: pip install audioop-lts
        import audioop_lts as _audioop  # type: ignore
    except ImportError:
        _audioop = None

if _audioop is None:
    import numpy as _np

    def pcm_rms(data: bytes) -> float:
        if not data:
            return 0.0
        a = _np.frombuffer(data, dtype="<i2").astype(_np.float32)
        return float(_np.sqrt(_np.mean(a * a))) if a.size else 0.0

    def pcm_scale(data: bytes, factor: float) -> bytes:
        if not data:
            return data
        a = _np.frombuffer(data, dtype="<i2").astype(_np.float32) * factor
        return _np.clip(a, -32768, 32767).astype("<i2").tobytes()

    def pcm_resample(data: bytes, state: Any, src: int, dst: int) -> tuple[bytes, Any]:
        if not data or src == dst:
            return data, state
        a = _np.frombuffer(data, dtype="<i2").astype(_np.float32)
        ratio = dst / src
        n_out = max(1, int(len(a) * ratio))
        idx = _np.linspace(0, len(a) - 1, n_out)
        out = _np.interp(idx, _np.arange(len(a)), a)
        return _np.clip(out, -32768, 32767).astype("<i2").tobytes(), state

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


# --- автоматическая регулировка усиления -------------------------------------


class InputAGC:
    """
    Подтягивает речь звонящего к целевому уровню и приглушает фон.

    Два измерителя: средний уровень речи (для усиления) и пиковый (для порога
    фона). Оба учатся ТОЛЬКО по переднему плану — иначе усилитель подстроится
    под голоса на заднем плане и поднимет их. Решение «фон / не фон» принимается
    с упреждением в несколько кадров, чтобы не резать начала слов. Никогда не
    ослабляет речь ниже min_gain, пики мягко ограничивает.
    """

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
        self.level: float | None = None   # средний уровень речи
        self.peak: float | None = None    # пиковый уровень речи
        self.applied: list[float] = []
        # порог фона
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
        import numpy as np

        a = np.frombuffer(data[: len(data) // 2 * 2], dtype="<i2").astype(np.float32)
        rms = float(np.sqrt(np.mean(a * a))) if a.size else 0.0
        self.total_frames += 1

        # огибающая: быстро вверх, медленно вниз
        self._env = rms if self._env is None else max(rms, self._env * 0.85)
        foreground = (
            self.peak is None
            or self.gate_ratio == 0.0
            or self._env >= self.peak * self.gate_ratio
        )

        # учимся только по переднему плану
        if adapt and rms > self.floor and foreground:
            if self.level is None:
                self.level, self.peak = rms, rms
            else:
                self.level = self.level * 0.93 + rms * 0.07
                self.peak = max(rms, self.peak * 0.985)
            desired = min(self.max_gain, max(self.min_gain, self.target / self.level))
            self.gain += (desired - self.gain) * 0.12
            self.applied.append(self.gain)

        # упреждение: решение по кадру принимаем, видя следующие LOOKAHEAD кадров
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
        import numpy as np

        if not self.applied:
            return 0.0
        return round(20 * float(np.log10(float(np.mean(self.applied)))), 1)


# --- шумоподавление -----------------------------------------------------------
# 2026-09-02: pyrnnoise упал на `Graph.__init__() got an unexpected keyword
# argument 'rate'` (несовместимость с PyAV после пересборки образа) и унёс с
# собой _audio_task_handler — весь входящий звук пропал, при живом исходящем.
# Фильтр качества звука не имеет права рвать тракт: любая ошибка внутри него
# теперь один раз логируется и дальше аудио идёт как есть.

if RNNoiseFilter is not None:

    class SafeRNNoiseFilter(RNNoiseFilter):  # type: ignore[misc,valid-type]
        """RNNoise, который при первой же ошибке отключается вместо падения."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self._broken = False

        def _disable(self, exc: Exception) -> None:
            if not self._broken:
                self._broken = True
                log.error(
                    "RNNoise disabled for this call after error: %s. "
                    "Audio continues unfiltered. Set ENABLE_RNNOISE=false to silence this.",
                    exc,
                )

        async def start(self, sample_rate: int) -> None:
            try:
                await super().start(sample_rate)
            except Exception as exc:
                self._disable(exc)

        async def stop(self) -> None:
            parent = getattr(super(), "stop", None)
            if parent is None:
                return
            try:
                await parent()
            except Exception as exc:
                self._disable(exc)

        async def process_frame(self, frame: Frame) -> None:
            if self._broken:
                return
            parent = getattr(super(), "process_frame", None)
            if parent is None:
                return
            try:
                await parent(frame)
            except Exception as exc:
                self._disable(exc)

        async def filter(self, audio: bytes) -> bytes:
            if self._broken:
                return audio
            try:
                return await super().filter(audio)
            except Exception as exc:
                self._disable(exc)
                return audio

else:
    SafeRNNoiseFilter = None  # type: ignore[assignment]


def build_audio_filter():
    """Возвращает фильтр входящего аудио или None, если он недоступен/выключен."""
    if not ENABLE_RNNOISE:
        return None
    if SafeRNNoiseFilter is None:
        log.warning("RNNoiseFilter unavailable (import failed) — running without it")
        return None
    try:
        return SafeRNNoiseFilter()
    except Exception as exc:
        log.error("RNNoiseFilter construction failed (%s) — running without it", exc)
        return None


def analyze_pcm(data: bytes, rate: int) -> dict[str, Any]:
    """
    Числа вместо ушей. Что смотреть:
      rms_dbfs        < -35  -> слишком тихо, ASR не слышит
      clipped_pct     > 1    -> перегруз, искажения
      dropout_runs    > 5    -> пропадают куски звука (рваная речь)
      speech_band_pct < 60   -> в звуке мало речи, много мусора
      above_4k_pct    > 15   -> для 8 кГц линии там быть нечего: артефакты
    """
    import numpy as np

    a = np.frombuffer(data[: len(data) // 2 * 2], dtype="<i2").astype(np.float32)
    n = int(a.size)
    if n < rate:
        return {"error": "too short", "samples": n}

    def dbfs(x: float) -> float:
        return round(20 * float(np.log10(max(x, 1.0) / 32768.0)), 1)

    rms = float(np.sqrt(np.mean(a * a)))
    peak = float(np.max(np.abs(a)))
    clipped = float(np.mean(np.abs(a) >= 32700)) * 100

    frame = int(rate * 0.02)
    nf = n // frame
    frames = a[: nf * frame].reshape(nf, frame)
    frame_rms = np.sqrt(np.mean(frames * frames, axis=1))
    silence_thr = 32768 * 10 ** (-50 / 20)
    silence_pct = float(np.mean(frame_rms < silence_thr)) * 100
    zero_frames = np.all(frames == 0, axis=1)
    dropout_runs = int(np.sum(np.diff(np.concatenate(([0], zero_frames.astype(int)))) == 1))

    seg = a[: min(n, rate * 30)]
    spec = np.abs(np.fft.rfft(seg * np.hanning(seg.size))) ** 2
    freqs = np.fft.rfftfreq(seg.size, 1.0 / rate)
    total = float(np.sum(spec)) or 1.0
    speech = float(np.sum(spec[(freqs > 300) & (freqs < 3400)])) / total * 100
    above_4k = float(np.sum(spec[freqs > 4000])) / total * 100
    below_100 = float(np.sum(spec[freqs < 100])) / total * 100

    return {
        "duration_s": round(n / rate, 1),
        "rms_dbfs": dbfs(rms),
        "peak_dbfs": dbfs(peak),
        "clipped_pct": round(clipped, 2),
        "silence_pct": round(silence_pct, 1),
        "dropout_runs": dropout_runs,
        "zero_frames_pct": round(float(np.mean(zero_frames)) * 100, 1),
        "dc_offset": round(float(np.mean(a)), 1),
        "speech_band_pct": round(speech, 1),
        "above_4k_pct": round(above_4k, 1),
        "below_100hz_pct": round(below_100, 1),
    }


def read_wav_or_raw(path: str, default_rate: int) -> tuple[bytes, int]:
    try:
        with wave.open(path, "rb") as w:
            return w.readframes(w.getnframes()), w.getframerate()
    except Exception:
        with open(path, "rb") as f:
            return f.read(), default_rate


# =============================================================================
# 3. ДВИЖОК ХАРАКТЕРА
# =============================================================================

# Шкалы характера — ровно те же, что в bbb (таблица companion_settings).
TRAITS = (
    "openness",
    "conscientiousness",
    "extraversion",
    "agreeableness",
    "neuroticism",
    "sarcasm",
    "energy",
    "proactivity",
    "tough_love",
    "ego",
)

_TRAIT_SCALES: tuple[tuple[str, str], ...] = (
    ("openness",          "Открытость (консерватор - творец)"),
    ("conscientiousness", "Собранность (хаос - педант)"),
    ("extraversion",      "Экстраверсия (интроверт - душа компании)"),
    ("agreeableness",     "Дружелюбие (критик - эмпат)"),
    ("neuroticism",       "Эмоциональность (спокоен - легко возбудим)"),
    ("sarcasm",           "Сарказм (серьезный - ироничный)"),
    ("energy",            "Энергетика (медленный - гиперэнергичный)"),
    ("proactivity",       "Инициативность (ведомый - ведущий)"),
    ("tough_love",        "Стиль поддержки (мягко - жестко мотивирует)"),
    ("ego",               "Эго (скромный - высокомерный)"),
)

# Акцент и манера речи по языку — как lang_profiles в bbb.
_SPEECH_STYLE: dict[str, str] = {
    "ru": (
        "Speak with a native Russian accent. Use natural Russian conversational "
        "fillers (like 'ну', 'так', 'смотрите'). Let your pacing and pauses follow "
        "the psychological portrait above."
    ),
    "ro": (
        "Speak with a native Moldovan Romanian accent. Use natural fillers "
        "(like 'deci', 'păi', 'adică'). Let your pacing and pauses follow the "
        "psychological portrait above."
    ),
    "en": (
        "Speak with a neutral business English accent. Use natural fillers "
        "(like 'so', 'alright'). Let your pacing and pauses follow the "
        "psychological portrait above."
    ),
}


@dataclass
class Persona:
    """Характер бота. Поля повторяют companion_settings из bbb."""

    persona_name: str = ""
    lore: str = ""
    voice_model: str = "Enceladus"
    language: str = DEFAULT_LANG
    system_prompt: str = ""
    personality_enabled: bool = True

    openness: int = 5
    conscientiousness: int = 5
    extraversion: int = 5
    agreeableness: int = 5
    neuroticism: int = 5
    sarcasm: int = 5
    energy: int = 5
    proactivity: int = 5
    tough_love: int = 5
    ego: int = 5

    @classmethod
    def from_row(cls, row: dict[str, Any] | None) -> "Persona":
        p = cls()
        if not row:
            return p
        for f in ("persona_name", "lore", "voice_model", "language", "system_prompt"):
            val = row.get(f)
            if val:
                setattr(p, f, str(val))
        for f in TRAITS:
            val = row.get(f)
            if val is not None:
                try:
                    setattr(p, f, max(1, min(10, int(val))))
                except (TypeError, ValueError):
                    pass
        if row.get("personality_enabled") is not None:
            p.personality_enabled = bool(row["personality_enabled"])
        return p


def build_personality_block(p: Persona, lang: str) -> str:
    """<AI_IDENTITY> + <BEHAVIOR_ENGINE> — та же конструкция, что в bbb."""
    if not p.personality_enabled:
        return ""

    lang = (lang or DEFAULT_LANG).lower()[:2]
    out: list[str] = ["<AI_IDENTITY>"]
    if p.persona_name:
        out.append(f"Твое имя: {p.persona_name}")
    if p.lore:
        out.append(f"Твоя личная предыстория (LORE): {p.lore}")
        out.append(
            "ВНИМАНИЕ: Это ТВОИ интересы и ТВОЯ история. "
            "НИКОГДА не приписывай эти факты собеседнику!"
        )
    out.append("</AI_IDENTITY>")
    out.append("")

    out.append("<BEHAVIOR_ENGINE>")
    out.append("ПСИХОЛОГИЧЕСКИЙ ПОРТРЕТ (Шкала 1-10):")
    for i, (field_name, label) in enumerate(_TRAIT_SCALES, start=1):
        out.append(f"{i}. {label}: {getattr(p, field_name)}")
    out.append("")
    out.append(
        "ИНСТРУКЦИЯ К ХАРАКТЕРУ: Адаптируй свой лексикон, длину пауз, скорость речи "
        "и эмоции СТРОГО под эти 10 показателей. Они важнее любых общих указаний "
        "о тоне ниже по промпту."
    )
    out.append(f"МАНЕРА РЕЧИ: {_SPEECH_STYLE.get(lang, _SPEECH_STYLE['en'])}")
    out.append("</BEHAVIOR_ENGINE>")

    return "\n".join(out)


TELEPHONY_RULES = """<CALL_RULES>
- This is a phone call. Never output markdown, emoji, lists or URLs — everything you say is spoken aloud.
- Pronounce phone numbers and codes digit by digit.
- If you need to send a link or an address, use the send_sms tool instead of reading it aloud.
- Never invent facts, prices, availability or dates. If you do not know, say so and offer a callback.
- If the caller asks whether you are a human or an AI assistant, answer honestly.
- If the line is noisy or the caller is unclear, ask them to repeat before guessing. A single unclear turn never changes what you do: keep the topic, keep the language, keep the call going.
</CALL_RULES>"""


# =============================================================================
# 4. РАБОЧИЕ ЧАСЫ
# =============================================================================

_DAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_DEFAULT_HOURS = {d: ["09:00", "17:00"] for d in _DAY_KEYS[:5]}


def parse_working_hours(raw: Any) -> dict[str, list[str]]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = None
    if not isinstance(raw, dict) or not raw:
        return dict(_DEFAULT_HOURS)
    out: dict[str, list[str]] = {}
    for day, val in raw.items():
        key = str(day).lower()[:3]
        if key in _DAY_KEYS and isinstance(val, (list, tuple)) and len(val) == 2:
            out[key] = [str(val[0]), str(val[1])]
    return out or dict(_DEFAULT_HOURS)


def next_open_slot(hours: dict[str, list[str]], now: dt.datetime) -> str:
    """Ближайшее время, когда с клиентом сможет говорить человек."""
    for day_offset in range(0, 8):
        day = now + dt.timedelta(days=day_offset)
        window = hours.get(_DAY_KEYS[day.weekday()])
        if not window:
            continue
        try:
            sh, sm = (int(x) for x in window[0].split(":")[:2])
            eh, em = (int(x) for x in window[1].split(":")[:2])
        except (ValueError, IndexError):
            continue
        start = day.replace(hour=sh, minute=sm, second=0, microsecond=0)
        end = day.replace(hour=eh, minute=em, second=0, microsecond=0)
        if day_offset == 0 and now < end:
            when = max(now, start)
            return when.strftime("%A %d %B, %H:%M")
        if day_offset > 0:
            return start.strftime("%A %d %B, %H:%M")
    return "нет доступного окна"


def office_state(hours: dict[str, list[str]], now: dt.datetime) -> tuple[bool, str]:
    """Возвращает (открыто_сейчас, человекочитаемое расписание)."""
    key = _DAY_KEYS[now.weekday()]
    is_open = False
    window = hours.get(key)
    if window:
        try:
            start_h, start_m = (int(x) for x in window[0].split(":")[:2])
            end_h, end_m = (int(x) for x in window[1].split(":")[:2])
            start = now.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
            end = now.replace(hour=end_h, minute=end_m, second=0, microsecond=0)
            is_open = start <= now <= end
        except (ValueError, IndexError):
            is_open = False
    # jsonb не хранит порядок ключей — без сортировки в промпт уезжает
    # "Fri, Mon, Thu, Tue, Wed", что модель читает вслух как есть.
    readable = ", ".join(
        f"{d.capitalize()} {hours[d][0]}-{hours[d][1]}" for d in _DAY_KEYS if d in hours
    )
    return is_open, readable or "Mon-Fri 09:00-17:00"


# =============================================================================
# 5. ДОСТУП К ДАННЫМ
# =============================================================================


async def sb_select(table: str, params: dict[str, str], timeout: float = 5.0) -> list[dict]:
    """Чтение из PostgREST. Все значения экранируются — защита от инъекции в query."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return []
    query = "&".join(f"{k}={quote(str(v), safe='(),.*:+-')}" for k, v in params.items())
    url = f"{SUPABASE_URL}/rest/v1/{table}?{query}"
    try:
        resp = await http().get(url, headers=sb_headers(), timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else []
    except Exception as exc:
        log.warning("supabase select %s failed: %s", table, exc)
        return []


async def sb_rpc(fn: str, payload: dict, timeout: float = 5.0) -> Any:
    """Вызов SQL-функции через PostgREST. Нужен там, где фильтр — выражение."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    resp = await http().post(
        f"{SUPABASE_URL}/rest/v1/rpc/{fn}",
        headers={**sb_headers(), "Content-Type": "application/json"},
        json=payload,
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


async def get_client_data(client_id: str) -> dict | None:
    rows = await sb_select(
        "saas_clients",
        {
            "id": f"eq.{client_id}",
            "select": (
                "company_name,business_context,tone,bot_goal,"
                "subscription_status_assistent,system_message,timezone,working_hours,"
                "crm_provider,crm_config,"
                "saas_projects(tg_chat_id_notify,google_calendar_id)"
            ),
        },
    )
    if not rows:
        return None
    rec = rows[0]
    projects = rec.get("saas_projects") or []
    first = projects[0] if projects else {}
    rec["tg_chat_id_notify"] = first.get("tg_chat_id_notify")
    rec["google_calendar_id"] = first.get("google_calendar_id")
    return rec


async def get_persona(client_id: str) -> Persona:
    return Persona.from_row(await get_persona_row(client_id))


async def get_persona_row(client_id: str) -> dict | None:
    cache_key = f"persona:{client_id}"
    if redis_client:
        with contextlib.suppress(Exception):
            cached = await redis_client.get(cache_key)
            if cached:
                return json.loads(cached)

    cols = ",".join(
        ["system_prompt", "voice_model", "language", "persona_name", "lore",
         "personality_enabled", *TRAITS]
    )
    rows = await sb_select("bot_personas", {"client_id": f"eq.{client_id}", "select": cols})
    row = rows[0] if rows else None
    if redis_client and row:
        with contextlib.suppress(Exception):
            await redis_client.setex(cache_key, PERSONA_CACHE_TTL, json.dumps(row, default=str))
    return row


async def get_caller_memory(client_id: str, phone: str) -> tuple[dict, str]:
    default = {"core": "", "short": "", "long": ""}
    if not phone or phone == "Necunoscut":
        return default, "first_time"
    clean = "".join(filter(str.isdigit, str(phone)))
    rows = await sb_rpc(
        "person_memory_get",
        {"p_client_id": client_id, "p_phone": phone},
        timeout=2.5,
    )
    if not rows:
        return default, "first_time"
    rec = rows[0]
    memory = {
        "core": rec.get("core_identity") or "",
        "short": rec.get("short_term_context") or "",
        "long": rec.get("long_term_context") or "",
    }
    time_context = "first_time"
    last_at = rec.get("last_interaction_at")
    if last_at:
        try:
            last = dt.datetime.fromisoformat(str(last_at).replace("Z", "+00:00"))
            delta = (dt.datetime.now(dt.timezone.utc) - last).total_seconds() / 60
            time_context = "very_recent" if delta < 15 else ("same_day" if delta < 1440 else "new_day")
        except ValueError:
            pass
    return memory, time_context


# =============================================================================
# 5b. ПОИСК ЗВОНЯЩЕГО — ДИНАМИЧЕСКИЙ ПО ПРОВАЙДЕРАМ
# =============================================================================
# saas_clients.crm_provider говорит, где искать контакт этого клиента,
# saas_clients.crm_config (jsonb) хранит параметры провайдера.
# Kommo больше не зашит в код — он один из вариантов.
#
#   supabase (дефолт) — таблица end_clients, поиск по последним 8 цифрам
#   kommo             — {"subdomain": "...", "token": "..."}
#   webhook           — {"url": "...", "token": "..."}  (n8n: sheets/bitrix/...)
#   none              — не искать

CONTACT_LOOKUP_TIMEOUT = _env_float("CONTACT_LOOKUP_TIMEOUT", 2.0)


def phone_tail(phone: str | None, digits: int = 8) -> str:
    """Последние N цифр номера. 069635362, +373 69 63 53 62, 37369635362 -> 69635362."""
    clean = "".join(filter(str.isdigit, str(phone or "")))
    return clean[-digits:] if len(clean) >= digits else clean


def normalize_lang(value: Any) -> str | None:
    v = str(value or "").strip().lower()
    if not v:
        return None
    if v.startswith("ru") or "рус" in v:
        return "ru"
    if v.startswith("ro") or v.startswith("md") or "rom" in v or "rum" in v:
        return "ro"
    if v.startswith("en") or "engl" in v:
        return "en"
    return None


async def _lookup_supabase(phone: str, client_id: str, cfg: dict) -> dict:
    """
    Ищем в end_clients через SQL-функцию find_end_client_by_phone.
    Нормализация номера живёт в самой функции, служебных колонок в таблице нет.
    """
    tail = phone_tail(phone)
    if len(tail) < 8:
        return {"found": False}
    rows = await sb_rpc(
        "find_end_client_by_phone",
        {"p_client_id": client_id, "p_tail": tail},
        timeout=CONTACT_LOOKUP_TIMEOUT,
    )
    if not rows:
        return {"found": False}
    rec = rows[0] if isinstance(rows, list) else rows
    return {
        "found": True,
        "name": (rec.get("name") or "").strip() or None,
        "lang": normalize_lang(rec.get("language")),
        "source": "supabase",
    }


async def _lookup_kommo(phone: str, client_id: str, cfg: dict) -> dict:
    subdomain = str(cfg.get("subdomain") or KOMMO_SUBDOMAIN or "").strip()
    token = str(cfg.get("token") or KOMMO_ACCESS_TOKEN or "").strip()
    tail = phone_tail(phone)
    if not subdomain or not token or len(tail) < 6:
        return {"found": False}
    resp = await http().get(
        f"https://{subdomain}.kommo.com/api/v4/contacts",
        headers={"Authorization": f"Bearer {token}"},
        params={"query": tail},
        timeout=CONTACT_LOOKUP_TIMEOUT,
    )
    if resp.status_code != 200:
        return {"found": False}
    contacts = (resp.json().get("_embedded") or {}).get("contacts") or []
    if not contacts:
        return {"found": False}
    contact = contacts[0]
    lang = None
    for f in contact.get("custom_fields_values") or []:
        code = str(f.get("field_code") or "").upper()
        fname = str(f.get("field_name") or "").lower()
        if code == "LANG" or any(k in fname for k in ("язык", "limba", "lang")):
            lang = normalize_lang((f.get("values") or [{}])[0].get("value"))
            break
    return {
        "found": True,
        "name": (contact.get("name") or "").strip() or None,
        "lang": lang,
        "source": "kommo",
    }


async def _lookup_webhook(phone: str, client_id: str, cfg: dict) -> dict:
    """
    Универсальный адаптер. Отдаём номер — получаем {"name": ..., "language": ...}.
    Через него подключается всё, для чего не нужен отдельный клиент в Python:
    Google Sheets, Bitrix, Salesforce, самописные базы. Логика живёт в n8n.
    """
    url = str(cfg.get("url") or "").strip()
    if not url:
        return {"found": False}
    headers = {}
    if cfg.get("token"):
        headers["Authorization"] = f"Bearer {cfg['token']}"
    resp = await http().post(
        url,
        json={"client_id": client_id, "phone": phone, "phone_tail": phone_tail(phone)},
        headers=headers,
        timeout=CONTACT_LOOKUP_TIMEOUT,
    )
    if resp.status_code != 200:
        return {"found": False}
    data = resp.json()
    if isinstance(data, list):
        data = data[0] if data else {}
    if not isinstance(data, dict) or not data:
        return {"found": False}
    name = (data.get("name") or data.get("client_name") or "").strip() or None
    if not name and not data.get("language"):
        return {"found": False}
    return {
        "found": True,
        "name": name,
        "lang": normalize_lang(data.get("language") or data.get("lang")),
        "source": "webhook",
    }


_CONTACT_PROVIDERS = {
    "supabase": _lookup_supabase,
    "end_clients": _lookup_supabase,
    "kommo": _lookup_kommo,
    "webhook": _lookup_webhook,
    "sheets": _lookup_webhook,
    "bitrix": _lookup_webhook,
    "salesforce": _lookup_webhook,
}


async def lookup_contact(client_data: dict, client_id: str, phone: str) -> dict:
    """Один вход для всех провайдеров. Не нашли или упало — звоним как незнакомому."""
    if not phone or phone == "Necunoscut":
        return {"found": False}

    provider = str(client_data.get("crm_provider") or "supabase").strip().lower()
    if provider in ("none", "off", "disabled"):
        return {"found": False}

    cfg = client_data.get("crm_config") or {}
    if isinstance(cfg, str):
        with contextlib.suppress(Exception):
            cfg = json.loads(cfg)
    if not isinstance(cfg, dict):
        cfg = {}

    fn = _CONTACT_PROVIDERS.get(provider)
    if fn is None:
        log.warning("unknown crm_provider %r for client %s", provider, client_id)
        return {"found": False}

    try:
        result = await asyncio.wait_for(
            fn(phone, client_id, cfg), timeout=CONTACT_LOOKUP_TIMEOUT + 0.5
        )
        if result.get("found"):
            log.info(
                "contact found via %s: name=%s lang=%s",
                result.get("source"),
                result.get("name") or "-",
                result.get("lang") or "-",
            )
        return result
    except Exception as exc:
        log.warning("contact lookup (%s) failed: %s", provider, exc)
        return {"found": False}


async def upload_debug_wav(client_id: str, filepath: str) -> str | None:
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    try:
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        storage_path = f"debug-input/{client_id}/in_{uuid.uuid4().hex[:8]}.wav"

        def _upload() -> str:
            with open(filepath, "rb") as f:
                supabase.storage.from_("call-recordings").upload(
                    path=storage_path, file=f, file_options={"content-type": "audio/wav"}
                )
            return supabase.storage.from_("call-recordings").get_public_url(storage_path)

        return await asyncio.to_thread(_upload)
    except Exception as exc:
        log.warning("debug wav upload failed: %s", exc)
        return None


async def ensure_end_client(client_id: str, phone: str, name: str = "", lang: str = "") -> None:
    """
    Каждый входящий с незнакомого номера получает карточку в end_clients.
    Имя и язык дописываются после разговора, когда бот их узнал.
    Повторный вызов ничего не ломает — на (client_id, phone) стоит unique.
    """
    if not phone or phone == "Necunoscut" or not SUPABASE_URL or not SUPABASE_KEY:
        return
    row: dict[str, Any] = {"client_id": client_id, "phone": phone, "lead_status": "new"}
    if name:
        row["name"] = name
    if lang:
        row["language"] = lang
    try:
        db = create_client(SUPABASE_URL, SUPABASE_KEY)
        await asyncio.to_thread(
            db.table("end_clients")
            .upsert(row, on_conflict="client_id,phone", ignore_duplicates=not (name or lang))
            .execute
        )
        log.info("end_clients upserted for %s (name=%s lang=%s)", phone, name or "-", lang or "-")
    except Exception as exc:
        log.warning("end_clients upsert failed: %s", exc)


async def send_tg_alert(chat_id: str | None, message: str) -> None:
    if not TG_BOT_TOKEN or not chat_id:
        return
    with contextlib.suppress(Exception):
        await http().post(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
            timeout=5.0,
        )


async def upload_audio_to_supabase(client_id: str, filepath: str) -> str | None:
    if not SUPABASE_URL or not SUPABASE_KEY or not filepath:
        return None
    if not await asyncio.to_thread(os.path.exists, filepath):
        return None
    try:
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        storage_path = f"records/{client_id}/record_{uuid.uuid4().hex[:8]}.wav"

        def _upload() -> str:
            with open(filepath, "rb") as f:
                supabase.storage.from_("call-recordings").upload(
                    path=storage_path, file=f, file_options={"content-type": "audio/wav"}
                )
            return supabase.storage.from_("call-recordings").get_public_url(storage_path)

        return await asyncio.to_thread(_upload)
    except Exception as exc:
        log.warning("audio upload failed: %s", exc)
        return None


# =============================================================================
# 6. АРХИВАРИУС (память + резюме для CRM)
# =============================================================================


async def run_archivist_and_notify_n8n(
    client_id: str,
    phone: str,
    client_name: str,
    old_memory: dict,
    chat_history: str,
    audio_url: str,
    sys_length: int,
    direction: str,
    call_status: str,
    tz_name: str,
    usage_stats: dict | None = None,
    audio_path: str | None = None,
    project_id: str = "",
    web_id: str = "",
    platform: str = "gsm_voice",
) -> None:
    if not chat_history.strip() or phone == "Necunoscut":
        return

    # Субтитры Gemini Live ненадёжны: модель понимает звук верно, а субтитры
    # к нему пишет отдельный слабый механизм. Поэтому архивариусу отдаём саму
    # запись — полная модель слушает весь разговор и пишет нормальную расшифровку.
    audio_part = None
    if audio_path:
        try:
            if await asyncio.to_thread(os.path.exists, audio_path):
                size = await asyncio.to_thread(os.path.getsize, audio_path)
                if 0 < size <= 18_000_000:
                    wav_bytes = await asyncio.to_thread(lambda: open(audio_path, "rb").read())
                    audio_part = types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav")
                else:
                    log.warning("[archivist] recording %d bytes — too big, using subtitles", size)
        except Exception as exc:
            log.warning("[archivist] cannot attach recording (%s), using subtitles", exc)

    today = dt.datetime.now(tz_for(tz_name)).strftime("%Y-%m-%d")
    clean_phone = "".join(filter(str.isdigit, str(phone)))

    prompt = f"""Ты ИИ-архивариус. Обнови память клиента и составь резюме звонка для CRM.
Дата звонка: {today}. Направление: {direction}.

СТАРАЯ ПАМЯТЬ:
CORE IDENTITY: {old_memory.get('core') or 'Нет данных'}
SHORT TERM: {old_memory.get('short') or 'Нет данных'}
LONG TERM: {old_memory.get('long') or 'Нет данных'}

{"АУДИОЗАПИСЬ РАЗГОВОРА ПРИЛОЖЕНА. Реплики бота (AI) в субтитрах ниже точные. Реплики клиента (Client) в субтитрах часто искажены и могут быть на случайных языках — ИГНОРИРУЙ их текст и слушай, что клиент реально сказал в записи. В записи может быть ФОН: телевизор, радио, чужие разговоры рядом с клиентом. Признаки фона: речь не обращена к боту, не в тему разговора, на другом языке, чем говорит клиент, или бот на неё не отреагировал. Фон — НЕ реплики клиента: не включай его в транскрипт, в резюме и в память."if audio_part else "Аудиозаписи нет, работай по субтитрам."}

СУБТИТРЫ ЗВОНКА:
{chat_history}

ИНСТРУКЦИЯ (выведи СТРОГО JSON, без markdown):
1. core_identity: обнови, если клиент сообщил фундаментальный факт.
2. short_term_context: факты старше 3 дней перенеси в long_term. Новые пиши как "[{today}]: факт".
3. long_term_context: сжатая история прошлых обращений.
4. summary: суть текущего звонка для менеджера.
5. sentiment: настрой и возражения.
6. next_step: следующий шаг (перезвонить, отправить КП и т.д.).
7. language: язык, на котором РЕАЛЬНО говорил клиент (ro/ru/en).
8. client_name: имя клиента, если он его назвал. Иначе пустая строка.
9. transcript: расшифровка разговора по записи, в формате "Client: ..." / "AI: ...", на языке оригинала каждой реплики. Только реплики бота и слова клиента, обращённые к боту; фон (телевизор, посторонние разговоры) пропускай. Если записи нет — верни субтитры, убрав из них строки Client, которые явно не в тему разговора.

{{"core_identity":"...","short_term_context":"...","long_term_context":"...","summary":"...","sentiment":"...","next_step":"...","language":"...","client_name":"...","transcript":"..."}}
"""

    data: dict[str, Any] = {}
    client = genai.Client(api_key=GEMINI_API_KEY)
    for attempt, model in enumerate(ARCHIVIST_MODELS):
        try:
            response = await client.aio.models.generate_content(
                model=model,
                contents=[audio_part, prompt] if audio_part else prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json"),
            )
            data = json.loads(response.text.strip())
            break
        except Exception as exc:
            log.warning("archivist model %s failed: %s", model, exc)
            if attempt < len(ARCHIVIST_MODELS) - 1:
                await asyncio.sleep(2)
    else:
        data = {
            "core_identity": old_memory.get("core", ""),
            "short_term_context": old_memory.get("short", ""),
            "long_term_context": old_memory.get("long", ""),
            "summary": "Ошибка генерации саммари: все модели недоступны.",
            "sentiment": "Неизвестно",
            "next_step": "Связаться вручную",
            "language": DEFAULT_LANG,
        }

    try:
        if web_id:
            await sb_rpc(
                "person_memory_upsert_web",
                {
                    "p_client_id": client_id,
                    "p_web_id": web_id,
                    "p_phone": phone or "",
                    "p_name": str(data.get("client_name") or client_name or "").strip(),
                    "p_core": data.get("core_identity", ""),
                    "p_short": data.get("short_term_context", ""),
                    "p_long": data.get("long_term_context", ""),
                },
                timeout=5.0,
            )
        else:
            await sb_rpc(
                "person_memory_upsert",
                {
                    "p_client_id": client_id,
                    "p_phone": phone,
                    "p_core": data.get("core_identity", ""),
                    "p_short": data.get("short_term_context", ""),
                    "p_long": data.get("long_term_context", ""),
                    "p_channel": "voice",
                },
                timeout=5.0,
            )
        log.info("[archivist] memory saved for %s", clean_phone)
    except Exception as exc:
        log.error("[archivist] memory save failed: %s", exc)

    # Дописываем в карточку то, что удалось узнать за разговор.
    # Язык НЕ записываем: он выводится из расшифровки, а она сейчас ненадёжна.
    # Один звонок с мусорным ASR прописал клиенту english, и следующий звонок
    # бот начал по-английски. Пишем только имя.
    learned_name = str(data.get("client_name") or "").strip()
    if learned_name and not web_id:
        await ensure_end_client(client_id, phone, learned_name, "")

    if not N8N_BASE_URL:
        return
    payload = {
        "client_id": client_id,
        "project_id": project_id,
        "web_id": web_id,
        "end_client_name": client_name,
        "end_client_phone": phone,
        "status": call_status,
        "transcript": (data.get("transcript") or "").strip() or chat_history,
        "summary": json.dumps(
            {
                "client_name": client_name,
                "summary": data.get("summary", ""),
                "sentiment": data.get("sentiment", ""),
                "next_step": data.get("next_step", ""),
                "language": data.get("language", ""),
            },
            ensure_ascii=False,
        ),
        "audio_url": audio_url,
        "system_instructions_length": sys_length,
        "platform": platform,
        "direction": direction,
        # Расход звонка идёт тем же вебхуком — n8n пишет его в call_logs,
        # отдельная таблица не нужна.
        **(usage_stats or {}),
    }
    try:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if N8N_WEBHOOK_SECRET:
            sig = hmac.new(N8N_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
            headers["X-Signature"] = f"sha256={sig}"
        await http().post(f"{N8N_BASE_URL}/post-call-summary", content=body, headers=headers, timeout=10.0)
        log.info("[archivist] report sent to n8n")
    except Exception as exc:
        log.error("[archivist] n8n post failed: %s", exc)


# =============================================================================
# 7. АДАПТЕР ASTERISK AUDIOSOCKET
# =============================================================================


class RawPCMFrameSerializer(FrameSerializer):
    async def serialize(self, frame: Frame) -> bytes | str | None:
        if isinstance(frame, OutputAudioRawFrame):
            return frame.audio
        return None

    async def deserialize(self, data: bytes | str) -> Frame | None:
        if isinstance(data, bytes):
            return InputAudioRawFrame(
                audio=data, sample_rate=PIPELINE_SAMPLE_RATE, num_channels=1
            )
        return None


class AsteriskAudioSocket:
    """
    Прикидывается WebSocket'ом, чтобы FastAPIWebsocketTransport работал поверх
    сырого TCP AudioSocket. Отправка блокирующая с пейсингом по реальной
    длительности звука — Pipecat не убегает вперёд линии.
    """

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader = reader
        self.writer = writer
        self.client_state = WebSocketState.CONNECTED
        self.application_state = WebSocketState.CONNECTED
        self.is_muted = False
        self.next_send_time = time.time()
        self._resample_state: Any = None
        self.last_rx_ts = 0.0  # для сторожа входящего аудио
        self.rx_bytes = 0
        self.last_tx_ts = 0.0  # когда бот последний раз что-то говорил
        self.agc = (
            InputAGC(INPUT_TARGET_DBFS, INPUT_MAX_GAIN_DB, INPUT_MIN_GAIN_DB)
            if INPUT_AGC
            else None
        )

    async def accept(self) -> None:
        return None

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.client_state = WebSocketState.DISCONNECTED
        self.application_state = WebSocketState.DISCONNECTED
        with contextlib.suppress(Exception):
            self.writer.close()
            await self.writer.wait_closed()

    async def receive_bytes(self) -> bytes:
        header = await self.reader.readexactly(3)
        payload_len = int.from_bytes(header[1:], "big")
        data = await self.reader.readexactly(payload_len) if payload_len else b""

        if header[0] == AS_TYPE_HANGUP:
            self.client_state = WebSocketState.DISCONNECTED
            raise ConnectionResetError("hangup")

        if not data:
            return b""

        # Asterisk отдаёт 8 кГц — тянем до частоты пайплайна, иначе Gemini
        # слышит замедленную речь и «угадывает» чужой язык.
        self.last_rx_ts = time.time()
        self.rx_bytes += len(data)

        if ASTERISK_INPUT_RATE != PIPELINE_SAMPLE_RATE:
            data, self._resample_state = pcm_resample(
                data, self._resample_state, ASTERISK_INPUT_RATE, PIPELINE_SAMPLE_RATE
            )
        if self.agc is not None:
            # пока бот говорит (и полсекунды после), уровень не подстраиваем —
            # в это время на входе в основном эхо его же голоса
            data = self.agc.process(data, adapt=(time.time() - self.last_tx_ts) > 0.6)
        return data

    async def receive(self) -> dict:
        while True:
            try:
                data = await self.receive_bytes()
                if not data:
                    continue
                if self.is_muted:
                    data = b"\x00" * len(data)
                return {"type": "websocket.receive", "bytes": data}
            except Exception:
                self.client_state = WebSocketState.DISCONNECTED
                return {"type": "websocket.disconnect", "code": 1000}

    async def send_bytes(self, data: bytes) -> None:
        if self.client_state != WebSocketState.CONNECTED or not data:
            return
        try:
            softened = pcm_scale(data, OUT_VOLUME)
            bytes_per_second = PIPELINE_SAMPLE_RATE * 2
            for i in range(0, len(softened), OUT_CHUNK_SIZE):
                chunk = softened[i : i + OUT_CHUNK_SIZE]
                now = time.time()
                if self.next_send_time < now:
                    self.next_send_time = now
                sleep_for = self.next_send_time - now
                if sleep_for > 0.01:
                    await asyncio.sleep(sleep_for)
                self.next_send_time += len(chunk) / bytes_per_second

                header = bytes([AS_TYPE_AUDIO_OUT]) + len(chunk).to_bytes(2, "big")
                self.writer.write(header + chunk)
                await self.writer.drain()
                self.last_tx_ts = time.time()
        except Exception as exc:
            log.warning("audio send failed: %s", exc)
            self.client_state = WebSocketState.DISCONNECTED


# =============================================================================
# 8. ПРОЦЕССОРЫ ПАЙПЛАЙНА
# =============================================================================


class UsageAggregator(FrameProcessor):
    """Считает токены звонка — база для биллинга SaaS."""

    def __init__(self) -> None:
        super().__init__()
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.turns = 0

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, MetricsFrame):
            for d in frame.data:
                if isinstance(d, LLMUsageMetricsData):
                    self.prompt_tokens += d.value.prompt_tokens
                    self.completion_tokens += d.value.completion_tokens
                    self.turns += 1
        await self.push_frame(frame, direction)

    def cost(self, system_prompt_tokens: int) -> tuple[int, int, float]:
        turns = max(1, self.turns)
        text_in = min(self.prompt_tokens, system_prompt_tokens * turns)
        audio_in = max(0, self.prompt_tokens - text_in)
        usd = (
            text_in / 1_000_000 * PRICE_TEXT_IN
            + audio_in / 1_000_000 * PRICE_AUDIO_IN
            + self.completion_tokens / 1_000_000 * PRICE_AUDIO_OUT
        )
        return text_in, audio_in, usd


class InboundAudioProbe(FrameProcessor):
    """
    Фиксирует, когда входящий звук реально дошёл до пайплайна.
    Вместе с AsteriskAudioSocket.last_rx_ts даёт точную картину:
    байты на сокете есть, а кадров в пайплайне нет = сломан транспорт
    или audio_in_filter.
    """

    def __init__(self) -> None:
        super().__init__()
        self.last_frame_ts = 0.0
        self.frames = 0
        self.dump: list[bytes] = [] if DUMP_INPUT_AUDIO else []
        self.bytes_seen = 0

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, InputAudioRawFrame):
            self.last_frame_ts = time.time()
            self.frames += 1
            self.bytes_seen += len(frame.audio)
            if DUMP_INPUT_AUDIO and self.bytes_seen <= 40_000_000:
                self.dump.append(frame.audio)
        await self.push_frame(frame, direction)

    def write_wav(self, path: str) -> bool:
        if not self.dump:
            return False
        try:
            with wave.open(path, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(PIPELINE_SAMPLE_RATE)
                w.writeframes(b"".join(self.dump))
            return True
        except Exception as exc:
            log.warning("input dump failed: %s", exc)
            return False

class ActivityProbe(FrameProcessor):
    """Запоминает момент последней речи — бота или клиента. Тишина не считается."""

    def __init__(self) -> None:
        super().__init__()
        self.last_activity_ts = time.time()

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(
            frame,
            (
                OutputAudioRawFrame,        # бот говорит
                TranscriptionFrame,         # клиент сказал — есть расшифровка
                InterimTranscriptionFrame,
                InterruptionFrame,          # Gemini услышал речь и перебил бота
                UserStartedSpeakingFrame,
            ),
        ):
            self.last_activity_ts = time.time()
        await self.push_frame(frame, direction)


async def dead_air_watchdog(call_id: str, activity: "ActivityProbe", task: PipelineTask) -> None:
    """Раз в 5 с: если DEAD_AIR_SECONDS никто не говорил — завершаем звонок."""
    try:
        while True:
            await asyncio.sleep(5.0)
            silent_for = time.time() - activity.last_activity_ts
            if silent_for >= DEAD_AIR_SECONDS:
                log.warning(
                    "[%s] DEAD AIR: no speech from either side for %.0fs — hanging up",
                    call_id,
                    silent_for,
                )
                with contextlib.suppress(Exception):
                    await task.queue_frames([CancelFrame()])
                return
    except asyncio.CancelledError:
        pass


async def audio_stall_watchdog(
    call_id: str, socket: "AsteriskAudioSocket", probe: InboundAudioProbe
) -> None:
    """Раз в 5 с сверяет сокет и пайплайн. Молчащий звонок больше не молчит в логах."""
    try:
        while True:
            await asyncio.sleep(5.0)
            now = time.time()
            socket_alive = socket.last_rx_ts and (now - socket.last_rx_ts) < 5.0
            pipeline_stalled = (
                probe.last_frame_ts == 0.0 or (now - probe.last_frame_ts) > AUDIO_STALL_SECONDS
            )
            if socket_alive and pipeline_stalled:
                log.error(
                    "[%s] INBOUND AUDIO STALLED: bytes arrive on the AudioSocket but no "
                    "InputAudioRawFrame reached the pipeline for %.0fs (frames so far: %d). "
                    "Most likely audio_in_filter or the input transport task crashed — "
                    "check for '_audio_task_handler unexpected exception' above, "
                    "or restart with ENABLE_RNNOISE=false.",
                    call_id,
                    AUDIO_STALL_SECONDS,
                    probe.frames,
                )
                return
    except asyncio.CancelledError:
        pass


class InterruptionRecoveryProcessor(FrameProcessor):
    """Клиент перебил и замолчал — бот мягко возвращает инициативу."""

    def __init__(self, context: LLMContext, delay: float = 4.0) -> None:
        super().__init__()
        self.context = context
        self.delay = delay
        self.task: Optional[PipelineTask] = None
        self.is_interrupted = False
        self.recovery_task: Optional[asyncio.Task] = None

    async def _recovery_timer(self) -> None:
        try:
            await asyncio.sleep(self.delay)
            if self.is_interrupted and self.task:
                self.context.add_message(
                    {
                        "role": "user",
                        "content": "SYSTEM EVENT: The caller interrupted you and then went "
                        "silent. Softly take the initiative back in one short sentence.",
                    }
                )
                await self.task.queue_frames([LLMRunFrame()])
                self.is_interrupted = False
        except asyncio.CancelledError:
            pass

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, InterruptionFrame):
            self.is_interrupted = True
            if self.recovery_task:
                self.recovery_task.cancel()
            self.recovery_task = asyncio.create_task(self._recovery_timer())
        elif isinstance(frame, (OutputAudioRawFrame, InputAudioRawFrame, UserStartedSpeakingFrame)):
            if self.recovery_task:
                self.recovery_task.cancel()
            self.is_interrupted = False
        await self.push_frame(frame, direction)


# =============================================================================
# 9. ТЕЛЕФОННЫЕ УТИЛИТЫ
# =============================================================================


def format_phone(phone: str | None) -> str:
    if not phone or phone == "Necunoscut":
        return "Necunoscut"
    clean = "".join(filter(str.isdigit, str(phone)))
    if not clean:
        return "Necunoscut"
    if clean.startswith("0") and len(clean) == 9:
        clean = "373" + clean[1:]
    elif len(clean) == 8:
        clean = "373" + clean
    if clean.startswith("373") and len(clean) >= 11:
        return f"+373 {clean[3:]}"
    if len(clean) > 3:
        return f"+{clean[:3]} {clean[3:]}"
    return f"+{clean}"


def extract_real_phone(*args: str | None) -> str:
    for val in args:
        if not val:
            continue
        for num in re.findall(r"\d{8,15}", str(val)):
            if not any(trunk in num for trunk in TRUNK_NUMBERS):
                return num
    return "Necunoscut"


def build_transcript(messages: list[dict]) -> tuple[str, int]:
    """Транскрипт без служебных вставок. Возвращает (текст, число реплик клиента)."""
    markers = ("SYSTEM EVENT:", "SYSTEM COMMAND:")
    lines: list[str] = []
    user_replies = 0
    for msg in messages:
        role = msg.get("role")
        if role not in ("user", "assistant"):
            continue
        content = msg.get("content")
        if isinstance(content, list):
            content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))
        content = (content or "").strip()
        if not content or any(m in content for m in markers):
            continue
        if role == "user":
            user_replies += 1
        lines.append(f"{'Client' if role == 'user' else 'AI'}: {content}")
    return "\n".join(lines), user_replies


# =============================================================================
# 10. СБОРКА СИСТЕМНОГО ПРОМПТА
# =============================================================================


def build_system_prompt(
    client_data: dict,
    persona: Persona,
    memory: dict,
    lang: str,
    now: dt.datetime,
    hours: dict[str, list[str]],
    caller_phone: str = "Necunoscut",
    caller_name: str = "",
) -> str:
    raw = persona.system_prompt or client_data.get("system_message") or "Ești un asistent virtual."
    is_open, readable_hours = office_state(hours, now)

    def safe(value: Any, fallback: str = "") -> str:
        return str(value or fallback).replace("{", "").replace("}", "")

    prompt = raw
    for token, value in (
        ("{company_name}", safe(client_data.get("company_name"), "Compania")),
        ("{business_context}", safe(client_data.get("business_context"))),
        ("{bot_goal}", safe(client_data.get("bot_goal"))),
        ("{tone}", safe(client_data.get("tone"), "friendly")),
        ("{current_datetime}", now.strftime("%A, %d %B %Y, %H:%M")),
        (
            "{office_status}",
            "Open"
            if is_open
            else "Closed for human appointments only — you, the assistant, are available as always",
        ),
        ("{lang}", lang),
        ("{persona_name}", safe(persona.persona_name, "Asistent")),
        ("{working_hours}", readable_hours),
    ):
        prompt = prompt.replace(token, value)

    # Характер идёт ПЕРВЫМ. Раньше он стоял в хвосте, после трёх тысяч токенов
    # клиентского промпта, и терялся — поэтому его и не было слышно.
    blocks = [build_personality_block(persona, lang), "", prompt, "", TELEPHONY_RULES, ""]

    # Номер звонящего. Раньше он никуда не передавался, и бот был вынужден
    # спрашивать номер у человека, который с этого номера и звонит.
    blocks.append("<CALLER>")
    if caller_phone and caller_phone != "Necunoscut":
        blocks.append(f"The caller is phoning from: {caller_phone}")
        blocks.append(
            "You already have this number. Never ask the caller for their phone number. "
            "Use it directly when saving a lead or sending an SMS. Ask only if they want "
            "to be reached on a different number."
        )
    else:
        blocks.append("The caller's number is hidden. Ask for it only if you need a callback.")
    if caller_name:
        blocks.append(f"The caller's name is {caller_name}. Use it naturally, do not re-ask.")
    else:
        blocks.append(
            "The contact card has no name. Check <CALLER_MEMORY> below: if a name is "
            "recorded there, that IS the caller's name — use it and do not ask again. "
            "Only if memory has no name either: ask how to address them in your first or "
            "second reply, once, then use the name for the rest of the call. Never invent one."
        )
    blocks.append("</CALLER>")
    blocks.append("")

    offset = now.strftime("%z")
    offset_fmt = f"{offset[:3]}:{offset[3:]}" if offset else "+00:00"
    next_slot = next_open_slot(hours, now)

    # Две РАЗНЫЕ доступности. Раньше они были смешаны в один блок, и бот,
    # увидев "офис закрыт", отказывался консультировать в 21:10.
    blocks.append("<AVAILABILITY>")
    blocks.append(
        "YOU ARE AVAILABLE 24/7. Consult, present, explain, answer questions and give "
        "prices at any hour of the day or night, including right now. The office being "
        "closed limits NOTHING for you — you are not the office, you are the assistant, "
        "and you work around the clock."
    )
    blocks.append(
        "NEVER tell the caller to call back later, never postpone their question to "
        "working hours, and never refuse to consult because of the time. If they want a "
        "consultation right now, give it right now, in full."
    )
    blocks.append(
        "IMPORTANT — do not confuse the two. A 'phone consultation' that the caller is "
        "asking you for right now IS THIS CALL, with you, and it is always available. "
        "Working hours have nothing to do with it. Only hand over to a human when the "
        "caller explicitly asks for a person, a manager, a specialist or a callback."
    )
    blocks.append(
        "Never say that colleagues are busy, that it is outside working hours, or that "
        "you cannot consult right now. You can, and you must."
    )
    blocks.append("")
    blocks.append(
        "PEOPLE are a separate matter. Meetings, callbacks and consultations WITH A HUMAN "
        f"only happen during working hours: {readable_hours}."
    )
    blocks.append(
        f"Right now it is {now.strftime('%A, %d %B %Y, %H:%M')} local time "
        f"({now.tzname()}, UTC offset {offset_fmt}). Human staff are "
        f"{'available now' if is_open else 'not available now'}. "
        f"The nearest slot with a person: {next_slot}."
    )
    blocks.append(
        "You may use the calendar at ANY hour, including right now. Only the slot itself "
        "must fall inside working hours. When the caller asks for a meeting, a callback "
        "or a person, book it — do not tell them to call back."
    )
    blocks.append(
        f"CRITICAL: every date you pass to a tool must be local time with the offset "
        f"{offset_fmt}. Example for tomorrow at 10:00 local: "
        f"2026-01-01T10:00:00{offset_fmt}. Never write local clock numbers with +00:00."
    )
    blocks.append("</AVAILABILITY>")
    blocks.append("")

    blocks.append("<CALLER_MEMORY>")
    blocks.append(f"CORE: {memory.get('core') or '-'}")
    blocks.append(f"RECENT: {memory.get('short') or '-'}")
    blocks.append(f"LONG TERM: {memory.get('long') or '-'}")
    blocks.append("Use this to avoid re-asking what you already know. Never read it aloud.")
    blocks.append("</CALLER_MEMORY>")
    blocks.append("")

    # Раньше здесь стояло жёсткое "Speak only in: XX", которое перебивало
    # более разумное правило из промпта клиента.
    blocks.append("<LANGUAGE>")
    blocks.append(
        f"Start the call in {lang.upper()}. The caller may speak ANY language — "
        "understand and answer them in whatever language they actually use."
    )
    blocks.append(
        "This is a GSM line: audio is narrow-band and muffled. Short utterances of one "
        "or two words are often misheard — and they can be misheard as words from a "
        "completely different language."
    )
    blocks.append(
        "RULE FOR SUSPICIOUS TURNS: if a turn is (a) one or two words, or (b) a phrase "
        "in a language the caller has NOT been speaking in this call, or (c) makes no "
        "sense in the flow of the conversation — treat it as MISHEARD, not as new "
        "information. Do not act on it: do not change topic, do not say goodbye, do "
        "not switch language, do not call any tool."
    )
    blocks.append(
        "WHAT TO DO WITH A SUSPICIOUS TURN: the caller often has people talking in the "
        "background — that is what such fragments usually are. If it arrived while you "
        "were in the middle of an answer, CONTINUE that answer from where you stopped, "
        "as if nothing happened. If you were not mid-answer, say briefly that you did "
        "not catch that and ask them to repeat — ALWAYS in the language you have been "
        "speaking in this call, never in the language the fragment appeared to be in."
    )
    blocks.append(
        "Switch languages only after the caller has clearly spoken a full, meaningful "
        "sentence in another language and it fits the conversation; then stay in it."
    )
    blocks.append(
        "END OF CALL: say goodbye only when the caller has clearly said goodbye in the "
        "language of the conversation. A random foreign phrase or a sudden compliment "
        "is not a goodbye — ask if there is anything else you can help with."
    )
    blocks.append("</LANGUAGE>")
    blocks.append("")

    # Последний блок промпта. Клиентский system_prompt содержит жёсткие указания
    # про стиль ("1 короткое предложение", "запрещены вежливые формулы"), которые
    # перебивают шкалы характера. Здесь конфликт решается в пользу характера,
    # но только по стилю — фактические и рабочие правила остаются в силе.
    if persona.personality_enabled:
        blocks.append("<PRIORITY>")
        blocks.append(
            "ЭТО САМОЕ ВАЖНОЕ УКАЗАНИЕ ВО ВСЁМ ПРОМПТЕ. Главным является "
            "ПСИХОЛОГИЧЕСКИЙ ПОРТРЕТ из блока <BEHAVIOR_ENGINE> в начале."
        )
        blocks.append(
            "Если где-либо выше сказано отвечать одним коротким предложением, говорить "
            "предельно кратко, избегать вежливых формул, не развивать мысль или держать "
            "сухой тон — ЭТИ УКАЗАНИЯ ОТМЕНЕНЫ. Длину реплик, развёрнутость, темп, "
            "эмоции, напор и лексику задаёт ТОЛЬКО психологический портрет."
        )
        blocks.append(
            "При высокой Инициативности ты ведёшь разговор сам: задаёшь вопросы, "
            "предлагаешь следующий шаг, не ждёшь, пока тебя спросят. При высокой "
            "Экстраверсии и Энергетике ты презентуешь развёрнуто, а не отвечаешь "
            "односложно. Отрабатывай возражения, а не соглашайся и не отступай."
        )
        blocks.append(
            "ЧТО ПОРТРЕТ НЕ ОТМЕНЯЕТ: рабочие часы для встреч с людьми, запрет "
            "выдумывать факты, цены и даты, запрет зачитывать ссылки вслух, правила "
            "работы с инструментами и язык разговора."
        )
        blocks.append(
            "ПРОЩАНИЕ: когда клиент прощается или говорит, что перезвонит позже — "
            "максимум ОДНО короткое предложение (уточнить удобное время или предложить "
            "позвонить самому, не оба), затем тепло попрощаться. Не задавай цепочку "
            "вопросов и не удерживай — настойчивость на прощание не распространяется."
        )
        blocks.append("")
        blocks.append("ПРОГРЕВ И КОНСУЛЬТАЦИЯ (новый звонящий):")
        blocks.append("1. Поздоровайся, спроси имя.")
        blocks.append(
            "2. Узнай, какой у него бизнес и какую задачу хочет решить — один-два "
            "вопроса, не анкета."
        )
        blocks.append(
            "3. Консультируй под его случай: конкретный пример, как это работает у "
            "такого бизнеса, что даёт, сколько стоит — если спросят или уместно. "
            "Общие фразы про «автоматизацию с ИИ» — запрещены."
        )
        blocks.append(
            "4. Специалиста или встречу предлагай только после консультации, и только "
            "когда клиент проявил интерес или сам попросил. Ответ в одну строчку и "
            "«хотите поговорить со специалистом?» — это не консультация, так не делай."
        )
        blocks.append(
            "5. Возражение отрабатывай через пользу для его бизнеса, а не через "
            "передачу человеку."
        )
        blocks.append(
            "Для известного клиента — продолжай по памяти с того места, где остановились."
        )
        blocks.append("</PRIORITY>")

    return "\n".join(b for b in blocks if b is not None)


def build_vad_params() -> GeminiVADParams:
    end = (
        types.EndSensitivity.END_SENSITIVITY_HIGH
        if VAD_END_SENSITIVITY == "high"
        else types.EndSensitivity.END_SENSITIVITY_LOW
    )
    start = (
        types.StartSensitivity.START_SENSITIVITY_HIGH
        if VAD_START_SENSITIVITY == "high"
        else types.StartSensitivity.START_SENSITIVITY_LOW
    )
    try:
        return GeminiVADParams(
            start_sensitivity=start,
            end_sensitivity=end,
            prefix_padding_ms=VAD_PREFIX_PADDING_MS,
            silence_duration_ms=VAD_SILENCE_MS,
            disabled=False,
        )
    except TypeError as exc:
        log.warning("GeminiVADParams: %s — using end/silence only", exc)
        return GeminiVADParams(
            end_sensitivity=end, silence_duration_ms=VAD_SILENCE_MS, disabled=False
        )


def build_tools(client_data: dict, readable_hours: str) -> list[dict]:
    tools = [
        {
            "name": "save_lead",
            "description": "Salvează datele de contact și motivul apelului în CRM.",
            "parameters": {
                "type": "object",
                "properties": {
                    "client_name": {"type": "string"},
                    "client_phone": {
                        "type": "string",
                        "description": (
                            "Doar dacă clientul cere să fie contactat pe ALT număr. "
                            "Numărul de la care sună este deja cunoscut — nu-l întreba."
                        ),
                    },
                    "request_summary": {"type": "string"},
                },
                "required": ["client_name", "request_summary"],
            },
        },
        {
            "name": "send_sms",
            "description": "Trimite un SMS clientului (linkuri, adrese, confirmări).",
            "parameters": {
                "type": "object",
                "properties": {"phone": {"type": "string"}, "message": {"type": "string"}},
                "required": ["phone", "message"],
            },
        },
        {
            "name": "end_call",
            "description": (
                "Încheie apelul. Folosește DOAR după ce clientul și-a luat rămas-bun clar "
                "și fără echivoc. Dacă nu ai înțeles ce a spus, cere-i să repete — "
                "NU închide. OBLIGATORIU: spune o scurtă frază de rămas-bun înainte."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    ]
    if client_data.get("google_calendar_id"):
        tools.append(
            {
                "name": "Booking_tool",
                "description": (
                    "Gestionează calendarul pentru întâlniri, apeluri inverse și consultații "
                    "CU UN OM. Poate fi folosit la ORICE oră, inclusiv noaptea — doar slotul "
                    f"programat trebuie să fie în intervalul: {readable_hours}. "
                    "NU folosi pentru consultația pe care o oferi tu însuți — aceea o dai "
                    "imediat, oricând. Pentru 'book' transmite obligatoriu client_name, "
                    "phone, request_summary, start_time și end_time."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["check", "book", "cancel"]},
                        "phone": {"type": "string"},
                        "client_name": {"type": "string"},
                        "request_summary": {"type": "string"},
                        "start_time": {"type": "string", "description": "ISO 8601 cu fus orar"},
                        "end_time": {"type": "string", "description": "ISO 8601 cu fus orar"},
                    },
                    "required": ["action"],
                },
            }
        )
    return tools


# =============================================================================
# 11. FASTAPI
# =============================================================================

security_scheme = HTTPBearer()


def verify_token(credentials: HTTPAuthorizationCredentials = Security(security_scheme)) -> str:
    if not API_SECRET_TOKEN:
        raise HTTPException(status_code=500, detail="Server config error: API token missing")
    if credentials.credentials != API_SECRET_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid authorization token")
    return credentials.credentials


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    global _http
    _http = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=3.0))
    server = await asyncio.start_server(handle_asterisk_conn, AUDIOSOCKET_HOST, AUDIOSOCKET_PORT)
    serve_task = asyncio.create_task(server.serve_forever())
    log.info("AudioSocket server listening on %s:%s", AUDIOSOCKET_HOST, AUDIOSOCKET_PORT)
    try:
        yield
    finally:
        serve_task.cancel()
        server.close()
        with contextlib.suppress(Exception):
            await server.wait_closed()
        if _http:
            await _http.aclose()
        if redis_client:
            with contextlib.suppress(Exception):
                await redis_client.aclose()


app = FastAPI(title="Lab Upgrade GSM Voice Agent", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS or ["https://dashboard.labupgrade.ai"],
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "active_calls": sum(_calls_per_client.values()),
        "redis": bool(redis_client),
    }


async def prewarm_call_context(client_id: str, phone: str) -> dict:
    """
    Готовит всё, что нужно боту, ПОКА идут гудки: клиента, персонажа, контакт
    звонящего и его память. К моменту Answer() ждать уже нечего.
    """
    client_data, persona_row = await asyncio.gather(
        get_client_data(client_id), get_persona_row(client_id)
    )
    if not client_data:
        return {}

    contact, (memory, time_context) = await asyncio.gather(
        lookup_contact(client_data, client_id, phone),
        get_caller_memory(client_id, phone),
    )

    # Токены CRM нужны только для поиска выше — в Redis их не кладём.
    safe_client_data = {k: v for k, v in client_data.items() if k != "crm_config"}

    return {
        "client_id": client_id,
        "phone": phone,
        "client_data": safe_client_data,
        "persona_row": persona_row,
        "contact": contact,
        "memory": memory,
        "time_context": time_context,
        "direction": "inbound",
        "prewarmed_at": time.time(),
    }


@app.get("/get_uuid")
async def get_client_uuid(
    sip_login: str | None = None,
    sip_login_gsm: str | None = None,
    phone: str | None = None,
    ani: str | None = None,
    from_hdr: str | None = None,
    all_id: str | None = None,
    token: str | None = None,
):
    """
    Вызывается диалпланом Asterisk ДО ответа на звонок, во время гудков.
    Возвращает уникальный id ЭТОГО звонка (а не id тенанта), а весь контекст
    кладёт в Redis. Уникальный id заодно чинит две вещи: одновременные звонки
    в одну компанию больше не путают номера и не пишут запись в один файл.
    """
    if INTERNAL_TOKEN and token != INTERNAL_TOKEN:
        return Response(content="error", media_type="text/plain", status_code=401)

    identifier = sip_login_gsm or sip_login
    if not identifier:
        return Response(content="error", media_type="text/plain")

    rows = await sb_select(
        "bot_channels", {"identifier": f"eq.{identifier}", "select": "client_id,project_id"}
    )
    if not rows:
        return Response(content="not_found", media_type="text/plain")

    client_id = str(rows[0].get("client_id"))
    project_id = str(rows[0].get("project_id") or "")
    formatted = format_phone(extract_real_phone(ani, all_id, from_hdr, phone))

    # Без Redis работаем по-старому: отдаём client_id, бот резолвит сам.
    if not redis_client:
        log.warning("redis unavailable — falling back to client_id as AudioSocket id")
        return Response(content=client_id, media_type="text/plain")

    call_uuid = str(uuid.uuid4())
    try:
        ctx = await prewarm_call_context(client_id, formatted)
        if not ctx:
            return Response(content="not_found", media_type="text/plain")
        ctx["project_id"] = project_id
        await redis_client.setex(
            f"call_context:{call_uuid}", 300, json.dumps(ctx, default=str)
        )
        log.info(
            "prewarmed call %s for client=%s phone=%s contact=%s",
            call_uuid[:8],
            client_id,
            formatted,
            "found" if ctx["contact"].get("found") else "unknown",
        )
        return Response(content=call_uuid, media_type="text/plain")
    except Exception as exc:
        log.error("prewarm failed (%s) — falling back to client_id", exc)
        return Response(content=client_id, media_type="text/plain")


class OutboundCallRequest(BaseModel):
    client_id: str
    target_phone: str
    call_purpose: str
    client_name: str = "client"
    custom_context: str = ""
    lang: str = DEFAULT_LANG
    project_id: str = ""


@app.post("/api/dial")
async def initiate_outbound_call(req: OutboundCallRequest, _: str = Depends(verify_token)):
    if not ASTERISK_ARI_URL:
        raise HTTPException(status_code=500, detail="ARI is not configured")

    call_uuid = str(uuid.uuid4())
    formatted_phone = format_phone(req.target_phone)
    if formatted_phone == "Necunoscut":
        raise HTTPException(status_code=400, detail="Invalid target_phone")

    if redis_client:
        with contextlib.suppress(Exception):
            # Тот же прогрев, что у входящего: карточка, память, персонаж — заранее.
            ctx = await prewarm_call_context(req.client_id, formatted_phone) or {}
            contact_name = (ctx.get("contact") or {}).get("name") or ""
            ctx.update(
                {
                    "client_id": req.client_id,
                    "target_phone": formatted_phone,
                    "client_name": req.client_name if req.client_name != "client" else (contact_name or "client"),
                    "call_purpose": req.call_purpose,
                    "custom_context": req.custom_context,
                    "lang": req.lang,
                    "project_id": req.project_id,
                    "direction": "outbound",
                }
            )
            await redis_client.setex(
                f"call_context:{call_uuid}", 600, json.dumps(ctx, default=str)
            )

    payload = {
        "endpoint": f"PJSIP/{''.join(filter(str.isdigit, formatted_phone))}{ASTERISK_ENDPOINT_SUFFIX}",
        "extension": "s",
        "context": "outbound-ai",
        "priority": 1,
        "variables": {"CALL_UUID": call_uuid},
    }
    try:
        resp = await http().post(
            ASTERISK_ARI_URL,
            json=payload,
            auth=(ASTERISK_ARI_USER or "", ASTERISK_ARI_PASS or ""),
            timeout=10.0,
        )
        if resp.status_code not in (200, 201):
            if redis_client:
                with contextlib.suppress(Exception):
                    await redis_client.delete(f"call_context:{call_uuid}")
            return {"status": "error", "details": resp.text}
        return {"status": "dialing", "call_uuid": call_uuid, "target": formatted_phone}
    except Exception as exc:
        if redis_client:
            with contextlib.suppress(Exception):
                await redis_client.delete(f"call_context:{call_uuid}")
        return {"status": "error", "message": str(exc)}

# =============================================================================
# WEB VOICE — голосовой виджет на сайте.
# Тот же звонок, что и по GSM: персонаж, память, инструменты, архивариус,
# подпись, биллинг. Отличается только транспорт (браузер) и ключ человека
# (visitor_id из браузера вместо номера телефона). Виджет опознаётся по ключу канала
# из bot_channels (platform = web), как страница Facebook опознаётся по page id.
# =============================================================================

WEB_OUTPUT_SAMPLE_RATE = _env_int("WEB_OUTPUT_SAMPLE_RATE", 24000)  # виджет играет 24 кГц


class WebAudioMixer:
    """Сводит микрофон посетителя (16 кГц) и голос бота (24 кГц) в один WAV 24 кГц моно."""

    def __init__(self, output_path: str) -> None:
        self.output_path = output_path
        self.target_rate = WEB_OUTPUT_SAMPLE_RATE
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

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, InputAudioRawFrame):
            with contextlib.suppress(Exception):
                self.mixer.add_user_audio(frame)
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


def _time_context_from(last_at: Any) -> str:
    if not last_at:
        return "first_time"
    try:
        last = dt.datetime.fromisoformat(str(last_at).replace("Z", "+00:00"))
        delta = (dt.datetime.now(dt.timezone.utc) - last).total_seconds() / 60
        return "very_recent" if delta < 15 else ("same_day" if delta < 1440 else "new_day")
    except ValueError:
        return "first_time"


async def get_web_visitor_context(client_id: str, visitor_id: str) -> tuple[dict, dict, str]:
    """Карточка и память посетителя по идентификатору браузера (person_memory_get_web)."""
    contact: dict = {"found": False, "name": "", "lang": "", "phone": ""}
    memory: dict = {"core": "", "short": "", "long": ""}
    if not visitor_id:
        return contact, memory, "first_time"
    try:
        rows = await sb_rpc(
            "person_memory_get_web",
            {"p_client_id": client_id, "p_web_id": visitor_id},
            timeout=2.5,
        )
    except Exception as exc:
        log.warning("web visitor lookup failed: %s", exc)
        return contact, memory, "first_time"
    if not rows:
        return contact, memory, "first_time"
    rec = rows[0]
    contact = {
        "found": bool(rec.get("end_client_id")),
        "name": rec.get("name") or "",
        "lang": rec.get("language") or "",
        "phone": rec.get("phone") or "",
    }
    memory = {
        "core": rec.get("core_identity") or "",
        "short": rec.get("short_term_context") or "",
        "long": rec.get("long_term_context") or "",
    }
    return contact, memory, _time_context_from(rec.get("last_interaction_at"))


@app.websocket("/ws")
async def web_voice_endpoint(
    websocket: WebSocket,
    key: str = Query(""),
    visitor_id: str = Query(""),
) -> None:
    call_id = uuid.uuid4().hex[:8]
    clog = logging.LoggerAdapter(log, {})
    key = re.sub(r"[^A-Za-z0-9_\-]", "", key or "")[:64]
    visitor_id = re.sub(r"[^A-Za-z0-9_\-]", "", visitor_id or "")[:64]
    clog.info("[%s] incoming WEB voice session key=%s visitor=%s", call_id, key[:12], visitor_id[:12])

    if not key:
        await websocket.close(code=1008, reason="Missing widget key")
        return

    # Виджет — такой же канал, как страница Facebook или номер WhatsApp:
    # строка в bot_channels (platform = web) по ключу даёт клиента и проект.
    try:
        channel_rows = await sb_select(
            "bot_channels",
            {"identifier": f"eq.{key}", "platform": "eq.web", "select": "client_id,project_id", "limit": "1"},
            timeout=2.5,
        )
    except Exception as exc:
        clog.error("[%s] widget channel lookup failed: %s", call_id, exc)
        await websocket.close(code=1011, reason="Channel lookup failed")
        return
    if not channel_rows or not channel_rows[0].get("client_id"):
        clog.warning("[%s] unknown widget key %s", call_id, key[:12])
        await websocket.close(code=1008, reason="Unknown widget key")
        return
    client_id = str(channel_rows[0]["client_id"])
    project_id = str(channel_rows[0].get("project_id") or "")

    if _call_semaphore.locked():
        clog.warning("[%s] concurrency limit reached, rejecting web session", call_id)
        await websocket.close(code=1013, reason="Busy")
        return

    context: Optional[LLMContext] = None
    usage = UsageAggregator()
    activity: ActivityProbe | None = None
    counted_client: Optional[str] = None
    system_prompt_tokens = 0
    system_instructions_length = 0
    started_at = dt.datetime.now(dt.timezone.utc)
    start_ts = time.time()
    tz_name = DEFAULT_TZ
    client_name = "client"
    is_known_caller = False
    learned_phone = ""
    known_phone = ""
    caller_memory: dict = {"core": "", "short": "", "long": ""}
    wav_path = f"/tmp/web_{call_id}.wav"
    mixer = WebAudioMixer(wav_path)

    async with _call_semaphore:
        try:
            client_data, persona_row = await asyncio.gather(
                get_client_data(client_id), get_persona_row(client_id)
            )
            if not client_data:
                clog.warning("[%s] client %s not found", call_id, client_id)
                await websocket.close(code=1008, reason="Client not found")
                return

            # Подписка проверяется по статусу веб-канала проекта — как у текстовых ботов.
            web_status = ""
            with contextlib.suppress(Exception):
                prow = await sb_select(
                    "saas_projects",
                    {"id": f"eq.{project_id}", "select": "web_subs_status", "limit": "1"},
                    timeout=2.5,
                )
                if prow:
                    web_status = str(prow[0].get("web_subs_status") or "").strip().lower()
            if web_status not in ("active", "trial"):
                clog.info("[%s] web channel inactive (status=%r) for project %s", call_id, web_status, project_id)
                await websocket.close(code=1008, reason="Subscription inactive")
                return

            if _calls_per_client.get(client_id, 0) >= MAX_CALLS_PER_CLIENT:
                clog.warning("[%s] per-client limit hit for %s", call_id, client_id)
                await websocket.close(code=1013, reason="Busy")
                return
            _calls_per_client[client_id] = _calls_per_client.get(client_id, 0) + 1
            counted_client = client_id

            persona = Persona.from_row(persona_row)
            contact, caller_memory, time_context = await get_web_visitor_context(client_id, visitor_id)

            tz_name = client_data.get("timezone") or DEFAULT_TZ
            hours = parse_working_hours(client_data.get("working_hours"))
            now = dt.datetime.now(tz_for(tz_name))

            client_name = (contact.get("name") or "").strip()
            call_lang = contact.get("lang") or persona.language or DEFAULT_LANG
            is_known_caller = bool(client_name)
            if not is_known_caller:
                client_name = "client"
            known_phone = contact.get("phone") or ""

            system_prompt = build_system_prompt(
                client_data,
                persona,
                caller_memory,
                call_lang,
                now,
                hours,
                caller_phone=known_phone or "Necunoscut",
                caller_name=client_name if is_known_caller else "",
            )
            system_prompt += (
                "\n\nCHANNEL: this is a voice chat from the company's WEBSITE, not a phone call. "
                "You do not know the visitor's phone number unless it is stated above or the visitor gives it. "
                "To hand over to a manager or to book, ask for a phone number and use save_lead."
            )
            _, readable_hours = office_state(hours, now)
            tools = [{"function_declarations": build_tools(client_data, readable_hours)}]
            full_system_text = system_prompt + json.dumps(tools, ensure_ascii=False)
            system_instructions_length = len(full_system_text)
            system_prompt_tokens = estimate_tokens(full_system_text)

            clog.info(
                "[%s] WEB client=%s persona=%s lang=%s visitor=%s caller=%s memory=%s sys=%d tok",
                call_id, client_id, persona.persona_name, call_lang, visitor_id[:12],
                client_name if is_known_caller else "unknown",
                "yes" if any(caller_memory.values()) else "no",
                system_prompt_tokens,
            )

            await websocket.accept()

            transport = FastAPIWebsocketTransport(
                websocket=websocket,
                params=FastAPIWebsocketParams(
                    audio_in_enabled=True,
                    audio_out_enabled=True,
                    audio_out_sample_rate=WEB_OUTPUT_SAMPLE_RATE,
                    add_wav_header=False,
                    serializer=RawPCMFrameSerializer(),
                ),
            )

            context = LLMContext(messages=[])
            context_aggregator = LLMContextAggregatorPair(
                context=context,
                realtime_service_mode=True,
                user_params=LLMUserAggregatorParams(
                    user_turn_strategies=ExternalUserTurnStrategies()
                ),
            )

            llm = GeminiLiveLLMService(
                api_key=GEMINI_API_KEY,
                tools=tools,
                settings=GeminiLiveLLMService.Settings(
                    model=GEMINI_MODEL,
                    voice=persona.voice_model,
                    system_instruction=system_prompt,
                    vad=build_vad_params(),
                ),
            )

            task: Optional[PipelineTask] = None
            saved_lead_hashes: set[str] = set()
            tg_chat = client_data.get("tg_chat_id_notify")
            company = client_data.get("company_name") or "Companie"

            async def call_n8n(path: str, params: dict, arguments: dict, timeout: float):
                url = f"{N8N_BASE_URL}/{path}"
                resp = await http().post(url, params=params, json=arguments, timeout=timeout)
                resp.raise_for_status()
                return resp.json()

            async def process_save_lead(fn: FunctionCallParams):
                nonlocal learned_phone
                phone_arg = str(fn.arguments.get("client_phone") or "").strip()
                if phone_arg:
                    learned_phone = phone_arg
                elif known_phone:
                    fn.arguments["client_phone"] = known_phone
                digest = hashlib.sha1(
                    json.dumps(fn.arguments, sort_keys=True, ensure_ascii=False).encode()
                ).hexdigest()
                if digest in saved_lead_hashes:
                    await fn.result_callback({"status": "success", "message": "Deja salvat."})
                    return
                try:
                    result = await call_n8n(
                        "save_lead",
                        {"client_id": client_id, "tg_chat_id": tg_chat or ""},
                        fn.arguments,
                        5.0,
                    )
                    saved_lead_hashes.add(digest)
                    await fn.result_callback(result)
                except asyncio.CancelledError:
                    with contextlib.suppress(Exception):
                        await fn.result_callback({"status": "cancelled"})
                    raise
                except Exception as exc:
                    await send_tg_alert(
                        tg_chat,
                        f"⚠️ <b>Eroare API (save_lead)</b>\n🏢 {company}\n🔧 <code>{exc}</code>",
                    )
                    await fn.result_callback({"error": f"Eroare CRM: {exc}"})

            async def process_booking(fn: FunctionCallParams):
                nonlocal learned_phone
                phone_arg = str(fn.arguments.get("phone") or "").strip()
                if phone_arg:
                    learned_phone = phone_arg
                try:
                    result = await call_n8n(
                        "booking",
                        {
                            "client_id": client_id,
                            "google_calendar_id": client_data.get("google_calendar_id") or "",
                        },
                        fn.arguments,
                        10.0,
                    )
                    await fn.result_callback(result)
                except asyncio.CancelledError:
                    with contextlib.suppress(Exception):
                        await fn.result_callback({"status": "cancelled"})
                    raise
                except Exception as exc:
                    await send_tg_alert(
                        tg_chat,
                        f"⚠️ <b>Eroare API (Booking_tool)</b>\n🏢 {company}\n🔧 <code>{exc}</code>",
                    )
                    await fn.result_callback({"status": "error", "message": str(exc)})

            async def process_sms(fn: FunctionCallParams):
                try:
                    await call_n8n("send_sms", {"client_id": client_id}, fn.arguments, 5.0)
                    await fn.result_callback({"status": "success", "message": "SMS trimis"})
                except asyncio.CancelledError:
                    with contextlib.suppress(Exception):
                        await fn.result_callback({"status": "cancelled"})
                    raise
                except Exception as exc:
                    await send_tg_alert(
                        tg_chat,
                        f"⚠️ <b>Eroare API (send_sms)</b>\n🏢 {company}\n🔧 <code>{exc}</code>",
                    )
                    await fn.result_callback({"status": "error", "message": str(exc)})

            async def process_end_call(fn: FunctionCallParams):
                elapsed = time.time() - start_ts
                if elapsed < MIN_SECONDS_BEFORE_END_CALL:
                    await fn.result_callback(
                        {
                            "status": "rejected",
                            "message": (
                                "Nu închide acum. Clientul nu și-a luat rămas-bun clar. "
                                "Cere-i să repete și continuă conversația."
                            ),
                        }
                    )
                    return
                await fn.result_callback({"status": "success", "message": "Call ended"})

                async def delayed_end():
                    await asyncio.sleep(3.5)
                    if task:
                        await task.queue_frames([CancelFrame()])

                asyncio.create_task(delayed_end())

            llm.register_function("save_lead", process_save_lead)
            llm.register_function("send_sms", process_sms)
            llm.register_function("end_call", process_end_call)
            if client_data.get("google_calendar_id"):
                llm.register_function("Booking_tool", process_booking)

            recovery = InterruptionRecoveryProcessor(context, delay=RECOVERY_DELAY_S)
            activity = ActivityProbe()
            user_catcher = WebUserAudioCatcher(mixer)
            ai_catcher = WebAIAudioCatcher(mixer)

            pipeline = Pipeline(
                [
                    transport.input(),
                    user_catcher,
                    context_aggregator.user(),
                    llm,
                    usage,
                    recovery,
                    activity,
                    ai_catcher,
                    transport.output(),
                    context_aggregator.assistant(),
                ]
            )

            task = PipelineTask(
                pipeline,
                params=PipelineParams(
                    allow_interruptions=True,
                    idle_timeout=IDLE_TIMEOUT_SECONDS,
                    enable_metrics=True,
                    enable_usage_metrics=True,
                ),
            )
            recovery.task = task

            # Браузер закрыл соединение (кнопка «стоп», закрытая вкладка) — завершаем сразу,
            # не дожидаясь сторожа мёртвого эфира.
            @transport.event_handler("on_client_disconnected")
            async def _on_web_client_disconnected(_transport, _client):
                clog.info("[%s] browser closed the connection", call_id)
                if task:
                    with contextlib.suppress(Exception):
                        await task.queue_frames([CancelFrame()])

            lang_names = {"ro": "РУМЫНСКОМ", "ru": "РУССКОМ", "en": "АНГЛИЙСКОМ"}
            lang_word = lang_names.get(call_lang, call_lang.upper())
            who = client_name if is_known_caller else "посетитель сайта"
            name_rule = (
                f"Обращайся к нему по имени ({client_name}) один раз в начале."
                if is_known_caller
                else "Имени ты не знаешь. Спроси, как обращаться, в первой-второй "
                "реплике, один раз, дальше — по имени. НИКОГДА не выдумывай имя."
            )
            lang_rule = (
                f"ПЕРВАЯ ЖЕ ТВОЯ ФРАЗА ДОЛЖНА БЫТЬ НА {lang_word} ЯЗЫКЕ. "
                "Это указание написано по-русски, но отвечать на нём НЕ НАДО."
            )
            notice_rule = "В первой фразе коротко предупреди, что разговор может записываться."

            if time_context == "very_recent":
                greeting = (
                    f"SYSTEM EVENT: {who} вернулся в голосовой чат на сайте спустя пару минут. "
                    f"Не здоровайся заново. {lang_rule} {name_rule} Продолжай суть."
                )
            elif time_context == "same_day":
                greeting = (
                    f"SYSTEM EVENT: {who} открыл голосовой чат на сайте повторно за сегодня. "
                    f"{lang_rule} {name_rule} Опирайся на память RECENT. Веди разговор сам, согласно портрету."
                )
            else:
                greeting = (
                    f"SYSTEM EVENT: {who} открыл голосовой чат на сайте компании. {lang_rule} "
                    f"{notice_rule} {name_rule} Начни диалог согласно портрету. "
                    "Если есть память RECENT, не переспрашивай известное."
                )

            context.add_message({"role": "user", "content": greeting})
            await task.queue_frames([LLMRunFrame()])

            runner = PipelineRunner()
            dead_air = asyncio.create_task(dead_air_watchdog(call_id, activity, task))
            try:
                await asyncio.wait_for(runner.run(task), timeout=MAX_CALL_SECONDS)
            except asyncio.TimeoutError:
                clog.warning("[%s] max call duration reached, terminating", call_id)
                with contextlib.suppress(Exception):
                    await task.queue_frames([CancelFrame()])
            finally:
                dead_air.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await dead_air

        except (WebSocketDisconnect, ConnectionResetError, asyncio.TimeoutError) as exc:
            clog.info("[%s] web session closed: %s", call_id, type(exc).__name__)
        except Exception as exc:
            clog.exception("[%s] web session failed: %s", call_id, exc)
        finally:
            if counted_client:
                _calls_per_client[counted_client] = max(
                    0, _calls_per_client.get(counted_client, 1) - 1
                )
                if _calls_per_client[counted_client] == 0:
                    _calls_per_client.pop(counted_client, None)

            with contextlib.suppress(Exception):
                mixer.close()
            with contextlib.suppress(Exception):
                if websocket.client_state == WebSocketState.CONNECTED:
                    await websocket.close()

            last_ts = activity.last_activity_ts if activity else time.time()
            duration = int(max(0.0, last_ts - start_ts))
            clog.info("[%s] web session finished, %ss, turns=%s", call_id, duration, usage.turns)

            if context is not None and client_id:
                transcript, user_replies = build_transcript(context.messages)
                if transcript:
                    clog.info("[%s] ДИАЛОГ:\n%s", call_id, transcript)
                text_in, audio_in, cost = usage.cost(system_prompt_tokens)
                usage_stats = {
                    "started_at": started_at.isoformat(),
                    "ended_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "duration_seconds": duration,
                    "turns": usage.turns,
                    "input_tokens": usage.prompt_tokens,
                    "output_tokens": usage.completion_tokens,
                    "total_cost_usd": round(cost, 6),
                }

                async def post_processing() -> None:
                    await asyncio.sleep(0.5)
                    try:
                        if user_replies == 0:
                            call_status, audio_url = "inbound_dropped", ""
                        else:
                            call_status = "completed"
                            audio_url = await upload_audio_to_supabase(client_id, wav_path) or ""
                        await run_archivist_and_notify_n8n(
                            client_id,
                            learned_phone or known_phone,
                            client_name,
                            caller_memory,
                            transcript,
                            audio_url,
                            system_instructions_length,
                            "inbound",
                            call_status,
                            tz_name,
                            usage_stats,
                            audio_path=wav_path,
                            project_id=project_id or "",
                            web_id=visitor_id,
                            platform="web_voice",
                        )
                    except Exception as exc:
                        log.error("[%s] web post-processing failed: %s", call_id, exc)
                    finally:
                        with contextlib.suppress(Exception):
                            if await asyncio.to_thread(os.path.exists, wav_path):
                                await asyncio.to_thread(os.remove, wav_path)
                        gc.collect()

                asyncio.create_task(post_processing())
            else:
                with contextlib.suppress(Exception):
                    if os.path.exists(wav_path):
                        os.remove(wav_path)
                gc.collect()


@app.get("/api/persona/{client_id}/preview")
async def persona_preview(client_id: str, lang: str = DEFAULT_LANG, _: str = Depends(verify_token)):
    """Дашборд показывает, во что превращаются ползунки характера."""
    persona = await get_persona(client_id)
    block = build_personality_block(persona, lang)
    return {
        "persona_name": persona.persona_name,
        "traits": {t: getattr(persona, t) for t in TRAITS},
        "personality_block": block,
        "estimated_tokens": estimate_tokens(block),
        "voice_model": persona.voice_model,
    }


@app.post("/api/persona/{client_id}/invalidate")
async def persona_invalidate(client_id: str, _: str = Depends(verify_token)):
    if redis_client:
        with contextlib.suppress(Exception):
            await redis_client.delete(f"persona:{client_id}")
    return {"status": "ok"}


# =============================================================================
# 12. ГЛАВНЫЙ ОБРАБОТЧИК ЗВОНКА
# =============================================================================


async def handle_asterisk_conn(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> None:
    call_id = uuid.uuid4().hex[:8]
    clog = logging.LoggerAdapter(log, {})
    clog.info("[%s] incoming AudioSocket connection", call_id)

    session_uuid = "unknown"
    client_id: Optional[str] = None
    target_phone = "Necunoscut"
    client_name = "client"
    is_outbound = False
    tz_name = DEFAULT_TZ
    caller_memory: dict = {"core": "", "short": "", "long": ""}
    context: Optional[LLMContext] = None
    usage = UsageAggregator()
    system_prompt_tokens = 0
    system_instructions_length = 0
    started_at = dt.datetime.now(dt.timezone.utc)
    start_ts = time.time()
    activity: ActivityProbe | None = None
    counted_client: Optional[str] = None
    socket: Optional[AsteriskAudioSocket] = None

    if _call_semaphore.locked():
        clog.warning("[%s] concurrency limit reached, rejecting", call_id)
        with contextlib.suppress(Exception):
            writer.close()
        return

    async with _call_semaphore:
        try:
            # --- handshake: Asterisk присылает UUID звонка ---
            header = await asyncio.wait_for(reader.readexactly(3), timeout=5.0)
            payload_len = int.from_bytes(header[1:], "big")
            uuid_bytes = await asyncio.wait_for(reader.readexactly(payload_len), timeout=5.0)
            session_uuid = str(uuid.UUID(bytes=uuid_bytes))

            # Redis отдаёт контекст и для исходящих (положил /api/dial),
            # и для входящих (положил /get_uuid во время гудков).
            call_ctx: dict = {}
            if redis_client:
                with contextlib.suppress(Exception):
                    raw = await redis_client.get(f"call_context:{session_uuid}")
                    if raw:
                        call_ctx = json.loads(raw)
                        await redis_client.delete(f"call_context:{session_uuid}")

            is_outbound = call_ctx.get("direction") == "outbound" or bool(
                call_ctx.get("call_purpose")
            )
            purpose = call_ctx.get("call_purpose", "")
            contact: dict = call_ctx.get("contact") or {}
            prewarmed = bool(call_ctx.get("prewarmed_at"))

            if call_ctx:
                client_id = call_ctx.get("client_id")
                target_phone = (
                    call_ctx.get("target_phone") or call_ctx.get("phone") or "Necunoscut"
                )
            else:
                # Старый диалплан или Redis лежал: id AudioSocket == id тенанта.
                client_id = session_uuid

            if not client_id:
                clog.warning("[%s] no client_id resolved", call_id)
                return

            # Лимит на клиента — защита от лавины звонков одного тенанта.
            if _calls_per_client.get(client_id, 0) >= MAX_CALLS_PER_CLIENT:
                clog.warning("[%s] per-client limit hit for %s", call_id, client_id)
                return
            _calls_per_client[client_id] = _calls_per_client.get(client_id, 0) + 1
            counted_client = client_id

            # Если контекст прогрет во время гудков — ни одного запроса до Answer().
            if prewarmed:
                client_data = call_ctx.get("client_data") or {}
                persona = Persona.from_row(call_ctx.get("persona_row"))
                caller_memory = call_ctx.get("memory") or caller_memory
                time_context = call_ctx.get("time_context", "first_time")
            else:
                client_data, persona = await asyncio.gather(
                    get_client_data(client_id), get_persona(client_id)
                )
                client_data = client_data or {}
                time_context = "first_time"

            if not client_data:
                clog.warning("[%s] client %s not found", call_id, client_id)
                return

            status = str(client_data.get("subscription_status_assistent", "")).strip().lower()
            if status in ("false", "0", "none", "null", "inactive", "expired", ""):
                clog.info("[%s] subscription inactive for %s", call_id, client_id)
                return

            tz_name = client_data.get("timezone") or DEFAULT_TZ
            hours = parse_working_hours(client_data.get("working_hours"))
            now = dt.datetime.now(tz_for(tz_name))

            if is_outbound:
                client_name = call_ctx.get("client_name") or ""
                call_lang = call_ctx.get("lang") or persona.language or DEFAULT_LANG
            else:
                if not prewarmed:
                    # Догоняем то, что не успели сделать во время гудков.
                    contact, (caller_memory, time_context) = await asyncio.gather(
                        lookup_contact(client_data, client_id, target_phone),
                        get_caller_memory(client_id, target_phone),
                    )
                client_name = (contact.get("name") or "").strip()
                call_lang = contact.get("lang") or persona.language or DEFAULT_LANG

            # Незнакомый входящий — сразу заводим карточку, не дожидаясь конца
            # разговора. Даже если звонок оборвётся, номер останется в базе.
            if not is_outbound and not contact.get("found"):
                asyncio.create_task(ensure_end_client(client_id, target_phone))

            # Имени может не быть — тогда обращаемся нейтрально, а не выдумываем.
            is_known_caller = bool(client_name)
            if not is_known_caller:
                client_name = "client"

            system_prompt = build_system_prompt(
                client_data,
                persona,
                caller_memory,
                call_lang,
                now,
                hours,
                caller_phone=target_phone,
                caller_name=client_name if is_known_caller else "",
            )
            _, readable_hours = office_state(hours, now)
            tools = [{"function_declarations": build_tools(client_data, readable_hours)}]
            full_system_text = system_prompt + json.dumps(tools, ensure_ascii=False)
            system_instructions_length = len(full_system_text)
            system_prompt_tokens = estimate_tokens(full_system_text)

            clog.info(
                "[%s] client=%s persona=%s lang=%s phone=%s caller=%s "
                "prewarmed=%s sys=%d tok",
                call_id,
                client_id,
                persona.persona_name,
                call_lang,
                target_phone,
                client_name if is_known_caller else "unknown",
                prewarmed,
                system_prompt_tokens,
            )

            # --- транспорт ---
            socket = AsteriskAudioSocket(reader, writer)
            transport = FastAPIWebsocketTransport(
                websocket=socket,
                params=FastAPIWebsocketParams(
                    audio_in_enabled=True,
                    audio_in_filter=build_audio_filter(),
                    audio_out_enabled=True,
                    audio_out_sample_rate=PIPELINE_SAMPLE_RATE,
                    add_wav_header=False,
                    serializer=RawPCMFrameSerializer(),
                ),
            )

            context = LLMContext(messages=[])
            context_aggregator = LLMContextAggregatorPair(
                context=context,
                realtime_service_mode=True,
                user_params=LLMUserAggregatorParams(
                    user_turn_strategies=ExternalUserTurnStrategies()
                ),
            )

            llm = GeminiLiveLLMService(
                api_key=GEMINI_API_KEY,
                tools=tools,
                settings=GeminiLiveLLMService.Settings(
                    model=GEMINI_MODEL,
                    voice=persona.voice_model,
                    system_instruction=system_prompt,
                    vad=build_vad_params(),
                ),
            )

            task: Optional[PipelineTask] = None
            saved_lead_hashes: set[str] = set()
            tg_chat = client_data.get("tg_chat_id_notify")
            company = client_data.get("company_name") or "Companie"

            async def call_n8n(path: str, params: dict, arguments: dict, timeout: float):
                url = f"{N8N_BASE_URL}/{path}"
                resp = await http().post(url, params=params, json=arguments, timeout=timeout)
                resp.raise_for_status()
                return resp.json()

            async def process_save_lead(fn: FunctionCallParams):
                # Номер звонящего известен серверу. Модель указывает его только
                # если клиент просит связаться по ДРУГОМУ номеру.
                if not str(fn.arguments.get("client_phone") or "").strip():
                    fn.arguments["client_phone"] = target_phone
                # Дедуп: модель иногда зовёт save_lead дважды на один и тот же лид.
                digest = hashlib.sha1(
                    json.dumps(fn.arguments, sort_keys=True, ensure_ascii=False).encode()
                ).hexdigest()
                if digest in saved_lead_hashes:
                    await fn.result_callback({"status": "success", "message": "Deja salvat."})
                    return
                socket.is_muted = True
                try:
                    result = await call_n8n(
                        "save_lead",
                        {"client_id": client_id, "tg_chat_id": tg_chat or ""},
                        fn.arguments,
                        5.0,
                    )
                    saved_lead_hashes.add(digest)
                    await fn.result_callback(result)
                except asyncio.CancelledError:
                    with contextlib.suppress(Exception):
                        await fn.result_callback({"status": "cancelled"})
                    raise
                except Exception as exc:
                    await send_tg_alert(
                        tg_chat,
                        f"⚠️ <b>Eroare API (save_lead)</b>\n🏢 {company}\n🔧 <code>{exc}</code>",
                    )
                    await fn.result_callback({"error": f"Eroare CRM: {exc}"})
                finally:
                    socket.is_muted = False

            async def process_booking(fn: FunctionCallParams):
                socket.is_muted = True
                try:
                    result = await call_n8n(
                        "booking",
                        {
                            "client_id": client_id,
                            "google_calendar_id": client_data.get("google_calendar_id") or "",
                        },
                        fn.arguments,
                        10.0,
                    )
                    await fn.result_callback(result)
                except asyncio.CancelledError:
                    with contextlib.suppress(Exception):
                        await fn.result_callback({"status": "cancelled"})
                    raise
                except Exception as exc:
                    await send_tg_alert(
                        tg_chat,
                        f"⚠️ <b>Eroare API (Booking_tool)</b>\n🏢 {company}\n🔧 <code>{exc}</code>",
                    )
                    await fn.result_callback({"status": "error", "message": str(exc)})
                finally:
                    socket.is_muted = False

            async def process_sms(fn: FunctionCallParams):
                socket.is_muted = True
                try:
                    await call_n8n("send_sms", {"client_id": client_id}, fn.arguments, 5.0)
                    await fn.result_callback({"status": "success", "message": "SMS trimis"})
                except asyncio.CancelledError:
                    with contextlib.suppress(Exception):
                        await fn.result_callback({"status": "cancelled"})
                    raise
                except Exception as exc:
                    await send_tg_alert(
                        tg_chat,
                        f"⚠️ <b>Eroare API (send_sms)</b>\n🏢 {company}\n🔧 <code>{exc}</code>",
                    )
                    await fn.result_callback({"status": "error", "message": str(exc)})
                finally:
                    socket.is_muted = False

            async def process_end_call(fn: FunctionCallParams):
                elapsed = time.time() - start_ts
                if elapsed < MIN_SECONDS_BEFORE_END_CALL:
                    clog.warning(
                        "[%s] end_call blocked at %.0fs — too early, likely misheard",
                        call_id,
                        elapsed,
                    )
                    await fn.result_callback(
                        {
                            "status": "rejected",
                            "message": (
                                "Nu închide acum. Clientul nu și-a luat rămas-bun clar. "
                                "Cere-i să repete și continuă conversația."
                            ),
                        }
                    )
                    return

                await fn.result_callback({"status": "success", "message": "Call ended"})

                async def delayed_end():
                    await asyncio.sleep(3.5)
                    if task:
                        await task.queue_frames([CancelFrame()])

                asyncio.create_task(delayed_end())

            llm.register_function("save_lead", process_save_lead)
            llm.register_function("send_sms", process_sms)
            llm.register_function("end_call", process_end_call)
            if client_data.get("google_calendar_id"):
                llm.register_function("Booking_tool", process_booking)

            recovery = InterruptionRecoveryProcessor(context, delay=RECOVERY_DELAY_S)
            probe = InboundAudioProbe()
            activity = ActivityProbe()

            pipeline = Pipeline(
                [
                    transport.input(),
                    probe,
                    context_aggregator.user(),
                    llm,
                    usage,
                    recovery,
                    activity,
                    transport.output(),
                    context_aggregator.assistant(),
                ]
            )

            task = PipelineTask(
                pipeline,
                params=PipelineParams(
                    allow_interruptions=True,
                    idle_timeout=IDLE_TIMEOUT_SECONDS,
                    enable_metrics=True,
                    enable_usage_metrics=True,
                ),
            )
            recovery.task = task

            lang_names = {"ro": "РУМЫНСКОМ", "ru": "РУССКОМ", "en": "АНГЛИЙСКОМ"}
            lang_word = lang_names.get(call_lang, call_lang.upper())
            who = client_name if is_known_caller else "неизвестный абонент"
            name_rule = (
                f"Обращайся к нему по имени ({client_name}) один раз в начале."
                if is_known_caller
                else "Имени ты не знаешь. Спроси, как обращаться, в первой-второй "
                "реплике, один раз, дальше — по имени. НИКОГДА не выдумывай имя."
            )
            lang_rule = (
                f"ПЕРВАЯ ЖЕ ТВОЯ ФРАЗА ДОЛЖНА БЫТЬ НА {lang_word} ЯЗЫКЕ. "
                "Это указание написано по-русски, но отвечать на нём НЕ НАДО."
            )

            if is_outbound:
                greeting = (
                    f"SYSTEM EVENT: {who} ответил на твой исходящий звонок. "
                    f"Цель звонка: {purpose}. {lang_rule} {name_rule} "
                    "Начни разговор строго в своём характере по портрету."
                )
            elif time_context == "very_recent":
                greeting = (
                    f"SYSTEM EVENT: {who} перезвонил спустя пару минут. Не здоровайся заново. "
                    f"{lang_rule} {name_rule} Скажи, что связь прервалась, и продолжай суть."
                )
            elif time_context == "same_day":
                greeting = (
                    f"SYSTEM EVENT: {who} звонит сегодня повторно. {lang_rule} {name_rule} "
                    "Опирайся на память RECENT. Веди разговор сам, согласно портрету."
                )
            else:
                greeting = (
                    f"SYSTEM EVENT: Входящий звонок, {who}. {lang_rule} {name_rule} "
                    "Начни диалог согласно портрету. Если есть память RECENT, не переспрашивай известное."
                )

            context.add_message({"role": "user", "content": greeting})
            await task.queue_frames([LLMRunFrame()])

            runner = PipelineRunner()
            watchdog = asyncio.create_task(audio_stall_watchdog(call_id, socket, probe))
            dead_air = asyncio.create_task(dead_air_watchdog(call_id, activity, task))
            try:
                await asyncio.wait_for(runner.run(task), timeout=MAX_CALL_SECONDS)
            except asyncio.TimeoutError:
                clog.warning("[%s] max call duration reached, terminating", call_id)
                with contextlib.suppress(Exception):
                    await task.queue_frames([CancelFrame()])
            finally:
                watchdog.cancel()
                dead_air.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await watchdog
                with contextlib.suppress(asyncio.CancelledError):
                    await dead_air

        except (asyncio.IncompleteReadError, ConnectionResetError, asyncio.TimeoutError) as exc:
            clog.info("[%s] connection closed: %s", call_id, type(exc).__name__)
        except Exception as exc:
            clog.exception("[%s] call failed: %s", call_id, exc)
        finally:
            if counted_client:
                _calls_per_client[counted_client] = max(
                    0, _calls_per_client.get(counted_client, 1) - 1
                )
                if _calls_per_client[counted_client] == 0:
                    _calls_per_client.pop(counted_client, None)

            with contextlib.suppress(Exception):
                writer.close()

            last_ts = activity.last_activity_ts if activity else time.time()
            duration = int(max(0.0, last_ts - start_ts))
            direction = "outbound" if is_outbound else "inbound"
            wav_path = os.path.join(
                ASTERISK_RECORDING_PATH, f"{session_uuid}.{ASTERISK_RECORDING_EXT}"
            )
            agc = socket.agc if socket else None
            clog.info(
                "[%s] call finished, %ss, turns=%s, входное усиление в среднем %+.1f дБ, "
                "приглушено как фон %.0f%% кадров",
                call_id,
                duration,
                usage.turns,
                agc.average_gain_db if agc else 0.0,
                (100.0 * agc.gated_frames / agc.total_frames) if (agc and agc.total_frames) else 0.0,
            )

            if context is not None and client_id:
                transcript, user_replies = build_transcript(context.messages)
                if transcript:
                    clog.info("[%s] ДИАЛОГ:\n%s", call_id, transcript)
                text_in, audio_in, cost = usage.cost(system_prompt_tokens)

                usage_stats = {
                    "started_at": started_at.isoformat(),
                    "ended_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "duration_seconds": duration,
                    "turns": usage.turns,
                    "input_tokens": usage.prompt_tokens,
                    "output_tokens": usage.completion_tokens,
                    "total_cost_usd": round(cost, 6),
                }

                async def post_processing() -> None:
                    await asyncio.sleep(0.5)
                    if DUMP_INPUT_AUDIO:
                        # 1) Что ушло в Gemini (после ресемплинга и фильтра)
                        try:
                            stats = analyze_pcm(b"".join(probe.dump), PIPELINE_SAMPLE_RATE)
                            ratio = (
                                round(probe.bytes_seen / socket.rx_bytes, 2)
                                if socket.rx_bytes
                                else 0
                            )
                            log.info(
                                "[%s] АНАЛИЗ ЗВУКА ДЛЯ GEMINI: %s | байт сокет=%d пайплайн=%d "
                                "отношение=%.2f (ожидается %.1f)",
                                call_id,
                                json.dumps(stats, ensure_ascii=False),
                                socket.rx_bytes,
                                probe.bytes_seen,
                                ratio,
                                PIPELINE_SAMPLE_RATE / ASTERISK_INPUT_RATE,
                            )
                        except Exception as exc:
                            log.warning("[%s] analyze (gemini) failed: %s", call_id, exc)
                        # 2) Что записал сам Asterisk — до Python
                        try:
                            if await asyncio.to_thread(os.path.exists, wav_path):
                                raw, rate = await asyncio.to_thread(
                                    read_wav_or_raw, wav_path, 16000
                                )
                                log.info(
                                    "[%s] АНАЛИЗ ЗАПИСИ ASTERISK (%d Hz): %s",
                                    call_id,
                                    rate,
                                    json.dumps(analyze_pcm(raw, rate), ensure_ascii=False),
                                )
                        except Exception as exc:
                            log.warning("[%s] analyze (asterisk) failed: %s", call_id, exc)

                        dump_path = f"/tmp/gemini_input_{call_id}.wav"
                        if probe.write_wav(dump_path):
                            url = await upload_debug_wav(client_id, dump_path)
                            log.info(
                                "[%s] ЗВУК, КОТОРЫЙ СЛЫШИТ GEMINI (%.1f s): %s",
                                call_id,
                                probe.bytes_seen / (PIPELINE_SAMPLE_RATE * 2),
                                url or dump_path,
                            )
                            with contextlib.suppress(Exception):
                                await asyncio.to_thread(os.remove, dump_path)
                    try:
                        if user_replies == 0:
                            status = (
                                "outbound_short_call" if is_outbound else "inbound_dropped"
                            )
                            audio_url = ""
                        else:
                            status = "completed"
                            audio_url = await upload_audio_to_supabase(client_id, wav_path) or ""

                        await run_archivist_and_notify_n8n(
                            client_id,
                            target_phone,
                            client_name,
                            caller_memory,
                            transcript,
                            audio_url,
                            system_instructions_length,
                            direction,
                            status,
                            tz_name,
                            usage_stats,
                            audio_path=wav_path,
                            project_id=call_ctx.get("project_id") or "",
                        )
                    except Exception as exc:
                        log.error("[%s] post-processing failed: %s", call_id, exc)
                    finally:
                        with contextlib.suppress(Exception):
                            if await asyncio.to_thread(os.path.exists, wav_path):
                                await asyncio.to_thread(os.remove, wav_path)
                        gc.collect()

                asyncio.create_task(post_processing())
            else:
                gc.collect()
