"""
Изолированный WebRTC + RTVI контур для «Сайта Будущего».

Legacy GSM и /ws НЕ затрагиваются.
Все общие компоненты берутся из core/.
Паттерны инициализации LLM и tools — как в main.py (web endpoint).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from typing import Any, Optional

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
    DEFAULT_TZ,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    IDLE_TIMEOUT_SECONDS,
    build_personality_block,
    build_tools,
    get_client_data,
    get_persona,
    log,
    resolve_voice_name,
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
    """Формат как в main.py: [{"function_declarations": [...]}]."""
    base = build_tools(client_data, readable_hours, web=True)
    base.append(UI_NAVIGATION_TOOL)
    return [{"function_declarations": base}]


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
    clog = logging.LoggerAdapter(log, {})
    clog.info("[%s] WebRTC session start client=%s visitor=%s", call_id, client_id, visitor_id)

    client_data = await get_client_data(client_id) or {}
    persona = await get_persona(client_id)
    call_lang = persona.language or DEFAULT_LANG

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

    llm.register_function("control_website_ui", process_control_website_ui)

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
