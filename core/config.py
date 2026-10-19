"""Shared Core Configuration: общие настройки, переменные окружения и константы."""

from __future__ import annotations

import logging
import os
from zoneinfo import ZoneInfo


def _env_int(name: str, default: int) -> int:
    val = os.getenv(name)
    if val is None or not val.strip():
        return default
    try:
        return int(val.strip())
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    val = os.getenv(name)
    if val is None or not val.strip():
        return default
    try:
        return float(val.strip())
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None or not val.strip():
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


# =============================================================================
# Ключи и сервисы
# =============================================================================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
REDIS_URL = os.getenv("REDIS_URL")
N8N_BASE_URL = os.getenv("N8N_BASE_URL")
N8N_WEBHOOK_SECRET = os.getenv("N8N_WEBHOOK_SECRET")

# =============================================================================
# Модели Gemini
# =============================================================================
GEMINI_MODEL = os.getenv("GEMINI_LIVE_MODEL", "gemini-3.8-live")
ARCHIVIST_MODELS = [
    m.strip()
    for m in os.getenv(
        "ARCHIVIST_MODELS",
        "gemini-3.8-flash,gemini-3.1-flash-lite,gemini-4-argon",
    ).split(",")
    if m.strip()
]

# =============================================================================
# Аудиопараметры и форматы
# =============================================================================
PIPELINE_SAMPLE_RATE = _env_int("PIPELINE_SAMPLE_RATE", 16000)
WEB_OUTPUT_SAMPLE_RATE = _env_int("WEB_OUTPUT_SAMPLE_RATE", 24000)
OUT_CHUNK_SIZE = _env_int("OUT_CHUNK_SIZE", 640)
OUT_VOLUME = _env_float("OUT_VOLUME", 0.75)
DUMP_INPUT_AUDIO = _env_bool("DUMP_INPUT_AUDIO", False)

# АРУ и фильтрация фона
INPUT_AGC = _env_bool("INPUT_AGC", True)
INPUT_TARGET_DBFS = _env_float("INPUT_TARGET_DBFS", -20.0)
INPUT_MAX_GAIN_DB = _env_float("INPUT_MAX_GAIN_DB", 24.0)
INPUT_MIN_GAIN_DB = _env_float("INPUT_MIN_GAIN_DB", 0.0)
BACKGROUND_GATE_DB = _env_float("BACKGROUND_GATE_DB", 10.0)
BACKGROUND_ATTEN_DB = _env_float("BACKGROUND_ATTEN_DB", 15.0)
BACKGROUND_HOLD_MS = _env_int("BACKGROUND_HOLD_MS", 300)

# VAD (Voice Activity Detection)
VAD_SILENCE_MS = _env_int("VAD_SILENCE_MS", 1500)
VAD_END_SENSITIVITY = os.getenv("VAD_END_SENSITIVITY", "low").strip().lower()
VAD_START_SENSITIVITY = os.getenv("VAD_START_SENSITIVITY", "low").strip().lower()
VAD_PREFIX_PADDING_MS = _env_int("VAD_PREFIX_PADDING_MS", 800)

# =============================================================================
# Лимиты и таймауты
# =============================================================================
DEFAULT_TZ = os.getenv("DEFAULT_TIMEZONE", "Europe/Chisinau")
DEFAULT_LANG = os.getenv("DEFAULT_LANG", "ro")
MAX_CONCURRENT_CALLS = _env_int("MAX_CONCURRENT_CALLS", 25)
MAX_CALLS_PER_CLIENT = _env_int("MAX_CALLS_PER_CLIENT", 5)
MAX_CALL_SECONDS = _env_int("MAX_CALL_SECONDS", 900)
MIN_SECONDS_BEFORE_END_CALL = _env_int("MIN_SECONDS_BEFORE_END_CALL", 25)
IDLE_TIMEOUT_SECONDS = _env_float("IDLE_TIMEOUT_SECONDS", 20.0)
PERSONA_CACHE_TTL = _env_int("PERSONA_CACHE_TTL", 60)

# Web виджет лимиты
WEB_CHAT_MAX_PER_VISITOR = _env_int("WEB_CHAT_MAX_PER_VISITOR", 60)
WEB_CHAT_MAX_PER_IP = _env_int("WEB_CHAT_MAX_PER_IP", 200)
WEB_CHAT_MAX_PER_SITE = _env_int("WEB_CHAT_MAX_PER_SITE", 1000)
WEB_CHAT_SESSION_TTL = _env_int("WEB_CHAT_SESSION_TTL", 7200)
WEB_CHAT_MAX_AUDIO_B64 = _env_int("WEB_CHAT_MAX_AUDIO_B64", 1_500_000)
WEB_CHAT_MAX_IMAGE_B64 = _env_int("WEB_CHAT_MAX_IMAGE_B64", 3_000_000)
WEB_CHAT_MAX_TEXT = 2000
TURNSTILE_SECRET_KEY = os.getenv("TURNSTILE_SECRET_KEY", "")
WEB_MAX_CALLS_PER_VISITOR = _env_int("WEB_MAX_CALLS_PER_VISITOR", 3)
WEB_MAX_CALLS_PER_IP = _env_int("WEB_MAX_CALLS_PER_IP", 6)
WEB_MAX_MINUTES_PER_DAY = _env_int("WEB_MAX_MINUTES_PER_DAY", 60)

# Цены токенов ($ / 1M)
PRICE_TEXT_IN = _env_float("PRICE_TEXT_IN", 0.75)
PRICE_AUDIO_IN = _env_float("PRICE_AUDIO_IN", 3.00)
PRICE_AUDIO_OUT = _env_float("PRICE_AUDIO_OUT", 12.00)
AUDIO_TOKENS_PER_SECOND = 25

# Asterisk
ASTERISK_ARI_URL = os.getenv("ASTERISK_ARI_URL", "http://asterisk:8088")
ASTERISK_ARI_USER = os.getenv("ASTERISK_ARI_USER", "asterisk")
ASTERISK_ARI_PASSWORD = os.getenv("ASTERISK_ARI_PASSWORD", "asterisk")
ASTERISK_AUDIOSOCKET_HOST = os.getenv("ASTERISK_AUDIOSOCKET_HOST", "0.0.0.0")
ASTERISK_AUDIOSOCKET_PORT = _env_int("AUDIOSOCKET_PORT", 8085)
ASTERISK_RECORDING_PATH = os.getenv("ASTERISK_RECORDING_PATH", "/var/spool/asterisk/monitor")
ASTERISK_RECORDING_EXT = os.getenv("ASTERISK_RECORDING_EXT", "wav16")

INTERNAL_TOKEN = os.getenv("INTERNAL_TOKEN")
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
log = logging.getLogger("core")


def tz_for(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or DEFAULT_TZ)
    except Exception:
        return ZoneInfo("UTC")
