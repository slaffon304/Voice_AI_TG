"""
Изолированный WebRTC + RTVI контур для «Сайта Будущего».

Legacy GSM и /ws НЕ затрагиваются.
Фаза 3.1: Анти-Диктовка.
Фаза 3.2: Zero-Click Dwell Sensing.
Фаза 3.3: ROI Calculator.
Фаза 3.4: Live Screen Audit (контракт + поток).
Фаза 3.5: Real-Time Sentiment UI Morphing.
Фаза 2.5: UI Worker Protocol v1 — приём ui-snapshot + DOM-команды
          (scroll_to, highlight, set_input_value, click).
Защита /api/offer: origin, blacklist, Turnstile, суточные лимиты.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import html
import logging
import re
import time
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pipecat.frames.frames import (
    CancelFrame,
    LLMMessagesAppendFrame,
    LLMRunFrame,
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
    build_personality_block,
    build_tools,
    call_n8n,
    este_blocat,
    get_client_data,
    get_persona,
    id_din_lookup,
    id_zapisi,
    log,
    normalizeaza_timp,
    origin_permis,
    peste_limita,
    propusk_valabil,
    resolve_voice_name,
    sb_select,
    send_tg_alert,
    slot_liber,
    telefon_valid,
)

router = APIRouter(tags=["webrtc-rtvi"])

DWELL_MIN_SECONDS = 3.0

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
        "Deschide automat secțiunile site-ului, afișează carduri interactive "
        "(servicii, prețuri, portofoliu, calendar de programare) sau evidențiază "
        "informații pe ecranul clientului. Folosește-l când utilizatorul cere "
        "să vadă ceva pe ecran sau când vrei să arăți informație vizual."
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
                "description": "Secțiunea sau widget-ul care trebuie afișat pe ecran",
            },
            "highlight_element": {
                "type": "string",
                "description": "ID-ul elementului sau tarifului pe care trebuie pus accent vizual",
            },
            "prefill_data": {
                "type": "object",
                "description": "Date pre-completate pentru formularul de pe ecran",
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


def _build_tools_with_ui(client_data: dict, readable_hours: str) -> list[dict]:
    base = build_tools(client_data, readable_hours, web=True)
    base.append(UI_NAVIGATION_TOOL)
    base.append(ROI_CALCULATOR_TOOL)
    base.append(SCREEN_AUDIT_TOOL)
    base.append(SENTIMENT_MORPH_TOOL)
    base.append(DOM_ACTION_TOOL)
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
) -> None:
    call_id = uuid.uuid4().hex[:8]
    clog = logging.LoggerAdapter(log, {})
    clog.info("[%s] WebRTC session start client=%s visitor=%s", call_id, client_id, visitor_id)

    client_data = await get_client_data(client_id) or {}
    persona = await get_persona(client_id)
    call_lang = persona.language or DEFAULT_LANG
    tz_name = client_data.get("timezone") or "Europe/Chisinau"
    company = client_data.get("company_name") or client_id
    tg_chat = client_data.get("tg_chat_id_notify") or ""
    start_ts = time.time()

    learned_phone = ""
    zapis_id = ""
    saved_lead_hashes: set[str] = set()
    dwell_seen: set[str] = set()
    last_roi: dict[str, Any] = {}
    audit_pending_focus: str = ""
    latest_snapshot: Any = None  # Фаза 2.5 — последний ui-snapshot
    sentiment_fired: set[str] = set()  # анти-спам для morph

    system_prompt = (
        build_personality_block(persona, call_lang)
        + "\n\n"
        + (client_data.get("system_prompt") or "")
        + "\n\n"
        "CHANNEL: this is a voice session from the company's WEBSITE via WebRTC. "
        "You can control the website UI with the control_website_ui tool. "
        "When the user asks to see services, prices, contacts or wants to book — "
        "call control_website_ui first, then give a short spoken answer. "
        "You do not know the visitor's phone number unless they give it. "
        "ANTI-DICTATION: never ask the visitor to dictate a phone number digit by digit. "
        "If a phone is needed for booking or a lead, open the on-screen form "
        "(control_website_ui section=booking_widget) and wait for the form data "
        "from the UI. When a SYSTEM UI EVENT brings a phone number, use it. "
        "DWELL: if you receive SYSTEM UI EVENT about the visitor lingering on a plan "
        "or element, give one short helpful comment (1 sentence). Do not repeat. "
        "ROI: when the visitor talks about missed calls or savings, call "
        "update_roi_calculator, then speak net_monthly_savings from the result. "
        "SCREEN AUDIT: when the visitor asks to review their page/CTA/form, call "
        "request_screen_audit. Wait for SYSTEM UI EVENT with page summary, then "
        "give 2–3 concrete observations and optionally highlight elements via "
        "control_website_ui. Do not invent page content you were not given. "
        "SENTIMENT (Фаза 3.5): listen for hesitation, soft tone, long pauses, "
        "or objection words. When you detect doubt / price concern / trust gap, "
        "call morph_ui_for_sentiment once, then briefly reassure while the UI "
        "shows cases or guarantees. Do not call it repeatedly for the same signal. "
        "DOM (Фаза 2.5): you may receive SYSTEM UI EVENT with ui-snapshot data. "
        "Use dom_action for precise scroll_to / highlight / set_input_value / click "
        "when you have a ref or target_id. Prefer high-level control_website_ui first."
    )

    tools = _build_tools_with_ui(client_data, "")

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
        if task is not None:
            await task.queue_frames([
                RTVIUICommandFrame(
                    command="navigate_and_render",
                    payload={
                        "section": section,
                        "highlight": highlight,
                        "prefill": prefill,
                    },
                )
            ])
        await params.result_callback({
            "status": "ui_updated",
            "active_section": section,
            "instruction": (
                f"Section '{section}' is now shown on screen. "
                "Give a short spoken summary of what the visitor sees."
            ),
        })

    async def process_update_roi(params: FunctionCallParams):
        nonlocal last_roi
        result = _compute_roi(params.arguments or {})
        last_roi = result
        if task is not None:
            await task.queue_frames([
                RTVIUICommandFrame(
                    command="navigate_and_render",
                    payload={"section": "roi_calculator", "highlight": None, "prefill": result},
                ),
                RTVIUICommandFrame(command="update_roi", payload=result),
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
                RTVIUICommandFrame(
                    command="start_screen_audit",
                    payload={"focus": focus, "reason": reason},
                )
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
                RTVIUICommandFrame(command=action, payload=payload)
            ])

        await params.result_callback({
            "status": "command_sent",
            "action": action,
            "payload": payload,
            "instruction": f"DOM command '{action}' sent. Continue speaking naturally.",
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
    llm.register_function("control_website_ui", process_control_website_ui)
    llm.register_function("update_roi_calculator", process_update_roi)
    llm.register_function("request_screen_audit", process_request_screen_audit)
    llm.register_function("morph_ui_for_sentiment", process_morph_ui_for_sentiment)
    llm.register_function("dom_action", process_dom_action)
    llm.register_function("save_lead", process_save_lead)
    llm.register_function("Booking_tool", process_booking)
    llm.register_function("send_sms", process_sms)
    llm.register_function("end_call", process_end_call)

    # ----- UI event / snapshot handlers (Фаза 2.5 + 3.x) -----

    @rtvi.event_handler("on_client_message")
    async def on_client_message(rtvi_proc, msg):
        nonlocal learned_phone, audit_pending_focus
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
                    "or dom_action to highlight weak spots. Do not invent content not in this summary."
                ),
            })
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

    # Фаза 2.5 — приём ui-snapshot (A11y tree)
    @rtvi.event_handler("on_ui_message")
    async def on_ui_message(rtvi_proc, message):
        nonlocal latest_snapshot
        # message may be UISnapshotMessage / UIEventMessage / etc.
        msg_type = getattr(message, "type", None) or (
            message.get("type") if isinstance(message, dict) else None
        )
        if msg_type == "ui-snapshot" or isinstance(message, RTVIUISnapshotFrame):
            tree = None
            if isinstance(message, RTVIUISnapshotFrame):
                tree = getattr(message, "tree", None)
            else:
                data = getattr(message, "data", None) or (
                    message.get("data") if isinstance(message, dict) else {}
                )
                if isinstance(data, dict):
                    tree = data.get("tree") or data
            if tree is not None:
                latest_snapshot = tree
                clog.debug("[%s] ui-snapshot received (keys=%s)", call_id, list(tree.keys()) if isinstance(tree, dict) else type(tree))
            return

        # Also surface generic ui-event as SYSTEM UI EVENT if useful
        if msg_type == "ui-event":
            data = getattr(message, "data", None) or (
                message.get("data") if isinstance(message, dict) else {}
            ) or {}
            name = getattr(message, "name", None) or data.get("name") or data.get("event") or "ui-event"
            context.add_message({
                "role": "user",
                "content": f"SYSTEM UI EVENT (ui-event/{name}): {data}",
            })
            if task is not None:
                await task.queue_frames([LLMRunFrame()])

    pipeline = Pipeline([
        transport.input(),
        rtvi,
        context_aggregator.user(),
        llm,
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

    runner = PipelineRunner()
    try:
        await runner.run(task)
    except Exception as exc:
        clog.exception("[%s] WebRTC session error: %s", call_id, exc)
    finally:
        clog.info("[%s] WebRTC session ended", call_id)


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
    turnstile_token = str(body.get("turnstile_token") or body.get("cf-turnstile-response") or "").strip()

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

    depasit = await peste_limita(visitor_id, ip)
    if depasit:
        log.warning("webrtc daily limit: %s", depasit)
        return JSONResponse({"error": "daily_limit", "detail": depasit}, status_code=429)

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

    asyncio.create_task(
        run_webrtc_session(transport, client_id, visitor_id or uuid.uuid4().hex, project_id)
    )

    answer = connection.get_answer()
    return {
        "sdp": answer["sdp"],
        "type": answer["type"],
    }
