import asyncio
import audioop
import datetime
import json
import os
import time
import uuid
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from google import genai
from google.genai import types
import httpx
from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    Frame,
    InputAudioRawFrame,
    InterruptionFrame,
    LLMRunFrame,
    OutputAudioRawFrame,
    UserStartedSpeakingFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.serializers.base_serializer import FrameSerializer
from pipecat.services.google.gemini_live.llm import (
    GeminiLiveLLMService,
    GeminiVADParams,
)
from pipecat.services.llm_service import FunctionCallParams
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)
from pydantic import BaseModel
import pytz
from starlette.websockets import WebSocketState
from supabase import Client, create_client
import redis.asyncio as redis

# ==========================================
# ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ (БЕЗ ХАРДКОРА)
# ==========================================
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
REDIS_URL = os.getenv("REDIS_URL")

ASTERISK_ARI_URL = os.getenv("ASTERISK_ARI_URL", "http://187.77.69.233:8088/ari/channels")
ASTERISK_ARI_USER = os.getenv("ASTERISK_ARI_USER", "asterisk")
ASTERISK_ARI_PASS = os.getenv("ASTERISK_ARI_PASS", "labupgrade_ari_pass")
ASTERISK_ENDPOINT_SUFFIX = os.getenv("ASTERISK_ENDPOINT_SUFFIX", "@moldcell_endpoint")
N8N_BASE_URL = os.getenv("N8N_BASE_URL", "https://n8n.labupgrade.in/webhook")
ASTERISK_RECORDING_PATH = os.getenv("ASTERISK_RECORDING_PATH", "/var/spool/asterisk/monitor")

# Инициализация пула соединений Redis для управления сессиями
redis_client = redis.from_url(REDIS_URL, decode_responses=True) if REDIS_URL else None


class RawPCMFrameSerializer(FrameSerializer):
    async def serialize(self, frame: Frame) -> bytes | str | None:
        if isinstance(frame, OutputAudioRawFrame):
            return frame.audio
        return None

    async def deserialize(self, data: bytes | str) -> Frame | None:
        if isinstance(data, bytes):
            return InputAudioRawFrame(
                audio=data, sample_rate=16000, num_channels=1
            )
        return None


# ==========================================
# АДАПТЕР ASTERISK -> WEBSOCKET (С ПЛАВНЫМ PACING)
# ==========================================
class AsteriskWSAdapter:
    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer
        self.client_state = WebSocketState.CONNECTED
        self.application_state = WebSocketState.CONNECTED
        self.in_state = None
        self.out_state = None
        self.next_send_time = time.time()

    async def accept(self):
        pass

    async def close(self, code=1000, reason=""):
        self.client_state = WebSocketState.DISCONNECTED
        self.application_state = WebSocketState.DISCONNECTED
        self.writer.close()
        try:
            await self.writer.wait_closed()
        except Exception:
            pass

    async def receive_bytes(self):
        """Звук от клиента (Asterisk -> ИИ)"""
        try:
            header = await self.reader.readexactly(3)
            p_len = int.from_bytes(header[1:], byteorder="big")
            data = await self.reader.readexactly(p_len)
            if header[0] == 0x00:
                self.client_state = WebSocketState.DISCONNECTED
                raise Exception("Hangup")

            resampled, self.in_state = audioop.ratecv(
                data, 2, 1, 8000, 16000, self.in_state
            )
            return resampled
        except Exception:
            self.client_state = WebSocketState.DISCONNECTED
            raise

    async def receive(self):
        try:
            data = await self.receive_bytes()
            return {"type": "websocket.receive", "bytes": data}
        except Exception:
            self.client_state = WebSocketState.DISCONNECTED
            return {"type": "websocket.disconnect", "code": 1000}

    async def send_bytes(self, data):
        """Плавная отправка (Pacing) без заиканий для RTP-канала"""
        if self.client_state != WebSocketState.CONNECTED:
            return
        try:
            softened_data = audioop.mul(data, 2, 0.75)
            resampled, self.out_state = audioop.ratecv(
                softened_data, 2, 1, 24000, 8000, self.out_state
            )

            audio_duration = len(resampled) / 16000.0
            now = time.time()

            if self.next_send_time < now:
                self.next_send_time = now

            sleep_time = self.next_send_time - now
            if sleep_time > 0.01:
                await asyncio.sleep(sleep_time)

            self.next_send_time += audio_duration

            header = b"\x10" + len(resampled).to_bytes(2, byteorder="big")
            self.writer.write(header + resampled)
            await self.writer.drain()
        except Exception:
            pass


app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- 1. ФУНКЦИИ БАЗЫ ДАННЫХ И УВЕДОМЛЕНИЙ ---
async def get_client_data(client_id: str):
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("❌ ОШИБКА: В переменных окружения отсутствуют ключи SUPABASE_URL sau SUPABASE_KEY.", flush=True)
        return None

    clean_url = SUPABASE_URL.replace("/rest/v1", "").rstrip("/")
    url = f"{clean_url}/rest/v1/saas_clients?id=eq.{client_id}&select=company_name,business_context,tone,bot_goal,subscription_status_assistent,system_message,saas_projects(tg_chat_id_notify,google_calendar_id)"
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()

            if len(data) > 0:
                client_record = data[0]
                projects = client_record.get("saas_projects", [])
                if projects and len(projects) > 0:
                    client_record["tg_chat_id_notify"] = projects[0].get("tg_chat_id_notify")
                    client_record["google_calendar_id"] = projects[0].get("google_calendar_id")
                else:
                    client_record["tg_chat_id_notify"] = None
                    client_record["google_calendar_id"] = None
                return client_record
            return None
        except Exception as e:
            print(f"❌ ОШИБКА СВЯЗИ С SUPABASE (saas_clients): {e}", flush=True)
            return None


async def get_persona_data(client_id: str):
    """Вытягивает динамические настройки бота (промпт, голос, язык) из новой таблицы"""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None

    clean_url = SUPABASE_URL.replace("/rest/v1", "").rstrip("/")
    url = f"{clean_url}/rest/v1/bot_personas?client_id=eq.{client_id}&select=system_prompt,voice_model,language"
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers, timeout=5.0)
            response.raise_for_status()
            data = response.json()
            if len(data) > 0:
                return data[0]
            return None
        except Exception as e:
            print(f"❌ ОШИБКА СВЯЗИ С SUPABASE (bot_personas): {e}", flush=True)
            return None


async def send_tg_alert(chat_id: str, message: str):
    if not TG_BOT_TOKEN or not chat_id:
        return

    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}

    async with httpx.AsyncClient() as client:
        try:
            await client.post(url, json=payload, timeout=5.0)
        except Exception as e:
            print(f"❌ EROARE la trimiterea alertei TG: {e}", flush=True)


async def generate_summary(transcript: str) -> str:
    if not transcript or len(transcript.strip()) < 10:
        return "{}"

    try:
        client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        prompt = (
            "Analizează transcriptul. Returnează un obiect JSON valid "
            "(fără formatare markdown, doar JSON pur) cu următoarele chei:\n"
            '"client_name": Numele clientului (sau null),\n'
            '"client_phone": Numărul de telefon (sau null),\n'
            '"summary": Esența apelului,\n'
            '"sentiment": Starea emoțională și obiecțiile,\n'
            '"language": Limba principală a clientului din dialog (ex: \'Română\', \'Русский\', \'English\'),\n'
            '"next_step": Ce trebuie de făcut.\n\n'
            f"Transcript:\n{transcript}"
        )

        response = await client.aio.models.generate_content(
            model="gemini-3.6-flash",
            contents=prompt,
            config=genai.types.GenerateContentConfig(
                response_mime_type="application/json",
            ),
        )
        return response.text
    except Exception as e:
        print(f"❌ Ошибка генерации саммари: {e}", flush=True)
        return "{}"


async def upload_audio_to_supabase(client_id: str, filepath: str) -> str | None:
    if not SUPABASE_URL or not SUPABASE_KEY or not os.path.exists(filepath):
        return None

    try:
        clean_supa_url = SUPABASE_URL.replace("/rest/v1", "").rstrip("/")
        supabase: Client = create_client(clean_supa_url, SUPABASE_KEY)
        bucket_name = "call-recordings"
        file_name = os.path.basename(filepath)
        storage_path = f"records/{client_id}/{file_name}"

        def _upload():
            with open(filepath, "rb") as f:
                supabase.storage.from_(bucket_name).upload(
                    path=storage_path,
                    file=f,
                    file_options={"content-type": "audio/wav"},
                )
            return supabase.storage.from_(bucket_name).get_public_url(storage_path)

        audio_url = await asyncio.to_thread(_upload)
        print(f"✅ Аудио успешно загружено в Supabase: {audio_url}", flush=True)
        return audio_url
    except Exception as e:
        print(f"❌ Ошибка при отправке файла в Supabase Storage: {e}", flush=True)
        return None


async def send_final_report_to_n8n(
    client_id: str,
    end_client_name: str,
    end_client_phone: str,
    status: str,
    transcript: str,
    summary: str,
    audio_url: str,
    system_instructions_length: int,
):
    payload = {
        "client_id": client_id,
        "end_client_name": end_client_name,
        "end_client_phone": end_client_phone,
        "status": status,
        "transcript": transcript,
        "summary": summary,
        "audio_url": audio_url,
        "system_instructions_length": system_instructions_length,
        "platform": "gsm_voice",
    }

    async with httpx.AsyncClient() as http_client:
        try:
            await http_client.post(
                f"{N8N_BASE_URL}/post-call-summary",
                json=payload,
                timeout=10.0,
            )
            print("✅ Отчет успешно отправлен в n8n", flush=True)
        except Exception as e:
            print(f"❌ Ошибка отправки финального отчета в n8n: {e}", flush=True)


# --- 2. ЭНДПОИНТ ДЛЯ ASTERISK (GET UUID) ---
@app.get("/get_uuid")
async def get_client_uuid(sip_login: str = None, sip_login_gsm: str = None):
    if not sip_login and not sip_login_gsm:
        return Response(content="error", media_type="text/plain")

    clean_url = SUPABASE_URL.replace("/rest/v1", "").rstrip("/")
    identifier = sip_login_gsm if sip_login_gsm else sip_login

    url = f"{clean_url}/rest/v1/bot_channels?identifier=eq.{identifier}&select=client_id"
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            if data and isinstance(data, list) and len(data) > 0:
                return Response(content=str(data[0].get("client_id")), media_type="text/plain")
            return Response(content="not_found", media_type="text/plain")
        except Exception as e:
            print(f"❌ Ошибка в get_client_uuid: {e}", flush=True)
            return Response(content="error", media_type="text/plain")


class OutboundCallRequest(BaseModel):
    client_id: str
    target_phone: str
    client_name: str = "client"
    call_purpose: str = "Confirmarea programării"
    custom_context: str = ""
    lang: str = "ro"


@app.post("/api/dial")
async def initiate_outbound_call(req: OutboundCallRequest):
    call_uuid = str(uuid.uuid4())
    call_data = {
        "client_id": req.client_id,
        "target_phone": req.target_phone,
        "client_name": req.client_name,
        "call_purpose": req.call_purpose,
        "custom_context": req.custom_context,
        "lang": req.lang,
    }

    if redis_client:
        await redis_client.setex(f"call_context:{call_uuid}", 600, json.dumps(call_data))
    else:
        print("⚠️ REDIS_URL не настроен. Исходящий вызов может не сработать в кластере.", flush=True)

    print(f"📞 [OUTBOUND] Создана задача звонка {call_uuid} -> {req.target_phone} ({req.client_name})", flush=True)

    payload = {
        "endpoint": f"PJSIP/{req.target_phone}{ASTERISK_ENDPOINT_SUFFIX}",
        "extension": "s",
        "context": "outbound-ai",
        "priority": 1,
        "variables": {"CALL_UUID": call_uuid},
    }

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                ASTERISK_ARI_URL,
                json=payload,
                auth=(ASTERISK_ARI_USER, ASTERISK_ARI_PASS),
                timeout=10.0,
            )
            if resp.status_code not in (200, 201):
                print(f"❌ ОШИБКА ASTERISK ARI: {resp.text}", flush=True)
                if redis_client:
                    await redis_client.delete(f"call_context:{call_uuid}")
                return {"status": "error", "details": resp.text}

            return {
                "status": "dialing",
                "call_uuid": call_uuid,
                "target": req.target_phone,
            }
        except Exception as e:
            if redis_client:
                await redis_client.delete(f"call_context:{call_uuid}")
            print(f"❌ ОШИБКА СОЕДИНЕНИЯ С ARI: {e}", flush=True)
            return {"status": "error", "message": str(e)}


class InterruptionRecoveryProcessor(FrameProcessor):
    def __init__(self, context):
        super().__init__()
        self.context = context
        self.task = None
        self.is_interrupted = False
        self.recovery_task = None

    async def _recovery_timer(self):
        try:
            await asyncio.sleep(4.0)
            if self.is_interrupted and self.task:
                print("⏳ [UX] Сработал таймер: тишина după întrerupere. Возвращаем бота în dialog.", flush=True)
                self.context.add_message({
                    "role": "system",
                    "content": "SYSTEM COMMAND: The user interrupted you but then went silent. Softly and elegantly take the initiative back. Say something like: 'Scuzați, cred că nu v-am auzit clar. Să continui de unde am rămas?'",
                })
                await self.task.queue_frames([LLMRunFrame()])
                self.is_interrupted = False
        except asyncio.CancelledError:
            pass

    async def process_frame(self, frame: Frame, direction: FrameDirection):
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


# --- 3. ГЛАВНЫЙ ОБРАБОТЧИК ASTERISK ---
async def handle_asterisk_conn(reader, writer):
    print("--- ВХОДЯЩИЙ ЗВОНОК ---", flush=True)
    system_instructions_length = 0
    client_id = None
    target_phone = "Necunoscut"
    client_name = "Necunoscut"
    wav_filename = None

    try:
        header = await reader.readexactly(3)
        payload_len = int.from_bytes(header[1:], byteorder="big")
        uuid_bytes = await reader.readexactly(payload_len)
        session_uuid = str(uuid.UUID(bytes=uuid_bytes))

        print(f"--- ВХОДЯЩИЙ/ИСХОДЯЩИЙ ЗВОНОК | UUID сессии: {session_uuid} ---", flush=True)

        if not session_uuid:
            print("❌ ОТКАЗ (403): UUID lipsește din URL.", flush=True)
            writer.close()
            return

        is_outbound = False
        outbound_info = {}

        if redis_client:
            raw_data = await redis_client.get(f"call_context:{session_uuid}")
            if raw_data:
                is_outbound = True
                outbound_info = json.loads(raw_data)
                await redis_client.delete(f"call_context:{session_uuid}")
        
        if is_outbound:
            client_id = outbound_info.get("client_id")
            target_phone = outbound_info.get("target_phone", "Necunoscut")
            client_name = outbound_info.get("client_name", "Necunoscut")
            print(f"📞 [OUTBOUND] Распознана задача исходящего звонка. Настоящий client_id: {client_id}", flush=True)
        else:
            client_id = session_uuid
            print(f"📞 [INBOUND] Входящий звонок. client_id: {client_id}", flush=True)

        client_data = await get_client_data(client_id)
        if not client_data:
            print(f"❌ ОТКАЗ (403): get_client_data a returnat None pentru client_id={client_id}. Închidem conexiunea.", flush=True)
            writer.close()
            return

        sub_status = str(client_data.get("subscription_status_assistent", "")).strip().lower()
        if sub_status == "false":
            print("❌ ОТКАЗ (403): Abonamentul este inactiv (false).", flush=True)
            writer.close()
            return

        print("🟢 TOATE VERIFICĂRILE AU TRECUT! Ridicăm apelul.", flush=True)

        # СНАЧАЛА вытягиваем динамическую Персону бота из новой таблицы
        persona_data = await get_persona_data(client_id) or {}

        # ТОЛЬКО ТЕПЕРЬ определяем язык для текущего звонка
        if is_outbound:
            call_lang = outbound_info.get("lang", "ro")
        else:
            call_lang = persona_data.get("language", "ro")

        raw_prompt = persona_data.get("system_prompt")
        if not raw_prompt:
            raw_prompt = client_data.get("system_message", "Ești un asistent virtual.")
            
        voice_model = persona_data.get("voice_model", "Enceladus")

        tz = pytz.timezone("Europe/Chisinau")
        current_time = datetime.datetime.now(tz).strftime("%A, %d %B %Y, %H:%M")
        office_status = "Open"

        system_prompt = raw_prompt.replace("{company_name}", client_data.get("company_name") or "Compania noastră")
        system_prompt = system_prompt.replace("{business_context}", client_data.get("business_context") or "")
        system_prompt = system_prompt.replace("{bot_goal}", client_data.get("bot_goal") or "")
        system_prompt = system_prompt.replace("{tone}", client_data.get("tone") or "friendly")
        system_prompt = system_prompt.replace("{current_datetime}", current_time)
        system_prompt = system_prompt.replace("{office_status}", office_status)
        system_prompt = system_prompt.replace("{lang}", call_lang)

        tools = [
            {
                "function_declarations": [
                    {
                        "name": "save_lead",
                        "description": "Salvează datele de contact și motivul apelului în CRM. Dacă sunt date dela Booking_tool, include si pe ele.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "client_name": {"type": "string"},
                                "client_phone": {"type": "string"},
                                "request_summary": {"type": "string"},
                                "event_id": {"type": "string", "description": "ID-ul evenimentului din calendar (dacă a fost creat)"},
                            },
                            "required": ["client_name", "client_phone", "request_summary"],
                        },
                    },
                    {
                        "name": "Booking_tool",
                        "description": "Gestionează calendarul: verifică, rezervă, anulează sau reprogramează.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "action": {
                                    "type": "string",
                                    "enum": ["check", "book", "lookup", "reschedule", "cancel"],
                                    "description": "Tipul acțiunii",
                                },
                                "phone": {"type": "string", "description": "Telefonul clientului"},
                                "client_name": {"type": "string", "description": "Numele clientului (obligatoriu pentru 'book')"},
                                "request_summary": {"type": "string", "description": "Motivul programării sau scurtă descriere (ex: 'Consultație automatizare')"},
                                "start_time": {"type": "string", "description": "ISO 8601 start"},
                                "end_time": {"type": "string", "description": "ISO 8601 end"},
                                "event_id": {"type": "string", "description": "ID-ul REAL al evenimentului obținut exclusiv din acțiunea 'lookup'."},
                            },
                            "required": ["action"],
                        },
                    },
                    {
                        "name": "send_sms",
                        "description": "Trimite un SMS clientului cu informații utile (adresă, confirmarea programării, link sau rezumatul discuției). Apelează doar când clientul cere sau acceptă să primească informația prin SMS.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "phone": {"type": "string", "description": "Numărul de telefon al clientului"},
                                "message": {"type": "string", "description": "Textul scurt al mesajului SMS (fără emoticoane, maxim 160 caractere)"},
                                "purpose": {
                                    "type": "string",
                                    "enum": ["address", "booking_confirmation", "info", "other"],
                                    "description": "Scopul trimiterii SMS-ului",
                                },
                            },
                            "required": ["phone", "message"],
                        },
                    },
                ]
            }
        ]

        full_system_text = system_prompt + json.dumps(tools)
        system_instructions_length = len(full_system_text)

        fake_websocket = AsteriskWSAdapter(reader, writer)
        transport = FastAPIWebsocketTransport(
            websocket=fake_websocket,
            params=FastAPIWebsocketParams(
                audio_in_enabled=True,
                audio_out_enabled=True,
                add_wav_header=False,
                serializer=RawPCMFrameSerializer(),
            ),
        )

        context = LLMContext(messages=[{"role": "system", "content": system_prompt}])
        context_aggregator = LLMContextAggregatorPair(context=context)

        llm = GeminiLiveLLMService(
            api_key=os.getenv("GEMINI_API_KEY"),
            tools=tools,
            settings=GeminiLiveLLMService.Settings(
                model="gemini-3.1-flash-live-preview",
                voice=voice_model,
                system_instruction=system_prompt,
                vad=GeminiVADParams(
                    start_sensitivity=types.StartSensitivity.START_SENSITIVITY_LOW,
                    silence_duration_ms=1000,
                ),
            ),
        )

        async def process_save_lead(params: FunctionCallParams):
            tg_chat_id = client_data.get("tg_chat_id_notify", "")
            company_name = client_data.get("company_name", "Necunoscut")
            async with httpx.AsyncClient() as http_client:
                try:
                    response = await http_client.post(
                        f"{N8N_BASE_URL}/save_lead?client_id={client_id}&tg_chat_id={tg_chat_id}",
                        json=params.arguments,
                        timeout=5.0,
                    )
                    response.raise_for_status()
                    await params.result_callback(response.json())
                except asyncio.CancelledError:
                    try:
                        await params.result_callback({"status": "cancelled", "message": "Client interrupted. Await client input."})
                    except Exception:
                        pass
                    raise
                except Exception as e:
                    error_msg = f"⚠️ <b>Eroare API (save_lead)</b>\n🏢 Companie: {company_name}\n🔧 Detalii eroare: <code>{str(e)}</code>\nN8N nu a putut salva lead-ul!"
                    await send_tg_alert(tg_chat_id, error_msg)
                    await params.result_callback({"error": f"Eroare CRM: {str(e)}"})

        async def process_booking_tool(params: FunctionCallParams):
            cal_id = client_data.get("google_calendar_id", "")
            tg_chat_id = client_data.get("tg_chat_id_notify", "")
            company_name = client_data.get("company_name", "Necunoscut")
            async with httpx.AsyncClient() as http_client:
                try:
                    response = await http_client.post(
                        f"{N8N_BASE_URL}/booking?client_id={client_id}&google_calendar_id={cal_id}",
                        json=params.arguments,
                        timeout=10.0,
                    )
                    response.raise_for_status()
                    await params.result_callback(response.json())
                except asyncio.CancelledError:
                    try:
                        await params.result_callback({"status": "cancelled", "message": "Client interrupted the tool call. Stop and listen."})
                    except Exception:
                        pass
                    raise
                except Exception as e:
                    error_msg = f"⚠️ <b>Eroare API (Booking_tool)</b>\n🏢 Companie: {company_name}\n🔧 Detalii eroare: <code>{str(e)}</code>\nN8N nu a procesat rezervarea!"
                    await send_tg_alert(tg_chat_id, error_msg)
                    await params.result_callback({"status": "error", "message": f"Sistemul de rezervări nu răspunde: {str(e)}"})

        async def process_send_sms(params: FunctionCallParams):
            tg_chat_id = client_data.get("tg_chat_id_notify", "")
            company_name = client_data.get("company_name", "Necunoscut")
            async with httpx.AsyncClient() as http_client:
                try:
                    response = await http_client.post(
                        f"{N8N_BASE_URL}/send_sms?client_id={client_id}&tg_chat_id={tg_chat_id}",
                        json=params.arguments,
                        timeout=5.0,
                    )
                    response.raise_for_status()
                    await params.result_callback({"status": "success", "message": "SMS-ul a fost trimis cu succes către client."})
                except asyncio.CancelledError:
                    try:
                        await params.result_callback({"status": "cancelled", "message": "Client interrupted the tool call."})
                    except Exception:
                        pass
                    raise
                except Exception as e:
                    error_msg = f"⚠️ <b>Eroare API (send_sms)</b>\n🏢 Companie: {company_name}\n🔧 Detalii eroare: <code>{str(e)}</code>\nN8N nu a putut trimite SMS-ul!"
                    await send_tg_alert(tg_chat_id, error_msg)
                    await params.result_callback({"status": "error", "message": f"Eroare la trimiterea SMS: {str(e)}"})

        llm.register_function("save_lead", process_save_lead)
        llm.register_function("Booking_tool", process_booking_tool)
        llm.register_function("send_sms", process_send_sms)

        wav_filename = f"{ASTERISK_RECORDING_PATH}/{session_uuid}.wav"

        recovery_processor = InterruptionRecoveryProcessor(context)

        pipeline = Pipeline(
            [
                transport.input(),
                context_aggregator.user(),
                llm,
                recovery_processor,
                transport.output(),
                context_aggregator.assistant(),
            ]
        )

        task = PipelineTask(
            pipeline,
            params=PipelineParams(allow_interruptions=True, idle_timeout=20.0),
        )
        recovery_processor.task = task

        runner = PipelineRunner()

        if is_outbound:
            purpose = outbound_info.get("call_purpose", "Confirmarea programării")
            custom_context = outbound_info.get("custom_context", "")
            context.add_message({
                "role": "system",
                "content": f"ATENȚIE: Acesta este un apel DE IEȘIRE (Outbound call). Scopul apelului: {purpose}. Detalii: {custom_context}."
            })
            greeting_prompt = (
                f"SYSTEM EVENT: Clientul a răspuns la apelul de ieșire. "
                f"Începe conversația în limba '{call_lang}'. Salută-l pe {client_name} și menționează politicos scopul apelului: {purpose}. "
                "Nu adăuga informații inutile."
            )
        else:
            greeting_prompt = (
                f"SYSTEM EVENT: Clientul s-a conectat pe linia de intrare. "
                f"Începe conversația politicos în limba '{call_lang}' și întreabă-l cu ce îl poți ajuta."
            )

        context.add_message({"role": "user", "content": greeting_prompt})

        await task.queue_frames([LLMRunFrame()])
        await runner.run(task)

    except Exception as e:
        print(f"❌ Ошибка соединения: {e}", flush=True)
    finally:
        print("📞 Звонок завершен. Начинаем фоновые задачи...", flush=True)

        if "context" in locals() and client_id:
            messages = context.messages
            user_replies = [
                m["content"] for m in messages
                if m.get("role") == "user" and "SYSTEM EVENT:" not in m.get("content", "")
            ]

            full_transcript = ""
            for msg in messages:
                if msg.get("role") in ["user", "assistant"] and msg.get("content"):
                    if "SYSTEM COMMAND:" not in msg["content"]:
                        role = "Client" if msg["role"] == "user" else "AI"
                        full_transcript += f"{role}: {msg['content']}\n"

            if len(user_replies) == 0:
                print("⚠️ [ФИЛЬТР] Короткий звонок без ответа пользователя. Пропускаем Gemini.", flush=True)
                call_status = "outbound_short_call" if is_outbound else "inbound_dropped"
                await send_final_report_to_n8n(
                    client_id=client_id,
                    end_client_name=client_name,
                    end_client_phone=target_phone,
                    status=call_status,
                    transcript=full_transcript,
                    summary="{}",
                    audio_url="",
                    system_instructions_length=system_instructions_length,
                )
            else:
                summary = await generate_summary(full_transcript)
                audio_url = await upload_audio_to_supabase(client_id, wav_filename)
                await send_final_report_to_n8n(
                    client_id=client_id,
                    end_client_name=client_name,
                    end_client_phone=target_phone,
                    status="completed",
                    transcript=full_transcript,
                    summary=summary,
                    audio_url=audio_url or "",
                    system_instructions_length=system_instructions_length,
                )

        if wav_filename and os.path.exists(wav_filename):
            try:
                os.remove(wav_filename)
            except Exception as e:
                print(f"⚠️ Nu s-a putut șterge fișierul audio: {e}")

        print("✅ Пост-обработка завершена успешно.", flush=True)
        writer.close()


@app.on_event("startup")
async def startup_event():
    server = await asyncio.start_server(handle_asterisk_conn, "0.0.0.0", 8085)
    print("🚀 AudioSocket сервер запущен на порту 8085", flush=True)
    asyncio.create_task(server.serve_forever())
