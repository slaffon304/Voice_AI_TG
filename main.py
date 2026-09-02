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
  * учёт токенов и себестоимости звонка (gsm_call_logs)
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
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx
from fastapi import Depends, FastAPI, HTTPException, Response, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from starlette.websockets import WebSocketState

import redis.asyncio as redis
from google import genai
from google.genai import types
from supabase import Client, create_client

from pipecat.audio.filters.rnnoise_filter import RNNoiseFilter
from pipecat.frames.frames import (
    CancelFrame,
    Frame,
    InputAudioRawFrame,
    InterruptionFrame,
    LLMRunFrame,
    MetricsFrame,
    OutputAudioRawFrame,
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
KOMMO_SUBDOMAIN = os.getenv("KOMMO_SUBDOMAIN")
KOMMO_ACCESS_TOKEN = os.getenv("KOMMO_ACCESS_TOKEN")

# Транк, номер которого нельзя принимать за номер клиента.
TRUNK_NUMBERS = [
    n.strip() for n in os.getenv("TRUNK_NUMBERS", "78001079,078001079").split(",") if n.strip()
]

# Протокол AudioSocket. Вынесено в конфиг, т.к. значения зависят от сборки Asterisk.
AS_TYPE_HANGUP = _env_int("AS_TYPE_HANGUP", 0x00)
AS_TYPE_AUDIO_IN_8K = _env_int("AS_TYPE_AUDIO_IN_8K", 0x10)
AS_TYPE_AUDIO_OUT = _env_int("AS_TYPE_AUDIO_OUT", 0x12)
RESAMPLE_INPUT_8K = _env_bool("RESAMPLE_INPUT_8K", True)

PIPELINE_SAMPLE_RATE = _env_int("PIPELINE_SAMPLE_RATE", 16000)
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


# =============================================================================
# 3. ДВИЖОК ХАРАКТЕРА
# =============================================================================

TRAITS = (
    "warmth",
    "energy",
    "formality",
    "assertiveness",
    "verbosity",
    "empathy",
    "humor",
    "persistence",
    "patience",
    "precision",
)

# Каждая шкала 1..10 разворачивается в конкретную поведенческую директиву.
# Три ведра: 1-3 (low), 4-7 (mid), 8-10 (high).
_TRAIT_DIRECTIVES: dict[str, tuple[str, str, str]] = {
    "warmth": (
        "Keep a neutral, businesslike register. No small talk.",
        "Be polite and pleasant, with brief human touches.",
        "Be openly warm: acknowledge the person before moving to business.",
    ),
    "energy": (
        "Speak calmly and unhurriedly; leave space between sentences.",
        "Keep a natural, even tempo.",
        "Speak with clear energy and forward momentum.",
    ),
    "formality": (
        "Use everyday, informal wording.",
        "Use a polite, neutral professional register.",
        "Use strictly formal, professional wording. No slang.",
    ),
    "assertiveness": (
        "Follow the caller's lead. Answer what is asked, nothing more.",
        "Guide the conversation, but yield whenever the caller takes over.",
        "Lead the call: set the agenda and drive it to the next step yourself.",
    ),
    "verbosity": (
        "Answer in one short sentence. Never read more than three items aloud.",
        "Keep answers to one or two sentences; expand only when asked.",
        "Give complete answers with context, still natural for speech.",
    ),
    "empathy": (
        "Stay factual. Do not comment on the caller's feelings.",
        "Acknowledge frustration in one short phrase, then solve the problem.",
        "Name and validate the caller's feelings before solving the problem.",
    ),
    "humor": (
        "No jokes at all.",
        "An occasional light remark is fine, never at the caller's expense.",
        "Use light humour freely while staying respectful.",
    ),
    "persistence": (
        "Never push. If the caller declines, close the call politely.",
        "Make one clear attempt at the next step; accept a refusal.",
        "Make up to two attempts to secure the next step, then accept a refusal.",
    ),
    "patience": (
        "Move briskly. Re-ask once, then offer a callback.",
        "Give the caller time to think before prompting again.",
        "Be very patient: rephrase and repeat calmly as many times as needed.",
    ),
    "precision": (
        "Approximate answers are acceptable.",
        "Be accurate and say plainly when you are unsure.",
        "Be exact with names, dates, times and numbers, and read them back for confirmation.",
    ),
}

_SPEECH_STYLE: dict[str, str] = {
    "ro": (
        "Speak Romanian as spoken in Moldova: clear, natural, unaffected. "
        "Natural fillers: 'deci', 'păi', 'adică', 'bun'."
    ),
    "ru": (
        "Speak natural conversational Russian. "
        "Natural fillers: 'так', 'смотрите', 'то есть', 'хорошо'."
    ),
    "en": (
        "Speak natural conversational English at a relaxed business pace. "
        "Natural fillers: 'so', 'alright', 'you know'."
    ),
}

_ADDRESS_FORM: dict[str, tuple[str, str]] = {
    # (informal, formal)
    "ro": ("Address the caller informally ('tu').", "Address the caller formally ('dumneavoastră')."),
    "ru": ("Address the caller informally ('ты').", "Address the caller formally ('вы')."),
    "en": ("Use a casual second person.", "Use a courteous, professional second person."),
}

_RATE_DIRECTIVE = {
    "slow": "Speak noticeably slower than average.",
    "normal": "Speak at an average conversational pace.",
    "fast": "Speak briskly, but stay fully intelligible.",
}


@dataclass
class Persona:
    """Характер бота. Одна строка bot_personas на клиента."""

    persona_name: str = "Asistent"
    lore: str = ""
    voice_model: str = "Enceladus"
    language: str = DEFAULT_LANG
    system_prompt: str = ""

    personality_enabled: bool = True
    warmth: int = 6
    energy: int = 5
    formality: int = 7
    assertiveness: int = 5
    verbosity: int = 4
    empathy: int = 6
    humor: int = 3
    persistence: int = 5
    patience: int = 7
    precision: int = 8

    speech_rate: str = "normal"
    use_fillers: bool = True
    address_form: str = "auto"  # formal | informal | auto
    catchphrases: str = ""
    forbidden_topics: str = ""

    @classmethod
    def from_row(cls, row: dict[str, Any] | None) -> "Persona":
        p = cls()
        if not row:
            return p
        for f in (
            "persona_name",
            "lore",
            "voice_model",
            "language",
            "system_prompt",
            "speech_rate",
            "address_form",
            "catchphrases",
            "forbidden_topics",
        ):
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
        for f in ("personality_enabled", "use_fillers"):
            val = row.get(f)
            if val is not None:
                setattr(p, f, bool(val))
        return p

    # --- характер -> технические параметры, не только текст промпта ---

    @property
    def silence_duration_ms(self) -> int:
        """Терпеливый бот дольше ждёт, пока собеседник додумает фразу."""
        return int(max(600, min(1600, 600 + self.patience * 90)))

    @property
    def end_sensitivity(self):
        return (
            types.EndSensitivity.END_SENSITIVITY_LOW
            if self.patience >= 8
            else types.EndSensitivity.END_SENSITIVITY_HIGH
        )

    @property
    def recovery_delay(self) -> float:
        """Через сколько секунд молчания бот перехватывает инициативу."""
        return round(2.5 + self.patience * 0.25, 2)

    @property
    def is_formal(self) -> bool:
        if self.address_form == "formal":
            return True
        if self.address_form == "informal":
            return False
        return self.formality >= 5


def _bucket(v: int) -> int:
    return 0 if v <= 3 else (1 if v <= 7 else 2)


def build_personality_block(p: Persona, lang: str) -> str:
    """Собирает компактный блок характера (~250 токенов) для system_instruction."""
    if not p.personality_enabled:
        return ""

    lang = (lang or DEFAULT_LANG).lower()[:2]
    lines: list[str] = ["<PERSONA>"]
    lines.append(f"Your name is {p.persona_name}. You are a voice agent on a phone call.")
    if p.lore:
        lines.append(f"Background (yours, never the caller's): {p.lore}")

    lines.append("")
    lines.append("BEHAVIOUR (follow every line):")
    for trait in TRAITS:
        directive = _TRAIT_DIRECTIVES[trait][_bucket(getattr(p, trait))]
        lines.append(f"- {directive}")

    lines.append("")
    lines.append("SPEECH:")
    lines.append(f"- {_SPEECH_STYLE.get(lang, _SPEECH_STYLE['en'])}")
    lines.append(f"- {_RATE_DIRECTIVE.get(p.speech_rate, _RATE_DIRECTIVE['normal'])}")
    forms = _ADDRESS_FORM.get(lang, _ADDRESS_FORM["en"])
    lines.append(f"- {forms[1] if p.is_formal else forms[0]}")
    if not p.use_fillers:
        lines.append("- Do not use conversational fillers; speak cleanly.")
    if p.catchphrases:
        lines.append(f"- Signature phrases you may use sparingly: {p.catchphrases}")
    if p.forbidden_topics:
        lines.append(f"- Never discuss: {p.forbidden_topics}")

    lines.append("</PERSONA>")
    return "\n".join(lines)


TELEPHONY_RULES = """<CALL_RULES>
- This is a phone call. Never output markdown, emoji, lists or URLs — everything you say is spoken aloud.
- Pronounce phone numbers and codes digit by digit.
- If you need to send a link or an address, use the send_sms tool instead of reading it aloud.
- Never invent facts, prices, availability or dates. If you do not know, say so and offer a callback.
- If the caller asks whether you are a human or an AI assistant, answer honestly.
- If the line is noisy or the caller is unclear, ask them to repeat once before guessing.
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
    readable = ", ".join(
        f"{d.capitalize()} {w[0]}-{w[1]}" for d, w in hours.items() if d in _DAY_KEYS
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


async def get_client_data(client_id: str) -> dict | None:
    rows = await sb_select(
        "saas_clients",
        {
            "id": f"eq.{client_id}",
            "select": (
                "company_name,business_context,tone,bot_goal,"
                "subscription_status_assistent,system_message,timezone,working_hours,"
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
    cache_key = f"persona:{client_id}"
    if redis_client:
        with contextlib.suppress(Exception):
            cached = await redis_client.get(cache_key)
            if cached:
                return Persona.from_row(json.loads(cached))

    cols = ",".join(
        ["system_prompt", "voice_model", "language", "persona_name", "lore",
         "personality_enabled", "speech_rate", "use_fillers", "address_form",
         "catchphrases", "forbidden_topics", *TRAITS]
    )
    rows = await sb_select("bot_personas", {"client_id": f"eq.{client_id}", "select": cols})
    row = rows[0] if rows else None
    if redis_client and row:
        with contextlib.suppress(Exception):
            await redis_client.setex(cache_key, PERSONA_CACHE_TTL, json.dumps(row, default=str))
    return Persona.from_row(row)


async def get_caller_memory(client_id: str, phone: str) -> tuple[dict, str]:
    default = {"core": "", "short": "", "long": ""}
    if not phone or phone == "Necunoscut":
        return default, "first_time"
    clean = "".join(filter(str.isdigit, str(phone)))
    rows = await sb_select(
        "caller_memories",
        {
            "client_id": f"eq.{client_id}",
            "phone": f"eq.{clean}",
            "select": "core_identity,short_term_context,long_term_context,last_interaction_at",
        },
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


async def lookup_inbound_client_in_kommo(caller_phone: str) -> dict:
    if not KOMMO_SUBDOMAIN or not KOMMO_ACCESS_TOKEN or caller_phone == "Necunoscut":
        return {"found": False}
    subdomain = KOMMO_SUBDOMAIN.encode("ascii", "ignore").decode().strip()
    token = KOMMO_ACCESS_TOKEN.encode("ascii", "ignore").decode().strip()
    clean = "".join(filter(str.isdigit, str(caller_phone)))
    if len(clean) < 6:
        return {"found": False}
    try:
        resp = await http().get(
            f"https://{subdomain}.kommo.com/api/v4/contacts",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            params={"query": clean[-8:] if len(clean) >= 8 else clean, "with": "leads"},
            timeout=2.5,
        )
        if resp.status_code != 200:
            return {"found": False}
        contacts = (resp.json().get("_embedded") or {}).get("contacts") or []
        if not contacts:
            return {"found": False}
        contact = contacts[0]
        lang = DEFAULT_LANG
        for f in contact.get("custom_fields_values") or []:
            code = str(f.get("field_code") or "").upper()
            name = str(f.get("field_name") or "").lower()
            if code == "LANG" or any(k in name for k in ("язык", "limba", "lang")):
                val = str((f.get("values") or [{}])[0].get("value", "")).lower()
                if "ru" in val or "рус" in val:
                    lang = "ru"
                elif any(k in val for k in ("ro", "rom", "md")):
                    lang = "ro"
                elif "en" in val:
                    lang = "en"
                break
        return {"found": True, "name": contact.get("name") or "client", "lang": lang}
    except Exception as exc:
        log.warning("kommo lookup failed: %s", exc)
        return {"found": False}


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


async def insert_call_log(row: dict) -> None:
    if not SUPABASE_URL or not SUPABASE_KEY:
        return
    try:
        db = create_client(SUPABASE_URL, SUPABASE_KEY)
        await asyncio.to_thread(db.table("gsm_call_logs").insert(row).execute)
    except Exception as exc:
        log.warning("call log insert failed: %s", exc)


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
) -> None:
    if not chat_history.strip() or phone == "Necunoscut":
        return

    today = dt.datetime.now(tz_for(tz_name)).strftime("%Y-%m-%d")
    clean_phone = "".join(filter(str.isdigit, str(phone)))

    prompt = f"""Ты ИИ-архивариус. Обнови память клиента и составь резюме звонка для CRM.
Дата звонка: {today}. Направление: {direction}.

СТАРАЯ ПАМЯТЬ:
CORE IDENTITY: {old_memory.get('core') or 'Нет данных'}
SHORT TERM: {old_memory.get('short') or 'Нет данных'}
LONG TERM: {old_memory.get('long') or 'Нет данных'}

ТРАНСКРИПТ ЗВОНКА:
{chat_history}

ИНСТРУКЦИЯ (выведи СТРОГО JSON, без markdown):
1. core_identity: обнови, если клиент сообщил фундаментальный факт.
2. short_term_context: факты старше 3 дней перенеси в long_term. Новые пиши как "[{today}]: факт".
3. long_term_context: сжатая история прошлых обращений.
4. summary: суть текущего звонка для менеджера.
5. sentiment: настрой и возражения.
6. next_step: следующий шаг (перезвонить, отправить КП и т.д.).
7. language: язык клиента (ro/ru/en).

{{"core_identity":"...","short_term_context":"...","long_term_context":"...","summary":"...","sentiment":"...","next_step":"...","language":"..."}}
"""

    data: dict[str, Any] = {}
    client = genai.Client(api_key=GEMINI_API_KEY)
    for attempt, model in enumerate(ARCHIVIST_MODELS):
        try:
            response = await client.aio.models.generate_content(
                model=model,
                contents=prompt,
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
        db = create_client(SUPABASE_URL, SUPABASE_KEY)
        await asyncio.to_thread(
            db.table("caller_memories")
            .upsert(
                {
                    "client_id": client_id,
                    "phone": clean_phone,
                    "core_identity": data.get("core_identity", ""),
                    "short_term_context": data.get("short_term_context", ""),
                    "long_term_context": data.get("long_term_context", ""),
                    "last_interaction_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                },
                on_conflict="client_id,phone",
            )
            .execute
        )
        log.info("[archivist] memory saved for %s", clean_phone)
    except Exception as exc:
        log.error("[archivist] memory save failed: %s", exc)

    if not N8N_BASE_URL:
        return
    payload = {
        "client_id": client_id,
        "end_client_name": client_name,
        "end_client_phone": phone,
        "status": call_status,
        "transcript": chat_history,
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
        "platform": "gsm_voice",
        "direction": direction,
    }
    try:
        await http().post(f"{N8N_BASE_URL}/post-call-summary", json=payload, timeout=10.0)
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
        if RESAMPLE_INPUT_8K and header[0] == AS_TYPE_AUDIO_IN_8K:
            data, self._resample_state = pcm_resample(
                data, self._resample_state, 8000, PIPELINE_SAMPLE_RATE
            )
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
        elif isinstance(frame, (OutputAudioRawFrame, UserStartedSpeakingFrame)):
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
        ("{office_status}", "Open" if is_open else "Closed"),
        ("{lang}", lang),
        ("{persona_name}", safe(persona.persona_name, "Asistent")),
        ("{working_hours}", readable_hours),
    ):
        prompt = prompt.replace(token, value)

    blocks = [prompt, "", build_personality_block(persona, lang), "", TELEPHONY_RULES, ""]

    blocks.append("<SCHEDULE>")
    blocks.append(f"Now: {now.strftime('%A, %d %B %Y, %H:%M')} ({now.tzname()}).")
    blocks.append(f"Working hours: {readable_hours}.")
    blocks.append(f"The office is currently {'OPEN' if is_open else 'CLOSED'}.")
    blocks.append(
        "Never schedule anything outside working hours. If the caller asks for a closed "
        "slot, decline politely and offer the first available working slot."
    )
    blocks.append("</SCHEDULE>")
    blocks.append("")

    blocks.append("<CALLER_MEMORY>")
    blocks.append(f"CORE: {memory.get('core') or '-'}")
    blocks.append(f"RECENT: {memory.get('short') or '-'}")
    blocks.append(f"LONG TERM: {memory.get('long') or '-'}")
    blocks.append("Use this to avoid re-asking what you already know. Never read it aloud.")
    blocks.append("</CALLER_MEMORY>")
    blocks.append("")
    blocks.append(f"Speak only in: {lang.upper()}.")

    return "\n".join(b for b in blocks if b is not None)


def build_tools(client_data: dict, readable_hours: str) -> list[dict]:
    tools = [
        {
            "name": "save_lead",
            "description": "Salvează datele de contact și motivul apelului în CRM.",
            "parameters": {
                "type": "object",
                "properties": {
                    "client_name": {"type": "string"},
                    "client_phone": {"type": "string"},
                    "request_summary": {"type": "string"},
                },
                "required": ["client_name", "client_phone", "request_summary"],
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
                "Încheie apelul. OBLIGATORIU: spune o scurtă frază de rămas-bun ÎNAINTE "
                "de a apela această funcție."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    ]
    if client_data.get("google_calendar_id"):
        tools.append(
            {
                "name": "Booking_tool",
                "description": (
                    f"Gestionează calendarul. Programează DOAR în intervalul: {readable_hours}. "
                    "Pentru 'book' transmite obligatoriu client_name, phone, request_summary, "
                    "start_time și end_time."
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


@app.get("/get_uuid")
async def get_client_uuid(
    sip_login: str | None = None,
    sip_login_gsm: str | None = None,
    phone: str | None = None,
    ani: str | None = None,
    from_hdr: str | None = None,
    all_id: str | None = None,
    call_uuid: str | None = None,
    token: str | None = None,
):
    """Вызывается диалпланом Asterisk: sip_login -> client_id."""
    if INTERNAL_TOKEN and token != INTERNAL_TOKEN:
        return Response(content="error", media_type="text/plain", status_code=401)

    identifier = sip_login_gsm or sip_login
    if not identifier:
        return Response(content="error", media_type="text/plain")

    rows = await sb_select(
        "bot_channels", {"identifier": f"eq.{identifier}", "select": "client_id"}
    )
    if not rows:
        return Response(content="not_found", media_type="text/plain")

    client_id = str(rows[0].get("client_id"))
    formatted = format_phone(extract_real_phone(ani, all_id, from_hdr, phone))

    if formatted != "Necunoscut" and redis_client:
        with contextlib.suppress(Exception):
            if call_uuid:
                # Точная привязка номера к конкретному звонку.
                await redis_client.setex(f"inbound_phone:{call_uuid}", 120, formatted)
            # Совместимость со старым диалпланом: очередь вместо одного ключа,
            # чтобы одновременные звонки не перетирали номер друг другу.
            await redis_client.lpush(f"inbound_phone_q:{client_id}", formatted)
            await redis_client.expire(f"inbound_phone_q:{client_id}", 120)
    return Response(content=client_id, media_type="text/plain")


class OutboundCallRequest(BaseModel):
    client_id: str
    target_phone: str
    call_purpose: str
    client_name: str = "client"
    custom_context: str = ""
    lang: str = DEFAULT_LANG


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
            await redis_client.setex(
                f"call_context:{call_uuid}",
                600,
                json.dumps(
                    {
                        "client_id": req.client_id,
                        "target_phone": formatted_phone,
                        "client_name": req.client_name,
                        "call_purpose": req.call_purpose,
                        "custom_context": req.custom_context,
                        "lang": req.lang,
                    }
                ),
            )

    payload = {
        "endpoint": f"PJSIP/{formatted_phone}{ASTERISK_ENDPOINT_SUFFIX}",
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
        "vad": {
            "silence_duration_ms": persona.silence_duration_ms,
            "recovery_delay_s": persona.recovery_delay,
        },
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
    counted_client: Optional[str] = None

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

            outbound_info: dict = {}
            inbound_crm: dict = {}

            if redis_client:
                with contextlib.suppress(Exception):
                    raw = await redis_client.get(f"call_context:{session_uuid}")
                    if raw:
                        is_outbound = True
                        outbound_info = json.loads(raw)
                        await redis_client.delete(f"call_context:{session_uuid}")

            purpose = ""
            if is_outbound:
                client_id = outbound_info.get("client_id")
                target_phone = outbound_info.get("target_phone", "Necunoscut")
                client_name = outbound_info.get("client_name", "client")
                call_lang = outbound_info.get("lang", DEFAULT_LANG)
                purpose = outbound_info.get("call_purpose", "")
            else:
                client_id = session_uuid
                call_lang = DEFAULT_LANG
                if redis_client:
                    with contextlib.suppress(Exception):
                        phone = await redis_client.get(f"inbound_phone:{session_uuid}")
                        if not phone:
                            phone = await redis_client.rpop(f"inbound_phone_q:{client_id}")
                        if phone:
                            target_phone = phone

            if not client_id:
                clog.warning("[%s] no client_id resolved", call_id)
                return

            # Лимит на клиента — защита от лавины звонков одного тенанта.
            if _calls_per_client.get(client_id, 0) >= MAX_CALLS_PER_CLIENT:
                clog.warning("[%s] per-client limit hit for %s", call_id, client_id)
                return
            _calls_per_client[client_id] = _calls_per_client.get(client_id, 0) + 1
            counted_client = client_id

            # Параллельная загрузка — экономит ~300-500 мс до первой фразы.
            client_data, persona = await asyncio.gather(
                get_client_data(client_id), get_persona(client_id)
            )
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

            if not is_outbound:
                inbound_crm = await lookup_inbound_client_in_kommo(target_phone)
                if inbound_crm.get("found"):
                    client_name = inbound_crm.get("name") or "client"
                    call_lang = str(inbound_crm.get("lang") or persona.language).lower().strip()
                else:
                    call_lang = persona.language or DEFAULT_LANG

            caller_memory, time_context = await get_caller_memory(client_id, target_phone)

            system_prompt = build_system_prompt(
                client_data, persona, caller_memory, call_lang, now, hours
            )
            _, readable_hours = office_state(hours, now)
            tools = [{"function_declarations": build_tools(client_data, readable_hours)}]
            full_system_text = system_prompt + json.dumps(tools, ensure_ascii=False)
            system_instructions_length = len(full_system_text)
            system_prompt_tokens = estimate_tokens(full_system_text)

            clog.info(
                "[%s] client=%s persona=%s lang=%s phone=%s sys=%d tok",
                call_id,
                client_id,
                persona.persona_name,
                call_lang,
                target_phone,
                system_prompt_tokens,
            )

            # --- транспорт ---
            socket = AsteriskAudioSocket(reader, writer)
            transport = FastAPIWebsocketTransport(
                websocket=socket,
                params=FastAPIWebsocketParams(
                    audio_in_enabled=True,
                    audio_in_filter=RNNoiseFilter(),
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
                    vad=GeminiVADParams(
                        end_sensitivity=persona.end_sensitivity,
                        silence_duration_ms=persona.silence_duration_ms,
                        disabled=False,
                    ),
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

            recovery = InterruptionRecoveryProcessor(context, delay=persona.recovery_delay)

            pipeline = Pipeline(
                [
                    transport.input(),
                    context_aggregator.user(),
                    llm,
                    usage,
                    recovery,
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

            if is_outbound:
                greeting = (
                    f"SYSTEM EVENT: The person ({client_name}) answered your outbound call. "
                    f"Goal of this call: {purpose}. Caller language: {call_lang}. "
                    "Open the conversation in character."
                )
            elif time_context == "very_recent":
                greeting = (
                    f"SYSTEM EVENT: {client_name} called back after a couple of minutes. "
                    f"Do not greet again. Language: {call_lang}. Say the line dropped and continue."
                )
            elif time_context == "same_day":
                greeting = (
                    f"SYSTEM EVENT: {client_name} is calling again today. Language: {call_lang}. "
                    "Use RECENT memory and ask what else you can help with."
                )
            else:
                greeting = (
                    f"SYSTEM EVENT: Inbound call from {client_name}. Language: {call_lang}. "
                    "Open the conversation. If RECENT memory exists, do not re-ask known facts."
                )

            context.add_message({"role": "user", "content": greeting})
            await task.queue_frames([LLMRunFrame()])

            runner = PipelineRunner()
            try:
                await asyncio.wait_for(runner.run(task), timeout=MAX_CALL_SECONDS)
            except asyncio.TimeoutError:
                clog.warning("[%s] max call duration reached, terminating", call_id)
                with contextlib.suppress(Exception):
                    await task.queue_frames([CancelFrame()])

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

            duration = int(time.time() - start_ts)
            direction = "outbound" if is_outbound else "inbound"
            wav_path = os.path.join(
                ASTERISK_RECORDING_PATH, f"{session_uuid}.{ASTERISK_RECORDING_EXT}"
            )
            clog.info("[%s] call finished, %ss, turns=%s", call_id, duration, usage.turns)

            if context is not None and client_id:
                transcript, user_replies = build_transcript(context.messages)
                text_in, audio_in, cost = usage.cost(system_prompt_tokens)

                async def post_processing() -> None:
                    await asyncio.sleep(0.5)
                    try:
                        await insert_call_log(
                            {
                                "client_id": client_id,
                                "phone": target_phone,
                                "direction": direction,
                                "started_at": started_at.isoformat(),
                                "ended_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                                "duration_seconds": duration,
                                "turns": usage.turns,
                                "input_tokens": usage.prompt_tokens,
                                "output_tokens": usage.completion_tokens,
                                "text_input_tokens": text_in,
                                "audio_input_tokens": audio_in,
                                "total_cost_usd": round(cost, 6),
                                "system_prompt_chars": system_instructions_length,
                            }
                        )

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
