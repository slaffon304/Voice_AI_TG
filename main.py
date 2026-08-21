import asyncio
import datetime
import json
import os
import re
import time
import uuid
from fastapi import FastAPI, Response, Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
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
    LLMUserAggregatorParams,
)
from pipecat.turns.user_turn_strategies import ExternalUserTurnStrategies
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
from pipecat.audio.filters.rnnoise_filter import RNNoiseFilter
from pydantic import BaseModel
import pytz
from starlette.websockets import WebSocketState
from supabase import Client, create_client
import redis.asyncio as redis
import gc

# ==========================================
# ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ
# ==========================================
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
REDIS_URL = os.getenv("REDIS_URL")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
API_SECRET_TOKEN = os.getenv("API_SECRET_TOKEN")

ASTERISK_ARI_URL = os.getenv("ASTERISK_ARI_URL", "http://187.77.69.233:8088/ari/channels")
ASTERISK_ARI_USER = os.getenv("ASTERISK_ARI_USER", "asterisk")
ASTERISK_ARI_PASS = os.getenv("ASTERISK_ARI_PASS", "labupgrade_ari_pass")
ASTERISK_ENDPOINT_SUFFIX = os.getenv("ASTERISK_ENDPOINT_SUFFIX", "@moldcell_endpoint")
N8N_BASE_URL = os.getenv("N8N_BASE_URL", "https://n8n.labupgrade.in/webhook")
ASTERISK_RECORDING_PATH = os.getenv("ASTERISK_RECORDING_PATH", "/var/spool/asterisk/monitor")

KOMMO_SUBDOMAIN = os.getenv("KOMMO_SUBDOMAIN")
KOMMO_ACCESS_TOKEN = os.getenv("KOMMO_ACCESS_TOKEN")

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
# АДАПТЕР ASTERISK (БЕЗ AUDIOOP, СКОРОСТНОЙ)
# ==========================================
class AsteriskWSAdapter:
    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer
        self.client_state = WebSocketState.CONNECTED
        self.application_state = WebSocketState.CONNECTED
        self.next_send_time = time.time()
        self.is_muted = False 

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
        try:
            header = await self.reader.readexactly(3)
            p_len = int.from_bytes(header[1:], byteorder="big")
            data = await self.reader.readexactly(p_len)
            
            if header[0] == 0x00:
                self.client_state = WebSocketState.DISCONNECTED
                raise Exception("Hangup")

            if not data or len(data) == 0:
                return b""

            return data
        except Exception:
            self.client_state = WebSocketState.DISCONNECTED
            raise

    async def receive(self):
        while True:
            try:
                data = await self.receive_bytes()
                
                if not data:
                    continue

                if self.is_muted:
                    data = b'\x00' * len(data)

                return {"type": "websocket.receive", "bytes": data}
            except Exception:
                self.client_state = WebSocketState.DISCONNECTED
                return {"type": "websocket.disconnect", "code": 1000}

    async def send_bytes(self, data):
        if self.client_state != WebSocketState.CONNECTED:
            return
        try:
            # 16000 Гц, 16 бит моно = 32000 байт/сек
            audio_duration = len(data) / 32000.0
            now = time.time()

            if self.next_send_time < now:
                self.next_send_time = now

            sleep_time = self.next_send_time - now
            if sleep_time > 0.01:
                await asyncio.sleep(sleep_time)

            self.next_send_time += audio_duration

            header = b"\x10" + len(data).to_bytes(2, byteorder="big")
            self.writer.write(header + data)
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

# ==========================================
# БЕЗОПАСНОСТЬ 
# ==========================================
security_scheme = HTTPBearer()

def verify_token(credentials: HTTPAuthorizationCredentials = Security(security_scheme)):
    if not API_SECRET_TOKEN:
        raise HTTPException(status_code=500, detail="Server config error: API token missing")
    if credentials.credentials != API_SECRET_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid authorization token")
    return credentials.credentials

# ==========================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==========================================
def format_kommo_phone(phone: str) -> str:
    if not phone or phone == "Necunoscut":
        return "Necunoscut"
    clean = "".join(filter(str.isdigit, str(phone)))
    if not clean: return "Necunoscut"
    if clean.startswith("0") and len(clean) == 9: clean = "373" + clean[1:]
    elif len(clean) == 8: clean = "373" + clean
    if clean.startswith("373") and len(clean) >= 11: return f"+373 {clean[3:]}"
    if len(clean) > 3: return f"+{clean[:3]} {clean[3:]}"
    return f"+{clean}"

def extract_real_phone(*args, ignore_trunk="78001079"):
    for val in args:
        if not val: continue
        matches = re.findall(r"\d{8,15}", str(val))
        for num in matches:
            if ignore_trunk not in num and num != "078001079": return num
    return "Necunoscut"

async def get_client_data(client_id: str):
    if not SUPABASE_URL or not SUPABASE_KEY: return None
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
        except Exception: return None

async def get_persona_data(client_id: str):
    if not SUPABASE_URL or not SUPABASE_KEY: return None
    clean_url = SUPABASE_URL.replace("/rest/v1", "").rstrip("/")
    url = f"{clean_url}/rest/v1/bot_personas?client_id=eq.{client_id}&select=system_prompt,voice_model,language"
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers, timeout=5.0)
            response.raise_for_status()
            data = response.json()
            if len(data) > 0: return data[0]
            return None
        except Exception: return None

async def get_caller_memory(client_id: str, phone: str):
    default_memory = {"core": "", "short": "", "long": ""}
    if not SUPABASE_URL or not SUPABASE_KEY or not phone or phone == "Necunoscut":
        return default_memory, "first_time"
    clean_phone = "".join(filter(str.isdigit, str(phone)))
    clean_url = SUPABASE_URL.replace("/rest/v1", "").rstrip("/")
    url = f"{clean_url}/rest/v1/caller_memories?client_id=eq.{client_id}&phone=eq.{clean_phone}&select=core_identity,short_term_context,long_term_context,last_interaction_at"
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    time_context = "first_time"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, timeout=2.0)
            if resp.status_code == 200:
                data = resp.json()
                if data and len(data) > 0:
                    record = data[0]
                    memory = {
                        "core": record.get("core_identity", ""),
                        "short": record.get("short_term_context", ""),
                        "long": record.get("long_term_context", "")
                    }
                    last_at_str = record.get("last_interaction_at")
                    if last_at_str:
                        last_time = datetime.datetime.fromisoformat(last_at_str.replace('Z', '+00:00'))
                        now = datetime.datetime.now(datetime.timezone.utc)
                        delta_minutes = int((now - last_time).total_seconds() / 60)
                        if delta_minutes < 15: time_context = "very_recent"
                        elif delta_minutes < 1440: time_context = "same_day"
                        else: time_context = "new_day"
                    return memory, time_context
    except Exception as e: print(f"⚠️ Ошибка Supabase при получении памяти: {e}", flush=True)
    return default_memory, time_context

async def lookup_inbound_client_in_kommo(caller_phone: str) -> dict:
    if not KOMMO_SUBDOMAIN or not KOMMO_ACCESS_TOKEN or caller_phone == "Necunoscut": return {}
    subdomain = KOMMO_SUBDOMAIN.encode("ascii", "ignore").decode("ascii").strip()
    token = KOMMO_ACCESS_TOKEN.encode("ascii", "ignore").decode("ascii").strip()
    clean_phone = "".join(filter(str.isdigit, str(caller_phone)))
    if len(clean_phone) < 6: return {}
    search_query = clean_phone[-8:] if len(clean_phone) >= 8 else clean_phone
    url = f"https://{subdomain}.kommo.com/api/v4/contacts"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    params = {"query": search_query, "with": "leads"}
    async with httpx.AsyncClient() as http_client:
        try:
            resp = await http_client.get(url, headers=headers, params=params, timeout=2.5)
            if resp.status_code == 200:
                data = resp.json()
                contacts = data.get("_embedded", {}).get("contacts", [])
                if contacts and len(contacts) > 0:
                    contact = contacts[0]
                    client_name = contact.get("name") or "client"
                    lang = "ro"
                    for f in contact.get("custom_fields_values") or []:
                        code = str(f.get("field_code") or "").upper()
                        name = str(f.get("field_name") or "").lower()
                        if code == "LANG" or "язык" in name or "limba" in name or "lang" in name:
                            val = str(f.get("values", [{}])[0].get("value", "")).lower()
                            if "ru" in val or "рус" in val: lang = "ru"
                            elif "ro" in val or "rom" in val or "md" in val: lang = "ro"
                            break
                    return {"found": True, "name": client_name, "lang": lang}
        except Exception: pass
    return {"found": False}

async def send_tg_alert(chat_id: str, message: str):
    if not TG_BOT_TOKEN or not chat_id: return
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    async with httpx.AsyncClient() as client:
        try: await client.post(url, json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"}, timeout=5.0)
        except Exception: pass

async def upload_audio_to_supabase(client_id: str, filepath: str) -> str | None:
    if not SUPABASE_URL or not SUPABASE_KEY or not os.path.exists(filepath): return None
    try:
        clean_supa_url = SUPABASE_URL.replace("/rest/v1", "").rstrip("/")
        supabase: Client = create_client(clean_supa_url, SUPABASE_KEY)
        bucket_name = "call-recordings"
        unique_filename = f"record_{uuid.uuid4().hex[:8]}.wav"
        storage_path = f"records/{client_id}/{unique_filename}"
        def _upload():
            with open(filepath, "rb") as f:
                supabase.storage.from_(bucket_name).upload(path=storage_path, file=f, file_options={"content-type": "audio/wav"})
            return supabase.storage.from_(bucket_name).get_public_url(storage_path)
        return await asyncio.to_thread(_upload)
    except Exception as e: return None

async def run_archivist_and_notify_n8n(client_id: str, phone: str, client_name: str, old_memory: dict, chat_history: str, audio_url: str, sys_length: int, direction: str, call_status: str):
    if not chat_history.strip() or phone == "Necunoscut": return
    print(f"🔄 [ARCHIVIST] Запуск консолидации памяти для {phone}...", flush=True)
    tz = pytz.timezone("Europe/Chisinau")
    today_date = datetime.datetime.now(tz).strftime('%Y-%m-%d')
    clean_phone = "".join(filter(str.isdigit, str(phone)))

    prompt = f"""Ты ИИ-архивариус. Твоя задача — обновить память пользователя и составить резюме звонка для CRM.
Дата звонка: {today_date}. Направление: {direction}.

СТАРАЯ ПАМЯТЬ:
CORE IDENTITY: {old_memory.get('core', 'Нет данных')}
SHORT TERM: {old_memory.get('short', 'Нет данных')}
LONG TERM: {old_memory.get('long', 'Нет данных')}

ТРАНСКРИПТ НОВОГО ЗВОНКА:
{chat_history}

ИНСТРУКЦИЯ (Выведи СТРОГО JSON):
1. 'core_identity': Обнови, если клиент сообщил фундаментальный факт.
2. 'short_term_context': Перемести старые факты (старше 3 дней) в long_term. Запиши новые факты из звонка в формате "[{today_date}]: факт".
3. 'long_term_context': Сжатая история прошлых обращений.
4. 'summary': Подробная суть текущего звонка для менеджера в CRM.
5. 'sentiment': Эмоциональный настрой и возражения.
6. 'next_step': Какой следующий шаг требуется (перезвонить, отправить КП и т.д.).
7. 'language': На каком языке говорил клиент (ro/ru/en).

Формат ответа (без markdown):
{{
    "core_identity": "...", "short_term_context": "...", "long_term_context": "...", "summary": "...", "sentiment": "...", "next_step": "...", "language": "..."
}}
"""
    fallback_models = ['gemini-3.6-flash', 'gemini-3.1-pro-preview', 'gemini-3.1-flash-lite', 'gemini-3.5-flash']
    attempt = 0
    data = {}
    client = genai.Client(api_key=GEMINI_API_KEY)
    while attempt < len(fallback_models):
        current_model = fallback_models[attempt]
        try:
            response = await client.aio.models.generate_content(
                model=current_model,
                contents=prompt,
                config=genai.types.GenerateContentConfig(response_mime_type="application/json"),
            )
            data = json.loads(response.text.strip())
            break
        except Exception:
            attempt += 1
            if attempt < len(fallback_models): await asyncio.sleep(3)
            else:
                data = {
                    "core_identity": old_memory.get('core', ''), "short_term_context": old_memory.get('short', ''),
                    "long_term_context": old_memory.get('long', ''), "summary": "Ошибка генерации саммари (Все API модели недоступны).",
                    "sentiment": "Неизвестно", "next_step": "Связаться вручную", "language": "ro"
                }

    try:
        clean_url = SUPABASE_URL.replace("/rest/v1", "").rstrip("/")
        db = create_client(clean_url, SUPABASE_KEY)
        await asyncio.to_thread(
            db.table("caller_memories").upsert({
                "client_id": client_id, "phone": clean_phone,
                "core_identity": data.get("core_identity", ""), "short_term_context": data.get("short_term_context", ""),
                "long_term_context": data.get("long_term_context", ""),
                "last_interaction_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }, on_conflict="client_id,phone").execute
        )
        print("💾 [ARCHIVIST] Память успешно сохранена.", flush=True)

        n8n_payload = {
            "client_id": client_id, "end_client_name": client_name, "end_client_phone": phone,
            "status": call_status, "transcript": chat_history,
            "summary": json.dumps({
                "client_name": client_name, "summary": data.get("summary", ""),
                "sentiment": data.get("sentiment", ""), "next_step": data.get("next_step", ""),
                "language": data.get("language", "")
            }, ensure_ascii=False),
            "audio_url": audio_url, "system_instructions_length": sys_length,
            "platform": "gsm_voice", "direction": direction,
        }
        async with httpx.AsyncClient() as http_client:
            await http_client.post(f"{N8N_BASE_URL}/post-call-summary", json=n8n_payload, timeout=10.0)
            print("✅ [ARCHIVIST] Отчет успешно отправлен в n8n", flush=True)
    except Exception as e: print(f"❌ [ARCHIVIST] Ошибка сохранения/отправки: {e}", flush=True)

@app.get("/get_uuid")
async def get_client_uuid(sip_login: str = None, sip_login_gsm: str = None, phone: str = None, ani: str = None, from_hdr: str = None, all_id: str = None):
    if not sip_login and not sip_login_gsm: return Response(content="error", media_type="text/plain")
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
                client_id = str(data[0].get("client_id"))
                raw_phone = extract_real_phone(ani, all_id, from_hdr, phone)
                formatted_phone = format_kommo_phone(raw_phone)
                if formatted_phone != "Necunoscut" and redis_client:
                    await redis_client.setex(f"incoming_phone:{client_id}", 60, formatted_phone)
                return Response(content=client_id, media_type="text/plain")
            return Response(content="not_found", media_type="text/plain")
        except Exception: return Response(content="error", media_type="text/plain")

class OutboundCallRequest(BaseModel):
    client_id: str
    target_phone: str
    call_purpose: str
    client_name: str = "client"
    custom_context: str = ""
    lang: str = "ro"

@app.post("/api/dial")
async def initiate_outbound_call(req: OutboundCallRequest, token: str = Depends(verify_token)):
    call_uuid = str(uuid.uuid4())
    formatted_phone = format_kommo_phone(req.target_phone)
    call_data = {
        "client_id": req.client_id, "target_phone": formatted_phone, "client_name": req.client_name,
        "call_purpose": req.call_purpose, "custom_context": req.custom_context, "lang": req.lang,
    }
    if redis_client: await redis_client.setex(f"call_context:{call_uuid}", 600, json.dumps(call_data))
    payload = {
        "endpoint": f"PJSIP/{formatted_phone}{ASTERISK_ENDPOINT_SUFFIX}",
        "extension": "s", "context": "outbound-ai", "priority": 1, "variables": {"CALL_UUID": call_uuid},
    }
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(ASTERISK_ARI_URL, json=payload, auth=(ASTERISK_ARI_USER, ASTERISK_ARI_PASS), timeout=10.0)
            if resp.status_code not in (200, 201):
                if redis_client: await redis_client.delete(f"call_context:{call_uuid}")
                return {"status": "error", "details": resp.text}
            return {"status": "dialing", "call_uuid": call_uuid, "target": formatted_phone}
        except Exception as e:
            if redis_client: await redis_client.delete(f"call_context:{call_uuid}")
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
                self.context.add_message({
                    "role": "system",
                    "content": "SYSTEM COMMAND: The user interrupted you but then went silent. Softly and elegantly take the initiative back.",
                })
                await self.task.queue_frames([LLMRunFrame()])
                self.is_interrupted = False
        except asyncio.CancelledError: pass

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, InterruptionFrame):
            self.is_interrupted = True
            if self.recovery_task: self.recovery_task.cancel()
            self.recovery_task = asyncio.create_task(self._recovery_timer())
        elif isinstance(frame, (OutputAudioRawFrame, UserStartedSpeakingFrame)):
            if self.recovery_task: self.recovery_task.cancel()
            self.is_interrupted = False
        await self.push_frame(frame, direction)

# ==========================================
# ГЛАВНЫЙ ОБРАБОТЧИК ASTERISK
# ==========================================
async def handle_asterisk_conn(reader, writer):
    print("--- ВХОДЯЩИЙ ЗВОНОК ---", flush=True)
    system_instructions_length = 0
    client_id = None
    target_phone = "Necunoscut"
    client_name = "client"
    is_outbound = False  
    session_uuid = "unknown"

    try:
        header = await reader.readexactly(3)
        payload_len = int.from_bytes(header[1:], byteorder="big")
        uuid_bytes = await reader.readexactly(payload_len)
        session_uuid = str(uuid.UUID(bytes=uuid_bytes))

        if not session_uuid:
            writer.close()
            return

        outbound_info = {}
        inbound_crm = {}

        if redis_client:
            raw_data = await redis_client.get(f"call_context:{session_uuid}")
            if raw_data:
                is_outbound = True
                outbound_info = json.loads(raw_data)
                await redis_client.delete(f"call_context:{session_uuid}")
        
        if is_outbound:
            client_id = outbound_info.get("client_id")
            target_phone = outbound_info.get("target_phone", "Necunoscut")
            client_name = outbound_info.get("client_name", "client")
            call_lang = outbound_info.get("lang", "ro")
            purpose = outbound_info.get("call_purpose", "")
        else:
            client_id = session_uuid
            if redis_client:
                saved_phone = await redis_client.get(f"incoming_phone:{client_id}")
                if saved_phone: target_phone = saved_phone
            
            inbound_crm = await lookup_inbound_client_in_kommo(target_phone)
            if inbound_crm.get("found"):
                client_name = inbound_crm.get("name") or "client"
                call_lang = str(inbound_crm.get("lang", "ro")).lower().strip()
            else:
                call_lang = "ro"

        client_data = await get_client_data(client_id)
        if not client_data:
            writer.close()
            return

        if str(client_data.get("subscription_status_assistent", "")).strip().lower() == "false":
            writer.close()
            return

        persona_data = await get_persona_data(client_id) or {}
        if not is_outbound and not inbound_crm.get("found"):
            call_lang = persona_data.get("language", "ro")

        caller_memory, time_context = await get_caller_memory(client_id, target_phone)

        raw_prompt = persona_data.get("system_prompt") or client_data.get("system_message", "Ești un asistent virtual.")
        tz = pytz.timezone("Europe/Chisinau")
        current_time = datetime.datetime.now(tz).strftime("%A, %d %B %Y, %H:%M")
        
        safe_company_name = str(client_data.get("company_name") or "Compania").replace("{", "").replace("}", "")
        safe_business_context = str(client_data.get("business_context") or "").replace("{", "").replace("}", "")
        safe_bot_goal = str(client_data.get("bot_goal") or "").replace("{", "").replace("}", "")

        system_prompt = raw_prompt.replace("{company_name}", safe_company_name)
        system_prompt = system_prompt.replace("{business_context}", safe_business_context)
        system_prompt = system_prompt.replace("{bot_goal}", safe_bot_goal)
        system_prompt = system_prompt.replace("{tone}", client_data.get("tone") or "friendly")
        system_prompt = system_prompt.replace("{current_datetime}", current_time)
        system_prompt = system_prompt.replace("{office_status}", "Open")
        system_prompt = system_prompt.replace("{lang}", call_lang)

        system_prompt += f"\n\n<USER_MEMORY>\n"
        system_prompt += f"CORE: {caller_memory['core']}\n"
        system_prompt += f"RECENT: {caller_memory['short']}\n"
        system_prompt += f"LONG TERM: {caller_memory['long']}\n"
        system_prompt += "</USER_MEMORY>\n"

        active_tools = [
            {
                "name": "save_lead",
                "description": "Salvează datele de contact și motivul apelului în CRM.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "client_name": {"type": "string"},
                        "client_phone": {"type": "string"},
                        "request_summary": {"type": "string"}
                    },
                    "required": ["client_name", "client_phone", "request_summary"],
                },
            },
            {
                "name": "send_sms",
                "description": "Trimite un SMS clientului.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "phone": {"type": "string"},
                        "message": {"type": "string"}
                    },
                    "required": ["phone", "message"],
                },
            },
            {
                "name": "end_call",
                "description": "Încheie apelul. OBLIGATORIU: Spune o scurtă frază de rămas-bun ÎNAINTE de a apela această funcție (ex: 'O zi bună, la revedere!'). Nu folosi această funcție fără a saluta la final.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        ]

        if client_data.get("google_calendar_id"):
            active_tools.append({
                "name": "Booking_tool",
                "description": "Gestionează calendarul. Folosește această funcție DOAR atunci când clientul cere explicit o programare.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["check", "book", "cancel"]},
                        "phone": {"type": "string"},
                        "start_time": {"type": "string"}
                    },
                    "required": ["action"],
                },
            })

        tools = [{"function_declarations": active_tools}]
        full_system_text = system_prompt + json.dumps(tools)
        system_instructions_length = len(full_system_text)

        fake_websocket = AsteriskWSAdapter(reader, writer)
        
        transport = FastAPIWebsocketTransport(
            websocket=fake_websocket,
            params=FastAPIWebsocketParams(
                audio_in_enabled=True,
                audio_in_filter=RNNoiseFilter(), 
                audio_out_enabled=True,
                audio_out_sample_rate=16000,
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
            )
        )

        llm = GeminiLiveLLMService(
            api_key=GEMINI_API_KEY,
            tools=tools,
            settings=GeminiLiveLLMService.Settings(
                model="gemini-3.1-flash-live-preview",
                voice=persona_data.get("voice_model", "Enceladus"),
                system_instruction=system_prompt, 
                vad=GeminiVADParams(
                    end_sensitivity=types.EndSensitivity.END_SENSITIVITY_LOW,
                    silence_duration_ms=2000,
                    disabled=False,
                ),
            ),
        )

        async def process_save_lead(params: FunctionCallParams):
            fake_websocket.is_muted = True 
            tg_chat = client_data.get("tg_chat_id_notify", "")
            comp_name = client_data.get("company_name", "Companie")
            async with httpx.AsyncClient() as http_client:
                try:
                    response = await http_client.post(f"{N8N_BASE_URL}/save_lead?client_id={client_id}&tg_chat_id={tg_chat}", json=params.arguments, timeout=5.0)
                    response.raise_for_status()
                    await params.result_callback(response.json())
                except asyncio.CancelledError:
                    try: await params.result_callback({"status": "cancelled", "message": "Client interrupted."})
                    except: pass
                    raise
                except Exception as e:
                    await send_tg_alert(tg_chat, f"⚠️ <b>Eroare API (save_lead)</b>\n🏢 Companie: {comp_name}\n🔧 Detalii eroare: <code>{str(e)}</code>")
                    await params.result_callback({"error": f"Eroare CRM: {str(e)}"})
                finally:
                    fake_websocket.is_muted = False 

        async def process_booking(params: FunctionCallParams):
            fake_websocket.is_muted = True
            cal_id = client_data.get("google_calendar_id", "")
            tg_chat = client_data.get("tg_chat_id_notify", "")
            comp_name = client_data.get("company_name", "Companie")
            async with httpx.AsyncClient() as http_client:
                try:
                    response = await http_client.post(f"{N8N_BASE_URL}/booking?client_id={client_id}&google_calendar_id={cal_id}", json=params.arguments, timeout=10.0)
                    response.raise_for_status()
                    await params.result_callback(response.json())
                except asyncio.CancelledError:
                    try: await params.result_callback({"status": "cancelled", "message": "Client interrupted."})
                    except: pass
                    raise
                except Exception as e:
                    await send_tg_alert(tg_chat, f"⚠️ <b>Eroare API (Booking_tool)</b>\n🏢 Companie: {comp_name}\n🔧 Detalii eroare: <code>{str(e)}</code>")
                    await params.result_callback({"status": "error", "message": str(e)})
                finally:
                    fake_websocket.is_muted = False

        async def process_sms(params: FunctionCallParams):
            fake_websocket.is_muted = True
            tg_chat = client_data.get("tg_chat_id_notify", "")
            comp_name = client_data.get("company_name", "Companie")
            async with httpx.AsyncClient() as http_client:
                try:
                    response = await http_client.post(f"{N8N_BASE_URL}/send_sms?client_id={client_id}", json=params.arguments, timeout=5.0)
                    response.raise_for_status()
                    await params.result_callback({"status": "success", "message": "SMS trimis"})
                except asyncio.CancelledError:
                    try: await params.result_callback({"status": "cancelled", "message": "Client interrupted."})
                    except: pass
                    raise
                except Exception as e:
                    await send_tg_alert(tg_chat, f"⚠️ <b>Eroare API (send_sms)</b>\n🏢 Companie: {comp_name}\n🔧 Detalii eroare: <code>{str(e)}</code>")
                    await params.result_callback({"status": "error", "message": str(e)})
                finally:
                    fake_websocket.is_muted = False

        async def process_end_call(params: FunctionCallParams):
            await params.result_callback({"status": "success", "message": "Call ended"})
            async def delayed_end():
                await asyncio.sleep(3.5)
                if task: await task.queue_frames([CancelFrame()])
            asyncio.create_task(delayed_end())

        llm.register_function("save_lead", process_save_lead)
        llm.register_function("send_sms", process_sms)
        llm.register_function("end_call", process_end_call)
        if client_data.get("google_calendar_id"):
            llm.register_function("Booking_tool", process_booking)

        recovery_processor = InterruptionRecoveryProcessor(context)

        pipeline = Pipeline([
            transport.input(),
            context_aggregator.user(),
            llm,
            recovery_processor,
            transport.output(),
            context_aggregator.assistant(),
        ])

        task = PipelineTask(pipeline, params=PipelineParams(allow_interruptions=True, idle_timeout=20.0))
        recovery_processor.task = task
        runner = PipelineRunner()

        if is_outbound:
            greeting_prompt = f"SYSTEM EVENT: Клиент ({client_name}) ответил на исходящий звонок. Цель звонка, которую ты должен выполнить: {purpose}. Язык клиента: {call_lang}. Начни разговор согласно твоему системному промпту и указанной цели."
        else:
            if time_context == "very_recent":
                greeting_prompt = f"SYSTEM EVENT: Клиент {client_name} перезвонил спустя пару минут. Не здоровайся заново. Язык клиента: {call_lang}. Скажи: 'Да-да, слушаю, связь прервалась' и продолжай суть."
            elif time_context == "same_day":
                greeting_prompt = f"SYSTEM EVENT: Клиент {client_name} снова на связи. Уточни, чем еще можешь помочь по контексту прошлых бесед. Язык клиента: {call_lang}. Опирайся на память (RECENT)."
            else:
                greeting_prompt = f"SYSTEM EVENT: Входящий звонок. Клиент: {client_name}. Язык клиента: {call_lang}. Начни диалог. Если есть память (RECENT), учитывай её и не задавай одни и те же вопросы."

        context.add_message({"role": "user", "content": greeting_prompt})
        await task.queue_frames([LLMRunFrame()])
        await runner.run(task)

    except Exception as e:
        print(f"❌ Ошибка соединения: {e}", flush=True)
    finally:
        print("📞 Звонок завершен. Закрываем сокет и собираем данные...", flush=True)
        try: writer.close()
        except Exception: pass

        call_direction = "outbound" if is_outbound else "inbound"
        wav_filename = f"{ASTERISK_RECORDING_PATH}/{session_uuid}.wav"
        
        has_context = "context" in locals() and context is not None
        if has_context and client_id:
            user_replies = [m["content"] for m in context.messages if m.get("role") == "user" and "SYSTEM EVENT:" not in m.get("content", "")]
            full_transcript = ""
            for msg in context.messages:
                if msg.get("role") in ["user", "assistant"] and msg.get("content"):
                    if "SYSTEM COMMAND:" not in msg["content"]:
                        role = "Client" if msg["role"] == "user" else "AI"
                        full_transcript += f"{role}: {msg['content']}\n"

            async def background_post_processing():
                await asyncio.sleep(0.5)
                try:
                    if len(user_replies) == 0:
                        call_status = "outbound_short_call" if is_outbound else "inbound_dropped"
                        await run_archivist_and_notify_n8n(client_id, target_phone, client_name, caller_memory, full_transcript, "", system_instructions_length, call_direction, call_status)
                    else:
                        audio_url = await upload_audio_to_supabase(client_id, wav_filename)
                        await run_archivist_and_notify_n8n(client_id, target_phone, client_name, caller_memory, full_transcript, audio_url or "", system_instructions_length, call_direction, "completed")
                except Exception as post_err: print(f"❌ ОШИБКА В ФОНОВОЙ ПОСТ-ОБРАБОТКЕ: {post_err}", flush=True)
                finally:
                    if wav_filename and os.path.exists(wav_filename):
                        try: os.remove(wav_filename)
                        except Exception: pass
                    gc.collect()

            asyncio.create_task(background_post_processing())
        else:
            gc.collect()

@app.on_event("startup")
async def startup_event():
    server = await asyncio.start_server(handle_asterisk_conn, "0.0.0.0", 8085)
    print("🚀 AudioSocket сервер запущен на порту 8085", flush=True)
    asyncio.create_task(server.serve_forever())
