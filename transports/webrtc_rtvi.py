"""
Изолированный WebRTC + RTVI контур для «Сайта Будущего».

Legacy GSM и /ws НЕ затрагиваются.
Паттерны LLM, tools и обработчиков — как в main.py (web endpoint).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import html
import logging
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Request
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
    get_client_data,
    get_persona,
    id_din_lookup,
    id_zapisi,
    log,
    normalizeaza_timp,
    resolve_voice_name,
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
    """Формат как в main.py: [{"function_declarations": [...]}]."""
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

    known_phone = ""
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
        "You do not know the visitor's phone number unless they give it."
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

    # ----- UI -----
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

    # ----- save_lead -----
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

    # ----- Booking_tool -----
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
            await params.result_callback(TELEFON_INCOMPLET)
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

    # ----- send_sms -----
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

    # ----- end_call -----
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
        msg_type = getattr(msg, "type", None) or (msg.get("type") if isinstance(msg, dict) else None)
        if msg_type != "ui_user_interaction":
            return
        data = getattr(msg, "data", None) or (msg.get("data") if isinstance(msg, dict) else {}) or {}
        description = data.get("description", str(data))
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
    body = await request.json()
    offer_sdp = body.get("sdp")
    offer_type = body.get("type", "offer")
    client_id = (body.get("client_id") or "").strip()
    visitor_id = (body.get("visitor_id") or uuid.uuid4().hex)[:64]
    project_id = (body.get("project_id") or "").strip()

    if not offer_sdp:
        return {"error": "missing sdp"}, 400
    if not client_id:
        return {"error": "missing client_id"}, 400

    client_data = await get_client_data(client_id)
    if not client_data:
        return {"error": "unknown client_id"}, 404

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
        run_webrtc_session(transport, client_id, visitor_id, project_id)
    )

    answer = connection.get_answer()
    return {
        "sdp": answer["sdp"],
        "type": answer["type"],
    }
