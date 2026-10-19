"""
Изолированный WebRTC + RTVI контур для «Сайта Будущего».

Legacy GSM и /ws НЕ затрагиваются.
Фаза 3.1: Анти-Диктовка.
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
from typing import Optional

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


def _build_tools_with_ui(client_data: dict, readable_hours: str) -> list[dict]:
    base = build_tools(client_data, readable_hours, web=True)
    base.append(UI_NAVIGATION_TOOL)
    return [{"function_declarations": base}]


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
        "from the UI. When a SYSTEM UI EVENT brings a phone number, use it."
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
                "Booking_tool": RTVIFunctionCallReportLevel.ARGUMENTS,
            }
        ),
    )

    context = LLMContext(messages=[])
    context_aggregator = LLMContextAggregatorPair(context)
    task: Optional[PipelineTask] = None

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
                    "Forma de pe ecran este deschisă. Nu cere numărul pe voice, "
                    "cifră cu cifră. Spune scurt să completeze telefonul în formular "
                    "sau să apese autofill. Așteaptă SYSTEM UI EVENT cu numărul, "
                    "apoi apelează din nou Booking_tool action=book."
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
            await call_n8n("send_sms", {"client_id": client_id}, params.arguments, 5.0)
            await params.result_callback({"status": "success", "message": "SMS trimis"})
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                await params.result_callback({"status": "cancelled"})
            raise
        except Exception as exc:
            await send_tg_alert(
                tg_chat,
                f"⚠️ <b>Eroare API (send_sms)</b>\n🏢 {company}\n🔧 <code>{html.escape(str(exc))}</code>",
            )
            await params.result_callback({"status": "error", "message": str(exc)})

    async def process_end_call(params: FunctionCallParams):
        elapsed = time.time() - start_ts
        if elapsed < MIN_SECONDS_BEFORE_END_CALL:
            await params.result_callback({
                "status": "rejected",
                "message": (
                    "Nu închide acum. Clientul nu și-a luat rămas-bun clar. "
                    "Cere-i să repete și continuă conversația."
                ),
            })
            return
        await params.result_callback({"status": "success", "message": "Call ended"})

        async def delayed_end():
            await asyncio.sleep(3.5)
            if task is not None:
                await task.queue_frames([CancelFrame()])

        asyncio.create_task(delayed_end())

    llm.register_function("control_website_ui", process_control_website_ui)
    llm.register_function("save_lead", process_save_lead)
    llm.register_function("send_sms", process_sms)
    llm.register_function("end_call", process_end_call)
    if client_data.get("google_calendar_id"):
        llm.register_function("Booking_tool", process_booking)

    @rtvi.event_handler("on_client_message")
    async def on_client_message(rtvi_proc, msg):
        nonlocal learned_phone
        msg_type = getattr(msg, "type", None) or (msg.get("type") if isinstance(msg, dict) else None)
        if msg_type != "ui_user_interaction":
            return
        data = getattr(msg, "data", None) or (msg.get("data") if isinstance(msg, dict) else {}) or {}
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
async def webrtc_offer(request: Request):
    """
    Сигналинг WebRTC + та же защита, что у /ws:
    ключ виджета, origin, blacklist, Turnstile, суточные лимиты.
    """
    body = await request.json()
    offer_sdp = body.get("sdp")
    offer_type = body.get("type", "offer")
    key = re.sub(r"[^A-Za-z0-9_\-]", "", str(body.get("key") or ""))[:64]
    visitor_id = re.sub(r"[^A-Za-z0-9_\-]", "", str(body.get("visitor_id") or ""))[:64]
    turnstile_token = str(body.get("t") or "")
    project_id = str(body.get("project_id") or "").strip()

    if not offer_sdp:
        return JSONResponse({"error": "missing sdp"}, status_code=400)
    if not key:
        return JSONResponse({"error": "missing widget key"}, status_code=400)

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
