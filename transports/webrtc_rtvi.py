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
  Фаза 2.5 UI protocol: ui-snapshot + DOM-команды (scroll_to, highlight,
            set_input_value, click) через RTVIUICommandFrame
  Agentic Tool-State: set_agent_state → Thinking Orb (thinking-orbs)

Защита /api/offer: origin, blacklist, Turnstile, суточные лимиты.
  Soft deadline (warn → close).
  Mid-session abuse: verify → block (как legacy).
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import hashlib
import html
import logging
import re
import time
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse
from pathlib import Path
from pipecat.frames.frames import (
    CancelFrame,
    Frame,
    LLMMessagesAppendFrame,
    LLMRunFrame,
    TranscriptionFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.processors.frameworks.rtvi import (
    RTVIConfig,
    RTVIFunctionCallReportLevel,
    RTVIObserver,
    RTVIObserverParams,
    RTVIProcessor,
    RTVIUICommandFrame,
    RTVIUISnapshotFrame,
)
from pipecat.services.google.gemini_live.llm import GeminiLiveLLMService, GeminiVADParams
from pipecat.services.llm_service import FunctionCallParams
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

from core import (
    DEFAULT_LANG,
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
)

router = APIRouter(tags=["webrtc-rtvi"])

_STATIC = Path(__file__).resolve().parent.parent / "static"

@router.get("/widget-genui.js")
async def serve_widget_genui():
    return FileResponse(_STATIC / "widget-genui.js", media_type="application/javascript")


DWELL_MIN_SECONDS = 3.0
# Soft close: предупреждение за столько секунд до конца budget
SOFT_DEADLINE_WARN_BEFORE = 30
# Повторов «списка вопросов» до требования верификации / блока
ABUSE_REPEAT_THRESHOLD = 3


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
        "Controls the website interface in real time. "
        "SERIES mode (default for clients): open a prepared section "
        "(hero, services, pricing, cases, booking_widget, contacts, roi_calculator) "
        "and optionally highlight an element or prefill a form. "
        "CONCEPT mode (labupgrade.ai): you may also pass a 'components' list to "
        "assemble the view from design-system primitives. Prefer 'section' when in doubt."
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
                "description": "Prepared section to show (series mode). Always provide when possible.",
            },
            "highlight_element": {
                "type": "string",
                "description": "Element id or plan id to visually emphasize",
            },
            "prefill_data": {
                "type": "object",
                "description": "Data to pre-fill into the visible form (name, phone, slot, etc.)",
            },
            "components": {
                "type": "array",
                "description": (
                    "Optional. CONCEPT mode only: list of design-system components "
                    "to compose the view. Each item: {type, props}. "
                    "Series clients ignore this field."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string"},
                        "props": {"type": "object"},
                    },
                },
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

# Фаза 2.5 — DOM actions via UI Worker Protocol (scroll_to / highlight / set_input_value / click)
DOM_ACTION_TOOL = {
    "name": "dom_action",
    "description": (
        "Low-level DOM manipulation on the page the visitor is looking at. "
        "Use after a ui-snapshot is available or when you know a stable target_id / ref. "
        "Prefer control_website_ui for high-level section navigation; use this for precise "
        "scroll, highlight, form fill or click."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["scroll_to", "highlight", "set_input_value", "click", "focus"],
                "description": "DOM command to execute",
            },
            "ref": {
                "type": "string",
                "description": "Stable a11y snapshot ref (e.g. 'e42') from the latest ui-snapshot",
            },
            "target_id": {
                "type": "string",
                "description": "Fallback DOM id (document.getElementById) when ref is unknown",
            },
            "value": {
                "type": "string",
                "description": "Value for set_input_value",
            },
            "duration_ms": {
                "type": "number",
                "description": "Highlight duration in ms (default 2000)",
            },
        },
        "required": ["action"],
    },
}

# Agentic Tool-State + Thinking Orbs
# Front-end will render the matching orb from the `thinking-orbs` library.
AGENT_STATE_TOOL = {
    "name": "set_agent_state",
    "description": (
        "Update the visual agent state indicator on the page (Thinking Orb). "
        "Call this when you start or finish a meaningful action so the visitor "
        "sees what you are doing. Use short-lived states; return to 'breathing' "
        "or clear when idle."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "state": {
                "type": "string",
                "enum": [
                    "working",
                    "searching",
                    "solving",
                    "listening",
                    "connecting",
                    "weaving",
                    "composing",
                    "breathing",
                    "shaping",
                    "idle",
                ],
                "description": "Current agent activity shown as a Thinking Orb",
            },
            "label": {
                "type": "string",
                "description": "Optional short label next to the orb (e.g. 'Checking calendar')",
            },
        },
        "required": ["state"],
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
    base.append(DOM_ACTION_TOOL)
    base.append(AGENT_STATE_TOOL)
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
            return float(v) if v is not None else default
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

    # Память / карточка по visitor_id (RPC → person_memory через end_client)
    contact, visitor_memory, time_ctx = await get_web_visitor_context(client_id, visitor_id)
    if contact.get("phone") and telefon_valid(contact["phone"]):
        learned_phone = "".join(filter(str.isdigit, str(contact["phone"])))
        phone_verified_session = True
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
    )
    clog.info(
        "[%s] session_index=%s max_sec=%s lang=%s prompt_chars=%s",
        call_id, session_index, max_session_seconds, call_lang, len(system_prompt),
    )
    tools = _build_tools_with_ui(client_data, readable_hours)

    wav_path = f"/tmp/webrtc_{call_id}.wav"
    mixer = WebAudioMixer(wav_path)
    user_catcher = WebUserAudioCatcher(mixer)
    ai_catcher = WebAIAudioCatcher(mixer)

    llm = GeminiLiveLLMService(
        api_key=GEMINI_API_KEY,
        tools=tools,
        settings=GeminiLiveLLMService.Settings(
            model=GEMINI_MODEL,
            voice=resolve_voice_name(persona.voice_model),
            system_instruction=system_prompt,
            vad=GeminiVADParams(
                start_sensitivity="low",
                end_sensitivity="low",
            ),
        ),
    )

    rtvi = RTVIProcessor(config=RTVIConfig(config=[]))
    rtvi_observer = RTVIObserver(
        rtvi,
        params=RTVIObserverParams(
            function_call_report_level={
                "*": RTVIFunctionCallReportLevel.NAME,
                "control_website_ui": RTVIFunctionCallReportLevel.FULL,
                "update_roi_calculator": RTVIFunctionCallReportLevel.FULL,
                "request_screen_audit": RTVIFunctionCallReportLevel.FULL,
                "morph_ui_for_sentiment": RTVIFunctionCallReportLevel.FULL,
                "dom_action": RTVIFunctionCallReportLevel.FULL,
                "set_agent_state": RTVIFunctionCallReportLevel.FULL,
                "flag_session_abuse": RTVIFunctionCallReportLevel.FULL,
                "Booking_tool": RTVIFunctionCallReportLevel.ARGUMENTS,
            }
        ),
    )

    context = LLMContext(messages=[])
    context_aggregator = LLMContextAggregatorPair(context)
    task: Optional[PipelineTask] = None

    # ----- Tool handlers -----

    async def process_control_website_ui(params: FunctionCallParams):
        section = params.arguments.get("section", "hero")
        highlight = params.arguments.get("highlight_element")
        prefill = params.arguments.get("prefill_data") or {}
        components = params.arguments.get("components")  # CONCEPT mode (optional)

        payload: dict[str, Any] = {
            "section": section,
            "highlight": highlight,
            "prefill": prefill,
        }
        if components:
            payload["components"] = components

        if task is not None:
            await task.queue_frames([
                RTVIUICommandFrame(
                    command="navigate_and_render",
                    payload=payload,
                ),
                RTVIUICommandFrame(
                    command="set_agent_state",
                    payload={"state": "breathing"},
                ),
            ])
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

    async def process_update_roi(params: FunctionCallParams):
        nonlocal last_roi
        result = _compute_roi(params.arguments or {})
        last_roi = result
        if task is not None:
            await task.queue_frames([
                RTVIUICommandFrame(
                    command="set_agent_state",
                    payload={"state": "solving", "label": "Calculating savings"},
                ),
                RTVIUICommandFrame(
                    command="navigate_and_render",
                    payload={"section": "roi_calculator", "highlight": None, "prefill": result},
                ),
                RTVIUICommandFrame(command="update_roi", payload=result),
                RTVIUICommandFrame(
                    command="set_agent_state",
                    payload={"state": "breathing"},
                ),
            ])
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
        if task is not None:
            await task.queue_frames([
                # Show Thinking Orb while audit is in progress
                RTVIUICommandFrame(
                    command="set_agent_state",
                    payload={"state": "searching", "label": "Reviewing page"},
                ),
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
                "Wait for SYSTEM UI EVENT with the page summary before giving findings. "
                "After you speak the findings, call set_agent_state(state='breathing')."
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

        if task is not None:
            frames = [
                RTVIUICommandFrame(
                    command="navigate_and_render",
                    payload={
                        "section": section,
                        "highlight": highlight,
                        "prefill": {"sentiment_signal": signal},
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

    async def process_dom_action(params: FunctionCallParams):
        """Фаза 2.5 — низкоуровневые DOM-команды UI Worker Protocol."""
        action = str(params.arguments.get("action") or "").strip()
        ref = params.arguments.get("ref")
        target_id = params.arguments.get("target_id")
        value = params.arguments.get("value")
        duration_ms = params.arguments.get("duration_ms") or 2000

        if action not in ("scroll_to", "highlight", "set_input_value", "click", "focus"):
            await params.result_callback({"status": "error", "message": f"Unknown action: {action}"})
            return

        payload: dict[str, Any] = {}
        if ref:
            payload["ref"] = ref
        if target_id:
            payload["target_id"] = target_id
        if action == "set_input_value":
            payload["value"] = value or ""
            payload["replace"] = True
        if action == "highlight":
            payload["duration_ms"] = duration_ms

        if task is not None:
            await task.queue_frames([
                RTVIUICommandFrame(command=action, payload=payload),
                RTVIUICommandFrame(
                    command="set_agent_state",
                    payload={"state": "breathing"},
                ),
            ])

        await params.result_callback({
            "status": "command_sent",
            "action": action,
            "payload": payload,
            "instruction": f"DOM command '{action}' sent. Continue speaking naturally.",
        })

    async def process_set_agent_state(params: FunctionCallParams):
        """Agentic Tool-State → Thinking Orb on the client."""
        state = str(params.arguments.get("state") or "breathing").strip()
        label = params.arguments.get("label")
        allowed = {
            "working", "searching", "solving", "listening",
            "connecting", "weaving", "composing", "breathing",
            "shaping", "idle",
        }
        if state not in allowed:
            await params.result_callback({"status": "error", "message": f"Unknown state: {state}"})
            return

        payload: dict[str, Any] = {"state": state}
        if label:
            payload["label"] = str(label)[:80]

        if task is not None:
            await task.queue_frames([
                RTVIUICommandFrame(command="set_agent_state", payload=payload)
            ])

        await params.result_callback({
            "status": "state_updated",
            "state": state,
            "instruction": "Agent state indicator updated. Continue the task.",
        })

    async def process_save_lead(params: FunctionCallParams):
        nonlocal learned_phone
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

        try:
            result = await call_n8n(
                "save_lead",
                {"client_id": client_id, "tg_chat_id": tg_chat or ""},
                params.arguments,
                5.0,
            )
            saved_lead_hashes.add(digest)
            await params.result_callback(result)
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                await params.result_callback({"status": "cancelled"})
            raise
        except Exception as exc:
            await send_tg_alert(
                tg_chat,
                f"⚠️ <b>Eroare API (save_lead)</b>\n🏢 {company}\n🔧 <code>{html.escape(str(exc))}</code>",
            )
            await params.result_callback({"error": f"Eroare CRM: {exc}"})

    async def process_booking(params: FunctionCallParams):
        nonlocal learned_phone, zapis_id
        phone_arg = str(params.arguments.get("phone") or "").strip()
        if not phone_arg and learned_phone:
            params.arguments["phone"] = phone_arg = learned_phone
        if telefon_valid(phone_arg):
            learned_phone = phone_arg

        action = params.arguments.get("action")
        normalizeaza_timp(params.arguments, tz_name)

        if action == "book" and not telefon_valid(phone_arg):
            if task is not None:
                await task.queue_frames([
                    RTVIUICommandFrame(
                        command="navigate_and_render",
                        payload={
                            "section": "booking_widget",
                            "highlight": "phone",
                            "prefill": {
                                "start_time": params.arguments.get("start_time"),
                                "end_time": params.arguments.get("end_time"),
                                "client_name": params.arguments.get("client_name"),
                                "request_summary": params.arguments.get("request_summary"),
                            },
                        },
                    )
                ])
            await params.result_callback({
                "status": "need_phone_via_form",
                "message": (
                    "Forma de pe ecran este deschisă. Nu cere numărul pe voice. "
                    "Așteaptă SYSTEM UI EVENT cu numărul, apoi Booking_tool action=book."
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
        try:
            if action == "book":
                proba = await call_n8n(
                    "booking", params_n8n, {**params.arguments, "action": "check"}, 10.0
                )
                if not slot_liber(proba):
                    await params.result_callback(proba)
                    return
            result = await call_n8n("booking", params_n8n, params.arguments, 10.0)
            zapis_id = id_zapisi(result) or zapis_id
            if action == "lookup":
                zapis_id = id_din_lookup(result) or zapis_id
            if action == "cancel":
                zapis_id = ""
            await params.result_callback(result)
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                await params.result_callback({"status": "cancelled"})
            raise
        except Exception as exc:
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
        try:
            result = await call_n8n(
                "send_sms",
                {"client_id": client_id},
                params.arguments,
                5.0,
            )
            await params.result_callback(result)
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                await params.result_callback({"status": "cancelled"})
            raise
        except Exception as exc:
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

    async def _require_verify(reason: str) -> None:
        nonlocal abuse_stage
        if abuse_stage in ("verify_required", "blocked"):
            return
        abuse_stage = "verify_required"
        clog.warning("[%s] abuse verify required: %s", call_id, reason)
        if task is not None:
            await task.queue_frames([
                RTVIUICommandFrame(
                    command="require_phone_verification",
                    payload={
                        "reason": "abuse_protection",
                        "message": (
                            "Open voice access is limited because of competitors "
                            "and bad-faith visitors. Confirm your phone on screen to continue."
                        ),
                    },
                )
            ])
            context.add_message({
                "role": "user",
                "content": (
                    "SYSTEM: Identity verification required due to suspicious activity. "
                    "Tell the visitor honestly (no 'demo' wording) that we limit open access "
                    "because of competitors/abuse, and ask them to confirm the phone on screen. "
                    "Do not continue deep product detail until SYSTEM UI EVENT phone_verified."
                ),
            })
            await task.queue_frames([LLMRunFrame()])

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
    llm.register_function("flag_session_abuse", process_flag_session_abuse)
    llm.register_function("update_roi_calculator", process_update_roi)
    llm.register_function("request_screen_audit", process_request_screen_audit)
    llm.register_function("morph_ui_for_sentiment", process_morph_ui_for_sentiment)
    llm.register_function("dom_action", process_dom_action)
    llm.register_function("set_agent_state", process_set_agent_state)
    llm.register_function("save_lead", process_save_lead)
    llm.register_function("Booking_tool", process_booking)
    llm.register_function("send_sms", process_sms)
    llm.register_function("end_call", process_end_call)

    # ----- UI event / snapshot handlers (Фаза 2.5 + 3.x) -----

    @rtvi.event_handler("on_client_message")
    async def on_client_message(rtvi_proc, msg):
        nonlocal learned_phone, audit_pending_focus, phone_verified_session, abuse_stage
        msg_type = getattr(msg, "type", None) or (msg.get("type") if isinstance(msg, dict) else None)
        if msg_type != "ui_user_interaction":
            return
        data = getattr(msg, "data", None) or (msg.get("data") if isinstance(msg, dict) else {}) or {}

        interaction = str(data.get("interaction") or data.get("event") or "click").lower()
        element_id = str(data.get("element_id") or data.get("element") or "").strip()
        section = str(data.get("section") or "").strip()
        dwell_ms = data.get("dwell_ms") or data.get("duration_ms") or 0
        try:
            dwell_sec = float(dwell_ms) / 1000.0 if float(dwell_ms) > 20 else float(dwell_ms)
        except (TypeError, ValueError):
            dwell_sec = 0.0

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

        # ----- Phone verified via widget form / SMS -----
        if interaction in ("phone_verified", "verify_phone"):
            phone_raw = str(data.get("phone") or data.get("value") or "").strip()
            if phone_raw and telefon_valid(phone_raw):
                learned_phone = "".join(filter(str.isdigit, phone_raw))
                phone_verified_session = True
                if abuse_stage == "verify_required":
                    abuse_stage = "verified"
                clog.info("[%s] phone verified via UI stage=%s", call_id, abuse_stage)
                context.add_message({
                    "role": "user",
                    "content": (
                        "SYSTEM UI EVENT: visitor verified phone on screen. "
                        "Use this number for booking/lead; do not ask them to dictate it. "
                        "You may continue the conversation."
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
                    "Give 2–3 concrete observations. Optionally call control_website_ui "
                    "or dom_action to highlight weak spots. Do not invent content not in this summary. "
                    "When finished speaking, call set_agent_state(state='breathing')."
                ),
            })
            if task is not None:
                # Return orb to neutral while the model prepares the answer
                await task.queue_frames([
                    RTVIUICommandFrame(
                        command="set_agent_state",
                        payload={"state": "composing", "label": "Preparing feedback"},
                    ),
                    LLMRunFrame(),
                ])
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
        form_phone = str(data.get("phone") or data.get("client_phone") or "").strip()
        form_name = str(data.get("client_name") or data.get("name") or "").strip()
        if telefon_valid(form_phone):
            learned_phone = form_phone
            description = (
                f"{description}; phone_from_form={form_phone}"
                + (f"; name_from_form={form_name}" if form_name else "")
            )

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
        rtvi,
        user_catcher,
        context_aggregator.user(),
        abuse_probe,
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
        observers=[rtvi_observer],
    )

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(_transport, _connection):
        clog.info("[%s] WebRTC client disconnected", call_id)
        with contextlib.suppress(Exception):
            await task.queue_frames([CancelFrame()])

    @rtvi.event_handler("on_client_ready")
    async def on_client_ready(rtvi_proc):
        await rtvi_proc.set_bot_ready()
        await task.queue_frames([
            LLMMessagesAppendFrame(messages=[{
                "role": "user",
                "content": (
                    "SYSTEM: Client just connected to the website. "
                    "Greet briefly and ask how you can help."
                ),
            }]),
            LLMRunFrame(),
        ])


    async def _session_soft_warn() -> None:
        """За SOFT_DEADLINE_WARN_BEFORE до конца — карточка + короткая реплика."""
        try:
            total = max(15, int(max_session_seconds))
            warn_at = max(5, total - SOFT_DEADLINE_WARN_BEFORE)
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

    runner = PipelineRunner()

    try:
        await runner.run(task)
    except Exception as exc:
        clog.exception("[%s] WebRTC session error: %s", call_id, exc)
    finally:
        duration = int(max(0.0, time.time() - start_ts))
        clog.info("[%s] WebRTC session ended, %ss", call_id, duration)

        with contextlib.suppress(Exception):
            deadline_handle.cancel()
        with contextlib.suppress(Exception):
            warn_handle.cancel()
        with contextlib.suppress(Exception):
            abuse_watch_handle.cancel()
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


@router.post("/api/offer")
async def webrtc_offer(request: Request) -> dict | JSONResponse:
    """Signalling endpoint for SmallWebRTCTransport (SDP offer → answer)."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid json"}, status_code=400)

    offer_sdp = body.get("sdp")
    offer_type = body.get("type", "offer")
    key = str(body.get("key") or body.get("widget_key") or "").strip()
    visitor_id = str(body.get("visitor_id") or "").strip()
    project_id = str(body.get("project_id") or "").strip()
    turnstile_token = str(body.get("turnstile_token") or body.get("t") or body.get("cf-turnstile-response") or "").strip()
    browser_lang = str(body.get("lang") or body.get("language") or body.get("locale") or "").strip()
    landing_url = str(body.get("landing_url") or body.get("url") or body.get("page_url") or "").strip()[:500]
    referrer = str(body.get("referrer") or body.get("ref") or "").strip()[:500]

    if not offer_sdp or not key:
        return JSONResponse({"error": "sdp and key required"}, status_code=400)

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
        return JSONResponse({"error": "channel lookup failed"}, status_code=500)

    if not channel_rows or not channel_rows[0].get("client_id"):
        return JSONResponse({"error": "unknown widget key"}, status_code=403)

    row = channel_rows[0]
    client_id = str(row["client_id"])
    if not project_id:
        project_id = str(row.get("project_id") or "")

    if row.get("voice_enabled") is False:
        return JSONResponse({"error": "voice disabled"}, status_code=403)

    if not origin_permis(origin, row.get("allowed_origins")):
        log.warning("webrtc origin refused: %s key=%s", origin, key[:12])
        return JSONResponse({"error": "origin not allowed"}, status_code=403)

    if await este_blocat(visitor_id, ip):
        log.warning("webrtc blocked visitor=%s ip=%s", visitor_id[:12], ip)
        return JSONResponse({"error": "blocked"}, status_code=403)

    if not await propusk_valabil(turnstile_token, ip, str(row.get("turnstile_secret_key") or "")):
        log.warning("webrtc turnstile failed ip=%s", ip)
        return JSONResponse({"error": "verification failed"}, status_code=403)

    limit_err, session_index, max_session_seconds = await web_session_budget(visitor_id, ip)
    if limit_err:
        log.warning("webrtc daily limit: %s", limit_err)
        return JSONResponse(
            {"error": "daily_limit", "detail": limit_err, "session_index": session_index},
            status_code=429,
        )

    connection = SmallWebRTCConnection()
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
    return {
        "sdp": answer["sdp"],
        "type": answer["type"],
        "session_index": session_index,
        "max_session_seconds": max_session_seconds,
    }
