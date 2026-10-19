"""
Изолированный WebRTC + RTVI контур для «Сайта Будущего».

Legacy GSM и /ws НЕ затрагиваются.
Все общие компоненты берутся из core/.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import json
import logging
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Request, WebSocket
from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    Frame,
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
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.transports.base_transport import TransportParams

from core import (
    DEFAULT_LANG,
    DEFAULT_TZ,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    IDLE_TIMEOUT_SECONDS,
    MAX_CALL_SECONDS,
    Persona,
    build_personality_block,
    build_tools,
    get_client_data,
    get_persona,
    log,
    run_archivist_and_notify_n8n,
    sb_select,
    tz_for,
    upload_audio_to_supabase,
)

router = APIRouter(tags=["webrtc-rtvi"])

# =============================================================================
# Инструмент управления интерфейсом
# =============================================================================

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
    """Существующие tools + control_website_ui."""
    tools = build_tools(client_data, readable_hours, web=True)
    # build_tools возвращает list[dict] function_declarations-ready
    if tools and "function_declarations" in tools[0]:
        tools[0]["function_declarations"].append(UI_NAVIGATION_TOOL)
    else:
        tools = [{"function_declarations": [UI_NAVIGATION_TOOL]}]
    return tools


# =============================================================================
# Основной пайплайн WebRTC-сессии
# =============================================================================

async def run_webrtc_session(
    transport: SmallWebRTCTransport,
    client_id: str,
    visitor_id: str,
    project_id: str = "",
) -> None:
    """Один WebRTC-сеанс «Сайта Будущего»."""
    call_id = uuid.uuid4().hex[:8]
    clog = logging.LoggerAdapter(log, {"call_id": call_id})
    clog.info("[%s] WebRTC session start client=%s visitor=%s", call_id, client_id, visitor_id)

    client_data = await get_client_data(client_id) or {}
    persona = await get_persona(client_id)
    tz_name = client_data.get("timezone") or DEFAULT_TZ
    call_lang = persona.language or DEFAULT_LANG

    # --- LLM ---
    system_prompt = (
        build_personality_block(persona, call_lang)
        + "\n\n"
        + (client_data.get("system_prompt") or "")
        + "\n\n"
        "You can control the website UI with the control_website_ui tool. "
        "When the user asks to see services, prices, contacts or wants to book — "
        "call control_website_ui first, then give a short spoken answer."
    )

    tools = _build_tools_with_ui(client_data, "")

    llm = GeminiLiveLLMService(
        api_key=GEMINI_API_KEY,
        model=GEMINI_MODEL,
        system_instruction=system_prompt,
        tools=tools,
        settings=GeminiLiveLLMService.Settings(
            vad=GeminiVADParams(
                start_sensitivity="low",
                end_sensitivity="low",
            )
        ),
    )

    # --- RTVI ---
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

    context = LLMContext()
    context_aggregator = LLMContextAggregatorPair(context)

    # --- Обработчик UI-инструмента ---
    async def process_control_website_ui(params: FunctionCallParams):
        section = params.arguments.get("section", "hero")
        highlight = params.arguments.get("highlight_element")
        prefill = params.arguments.get("prefill_data") or {}

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
            "instruction": f"Section '{section}' is now shown on screen. Give a short spoken summary.",
        })

    llm.register_function("control_website_ui", process_control_website_ui)

    # --- Обратные события от экрана ---
    @rtvi.event_handler("on_client_message")
    async def on_client_message(rtvi_proc, msg):
        if getattr(msg, "type", None) == "ui_user_interaction" or (
            isinstance(msg, dict) and msg.get("type") == "ui_user_interaction"
        ):
            data = msg.data if hasattr(msg, "data") else msg.get("data", {})
            description = data.get("description", str(data))
            context.add_message({
                "role": "user",
                "content": f"SYSTEM UI EVENT: Client interacted with the screen: {description}",
            })
            await task.queue_frames([LLMRunFrame()])

    # --- Pipeline ---
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
        # Короткое приветствие
        await task.queue_frames([
            LLMMessagesAppendFrame(messages=[{
                "role": "user",
                "content": "SYSTEM: Client just connected to the website. Greet briefly and ask how you can help.",
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


# =============================================================================
# Сигналинг (SDP offer/answer)
# =============================================================================

@router.post("/api/offer")
async def webrtc_offer(request: Request):
    """
    Сигналинг для SmallWebRTCTransport.
    Клиент присылает SDP offer, сервер возвращает answer.
    """
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

    # Проверяем, что клиент существует
    client_data = await get_client_data(client_id)
    if not client_data:
        return {"error": "unknown client_id"}, 404

    from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection

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

    # Запускаем пайплайн в фоне
    asyncio.create_task(
        run_webrtc_session(transport, client_id, visitor_id, project_id)
    )

    answer = connection.get_answer()
    return {
        "sdp": answer["sdp"],
        "type": answer["type"],
    }
