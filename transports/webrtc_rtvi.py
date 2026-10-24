"""
Изолированный WebRTC + RTVI контур для «Сайта Будущего».

Legacy GSM и /ws НЕ затрагиваются.

Стратегия продукта:
  - Клиентам (серия) — Intent-Matched Widgets: готовые секции + умное управление.
  - labupgrade.ai (концепт) — расширяемый payload с components для Prompt-to-Component.

Реализовано:
  Фаза 3.1 Анти-Диктовка
  Фаза 3.2 Zero-Click Dwell Sensing
  Фаза 3.3 ROI Calculator
  Фаза 3.4 Live Screen Audit
  Фаза 3.5 Real-Time Sentiment UI Morphing
  Фаза 2.5 UI protocol: ui-snapshot (хранится, в контекст модели не идёт)
  Agentic Tool-State: индикатор (Thinking Orb) переключает сервер сам,
            внутри каждого действия — у модели отдельного инструмента нет

Защита /api/offer: origin, blacklist, Turnstile, суточные лимиты.
  Soft deadline (warn → close).
  Mid-session abuse: verify → block (как legacy).
  Проверка номера кодом из SMS сразу после первых реплик (только +373);
  номер берётся только из подтверждения, запись — карточка с подтверждением.
  Пока номер подтверждается, звук посетителя в модель не идёт (токены не тратятся).
  Дневной предел минут голоса на сайт клиента — счётчик в Redis.
  Замер задержек: строка TIMING на каждый ответ агента и итог в конце разговора.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import hashlib
import hmac
import html
import json
import logging
import os
import re
import secrets
import statistics
import time
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse
from pathlib import Path
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    CancelFrame,
    Frame,
    FunctionCallInProgressFrame,
    FunctionCallResultFrame,
    InputAudioRawFrame,
    InputTransportMessageFrame,
    LLMMessagesAppendFrame,
    LLMRunFrame,
    TranscriptionFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.observers.base_observer import BaseObserver, FramePushed
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.turns.user_turn_strategies import ExternalUserTurnStrategies
from pipecat.processors.frameworks.rtvi import (
    RTVIFunctionCallReportLevel,
    RTVIObserver,
    RTVIObserverParams,
    RTVIProcessor,
    RTVIUICommandFrame,
    RTVIUISnapshotFrame,
)
from pipecat.services.google.gemini_live.llm import GeminiLiveLLMService, GeminiVADParams

try:
    from google.genai.types import EndSensitivity, StartSensitivity
except Exception:  # pragma: no cover
    StartSensitivity = None  # type: ignore
    EndSensitivity = None  # type: ignore
from pipecat.services.llm_service import FunctionCallParams
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

from core import (
    DEFAULT_LANG,
    DEFAULT_TZ,
    FARA_PROGRAMARE,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    IDLE_TIMEOUT_SECONDS,
    MIN_SECONDS_BEFORE_END_CALL,
    TELEFON_INCOMPLET,
    WebAIAudioCatcher,
    WebAudioMixer,
    WebUserAudioCatcher,
    build_system_prompt,
    build_tools,
    build_transcript,
    call_n8n,
    blocheaza,
    este_blocat,
    get_client_data,
    get_persona,
    get_web_visitor_context,
    id_din_lookup,
    id_zapisi,
    log,
    normalizeaza_timp,
    origin_permis,
    parse_working_hours,
    peste_limita,
    redis_client,
    web_session_budget,
    propusk_valabil,
    resolve_voice_name,
    run_archivist_and_notify_n8n,
    sb_select,
    send_tg_alert,
    slot_liber,
    telefon_valid,
    tz_for,
    upload_audio_to_supabase,
    WEB_MAX_MINUTES_PER_DAY,
)

router = APIRouter(tags=["webrtc-rtvi"])

_STATIC = Path(__file__).resolve().parent.parent / "static"

@router.get("/widget-genui.js")
async def serve_widget_genui():
    return FileResponse(_STATIC / "widget-genui.js", media_type="application/javascript")


@router.get("/genui-scenes.js")
async def serve_genui_scenes():
    """Слой сцен (каталог клиента на весь экран). Подгружается виджетом."""
    return FileResponse(
        _STATIC / "genui-scenes.js",
        media_type="application/javascript",
        headers={"Cache-Control": "public, max-age=300"},
    )


# ---------------------------------------------------------------------------
# Каталог сцен: bot_personas.flow_config.catalog (тексты на 9 языках)
# ---------------------------------------------------------------------------

SCENE_LANGS = {"ru", "ro", "en", "fr", "it", "pl", "uk", "pt", "cs"}
SCENE_NAMES = ["welcome", "services", "plans", "compare", "calculator", "case", "clients", "trust", "contacts", "booking"]
_catalog_cache: dict[str, tuple[float, Optional[dict]]] = {}


async def load_scene_catalog(client_id: str) -> Optional[dict]:
    """Каталог клиента или None. Кэш на минуту, чтобы не читать базу на каждый запрос."""
    if not client_id:
        return None
    hit = _catalog_cache.get(client_id)
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    cat: Optional[dict] = None
    try:
        rows = await sb_select(
            "bot_personas",
            {"client_id": f"eq.{client_id}", "select": "flow_config", "limit": "1"},
            timeout=2.5,
        )
        raw = rows[0].get("flow_config") if rows else None
        if isinstance(raw, str):
            raw = json.loads(raw)
        if isinstance(raw, dict) and isinstance(raw.get("catalog"), dict):
            c = raw["catalog"]
            if isinstance(c.get("plans"), list) or isinstance(c.get("services"), list):
                cat = c
    except Exception as exc:
        log.warning("scene catalog load %s: %s", client_id, exc)
        return hit[1] if hit else None
    _catalog_cache[client_id] = (time.time(), cat)
    return cat


def scene_lang(catalog: Optional[dict], lang: str) -> str:
    langs = (catalog or {}).get("languages") or []
    lang = (lang or "").lower()[:2]
    if lang in langs:
        return lang
    return "en" if "en" in langs else (langs[0] if langs else "en")


def localize_catalog(obj: Any, lang: str) -> Any:
    """Словари вида {ru:..., ro:..., en:...} превращаются в строку (или список) на одном языке."""
    if isinstance(obj, dict):
        if obj and set(obj.keys()) <= SCENE_LANGS:
            return obj.get(lang) if obj.get(lang) not in (None, "", []) else (obj.get("en") or next(iter(obj.values())))
        return {k: localize_catalog(v, lang) for k, v in obj.items()}
    if isinstance(obj, list):
        return [localize_catalog(v, lang) for v in obj]
    return obj


def _catalog_plans(catalog: dict) -> list[dict]:
    p = catalog.get("plans")
    items = p.get("items") if isinstance(p, dict) else p
    return [x for x in (items or []) if isinstance(x, dict) and x.get("id")]


def _picker(catalog: dict) -> dict:
    p = catalog.get("plans")
    pk = p.get("picker") if isinstance(p, dict) else None
    return pk if isinstance(pk, dict) else {}


def _calculator(catalog: dict) -> dict:
    c = catalog.get("calculator")
    return c if isinstance(c, dict) and c.get("inputs") and c.get("outputs") else {}


def scene_available(catalog: dict) -> list[str]:
    """Сцены, для которых у клиента есть данные. Остальные модели не предлагаем."""
    have = {
        "welcome": True,
        "services": bool(catalog.get("services")),
        "plans": bool(_catalog_plans(catalog)),
        "compare": len(_catalog_plans(catalog)) >= 2,
        "calculator": bool(_calculator(catalog)),
        "case": bool(catalog.get("cases")),
        "clients": bool(catalog.get("clients")),
        "trust": bool(catalog.get("trust")),
        "contacts": bool(catalog.get("contacts")),
        "booking": True,
    }
    return [n for n in SCENE_NAMES if have.get(n)]


def scene_need(catalog: dict, values: dict) -> float:
    """Нужная ёмкость тарифа: сумма «значение × вес» по полям подбора из каталога, плюс запас."""
    pk = _picker(catalog)
    total = 0.0
    for inp in pk.get("inputs") or []:
        with contextlib.suppress(TypeError, ValueError):
            total += float(values.get(inp.get("id")) or 0) * float(inp.get("weight") or 0)
    return total * (1 + float(pk.get("headroom") or 0))


def scene_plan_fits(catalog: dict, plan: dict, need: float, values: dict) -> bool:
    if need and float(plan.get("capacity") or 0) < need:
        return False
    limits = plan.get("limits") or {}
    for lim in _picker(catalog).get("limits") or []:
        want = values.get(lim.get("id"))
        if not want:
            continue
        have = limits.get(lim.get("plan_limit") or lim.get("id"))
        if isinstance(have, (int, float)) and have != 0 and have < float(want):
            return False
    return True


def scene_pick_plan(catalog: dict, need: float, values: dict) -> Optional[dict]:
    """Самый дешёвый тариф, который подходит по ёмкости и ограничениям (0 = без лимита)."""
    plans = _catalog_plans(catalog)
    for p in plans:
        if scene_plan_fits(catalog, p, need, values):
            return p
    return plans[-1] if plans else None


def calc_expr(expr: str, variables: dict) -> Optional[float]:
    """Формула калькулятора из каталога: числа, имена полей, + - * / и скобки."""
    import ast
    import operator

    ops = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.Name) and node.id in variables:
            return float(variables[node.id])
        if isinstance(node, ast.BinOp) and type(node.op) in ops:
            return ops[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -ev(node.operand)
        raise ValueError("bad expression")

    try:
        return ev(ast.parse(str(expr or ""), mode="eval"))
    except Exception:
        return None


_SAFE_ID = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
_RESERVED_ARGS = {"scene", "activity", "problem", "volume", "services", "service_reasons", "reason",
                  "billing", "compare_plan", "start_time", "end_time", "request_summary"}


def _extra_fields(catalog: dict) -> list[dict]:
    """Поля, которые модель передаёт числами: подбор тарифа и калькулятор (из каталога клиента)."""
    out, seen = [], set()
    pk = _picker(catalog)
    for group in (pk.get("inputs") or [], pk.get("limits") or [], _calculator(catalog).get("inputs") or []):
        for f in group:
            fid = str(f.get("id") or "")
            if _SAFE_ID.match(fid) and fid not in _RESERVED_ARGS and fid not in seen:
                seen.add(fid)
                out.append(f)
    return out


def build_scene_tool(catalog: dict) -> dict:
    available = scene_available(catalog)
    service_ids = [str(x.get("id")) for x in (catalog.get("services") or []) if isinstance(x, dict) and x.get("id")]
    plan_ids = [str(p.get("id")) for p in _catalog_plans(catalog)]
    props: dict[str, Any] = {
        "scene": {"type": "string", "enum": available, "description": "Which scene to show."},
        "activity": {"type": "string", "description": "Visitor's business in 2-5 words, in the conversation language (dossier)."},
        "problem": {"type": "string", "description": "Visitor's main problem in under 8 words, conversation language (dossier)."},
        "volume": {"type": "string", "description": "Short summary of the visitor's numbers in their words (dossier)."},
        "start_time": {"type": "string", "description": "booking: slot start, ISO 8601 local time."},
        "end_time": {"type": "string", "description": "booking: slot end, ISO 8601 local time."},
        "request_summary": {"type": "string", "description": "booking: purpose of the meeting, short."},
    }
    if service_ids:
        props["services"] = {"type": "array", "items": {"type": "string", "enum": service_ids},
                             "description": "services: 1-2 service ids that solve the visitor's problem, best first."}
        props["service_reasons"] = {"type": "array", "items": {"type": "string"},
                                    "description": "services: one short reason per chosen service, same order, visitor's language."}
    if plan_ids:
        props["reason"] = {"type": "string", "description": "plans: one short sentence why the recommended plan fits, visitor's language."}
        if any(p.get("year") for p in _catalog_plans(catalog)):
            props["billing"] = {"type": "string", "enum": ["month", "year"]}
        if len(plan_ids) >= 2:
            props["compare_plan"] = {"type": "string", "enum": plan_ids, "description": "compare: the plan the visitor asks about."}
    for f in _extra_fields(catalog):
        props[f["id"]] = {"type": "number", "description": str(f.get("ask") or f["id"])}
    return {
        "name": "show_scene",
        "description": (
            "Shows a full-screen scene from the company catalog on the visitor's screen and updates the visitor dossier. "
            "Pass every fact you learned (activity, problem, volume and the numeric fields) — the dossier, "
            "the recommended plan and the calculator are built from them by the server."
        ),
        "parameters": {"type": "object", "properties": props, "required": ["scene"]},
    }


def build_scene_prompt(catalog: dict, lang: str) -> str:
    """Индекс каталога для модели: какие сцены есть, услуги, тарифы, что спросить для подбора и расчёта."""
    c = localize_catalog(catalog, lang)
    cur = c.get("currency") or "EUR"
    out = ["<CATALOG>", "scenes available: " + ", ".join(scene_available(catalog))]
    for sv in c.get("services") or []:
        out.append(f"service {sv.get('id')}: {sv.get('title')} — {sv.get('short')}")
    for p in _catalog_plans(c):
        out.append(
            f"plan {p.get('id')}: {p.get('name')} — {'from ' if p.get('from') else ''}{p.get('month')} {cur}/month"
            + (f" ({p.get('year')} {cur}/month paid yearly)" if p.get("year") else "")
            + (f"; {p.get('highlight')}" if p.get("highlight") else "")
            + ("; most popular" if p.get("popular") else "")
        )
    note = (c.get("plans") or {}).get("note") if isinstance(c.get("plans"), dict) else None
    if note:
        out.append(f"plans note: {note}")
    pk = _picker(c)
    if pk.get("inputs"):
        asks = [f"{f.get('id')} ({f.get('ask')})" for f in (pk.get("inputs") or []) + (pk.get("limits") or [])]
        out.append("to pick a plan ask for and pass: " + "; ".join(asks) + ". The server picks the plan.")
    calc = _calculator(c)
    if calc:
        asks = [f"{f.get('id')} ({f.get('ask') or f.get('label')})" for f in calc.get("inputs") or []]
        out.append("calculator inputs: " + "; ".join(asks) + ". Defaults are used for anything not said.")
    names = [x.get("name") for x in (c.get("clients") or []) if isinstance(x, dict) and x.get("name")]
    if names:
        out.append("clients: " + ", ".join(names))
    k = c.get("contacts") or {}
    phones = ", ".join(f"{x.get('label')} {x.get('value')}" for x in (k.get("phones") or []) if isinstance(x, dict))
    if phones:
        out.append("phones: " + phones)
    if k.get("email"):
        out.append("email: " + str(k.get("email")))
    if k.get("address"):
        out.append("address: " + str(k.get("address")))
    out.append("</CATALOG>")
    return "\n".join(out)


DWELL_MIN_SECONDS = 3.0
# Soft close: предупреждение за столько секунд до конца budget
SOFT_DEADLINE_WARN_BEFORE = 30
# Повторов «списка вопросов» до требования верификации / блока
ABUSE_REPEAT_THRESHOLD = 3


def _env_int_local(name: str, default: int) -> int:
    try:
        return int((os.getenv(name) or "").strip() or default)
    except ValueError:
        return default


# Проверка номера кодом из SMS: когда начинать и сколько ждать
VERIFY_AFTER_TURNS = _env_int_local("WEB_VERIFY_AFTER_TURNS", 2)
VERIFY_AFTER_SECONDS = _env_int_local("WEB_VERIFY_AFTER_SECONDS", 40)
VERIFY_TIMEOUT_SECONDS = _env_int_local("WEB_VERIFY_TIMEOUT_SECONDS", 60)
SMS_CODE_TTL_SECONDS = 300
SMS_CODE_ATTEMPTS = 3
SMS_MAX_PER_SESSION = 3
SMS_RESEND_SECONDS = 30
SMS_MAX_PER_PHONE_DAY = _env_int_local("WEB_SMS_PER_PHONE_DAY", 3)
SMS_MAX_PER_IP_DAY = _env_int_local("WEB_SMS_PER_IP_DAY", 5)
# Только для теста, пока не готов SMS-шлюз: код пишется в лог вместо отправки
WEB_SMS_DEBUG = (os.getenv("WEB_SMS_DEBUG") or "").strip().lower() in ("1", "true", "yes")

SMS_CODE_TEXT = {
    "ru": "Код подтверждения {company}: {code}",
    "ro": "Codul de confirmare {company}: {code}",
    "en": "{company} verification code: {code}",
}


def normalize_md_phone(raw: Any) -> str:
    """Молдавский номер → 373XXXXXXXX (11 цифр). Любой другой → пустая строка."""
    d = "".join(ch for ch in str(raw or "") if ch.isdigit())
    if d.startswith("00373"):
        d = d[2:]
    if len(d) == 9 and d.startswith("0"):
        d = "373" + d[1:]
    elif len(d) == 8:
        d = "373" + d
    if len(d) == 11 and d.startswith("373"):
        return d
    return ""


def _host_of(url: str) -> str:
    try:
        return (url or "").split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0].lower()
    except Exception:
        return ""


async def _sms_quota_ok(phone: str, ip: str) -> bool:
    """Суточные лимиты SMS: на номер и на адрес. Считает только реальную отправку."""
    if not redis_client:
        log.warning("sms quota: redis недоступен — лимиты не проверены")
        return True
    day = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d")
    try:
        pkey = f"web_sms:p:{day}:{phone}"
        n = int(await redis_client.incr(pkey))
        if n == 1:
            await redis_client.expire(pkey, 26 * 3600)
        if n > SMS_MAX_PER_PHONE_DAY:
            return False
        if ip:
            ikey = f"web_sms:i:{day}:{ip}"
            m = int(await redis_client.incr(ikey))
            if m == 1:
                await redis_client.expire(ikey, 26 * 3600)
            if m > SMS_MAX_PER_IP_DAY:
                return False
    except Exception as exc:
        log.warning("sms quota redis: %s", exc)
    return True

DEFAULT_ICE_SERVERS = [
    "stun:stun.l.google.com:19302",
    "stun:stun1.l.google.com:19302",
    "stun:stun2.l.google.com:19302",
    "stun:stun.cloudflare.com:3478",
]


def _get_ice_servers() -> list[str]:
    raw = os.getenv("WEBRTC_ICE_SERVERS", "").strip()
    if not raw:
        return list(DEFAULT_ICE_SERVERS)
    try:
        if raw.startswith("[") and raw.endswith("]"):
            import json
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed if str(x).strip()]
        return [s.strip() for s in raw.split(",") if s.strip()]
    except Exception:
        return list(DEFAULT_ICE_SERVERS)


class RTVIAdapterProcessor(FrameProcessor):
    """Оборачивает входящие сообщения из WebRTC Data Channel в формат RTVI."""

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, InputTransportMessageFrame):
            msg = frame.message
            if isinstance(msg, dict) and msg.get("label") != "rtvi-ai":
                frame.message = {
                    "id": str(uuid.uuid4()),
                    "label": "rtvi-ai",
                    "type": "client-message",
                    "data": msg,
                }
        await self.push_frame(frame, direction)


class WebAbuseProbe(FrameProcessor):
    """Детект зачитывания списка / не-разговора (как AbuseProbe в main.py)."""

    def __init__(self) -> None:
        super().__init__()
        self.replici: list[str] = []
        self.repetari = 0

    @staticmethod
    def _cheie(text: str) -> str:
        cuvinte = re.findall(r"\w+", text.lower())
        return " ".join(sorted(c for c in cuvinte if len(c) > 3))

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, TranscriptionFrame):
            text = (getattr(frame, "text", "") or "").strip()
            if len(text) > 40:
                cheie = self._cheie(text)
                for veche in self.replici:
                    comune = set(cheie.split()) & set(veche.split())
                    if comune and len(comune) >= len(set(cheie.split())) * 0.5:
                        self.repetari += 1
                        break
                self.replici.append(cheie)
        await self.push_frame(frame, direction)


class MicGate(FrameProcessor):
    """Пауза микрофона для модели: пока номер подтверждается, звук посетителя не уходит в модель.

    Первые 1.5 с после закрытия вместо звука идёт тишина — чтобы модель закрыла
    начатую реплику посетителя. Дальше звук не отправляется совсем.
    """

    SILENCE_TAIL_SECONDS = 1.5

    def __init__(self) -> None:
        super().__init__()
        self.closed = False
        self.closed_at = 0.0

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            self.closed_at = time.time()

    def open(self) -> None:
        self.closed = False

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if self.closed and isinstance(frame, InputAudioRawFrame):
            if time.time() - self.closed_at < self.SILENCE_TAIL_SECONDS:
                silence = InputAudioRawFrame(
                    audio=b"\x00" * len(frame.audio),
                    sample_rate=frame.sample_rate,
                    num_channels=frame.num_channels,
                )
                await self.push_frame(silence, direction)
            return
        await self.push_frame(frame, direction)


class LatencyObserver(BaseObserver):
    """Замер задержек одного разговора. Ничего не меняет, только пишет в лог.

    Конец фразы посетителя — последний громкий кусок его звука, пока агент молчит
    (Gemini Live сам не сообщает, когда посетитель замолчал). От этой точки считается:
    когда модель вызвала инструмент, сколько он работал, когда команда ушла на экран,
    когда агент начал говорить. Отрисовку на экране подтверждает виджет.
    """

    SPEECH_RMS = 500  # порог громкости речи (16-бит PCM, около -36 дБ)

    def __init__(self, call_id: str, logger: Any) -> None:
        super().__init__()
        self.call_id = call_id
        self.log = logger
        self._seen: set[int] = set()
        self.bot_speaking = False
        self.speech_end = 0.0
        self.events: list[str] = []
        self.tool_started: dict[str, float] = {}
        self.ui_sent: dict[str, float] = {}
        self.replies_ms: list[int] = []

    def _first_time(self, frame: Frame) -> bool:
        key = frame.id
        sib = getattr(frame, "broadcast_sibling_id", None)
        if sib:
            key = min(frame.id, sib)
        if key in self._seen:
            return False
        if len(self._seen) > 20000:
            self._seen.clear()
        self._seen.add(key)
        return True

    def _rel(self, now: float) -> str:
        return f"+{int((now - self.speech_end) * 1000)}ms" if self.speech_end else "+?"

    async def on_push_frame(self, data: FramePushed) -> None:
        frame = data.frame
        try:
            if isinstance(frame, InputAudioRawFrame):
                if self.bot_speaking or not self._first_time(frame):
                    return
                n = len(frame.audio) // 2
                if n:
                    a = memoryview(frame.audio).cast("h")
                    step = 4
                    acc = 0
                    cnt = 0
                    for i in range(0, n, step):
                        v = a[i]
                        acc += v * v
                        cnt += 1
                    if cnt and (acc / cnt) ** 0.5 >= self.SPEECH_RMS:
                        self.speech_end = time.time()
                        self.events.clear()
                return
            if not isinstance(
                frame,
                (
                    BotStartedSpeakingFrame,
                    BotStoppedSpeakingFrame,
                    FunctionCallInProgressFrame,
                    FunctionCallResultFrame,
                    RTVIUICommandFrame,
                ),
            ):
                return
            if not self._first_time(frame):
                return
            now = time.time()
            if isinstance(frame, FunctionCallInProgressFrame):
                self.tool_started[frame.tool_call_id or frame.function_name] = now
                self.events.append(f"tool {frame.function_name} start {self._rel(now)}")
            elif isinstance(frame, FunctionCallResultFrame):
                t0 = self.tool_started.pop(frame.tool_call_id or frame.function_name, 0.0)
                took = f"{int((now - t0) * 1000)}ms" if t0 else "?"
                self.events.append(f"tool {frame.function_name} done in {took}")
            elif isinstance(frame, RTVIUICommandFrame):
                if frame.command == "set_agent_state":
                    return
                self.ui_sent[frame.command] = now
                self.events.append(f"screen {frame.command} sent {self._rel(now)}")
            elif isinstance(frame, BotStartedSpeakingFrame):
                self.bot_speaking = True
                if self.speech_end:
                    ms = int((now - self.speech_end) * 1000)
                    self.replies_ms.append(ms)
                    tail = (" | " + "; ".join(self.events)) if self.events else ""
                    self.log.info("[%s] TIMING voice %sms after visitor stopped%s", self.call_id, ms, tail)
                self.speech_end = 0.0
                self.events.clear()
            elif isinstance(frame, BotStoppedSpeakingFrame):
                self.bot_speaking = False
        except Exception as exc:  # замер не должен ломать разговор
            self.log.debug("[%s] latency observer: %s", self.call_id, exc)

    def screen_rendered(self, command: str) -> None:
        t0 = self.ui_sent.get(command)
        if t0:
            self.log.info(
                "[%s] TIMING screen %s rendered %sms after it was sent",
                self.call_id, command, int((time.time() - t0) * 1000),
            )

    def summary(self) -> None:
        if not self.replies_ms:
            return
        self.log.info(
            "[%s] TIMING summary replies=%s median=%sms max=%sms",
            self.call_id,
            len(self.replies_ms),
            int(statistics.median(self.replies_ms)),
            max(self.replies_ms),
        )


# Дневной предел минут голоса на сайт клиента (не обходится сменой браузера и адреса)
def _web_day_key(client_id: str) -> tuple[str, int]:
    acum = dt.datetime.now(tz_for(DEFAULT_TZ))
    start_zi = acum.replace(hour=5, minute=0, second=0, microsecond=0)
    if acum < start_zi:
        start_zi -= dt.timedelta(days=1)
    ttl = int((start_zi + dt.timedelta(days=1) - acum).total_seconds()) + 3600
    return f"web_seconds:{start_zi.strftime('%Y%m%d')}:{client_id}", ttl


async def web_seconds_used_today(client_id: str) -> int:
    if not redis_client or not client_id:
        return 0
    key, _ttl = _web_day_key(client_id)
    try:
        return int(await redis_client.get(key) or 0)
    except Exception as exc:
        log.warning("web day budget read: %s", exc)
        return 0


async def web_seconds_add(client_id: str, seconds: int) -> None:
    if not redis_client or not client_id or seconds <= 0:
        return
    key, ttl = _web_day_key(client_id)
    try:
        await redis_client.incrby(key, int(seconds))
        await redis_client.expire(key, ttl)
    except Exception as exc:
        log.warning("web day budget write: %s", exc)


ROI_DEFAULTS = {
    "cost_per_missed_lead": 50.0,
    "ai_monthly_cost": 299.0,
    "capture_rate": 0.35,
}

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

UI_NAVIGATION_TOOL = {
    "name": "control_website_ui",
    "description": (
        "Controls the website interface in real time (Adaptive Workspace & site sections). "
        "Open a prepared view (hero, services, pricing, cases, booking_widget, contacts, roi_calculator) "
        "and optionally highlight an item or prefill form fields."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "section": {
                "type": "string",
                "enum": [
                    "hero",
                    "services",
                    "pricing",
                    "cases",
                    "booking_widget",
                    "contacts",
                    "roi_calculator",
                ],
                "description": "Prepared section or workspace view to display.",
            },
            "highlight_element": {
                "type": "string",
                "description": "Optional element id, plan id, or card key to visually emphasize",
            },
            "prefill_data": {
                "type": "object",
                "description": "Optional data to pre-fill into the visible form (client_name, phone, start_time, request_summary)",
            },
        },
        "required": ["section"],
    },
}

ROI_CALCULATOR_TOOL = {
    "name": "update_roi_calculator",
    "description": (
        "Actualizează calculatorul ROI de pe ecran. Folosește când vizitatorul "
        "spune câte apeluri ratează pe zi / pe lună, costul unui lead pierdut, "
        "sau cere să calculezi economia."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "missed_calls_per_day": {"type": "number"},
            "missed_calls_per_month": {"type": "number"},
            "cost_per_missed_lead": {"type": "number"},
            "ai_monthly_cost": {"type": "number"},
            "capture_rate": {"type": "number"},
        },
    },
}

SCREEN_AUDIT_TOOL = {
    "name": "request_screen_audit",
    "description": (
        "Pornește auditul paginii pe care o vede vizitatorul. Folosește când "
        "cere să evaluezi site-ul, CTA, formularul sau conversia. Clientul va "
        "trimite un rezumat al paginii; tu îl comentezi scurt și poți evidenția zone."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "focus": {
                "type": "string",
                "enum": ["full_page", "cta", "form", "pricing", "hero", "mobile"],
                "description": "Pe ce să se concentreze auditul",
            },
            "reason": {
                "type": "string",
                "description": "De ce ceri auditul (scurt)",
            },
        },
    },
}

# Фаза 3.5 — Real-Time Sentiment UI Morphing
SENTIMENT_MORPH_TOOL = {
    "name": "morph_ui_for_sentiment",
    "description": (
        "Call immediately when you detect doubt, hesitation, price objection, "
        "trust gap or anxiety in the visitor's voice or words "
        "(long pauses, soft/uncertain tone, phrases like 'expensive', 'not sure', "
        "'risky', 'maybe later', 'I need to think'). "
        "Shows trust-building content (cases, guarantees, ROI, contacts) without being pushy."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "signal": {
                "type": "string",
                "enum": [
                    "doubt",
                    "price_objection",
                    "trust_gap",
                    "urgency",
                    "confusion",
                ],
                "description": "Detected emotional / objection signal",
            },
            "suggested_section": {
                "type": "string",
                "enum": [
                    "cases",
                    "pricing",
                    "roi_calculator",
                    "contacts",
                    "booking_widget",
                    "services",
                ],
                "description": "Preferred section to surface (defaults based on signal)",
            },
            "highlight_element": {
                "type": "string",
                "description": "Optional element id to highlight (e.g. 'guarantee', 'roi-result', 'case-byd')",
            },
        },
        "required": ["signal"],
    },
}

FLAG_ABUSE_TOOL = {
    "name": "flag_session_abuse",
    "description": (
        "Call when the visitor is clearly abusing the session: reading a script of "
        "competitor questions, spamming, probing internals, or acting in bad faith. "
        "Triggers on-screen identity verification (not a 'demo ended' message)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": "Short internal reason (repetitions, competitor probing, spam)",
            },
            "severity": {
                "type": "string",
                "enum": ["require_verify", "block"],
                "description": "require_verify first; block only if already verified and abuse continues",
            },
        },
        "required": ["reason"],
    },
}


def _build_tools_with_ui(client_data: dict, readable_hours: str) -> list[dict]:
    base = build_tools(client_data, readable_hours, web=True)
    base.append(UI_NAVIGATION_TOOL)
    base.append(ROI_CALCULATOR_TOOL)
    base.append(SCREEN_AUDIT_TOOL)
    base.append(SENTIMENT_MORPH_TOOL)
    base.append(FLAG_ABUSE_TOOL)
    return [{"function_declarations": base}]


def _build_tools_with_scenes(client_data: dict, readable_hours: str, catalog: dict) -> list[dict]:
    """Режим сцен: одна команда show_scene вместо разделов, калькулятора и «морфинга»."""
    base = build_tools(client_data, readable_hours, web=True)
    base.append(build_scene_tool(catalog))
    base.append(SCREEN_AUDIT_TOOL)
    base.append(FLAG_ABUSE_TOOL)
    return [{"function_declarations": base}]


def _compute_roi(args: dict[str, Any]) -> dict[str, Any]:
    per_day = args.get("missed_calls_per_day")
    per_month = args.get("missed_calls_per_month")
    try:
        if per_month is not None and float(per_month) > 0:
            missed_month = float(per_month)
        elif per_day is not None and float(per_day) > 0:
            missed_month = float(per_day) * 30.0
        else:
            missed_month = 0.0
    except (TypeError, ValueError):
        missed_month = 0.0

    def _num(key: str, default: float) -> float:
        try:
            v = args.get(key)
            if v is None:
                return default
            n = float(v)
            # Model sometimes sends 0 by mistake — treat non-positive as "use default"
            if n <= 0 and key in ("cost_per_missed_lead", "capture_rate", "ai_monthly_cost"):
                return default
            return n
        except (TypeError, ValueError):
            return default

    cost_lead = _num("cost_per_missed_lead", ROI_DEFAULTS["cost_per_missed_lead"])
    ai_cost = _num("ai_monthly_cost", ROI_DEFAULTS["ai_monthly_cost"])
    capture = max(0.0, min(1.0, _num("capture_rate", ROI_DEFAULTS["capture_rate"])))

    recovered = missed_month * capture
    gross_save = recovered * cost_lead
    net_save = gross_save - ai_cost
    payback_days = (ai_cost / (gross_save / 30.0)) if gross_save > 0 else None

    return {
        "missed_calls_per_month": round(missed_month, 1),
        "cost_per_missed_lead": round(cost_lead, 2),
        "ai_monthly_cost": round(ai_cost, 2),
        "capture_rate": round(capture, 2),
        "recovered_leads_per_month": round(recovered, 1),
        "gross_monthly_savings": round(gross_save, 2),
        "net_monthly_savings": round(net_save, 2),
        "payback_days": round(payback_days, 1) if payback_days is not None else None,
    }


# Подписи индикатора на языке разговора (раньше были только английские)
ORB_LABELS = {
    "ru": {
        "screen": "Готовлю экран",
        "roi": "Считаю выгоду",
        "audit": "Смотрю страницу",
        "audit_compose": "Готовлю выводы",
        "calendar": "Проверяю календарь",
        "lead": "Сохраняю заявку",
        "sms": "Отправляю SMS",
    },
    "ro": {
        "screen": "Pregătesc ecranul",
        "roi": "Calculez economia",
        "audit": "Analizez pagina",
        "audit_compose": "Pregătesc concluziile",
        "calendar": "Verific calendarul",
        "lead": "Salvez solicitarea",
        "sms": "Trimit SMS",
    },
    "en": {
        "screen": "Preparing the screen",
        "roi": "Calculating savings",
        "audit": "Reviewing the page",
        "audit_compose": "Preparing feedback",
        "calendar": "Checking the calendar",
        "lead": "Saving your request",
        "sms": "Sending SMS",
    },
}


def _orb_label(lang: str, key: str) -> str:
    return ORB_LABELS.get(lang, ORB_LABELS["en"]).get(key, "")


def _default_section_for_signal(signal: str) -> str:
    return {
        "doubt": "cases",
        "price_objection": "roi_calculator",
        "trust_gap": "cases",
        "urgency": "booking_widget",
        "confusion": "services",
    }.get(signal, "cases")


async def run_webrtc_session(
    transport: SmallWebRTCTransport,
    client_id: str,
    visitor_id: str,
    project_id: str = "",
    *,
    visitor_ip: str = "",
    browser_lang: str = "",
    landing_url: str = "",
    referrer: str = "",
    session_index: int = 1,
    max_session_seconds: int = 180,
) -> None:
    call_id = uuid.uuid4().hex[:8]
    clog = logging.LoggerAdapter(log, {})
    clog.info("[%s] WebRTC session start client=%s visitor=%s", call_id, client_id, visitor_id)

    client_data = await get_client_data(client_id) or {}
    persona = await get_persona(client_id)
    # Browser/device language wins when provided (widget sends navigator.language)
    call_lang = (browser_lang or "").strip() or persona.language or DEFAULT_LANG
    if "-" in call_lang:
        call_lang = call_lang.split("-")[0].lower()
    elif "_" in call_lang:
        call_lang = call_lang.split("_")[0].lower()
    else:
        call_lang = call_lang.lower()[:8]
    tz_name = client_data.get("timezone") or "Europe/Chisinau"
    company = client_data.get("company_name") or client_id
    tg_chat = client_data.get("tg_chat_id_notify") or ""
    start_ts = time.time()

    learned_phone = ""
    visitor_name = ""
    zapis_id = ""
    saved_lead_hashes: set[str] = set()
    dwell_seen: set[str] = set()
    last_roi: dict[str, Any] = {}
    audit_pending_focus: str = ""
    latest_snapshot: Any = None  # Фаза 2.5 — последний ui-snapshot
    sentiment_fired: set[str] = set()  # анти-спам для morph
    deadline_handle = None
    warn_handle = None
    abuse_watch_handle = None
    abuse_stage = "none"  # none | verify_required | verified | blocked
    phone_verified_session = False
    abuse_probe = WebAbuseProbe()
    mic_gate = MicGate()
    latency = LatencyObserver(call_id, clog)
    # Проверка номера кодом из SMS
    verify_stage = "none"  # none | pending | verified
    verify_code = ""
    verify_phone = ""
    verify_expires = 0.0
    verify_attempts = 0
    verify_sends = 0
    verify_last_send = 0.0
    verify_timeout_handle = None
    verify_watch_handle = None

    # Память / карточка по visitor_id (RPC → person_memory через end_client)
    contact, visitor_memory, time_ctx = await get_web_visitor_context(client_id, visitor_id)
    if contact.get("phone") and telefon_valid(contact["phone"]):
        learned_phone = "".join(filter(str.isdigit, str(contact["phone"])))
        phone_verified_session = True
        verify_stage = "verified"  # вернувшийся посетитель с номером в карточке
    visitor_name = (contact.get("name") or "").strip()
    if contact.get("event_id"):
        zapis_id = str(contact["event_id"])
    clog.info(
        "[%s] web visitor memory time_ctx=%s found=%s phone=%s name=%s",
        call_id,
        time_ctx,
        contact.get("found"),
        (learned_phone[:4] + "***") if learned_phone else "-",
        visitor_name or "-",
    )

    # Часы из БД клиента + единая сборка промпта (как в GSM-контуре)
    has_scenes = bool(await load_scene_catalog(client_id))
    hours = parse_working_hours(client_data.get("working_hours"))
    now = dt.datetime.now(tz_for(tz_name))
    system_prompt, readable_hours = build_system_prompt(
        client_data=client_data,
        persona=persona,
        memory=visitor_memory,
        lang=call_lang,
        now=now,
        hours=hours,
        channel="web",
        caller_name=visitor_name,
        landing_url=landing_url,
        referrer=referrer,
        ui_mode="scenes" if has_scenes else "sections",
    )
    clog.info(
        "[%s] session_index=%s max_sec=%s lang=%s prompt_chars=%s",
        call_id, session_index, max_session_seconds, call_lang, len(system_prompt),
    )
    # Сцены из каталога клиента. Нет каталога — старые разделы, как раньше.
    scene_catalog = await load_scene_catalog(client_id)
    scene_lang_used = scene_lang(scene_catalog, call_lang)
    scene_cat_loc = localize_catalog(scene_catalog, scene_lang_used) if scene_catalog else None
    scene_profile: dict[str, Any] = {}
    scene_values: dict[str, float] = {}  # цифры посетителя: поля подбора тарифа и калькулятора из каталога
    scene_billing = "month"
    if scene_catalog:
        system_prompt = system_prompt + "\n\n" + build_scene_prompt(scene_catalog, scene_lang_used)
        tools = _build_tools_with_scenes(client_data, readable_hours, scene_catalog)
        ui_tool = "show_scene"
    else:
        tools = _build_tools_with_ui(client_data, readable_hours)
        ui_tool = "control_website_ui"
    clog.info("[%s] ui mode=%s", call_id, "scenes" if scene_catalog else "sections")

    wav_path = f"/tmp/webrtc_{call_id}.wav"
    mixer = WebAudioMixer(wav_path)
    user_catcher = WebUserAudioCatcher(mixer)
    ai_catcher = WebAIAudioCatcher(mixer)

    vad_start = (os.getenv("WEBRTC_VAD_START_SENSITIVITY", "high") or "high").strip().lower()
    vad_end = (os.getenv("WEBRTC_VAD_END_SENSITIVITY", "high") or "high").strip().lower()
    start_sens = (
        StartSensitivity.START_SENSITIVITY_HIGH
        if vad_start == "high" and StartSensitivity is not None
        else (StartSensitivity.START_SENSITIVITY_LOW if StartSensitivity is not None else "START_SENSITIVITY_HIGH")
    )
    end_sens = (
        EndSensitivity.END_SENSITIVITY_HIGH
        if vad_end == "high" and EndSensitivity is not None
        else (EndSensitivity.END_SENSITIVITY_LOW if EndSensitivity is not None else "END_SENSITIVITY_HIGH")
    )

    llm = GeminiLiveLLMService(
        api_key=GEMINI_API_KEY,
        tools=tools,
        settings=GeminiLiveLLMService.Settings(
            model=GEMINI_MODEL,
            voice=resolve_voice_name(persona.voice_model),
            system_instruction=system_prompt,
            vad=GeminiVADParams(
                start_sensitivity=start_sens,
                end_sensitivity=end_sens,
            ),
        ),
    )

    rtvi_adapter = RTVIAdapterProcessor()
    rtvi = RTVIProcessor()
    rtvi_observer = RTVIObserver(
        rtvi,
        params=RTVIObserverParams(
            function_call_report_level={
                "*": RTVIFunctionCallReportLevel.NAME,
                "control_website_ui": RTVIFunctionCallReportLevel.FULL,
                "show_scene": RTVIFunctionCallReportLevel.FULL,
                "update_roi_calculator": RTVIFunctionCallReportLevel.FULL,
                "request_screen_audit": RTVIFunctionCallReportLevel.FULL,
                "morph_ui_for_sentiment": RTVIFunctionCallReportLevel.FULL,
                "flag_session_abuse": RTVIFunctionCallReportLevel.FULL,
                "Booking_tool": RTVIFunctionCallReportLevel.FULL,
            }
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
    task: Optional[PipelineTask] = None
    orb_reset_handle: Optional[asyncio.Task] = None

    # ----- Индикатор (Thinking Orb): переключает сервер, не модель -----

    async def _orb(state: str, label_key: str = "") -> None:
        """Показать состояние индикатора. Отменяет отложенный возврат в покой."""
        nonlocal orb_reset_handle
        if orb_reset_handle is not None and not orb_reset_handle.done():
            orb_reset_handle.cancel()
        orb_reset_handle = None
        if task is None:
            return
        payload: dict[str, Any] = {"state": state}
        label = _orb_label(call_lang, label_key) if label_key else ""
        if label:
            payload["label"] = label
        with contextlib.suppress(Exception):
            await task.queue_frames([RTVIUICommandFrame(command="set_agent_state", payload=payload)])

    async def _orb_rest(after: float = 0.0) -> None:
        """Вернуть индикатор в спокойное состояние сразу или через `after` секунд."""
        nonlocal orb_reset_handle
        if after <= 0:
            await _orb("breathing")
            return

        async def _later() -> None:
            nonlocal orb_reset_handle
            try:
                await asyncio.sleep(after)
                orb_reset_handle = None
                if task is not None:
                    with contextlib.suppress(Exception):
                        await task.queue_frames([
                            RTVIUICommandFrame(command="set_agent_state", payload={"state": "breathing"})
                        ])
            except asyncio.CancelledError:
                return

        if orb_reset_handle is not None and not orb_reset_handle.done():
            orb_reset_handle.cancel()
        orb_reset_handle = asyncio.create_task(_later())

    def _booking_prefill(extra: dict | None) -> dict:
        """Карточка записи: имя и подтверждённый номер подставляет сервер, не модель."""
        out = dict(extra or {})
        if not out.get("client_name") and visitor_name:
            out["client_name"] = visitor_name
        if learned_phone:
            out["phone"] = "+" + learned_phone
        return out

    # ----- Tool handlers -----

    async def process_control_website_ui(params: FunctionCallParams):
        section = params.arguments.get("section", "hero")
        highlight = params.arguments.get("highlight_element")
        prefill = params.arguments.get("prefill_data") or {}
        components = params.arguments.get("components")  # CONCEPT mode (optional)

        if section in ("booking_widget", "contacts"):
            if not phone_verified_session:
                await _start_verification("booking")
                await params.result_callback({
                    "status": "verify_first",
                    "instruction": (
                        "The visitor's phone is not verified yet. Phone verification is now on screen. "
                        "Wait for SYSTEM UI EVENT that the phone is verified, then show booking_widget again."
                    ),
                })
                return
            section = "booking_widget"
            prefill = _booking_prefill(prefill)

        payload: dict[str, Any] = {
            "section": section,
            "highlight": highlight,
            "prefill": prefill,
        }
        if components:
            payload["components"] = components

        await _orb("shaping", "screen")
        if task is not None:
            await task.queue_frames([
                RTVIUICommandFrame(
                    command="navigate_and_render",
                    payload=payload,
                ),
            ])
        await _orb_rest(1.2)
        await params.result_callback({
            "status": "ui_updated",
            "active_section": section,
            "has_components": bool(components),
            "instruction": (
                f"Section '{section}' is now shown on screen"
                + (" (with custom components)" if components else "")
                + ". Give a short spoken summary of what the visitor sees."
            ),
        })

    async def process_show_scene(params: FunctionCallParams):
        """Сцена из каталога. Тариф и расчёт считает сервер по правилам каталога; модель озвучивает результат."""
        nonlocal scene_billing
        args = params.arguments or {}
        cat = scene_catalog or {}
        loc = scene_cat_loc or {}
        available = scene_available(cat)
        scene = str(args.get("scene") or "welcome")
        if scene == "roi":
            scene = "calculator"
        if scene not in available:
            scene = "welcome"

        for k in ("activity", "problem", "volume"):
            v = str(args.get(k) or "").strip()
            if v:
                scene_profile[k] = v[:90]
        for f in _extra_fields(cat):
            with contextlib.suppress(TypeError, ValueError):
                v = float(args.get(f["id"]))
                if v > 0:
                    scene_values[f["id"]] = v
        if args.get("billing") in ("month", "year"):
            scene_billing = args["billing"]

        plans_loc = _catalog_plans(loc)
        by_id = {p.get("id"): p for p in plans_loc}
        picker = _picker(cat)
        has_numbers = any(scene_values.get(f.get("id")) for f in (picker.get("inputs") or []) + (picker.get("limits") or []))
        need = scene_need(cat, scene_values) if picker else 0.0
        if picker and has_numbers:
            rec = scene_pick_plan(loc, need, scene_values)
        else:
            rec = next((p for p in plans_loc if p.get("popular")), plans_loc[0] if plans_loc else None)
        rec_id = (rec or {}).get("id")
        if has_numbers and rec_id:
            scene_profile["solution_plan"] = rec_id
        fits = {p.get("id"): scene_plan_fits(loc, p, need, scene_values) for p in plans_loc} if has_numbers else {}

        def _price(p: dict) -> float:
            return float((p.get("year") if scene_billing == "year" and p.get("year") else p.get("month")) or 0)

        def _calc_values(p: Optional[dict]) -> dict:
            v: dict[str, float] = {"plan_price": _price(p) if p else 0.0}
            for inp in _calculator(cat).get("inputs") or []:
                v[inp["id"]] = float(scene_values.get(inp["id"]) or inp.get("default") or 0)
            return v

        def _plan_facts(p: dict) -> dict:
            return {
                "plan": p.get("name"),
                "price_month": p.get("month"),
                "price_month_paid_yearly": p.get("year"),
                "what_it_includes": p.get("highlight"),
                "fits_visitor": fits.get(p.get("id"), True),
            }

        scene_args: dict[str, Any] = {"billing": scene_billing}
        result: dict[str, Any] = {"status": "scene_shown", "scene": scene}
        orb_state, orb_key = "shaping", "screen"

        if scene == "services":
            valid = {str(x.get("id")) for x in (loc.get("services") or []) if isinstance(x, dict)}
            ids = [str(x) for x in (args.get("services") or []) if str(x) in valid][:2]
            reasons_in = [str(x).strip()[:140] for x in (args.get("service_reasons") or [])]
            scene_args["highlight"] = ids
            scene_args["reasons"] = {sid: reasons_in[i] for i, sid in enumerate(ids) if i < len(reasons_in) and reasons_in[i]}
            result["instruction"] = "Say in one sentence how this solves their problem, then ask the next qualifying question."
        elif scene == "plans":
            scene_args.update({"rec": rec_id, "need": round(need), "fits": fits,
                               "reason": str(args.get("reason") or "").strip()[:160]})
            if rec:
                result.update(_plan_facts(rec))
            if has_numbers or not picker:
                result["instruction"] = (
                    "Say the plan name, its monthly price and the main reason in one or two sentences. Details are on screen."
                )
            else:
                result["instruction"] = (
                    "No numbers yet, so the most popular plan is shown. Ask for the numbers listed in <CATALOG> "
                    "(to pick a plan), then call show_scene(scene='plans') again with them."
                )
        elif scene == "compare":
            ids = [p.get("id") for p in plans_loc]
            other = str(args.get("compare_plan") or "")
            if other not in by_id or other == rec_id:
                i = ids.index(rec_id) if rec_id in ids else 0
                other = ids[i - 1] if i > 0 else (ids[i + 1] if i + 1 < len(ids) else rec_id)
            a, b = (other, rec_id) if ids.index(other) <= ids.index(rec_id) else (rec_id, other)
            scene_args.update({"a": a, "b": b, "need": round(need), "fits": fits})
            if any(scene_values.get(i_["id"]) for i_ in _calculator(cat).get("inputs") or []):
                scene_args["calc"] = {k: v for k, v in _calc_values(None).items() if k != "plan_price"}
            result["recommended"] = _plan_facts(by_id[rec_id]) if rec_id in by_id else {}
            result["other"] = _plan_facts(by_id[other]) if other in by_id else {}
            result["instruction"] = "Explain the key difference in one or two sentences using these facts. The table is on screen."
        elif scene == "calculator":
            orb_state, orb_key = "solving", "roi"
            calc = _calculator(loc)
            vals = _calc_values(rec)
            scene_args.update({"plan": rec_id, "calc": {k: v for k, v in vals.items() if k != "plan_price"}})
            figures = {}
            for o in calc.get("outputs") or []:
                val = calc_expr(o.get("expr"), vals)
                if val is not None:
                    figures[str(o.get("label") or o.get("id"))] = round(val, 1)
            result.update({"plan": (rec or {}).get("name"), "inputs": vals, "figures": figures,
                           "instruction": "Say the main figure and the payback (if any) in one sentence. The calculation is on screen."})
        elif scene == "case":
            cs = [x for x in (loc.get("cases") or []) if isinstance(x, dict)]
            if cs:
                scene_args["id"] = cs[0].get("id")
                result["case"] = {k: cs[0].get(k) for k in ("industry", "before", "after", "unit", "metric", "period", "example")}
            result["instruction"] = "Tell the result in one sentence. If example=true, do not present it as a real client."
        elif scene == "clients":
            result["clients"] = [x.get("name") for x in (loc.get("clients") or []) if isinstance(x, dict)]
            result["instruction"] = "Name two or three of these clients in one sentence."
        elif scene == "trust":
            result["instruction"] = "Answer the concern in one or two sentences; the proof is on screen."
        elif scene == "contacts":
            result["instruction"] = (
                "The phone numbers, email and social links are on screen. Tapping 'Call' ends this site conversation "
                "and opens the phone call. Offer the booking as the alternative."
            )
        elif scene == "booking":
            if not phone_verified_session:
                await _start_verification("booking")
                await params.result_callback({
                    "status": "verify_first",
                    "instruction": (
                        "The visitor's phone is not verified yet. Phone verification is now on screen. "
                        "Wait for SYSTEM UI EVENT that the phone is verified, then call show_scene(scene='booking') again."
                    ),
                })
                return
            orb_state, orb_key = "searching", "calendar"
            scene_args.update(_booking_prefill({
                "start_time": str(args.get("start_time") or "").strip()[:40],
                "end_time": str(args.get("end_time") or "").strip()[:40],
                "request_summary": str(args.get("request_summary") or "").strip()[:200],
            }))
            result["instruction"] = "Ask once whether everything on the card is correct. On a clear yes call Booking_tool action='book'."
        else:
            result["instruction"] = "Continue the conversation; ask one forward question."

        await _orb(orb_state, orb_key)
        if task is not None:
            await task.queue_frames([
                RTVIUICommandFrame(
                    command="show_scene",
                    payload={
                        "scene": scene,
                        "args": scene_args,
                        "profile": dict(scene_profile),
                        "agent": persona.persona_name or "",
                    },
                ),
            ])
        await _orb_rest(1.2)
        await params.result_callback(result)

    async def process_update_roi(params: FunctionCallParams):
        nonlocal last_roi
        result = _compute_roi(params.arguments or {})
        last_roi = result
        await _orb("solving", "roi")
        if task is not None:
            await task.queue_frames([
                RTVIUICommandFrame(command="update_roi", payload=result),
            ])
        await _orb_rest(1.5)

        await params.result_callback({
            "status": "roi_updated",
            "figures": result,
            "instruction": (
                f"Calculator is on screen. Net monthly savings: "
                f"{result.get('net_monthly_savings')}. Speak this briefly."
            ),
        })

    async def process_request_screen_audit(params: FunctionCallParams):
        nonlocal audit_pending_focus
        focus = str(params.arguments.get("focus") or "full_page")
        reason = str(params.arguments.get("reason") or "")
        audit_pending_focus = focus
        await _orb("searching", "audit")
        if task is not None:
            await task.queue_frames([
                RTVIUICommandFrame(
                    command="start_screen_audit",
                    payload={"focus": focus, "reason": reason},
                ),
            ])
        await params.result_callback({
            "status": "audit_requested",
            "focus": focus,
            "instruction": (
                "Tell the visitor briefly that you are reviewing the page. "
                "Wait for SYSTEM UI EVENT with the page summary before giving findings."
            ),
        })

    async def process_morph_ui_for_sentiment(params: FunctionCallParams):
        """Фаза 3.5 — эмоционально-реактивная морфология UI."""
        signal = str(params.arguments.get("signal") or "doubt")
        section = (
            params.arguments.get("suggested_section")
            or _default_section_for_signal(signal)
        )
        highlight = params.arguments.get("highlight_element")
        if not highlight:
            highlight = {
                "doubt": "guarantee",
                "price_objection": "roi-result",
                "trust_gap": "cases-grid",
                "urgency": "booking-slot",
                "confusion": "services-bento",
            }.get(signal)

        # Анти-спам: один раз на сигнал за сессию
        if signal in sentiment_fired:
            await params.result_callback({
                "status": "already_shown",
                "instruction": "You already reacted to this signal. Continue the conversation naturally.",
            })
            return
        sentiment_fired.add(signal)

        morph_prefill: dict[str, Any] = {"sentiment_signal": signal}
        if section in ("booking_widget", "contacts"):
            if not phone_verified_session:
                section = "cases"
            else:
                section = "booking_widget"
                morph_prefill = _booking_prefill(morph_prefill)

        await _orb("shaping", "screen")
        if task is not None:
            frames = [
                RTVIUICommandFrame(
                    command="navigate_and_render",
                    payload={
                        "section": section,
                        "highlight": highlight,
                        "prefill": morph_prefill,
                    },
                )
            ]
            # Дополнительный highlight для гарантий / кейсов
            if highlight:
                frames.append(
                    RTVIUICommandFrame(
                        command="highlight",
                        payload={"target_id": highlight, "duration_ms": 3500},
                    )
                )
            await task.queue_frames(frames)
        await _orb_rest(1.2)

        await params.result_callback({
            "status": "ui_morphed",
            "signal": signal,
            "active_section": section,
            "instruction": (
                f"UI now shows '{section}' with trust content for signal '{signal}'. "
                "Give one short empathetic sentence and point to what is on screen. "
                "Do not over-sell."
            ),
        })

    async def process_save_lead(params: FunctionCallParams):
        nonlocal learned_phone, visitor_name
        lead_name = str(params.arguments.get("client_name") or "").strip()
        if lead_name:
            visitor_name = lead_name
        phone = str(params.arguments.get("client_phone") or "").strip()
        if not phone and learned_phone:
            params.arguments["client_phone"] = phone = learned_phone
        if telefon_valid(phone):
            learned_phone = phone

        digest = hashlib.sha256(
            f"{params.arguments.get('client_name')}|{phone}|{params.arguments.get('request_summary')}".encode()
        ).hexdigest()
        if digest in saved_lead_hashes:
            await params.result_callback({"status": "success", "message": "Deja salvat."})
            return

        await _orb("working", "lead")
        try:
            result = await call_n8n(
                "save_lead",
                {"client_id": client_id, "tg_chat_id": tg_chat or ""},
                params.arguments,
                5.0,
            )
            saved_lead_hashes.add(digest)
            await _orb_rest()
            await params.result_callback(result)
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                await params.result_callback({"status": "cancelled"})
            raise
        except Exception as exc:
            await _orb_rest()
            await send_tg_alert(
                tg_chat,
                f"⚠️ <b>Eroare API (save_lead)</b>\n🏢 {company}\n🔧 <code>{html.escape(str(exc))}</code>",
            )
            await params.result_callback({"error": f"Eroare CRM: {exc}"})

    async def process_booking(params: FunctionCallParams):
        nonlocal learned_phone, zapis_id, visitor_name
        book_name = str(params.arguments.get("client_name") or "").strip()
        if book_name:
            visitor_name = book_name
        phone_arg = str(params.arguments.get("phone") or "").strip()
        if not phone_arg and learned_phone:
            params.arguments["phone"] = phone_arg = learned_phone
        if telefon_valid(phone_arg):
            learned_phone = phone_arg

        action = params.arguments.get("action")
        normalizeaza_timp(params.arguments, tz_name)

        if action == "book" and not telefon_valid(phone_arg):
            await _start_verification("booking")
            await params.result_callback({
                "status": "verify_first",
                "message": (
                    "Numărul nu este confirmat. Pe ecran este verificarea prin SMS. "
                    "Nu cere numărul pe voce. Așteaptă SYSTEM UI EVENT că numărul e confirmat, "
                    "apoi arată cardul booking_widget și cere confirmarea."
                ),
            })
            return

        if action in ("cancel", "reschedule"):
            if not zapis_id:
                await params.result_callback(FARA_PROGRAMARE)
                return
            params.arguments["event_id"] = zapis_id

        params_n8n = {
            "client_id": client_id,
            "google_calendar_id": client_data.get("google_calendar_id") or "",
        }
        await _orb("searching", "calendar")
        try:
            if action == "book":
                proba = await call_n8n(
                    "booking", params_n8n, {**params.arguments, "action": "check"}, 10.0
                )
                if not slot_liber(proba):
                    await _orb_rest()
                    await params.result_callback(proba)
                    return
            result = await call_n8n("booking", params_n8n, params.arguments, 10.0)
            zapis_id = id_zapisi(result) or zapis_id
            if action == "lookup":
                zapis_id = id_din_lookup(result) or zapis_id
            if action == "cancel":
                zapis_id = ""
            await _orb_rest()
            await params.result_callback(result)
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                await params.result_callback({"status": "cancelled"})
            raise
        except Exception as exc:
            await _orb_rest()
            await send_tg_alert(
                tg_chat,
                f"⚠️ <b>Eroare API (Booking_tool)</b>\n🏢 {company}\n🔧 <code>{html.escape(str(exc))}</code>",
            )
            await params.result_callback({"status": "error", "message": str(exc)})

    async def process_sms(params: FunctionCallParams):
        phone = str(params.arguments.get("phone") or "").strip()
        if not phone and learned_phone:
            params.arguments["phone"] = phone = learned_phone
        if not telefon_valid(phone):
            await params.result_callback(TELEFON_INCOMPLET)
            return
        await _orb("working", "sms")
        try:
            result = await call_n8n(
                "send_sms",
                {"client_id": client_id},
                params.arguments,
                5.0,
            )
            await _orb_rest()
            await params.result_callback(result)
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                await params.result_callback({"status": "cancelled"})
            raise
        except Exception as exc:
            await _orb_rest()
            await params.result_callback({"status": "error", "message": str(exc)})

    async def process_end_call(params: FunctionCallParams):
        reason = str(params.arguments.get("reason") or "natural_end")
        elapsed = time.time() - start_ts
        if elapsed < MIN_SECONDS_BEFORE_END_CALL:
            await params.result_callback({
                "status": "too_early",
                "message": f"Call is only {elapsed:.0f}s old. Continue the conversation.",
            })
            return
        if task is not None:
            await task.queue_frames([CancelFrame()])
        await params.result_callback({"status": "ending", "reason": reason})

    # Register tools

    # ----- Проверка номера кодом из SMS -----

    async def _verify_timeout() -> None:
        """Номер не подтверждён за отведённое время — голос вежливо завершается."""
        try:
            await asyncio.sleep(VERIFY_TIMEOUT_SECONDS)
            if verify_stage == "verified" or task is None:
                return
            clog.info("[%s] verification timeout — ending voice", call_id)
            await task.queue_frames([
                RTVIUICommandFrame(
                    command="session_ended",
                    payload={"reason": "verify_timeout", "session_index": session_index},
                ),
                CancelFrame(),
            ])
        except asyncio.CancelledError:
            return
        except Exception as exc:
            clog.warning("[%s] verify timeout error: %s", call_id, exc)

    def _restart_verify_timeout() -> None:
        nonlocal verify_timeout_handle
        if verify_timeout_handle is not None and not verify_timeout_handle.done():
            verify_timeout_handle.cancel()
        verify_timeout_handle = asyncio.create_task(_verify_timeout())

    async def _start_verification(reason: str) -> None:
        nonlocal verify_stage
        if verify_stage != "none" or phone_verified_session or abuse_stage == "blocked":
            return
        verify_stage = "pending"
        clog.info("[%s] phone verification started reason=%s", call_id, reason)
        if task is None:
            return
        await task.queue_frames([
            RTVIUICommandFrame(
                command="require_phone_verification",
                payload={"reason": reason},
            )
        ])
        context.add_message({
            "role": "user",
            "content": (
                "SYSTEM: Phone verification starts now. If the visitor just asked something, "
                "answer it in one short sentence first. Then say honestly and briefly: because of "
                "bad-faith visitors and competitors we confirm the phone number; the field is on "
                "screen, the phone suggests the number by itself and the SMS code arrives in seconds; "
                "you will continue right after. The visitor's microphone is paused until then — "
                "you will not hear them, so say it once and then stay silent. "
                "Never ask to dictate the number. No 'demo' wording."
            ),
        })
        await task.queue_frames([LLMRunFrame()])
        # Пока номер подтверждается, голос посетителя в модель не идёт
        mic_gate.close()
        _restart_verify_timeout()

    async def _verify_watch() -> None:
        """Проверка начинается после N реплик посетителя или через N секунд."""
        try:
            while True:
                await asyncio.sleep(1.0)
                if verify_stage != "none" or phone_verified_session:
                    return
                elapsed = time.time() - start_ts
                turns = 0
                with contextlib.suppress(Exception):
                    _t, turns = build_transcript(list(getattr(context, "messages", None) or []))
                if turns >= VERIFY_AFTER_TURNS or elapsed >= VERIFY_AFTER_SECONDS:
                    await _start_verification(f"early_gate turns={turns} t={int(elapsed)}")
                    return
        except asyncio.CancelledError:
            return
        except Exception as exc:
            clog.warning("[%s] verify watch error: %s", call_id, exc)

    async def _verify_state(state: str, **extra: Any) -> None:
        if task is None:
            return
        await task.queue_frames([
            RTVIUICommandFrame(command="verify_state", payload={"state": state, **extra})
        ])

    async def _verify_request_code(raw_phone: str) -> None:
        nonlocal verify_code, verify_phone, verify_expires, verify_attempts
        nonlocal verify_sends, verify_last_send, verify_stage
        if phone_verified_session:
            await _verify_state("verified")
            return
        phone = normalize_md_phone(raw_phone)
        if not phone:
            await _verify_state("bad_phone")
            return
        now_ts = time.time()
        if verify_last_send and now_ts - verify_last_send < SMS_RESEND_SECONDS:
            await _verify_state("wait", seconds=int(SMS_RESEND_SECONDS - (now_ts - verify_last_send)) + 1)
            return
        if verify_sends >= SMS_MAX_PER_SESSION or not await _sms_quota_ok(phone, visitor_ip):
            clog.warning("[%s] sms limit phone=%s***", call_id, phone[:6])
            await _verify_state("limit")
            return
        code = f"{secrets.randbelow(1_000_000):06d}"
        lang_key = call_lang if call_lang in SMS_CODE_TEXT else "en"
        text = SMS_CODE_TEXT[lang_key].format(company=company, code=code)
        host = _host_of(landing_url)
        if host:
            text += f"\n\n@{host} #{code}"
        if WEB_SMS_DEBUG:
            clog.warning("[%s] WEB_SMS_DEBUG code=%s phone=%s", call_id, code, phone)
        else:
            try:
                await _orb("working", "sms")
                result = await call_n8n(
                    "send_sms",
                    {"client_id": client_id},
                    {"phone": "+" + phone, "text": text, "purpose": "web_verify"},
                    10.0,
                )
                await _orb_rest()
                if isinstance(result, dict) and str(result.get("status") or "").lower() == "error":
                    raise RuntimeError(str(result.get("message") or "sms error"))
            except Exception as exc:
                await _orb_rest()
                clog.warning("[%s] verification sms failed: %s", call_id, exc)
                await _verify_state("sms_failed")
                return
        verify_stage = "pending"
        verify_code = code
        verify_phone = phone
        verify_expires = now_ts + SMS_CODE_TTL_SECONDS
        verify_attempts = 0
        verify_sends += 1
        verify_last_send = now_ts
        clog.info("[%s] verification code sent phone=%s*** send=%s", call_id, phone[:6], verify_sends)
        await _verify_state("code_sent", phone="+" + phone)
        _restart_verify_timeout()

    async def _verify_submit_code(raw_code: str) -> None:
        nonlocal verify_code, verify_attempts, verify_stage, learned_phone
        nonlocal phone_verified_session, abuse_stage, deadline_handle, warn_handle
        if phone_verified_session:
            await _verify_state("verified")
            return
        code = "".join(ch for ch in str(raw_code or "") if ch.isdigit())
        if not verify_code or time.time() > verify_expires:
            verify_code = ""
            await _verify_state("expired")
            return
        verify_attempts += 1
        if not hmac.compare_digest(code, verify_code):
            left = SMS_CODE_ATTEMPTS - verify_attempts
            if left <= 0:
                verify_code = ""
                await _verify_state("expired")
            else:
                await _verify_state("bad_code", attempts_left=left)
            return
        # Номер подтверждён
        verify_code = ""
        verify_stage = "verified"
        learned_phone = verify_phone
        phone_verified_session = True
        if abuse_stage == "verify_required":
            abuse_stage = "verified"
        if verify_timeout_handle is not None and not verify_timeout_handle.done():
            verify_timeout_handle.cancel()
        mic_gate.open()
        clog.info("[%s] phone verified by SMS code phone=%s***", call_id, learned_phone[:6])
        await _verify_state("verified", phone="+" + learned_phone)
        # Время разговора считается заново с момента подтверждения
        with contextlib.suppress(Exception):
            deadline_handle.cancel()
        with contextlib.suppress(Exception):
            warn_handle.cancel()
        warn_handle = asyncio.create_task(_session_soft_warn())
        deadline_handle = asyncio.create_task(_session_deadline())
        context.add_message({
            "role": "user",
            "content": (
                "SYSTEM UI EVENT: the visitor's phone is verified by SMS code. Thank them in a few "
                "words and continue the consultation from where you stopped. Never ask for the "
                "phone again — it is known and will be used for booking and the lead."
            ),
        })
        if task is not None:
            await task.queue_frames([LLMRunFrame()])

    async def _require_verify(reason: str) -> None:
        """Подозрительное поведение до подтверждения номера → проверка номера."""
        nonlocal abuse_stage
        if abuse_stage in ("verify_required", "blocked"):
            return
        abuse_stage = "verify_required"
        clog.warning("[%s] abuse verify required: %s", call_id, reason)
        await _start_verification(f"abuse:{reason}")

    async def _block_abuse(reason: str) -> None:
        nonlocal abuse_stage
        abuse_stage = "blocked"
        clog.warning("[%s] abuse block: %s", call_id, reason)
        await blocheaza(client_id, visitor_id, visitor_ip, reason)
        if task is not None:
            await task.queue_frames([
                RTVIUICommandFrame(
                    command="session_blocked",
                    payload={"reason": reason},
                ),
                CancelFrame(),
            ])

    async def process_flag_session_abuse(params: FunctionCallParams):
        reason = str(params.arguments.get("reason") or "flagged").strip()[:120]
        severity = str(params.arguments.get("severity") or "require_verify").strip()
        if severity == "block" and (phone_verified_session or abuse_stage == "verified"):
            await params.result_callback({"status": "blocked", "reason": reason})
            await _block_abuse(f"post_verify:{reason}")
            return
        if abuse_stage == "none" or not phone_verified_session:
            await _require_verify(reason)
            await params.result_callback({
                "status": "verify_required",
                "instruction": "Ask visitor to confirm phone on screen. No demo wording.",
            })
            return
        # Already verified once in this session and model asks block / re-flag
        await params.result_callback({"status": "blocked", "reason": reason})
        await _block_abuse(f"repeat_after_verify:{reason}")

    llm.register_function("control_website_ui", process_control_website_ui)
    llm.register_function("show_scene", process_show_scene)
    llm.register_function("flag_session_abuse", process_flag_session_abuse)
    llm.register_function("update_roi_calculator", process_update_roi)
    llm.register_function("request_screen_audit", process_request_screen_audit)
    llm.register_function("morph_ui_for_sentiment", process_morph_ui_for_sentiment)
    llm.register_function("save_lead", process_save_lead)
    llm.register_function("Booking_tool", process_booking)
    llm.register_function("send_sms", process_sms)
    llm.register_function("end_call", process_end_call)

    # ----- UI event / snapshot handlers (Фаза 2.5 + 3.x) -----

    @rtvi.event_handler("on_client_message")
    async def on_client_message(rtvi_proc, msg):
        nonlocal audit_pending_focus, visitor_name
        msg_type = getattr(msg, "type", None) or (msg.get("type") if isinstance(msg, dict) else None)
        data = getattr(msg, "data", None) or (msg.get("data") if isinstance(msg, dict) else {}) or {}
        if isinstance(data, dict) and "type" in data:
            msg_type = data.get("type")
            data = data.get("data") or {}
        if msg_type != "ui_user_interaction":
            return

        interaction = str(data.get("interaction") or data.get("event") or "click").lower()
        element_id = str(data.get("element_id") or data.get("element") or "").strip()
        section = str(data.get("section") or "").strip()
        dwell_ms = data.get("dwell_ms") or data.get("duration_ms") or 0
        try:
            dwell_sec = float(dwell_ms) / 1000.0 if float(dwell_ms) > 20 else float(dwell_ms)
        except (TypeError, ValueError):
            dwell_sec = 0.0

        # ----- Виджет подтвердил отрисовку экрана (только для замера, в модель не идёт) -----
        if interaction == "ui_rendered":
            latency.screen_rendered(str(data.get("command") or ""))
            return

        # ----- Escape: visitor chose "don't want to talk" -----
        if interaction in ("escape", "mute_voice", "dont_want_to_talk", "decline_voice"):
            clog.info("[%s] visitor escape interaction=%s", call_id, interaction)
            context.add_message({
                "role": "user",
                "content": "SYSTEM UI EVENT: visitor chose not to continue by voice. End the voice session immediately. Do not argue.",
            })
            if task is not None:
                await task.queue_frames([CancelFrame()])
            return

        # ----- Проверка номера кодом из SMS -----
        if interaction == "verify_request_code":
            await _verify_request_code(str(data.get("phone") or ""))
            return
        if interaction == "verify_submit_code":
            await _verify_submit_code(str(data.get("code") or ""))
            return
        if interaction in ("phone_verified", "verify_phone"):
            # Номер без кода больше не принимается как подтверждённый
            clog.info("[%s] ignored unverified phone from UI", call_id)
            return

        # ----- Карточка записи подтверждена на экране -----
        # ----- Scene layer: visitor moved the calculator sliders / tapped Call -----
        if interaction == "roi_adjusted":
            ids = {str(f.get("id")) for f in (_calculator(scene_catalog or {}).get("inputs") or [])}
            changed = {}
            for key, val in (data or {}).items():
                if key in ids:
                    with contextlib.suppress(TypeError, ValueError):
                        v = float(val)
                        if v > 0:
                            scene_values[key] = v
                            changed[key] = v
            if changed:
                context.add_message({
                    "role": "user",
                    "content": (
                        "SYSTEM UI EVENT: the visitor adjusted the calculator on screen: "
                        + ", ".join(f"{k}={v:g}" for k, v in changed.items())
                        + ". Use these numbers from now on; do not comment unless asked."
                    ),
                })
            return
        if interaction == "call_tap":
            clog.info("[%s] visitor tapped Call on the contacts scene — site session ends", call_id)
            return

        if interaction == "booking_confirmed":
            bc_name = str(data.get("client_name") or "").strip()[:80]
            bc_start = str(data.get("start_time") or "").strip()[:40]
            bc_end = str(data.get("end_time") or "").strip()[:40]
            bc_note = str(data.get("request_summary") or "").strip()[:300]
            if bc_name:
                visitor_name = bc_name
            if not phone_verified_session:
                await _start_verification("booking")
                return
            context.add_message({
                "role": "user",
                "content": (
                    "SYSTEM UI EVENT: the visitor confirmed the booking card on screen: "
                    f"client_name={bc_name or visitor_name or '-'}, start_time={bc_start or '-'}"
                    + (f", end_time={bc_end}" if bc_end else "")
                    + (f", request_summary={bc_note}" if bc_note else "")
                    + ". Call Booking_tool action='book' now with exactly these details "
                    "(the verified phone is filled in automatically), then confirm briefly aloud."
                ),
            })
            if task is not None:
                await task.queue_frames([LLMRunFrame()])
            return

        # ----- Screen audit result from client -----
        if interaction == "screen_audit":
            page_summary = str(data.get("page_summary") or data.get("summary") or "").strip()
            issues = data.get("issues") or []
            url = str(data.get("url") or "").strip()
            focus = str(data.get("focus") or audit_pending_focus or "full_page")
            audit_pending_focus = ""
            if not page_summary and not issues:
                return
            issues_txt = ""
            if isinstance(issues, list) and issues:
                issues_txt = "; issues hint: " + ", ".join(str(x) for x in issues[:8])
            context.add_message({
                "role": "user",
                "content": (
                    f"SYSTEM UI EVENT: SCREEN AUDIT (focus={focus}"
                    f"{', url=' + url if url else ''}): {page_summary}{issues_txt}. "
                    f"Give 2–3 concrete observations. Optionally call {ui_tool} "
                    "to show a relevant screen. Do not invent content not in this summary."
                ),
            })
            await _orb("composing", "audit_compose")
            await _orb_rest(4.0)
            if task is not None:
                await task.queue_frames([LLMRunFrame()])
            return

        # ----- Dwell -----
        if interaction == "dwell":
            if dwell_sec < DWELL_MIN_SECONDS:
                return
            key = element_id or section or "unknown"
            if key in dwell_seen:
                return
            dwell_seen.add(key)
            label = element_id or section or "an element"
            context.add_message({
                "role": "user",
                "content": (
                    f"SYSTEM UI EVENT: DWELL — the visitor has been looking at "
                    f"'{label}' for about {dwell_sec:.0f} seconds without clicking. "
                    "Give one short helpful comment (one sentence). Do not push."
                ),
            })
            if task is not None:
                await task.queue_frames([LLMRunFrame()])
            return

        # ----- Form / generic UI -----
        description = data.get("description", str(data))
        form_name = str(data.get("client_name") or data.get("name") or "").strip()
        if form_name:
            visitor_name = form_name[:80]
        # Номер из произвольной формы не принимается: только через проверку кодом из SMS

        context.add_message({
            "role": "user",
            "content": f"SYSTEM UI EVENT: Client interacted with the screen: {description}",
        })
        if task is not None:
            await task.queue_frames([LLMRunFrame()])

    # Фаза 2.5 — приём ui-snapshot (A11y tree) + ui-event
    @rtvi.event_handler("on_ui_message")
    async def on_ui_message(rtvi_proc, message):
        nonlocal latest_snapshot
        msg_type = getattr(message, "type", None) or (
            message.get("type") if isinstance(message, dict) else None
        )

        # --- Snapshot: store only. Never dump the full tree into the LLM context. ---
        if msg_type == "ui-snapshot" or isinstance(message, RTVIUISnapshotFrame):
            tree = None
            if isinstance(message, RTVIUISnapshotFrame):
                tree = getattr(message, "tree", None) or getattr(message, "snapshot", None)
            else:
                data = getattr(message, "data", None) or (
                    message.get("data") if isinstance(message, dict) else {}
                )
                if isinstance(data, dict):
                    tree = data.get("tree") or data.get("snapshot") or data
                elif data is not None:
                    tree = data
            if tree is not None:
                latest_snapshot = tree
                # Keep a tiny high-level notice (not the tree itself)
                summary_hint = ""
                if isinstance(tree, dict):
                    # Common shapes: {nodes: [...]} or {tree: ...} or role-based
                    nodes = tree.get("nodes") or tree.get("children") or []
                    if isinstance(nodes, list) and nodes:
                        summary_hint = f" (~{len(nodes)} nodes)"
                clog.debug("[%s] ui-snapshot received%s", call_id, summary_hint)
            return

        # --- Generic ui-event ---
        if msg_type == "ui-event":
            data = getattr(message, "data", None) or (
                message.get("data") if isinstance(message, dict) else {}
            ) or {}
            name = (
                getattr(message, "name", None)
                or (data.get("name") if isinstance(data, dict) else None)
                or (data.get("event") if isinstance(data, dict) else None)
                or "ui-event"
            )
            # Noise filter
            if str(name) in ("pointermove", "scroll", "resize", "mousemove"):
                return
            context.add_message({
                "role": "user",
                "content": f"SYSTEM UI EVENT (ui-event/{name}): {data}",
            })
            if task is not None:
                await task.queue_frames([LLMRunFrame()])

    pipeline = Pipeline([
        transport.input(),
        rtvi_adapter,
        rtvi,
        user_catcher,
        context_aggregator.user(),
        abuse_probe,
        mic_gate,
        llm,
        ai_catcher,
        transport.output(),
        context_aggregator.assistant(),
    ])

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,
            idle_timeout=IDLE_TIMEOUT_SECONDS,
            enable_metrics=True,
        ),
        observers=[rtvi_observer, latency],
    )

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(_transport, _connection):
        clog.info("[%s] WebRTC client disconnected", call_id)
        with contextlib.suppress(Exception):
            await task.queue_frames([CancelFrame()])

    @rtvi.event_handler("on_client_ready")
    async def on_client_ready(rtvi_proc):
        with contextlib.suppress(Exception):
            await rtvi_proc.set_bot_ready()

    # Стартовое приветствие: память + имя, без повторной квалификации
    mem_core = ((visitor_memory or {}).get("core") or "").strip()
    mem_short = ((visitor_memory or {}).get("short") or "").strip()
    has_memory = bool(mem_core or mem_short or visitor_name)
    name_hint = visitor_name or ""

    if call_lang == "ro":
        if has_memory:
            greeting_text = (
                "SYSTEM EVENT: Client reconnectat. Vorbește prima! "
                "Ai memorie despre acest vizitator (vezi CALLER_MEMORY). "
                "Salută scurt, arată că îți amintești contextul (nișă/problemă) — NU reîntreba ce afacere are. "
                + (f"Folosește numele «{name_hint}». " if name_hint else
                   "Numele lipsește: întreabă o singură dată cum să-l/o abordezi, apoi folosește numele. ")
                + f"Deschide ecranul potrivit ({ui_tool}) și continuă de la obiectivul deja cunoscut. "
                "Maxim 2 fraze + o întrebare de avansare (nu de recunoaștere)."
            )
        else:
            greeting_text = (
                "SYSTEM EVENT: Client just connected. Speak first! "
                "WOW scurt (max 2 fraze): controlezi site-ul în timp real. "
                "Întreabă numele (o dată) și ce vrea să automatizeze. "
                + ("Apelează show_scene(scene='welcome') la început." if scene_catalog else
                   "Apelează control_website_ui(section=services) la început.")
            )
    else:
        if has_memory:
            greeting_text = (
                "SYSTEM EVENT: Returning visitor. Speak first! "
                "You already have CALLER_MEMORY about this person. "
                "Greet briefly and show you remember their niche/problem — do NOT re-ask what business they run. "
                + (f"Address them as «{name_hint}». " if name_hint else
                   "Name unknown: ask once how to address them, then use the name. ")
                + f"Open the right screen ({ui_tool}) and continue from the known goal. "
                "Max 2 sentences + one forward question (not a rediscovery question)."
            )
        else:
            greeting_text = (
                "SYSTEM EVENT: Client just connected. Speak first! "
                "Short WOW (max 2 sentences): you control the site live on their screen. "
                "Ask their first name once, and what they want to automate. "
                + ("Call show_scene(scene='welcome') immediately. " if scene_catalog else
                   "Call control_website_ui(section=services) immediately. ")
                + "When you learn the name, call save_lead with client_name (phone may wait)."
            )
    context.add_message({"role": "user", "content": greeting_text})
    await task.queue_frames([LLMRunFrame()])


    async def _session_soft_warn() -> None:
        """За SOFT_DEADLINE_WARN_BEFORE до конца — карточка + короткая реплика."""
        try:
            total = max(20, int(max_session_seconds))
            if total <= 60:
                warn_at = max(25, int(total * 0.75))
            else:
                warn_at = max(30, total - SOFT_DEADLINE_WARN_BEFORE)
            await asyncio.sleep(warn_at)
            if task is None or abuse_stage == "blocked":
                return
            remaining = max(5, total - warn_at)
            clog.info("[%s] soft deadline warn, ~%ss left", call_id, remaining)
            await task.queue_frames([
                RTVIUICommandFrame(
                    command="session_ending_soon",
                    payload={
                        "remaining_seconds": remaining,
                        "session_index": session_index,
                    },
                ),
                LLMMessagesAppendFrame(messages=[{
                    "role": "user",
                    "content": (
                        f"SYSTEM: About {remaining} seconds left in this voice session. "
                        "In one short sentence, steer to a concrete next step "
                        "(verified contact or booking on screen). No 'demo ended' wording."
                    ),
                }]),
                LLMRunFrame(),
            ])
        except asyncio.CancelledError:
            return
        except Exception as exc:
            clog.warning("[%s] soft warn error: %s", call_id, exc)

    async def _session_deadline() -> None:
        try:
            await asyncio.sleep(max(15, int(max_session_seconds)))
            clog.info("[%s] session time budget %ss reached — ending", call_id, max_session_seconds)
            if task is not None:
                await task.queue_frames([
                    RTVIUICommandFrame(
                        command="session_ended",
                        payload={"reason": "time_budget", "session_index": session_index},
                    ),
                    CancelFrame(),
                ])
        except asyncio.CancelledError:
            return
        except Exception as exc:
            clog.warning("[%s] session deadline error: %s", call_id, exc)

    async def _abuse_watchdog() -> None:
        """Как abuse_watchdog в main.py: повторы → verify → block после verify."""
        try:
            while True:
                await asyncio.sleep(5.0)
                if abuse_probe.repetari < ABUSE_REPEAT_THRESHOLD:
                    continue
                if abuse_stage == "blocked":
                    return
                if abuse_stage in ("none",) and not phone_verified_session:
                    await _require_verify(f"repetari:{abuse_probe.repetari}")
                    abuse_probe.repetari = 0  # даём шанс после UI
                    continue
                if abuse_stage in ("verified", "verify_required") or phone_verified_session:
                    await _block_abuse(f"repetari_after_gate:{abuse_probe.repetari}")
                    return
        except asyncio.CancelledError:
            return
        except Exception as exc:
            clog.warning("[%s] abuse watchdog error: %s", call_id, exc)

    warn_handle = asyncio.create_task(_session_soft_warn())
    deadline_handle = asyncio.create_task(_session_deadline())
    abuse_watch_handle = asyncio.create_task(_abuse_watchdog())
    if not phone_verified_session:
        verify_watch_handle = asyncio.create_task(_verify_watch())

    runner = PipelineRunner()

    try:
        await runner.run(task)
    except Exception as exc:
        clog.exception("[%s] WebRTC session error: %s", call_id, exc)
    finally:
        duration = int(max(0.0, time.time() - start_ts))
        clog.info("[%s] WebRTC session ended, %ss", call_id, duration)
        with contextlib.suppress(Exception):
            latency.summary()
        with contextlib.suppress(Exception):
            await web_seconds_add(client_id, duration)

        with contextlib.suppress(Exception):
            deadline_handle.cancel()
        with contextlib.suppress(Exception):
            warn_handle.cancel()
        with contextlib.suppress(Exception):
            abuse_watch_handle.cancel()
        with contextlib.suppress(Exception):
            if orb_reset_handle is not None:
                orb_reset_handle.cancel()
        with contextlib.suppress(Exception):
            if verify_watch_handle is not None:
                verify_watch_handle.cancel()
        with contextlib.suppress(Exception):
            if verify_timeout_handle is not None:
                verify_timeout_handle.cancel()
        with contextlib.suppress(Exception):
            mixer.close()

        try:
            messages = []
            if context is not None:
                messages = list(getattr(context, "messages", None) or [])

            transcript, user_replies = build_transcript(messages)
            if transcript:
                clog.info("[%s] ДИАЛОГ (%d user turns):\n%s", call_id, user_replies, transcript)

            call_status = "inbound_dropped" if user_replies == 0 else "completed"
            phone_for_crm = learned_phone or ""
            lead_was_saved = bool(saved_lead_hashes)

            usage_stats = {
                "duration_seconds": duration,
                "turns": user_replies,
                "platform": "web_voice",
            }

            async def _post() -> None:
                await asyncio.sleep(0.3)
                try:
                    audio_url = ""
                    audio_path = None
                    if user_replies > 0:
                        audio_url = await upload_audio_to_supabase(client_id, wav_path) or ""
                        audio_path = wav_path if audio_url else None
                        clog.info("[%s] recording uploaded=%s", call_id, bool(audio_url))

                    await run_archivist_and_notify_n8n(
                        client_id=client_id,
                        phone=phone_for_crm,
                        client_name=visitor_name,
                        old_memory=visitor_memory,
                        chat_history=transcript,
                        audio_url=audio_url,
                        sys_length=len(system_prompt),
                        direction="inbound",
                        call_status=call_status,
                        tz_name=tz_name,
                        usage_stats=usage_stats,
                        audio_path=audio_path,
                        project_id=project_id or "",
                        web_id=visitor_id or "",
                        platform="web_voice",
                        visitor_meta={"visitor_id": visitor_id or ""},
                        lead_saved=lead_was_saved,
                        tg_chat=tg_chat,
                    )
                    clog.info(
                        "[%s] archivist done status=%s lead_saved=%s",
                        call_id, call_status, lead_was_saved,
                    )
                except Exception as post_exc:
                    clog.exception("[%s] archivist failed: %s", call_id, post_exc)

            if transcript or user_replies > 0 or learned_phone:
                asyncio.create_task(_post())
            else:
                clog.info("[%s] skip archivist — empty session", call_id)
        except Exception as fin_exc:
            clog.exception("[%s] post-processing failed: %s", call_id, fin_exc)


def _cors_headers(request: Request) -> dict[str, str]:
    """Minimal CORS for browser widget on client sites."""
    origin = (request.headers.get("origin") or "").strip()
    # Reflect allowed-looking https origins; tighten via env on the app middleware.
    allow = origin if origin.startswith("https://") else "*"
    return {
        "Access-Control-Allow-Origin": allow,
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Authorization, Content-Type",
        "Access-Control-Max-Age": "86400",
        "Vary": "Origin",
    }


@router.options("/api/offer")
async def webrtc_offer_options(request: Request):
    return JSONResponse({}, status_code=204, headers=_cors_headers(request))

@router.get("/api/scene-catalog", response_model=None)
async def scene_catalog(key: str = "", lang: str = "en"):
    """Каталог для слоя сцен на языке разговора. Данные публичные — те же, что на сайте."""
    headers = {"Access-Control-Allow-Origin": "*", "Cache-Control": "public, max-age=120"}
    key = re.sub(r"[^A-Za-z0-9_\-]", "", key or "")[:64]
    if not key:
        return JSONResponse({"catalog": None}, headers=headers)
    try:
        rows = await sb_select(
            "bot_channels",
            {"identifier": f"eq.{key}", "platform": "eq.web", "select": "client_id", "limit": "1"},
            timeout=2.5,
        )
    except Exception as exc:
        log.warning("scene-catalog channel lookup: %s", exc)
        rows = []
    client_id = str(rows[0].get("client_id") or "") if rows else ""
    catalog = await load_scene_catalog(client_id)
    if not catalog:
        return JSONResponse({"catalog": None}, headers=headers)
    use = scene_lang(catalog, lang)
    return JSONResponse({"catalog": localize_catalog(catalog, use), "lang": use}, headers=headers)


@router.post("/api/offer", response_model=None)
async def webrtc_offer(request: Request):
    """Signalling endpoint for SmallWebRTCTransport (SDP offer → answer)."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid json"}, status_code=400, headers=_cors_headers(request))

    offer_sdp = body.get("sdp")
    offer_type = body.get("type", "offer")
    key = str(body.get("key") or body.get("widget_key") or "").strip()
    visitor_id = str(body.get("visitor_id") or "").strip()
    project_id = str(body.get("project_id") or "").strip()
    raw_lang = str(body.get("lang") or body.get("language") or body.get("locale") or "").strip()
    accept_lang = request.headers.get("accept-language") or ""
    device_lang = ""
    if accept_lang:
        primary = accept_lang.split(",")[0].split(";")[0].strip()
        if "-" in primary:
            device_lang = primary.split("-")[0].lower()
        elif "_" in primary:
            device_lang = primary.split("_")[0].lower()
        else:
            device_lang = primary.lower()[:8]
    browser_lang = device_lang or raw_lang
    landing_url = str(body.get("landing_url") or body.get("url") or body.get("page_url") or "").strip()[:500]
    referrer = str(body.get("referrer") or body.get("ref") or "").strip()[:500]
    turnstile_token = str(
        body.get("turnstile_token")
        or body.get("t")
        or body.get("cf-turnstile-response")
        or ""
    ).strip()
    if not offer_sdp or not key:
        return JSONResponse({"error": "sdp and key required"}, status_code=400, headers=_cors_headers(request))

    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    ip = forwarded or (request.client.host if request.client else "")
    origin = request.headers.get("origin") or ""

    try:
        channel_rows = await sb_select(
            "bot_channels",
            {
                "identifier": f"eq.{key}",
                "platform": "eq.web",
                "select": "client_id,project_id,allowed_origins,turnstile_secret_key,voice_enabled",
                "limit": "1",
            },
            timeout=2.5,
        )
    except Exception as exc:
        log.error("webrtc channel lookup failed: %s", exc)
        return JSONResponse({"error": "channel lookup failed"}, status_code=500, headers=_cors_headers(request))

    if not channel_rows or not channel_rows[0].get("client_id"):
        return JSONResponse({"error": "unknown widget key"}, status_code=403, headers=_cors_headers(request))

    row = channel_rows[0]
    client_id = str(row["client_id"])
    if not project_id:
        project_id = str(row.get("project_id") or "")

    if row.get("voice_enabled") is False:
        return JSONResponse({"error": "voice disabled"}, status_code=403, headers=_cors_headers(request))

    if not origin_permis(origin, row.get("allowed_origins")):
        log.warning("webrtc origin refused: %s key=%s", origin, key[:12])
        return JSONResponse({"error": "origin not allowed"}, status_code=403, headers=_cors_headers(request))

    if await este_blocat(visitor_id, ip):
        log.warning("webrtc blocked visitor=%s ip=%s", visitor_id[:12], ip)
        return JSONResponse({"error": "blocked"}, status_code=403, headers=_cors_headers(request))

    used_today = await web_seconds_used_today(client_id)
    if used_today >= WEB_MAX_MINUTES_PER_DAY * 60:
        log.warning("webrtc daily site minutes spent client=%s used=%ss", client_id, used_today)
        return JSONResponse(
            {"error": "daily_limit", "detail": "site_minutes"},
            status_code=429,
            headers=_cors_headers(request),
        )

    secret = str(row.get("turnstile_secret_key") or "")
    # Empty token is common on mobile if CF script lags; allow bypass only when
    # WEB_SKIP_TURNSTILE=1 on the voice server (debug / staged rollout).
    import os as _os
    skip_ts = (_os.getenv("WEB_SKIP_TURNSTILE") or "").strip().lower() in ("1", "true", "yes")
    if not await propusk_valabil(turnstile_token, ip, secret):
        if skip_ts:
            log.warning("webrtc turnstile failed ip=%s — WEB_SKIP_TURNSTILE, allowing", ip)
        else:
            log.warning("webrtc turnstile failed ip=%s token_len=%s", ip, len(turnstile_token))
            return JSONResponse(
                {"error": "verification failed"},
                status_code=403,
                headers=_cors_headers(request),
            )

    limit_err, session_index, max_session_seconds = await web_session_budget(visitor_id, ip)
    if limit_err:
        log.warning("webrtc daily limit: %s", limit_err)
        return JSONResponse(
            {"error": "daily_limit", "detail": limit_err, "session_index": session_index},
            status_code=429,
            headers=_cors_headers(request),
        )

    connection = SmallWebRTCConnection(ice_servers=_get_ice_servers())
    await connection.initialize(sdp=offer_sdp, type=offer_type)

    transport = SmallWebRTCTransport(
        webrtc_connection=connection,
        params=TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_out_sample_rate=24000,
        ),
    )

    vid = visitor_id or uuid.uuid4().hex
    asyncio.create_task(
        run_webrtc_session(
            transport,
            client_id,
            vid,
            project_id,
            visitor_ip=ip,
            browser_lang=browser_lang,
            landing_url=landing_url,
            referrer=referrer,
            session_index=session_index,
            max_session_seconds=max_session_seconds,
        )
    )

    answer = connection.get_answer()
    return JSONResponse(
        {
            "sdp": answer["sdp"],
            "type": answer["type"],
            "session_index": session_index,
            "max_session_seconds": max_session_seconds,
        },
        headers=_cors_headers(request),
    )
