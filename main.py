import os
import httpx
from fastapi import FastAPI, WebSocket, Query
from fastapi.middleware.cors import CORSMiddleware
import datetime
import pytz
import asyncio
import wave
import uuid
import numpy as np
from google import genai
from supabase import create_client, Client

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.frames.frames import Frame, InputAudioRawFrame, OutputAudioRawFrame, LLMRunFrame, EndFrame
from pipecat.serializers.base_serializer import FrameSerializer
from pipecat.services.llm_service import FunctionCallParams
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from pipecat.services.google.gemini_live.llm import GeminiLiveLLMService
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)

from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair

# Ключи доступа (должны быть в переменных окружения Coolify)
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN") # Токен бота для уведомлений об ошибках

class RawPCMFrameSerializer(FrameSerializer):
    async def serialize(self, frame: Frame) -> bytes | str | None:
        if isinstance(frame, OutputAudioRawFrame):
            return frame.audio
        return None
    
    async def deserialize(self, data: bytes | str) -> Frame | None:
        if isinstance(data, bytes):
            return InputAudioRawFrame(audio=data, sample_rate=16000, num_channels=1)
        return None

# ==========================================
# УМНЫЙ МИКШЕР "НА ЛЕТУ" (С РЕСЕМПЛИНГОМ)
# ==========================================
class AudioMixer:
    def __init__(self, output_path: str):
        self.output_path = output_path
        self._wav_file = None
        self.target_rate = 24000  # Gemini отдает 24 кГц
        self.ai_buffer = np.array([], dtype=np.int16)

    def add_ai_audio(self, frame: OutputAudioRawFrame):
        chunk = np.frombuffer(frame.audio, dtype=np.int16)
        self.ai_buffer = np.concatenate((self.ai_buffer, chunk))

    def add_user_audio(self, frame: InputAudioRawFrame):
        self._init_wav()
        
        # 1. Читаем аудио пользователя (16000 Гц)
        user_chunk = np.frombuffer(frame.audio, dtype=np.int16)
        
        # 2. Быстрый ресемплинг 16k -> 24k через линейную интерполяцию
        num_samples = int(len(user_chunk) * (self.target_rate / frame.sample_rate))
        x = np.arange(len(user_chunk))
        x_new = np.linspace(0, len(user_chunk) - 1, num_samples)
        user_resampled = np.interp(x_new, x, user_chunk).astype(np.int16)
        
        # 3. Достаем синхронный кусок аудио ИИ из буфера
        ai_samples = np.zeros(num_samples, dtype=np.int16)
        if len(self.ai_buffer) > 0:
            take_len = min(num_samples, len(self.ai_buffer))
            ai_samples[:take_len] = self.ai_buffer[:take_len]
            self.ai_buffer = self.ai_buffer[take_len:] 
            
        # 4. Микшируем (складываем) сигналы с защитой от цифрового перегруза
        mixed_chunk = np.clip(
            user_resampled.astype(np.int32) + ai_samples.astype(np.int32), 
            -32768, 32767
        ).astype(np.int16)
        
        # 5. Пишем готовый стерео-микс в файл
        self._wav_file.writeframes(mixed_chunk.tobytes())

    def _init_wav(self):
        if self._wav_file is None:
            self._wav_file = wave.open(self.output_path, 'wb')
            self._wav_file.setnchannels(1)  
            self._wav_file.setsampwidth(2)
            self._wav_file.setframerate(self.target_rate)

    def close(self):
        if self._wav_file and len(self.ai_buffer) > 0:
            self._wav_file.writeframes(self.ai_buffer.tobytes())
            self.ai_buffer = np.array([], dtype=np.int16)
        if self._wav_file:
            self._wav_file.close()
            self._wav_file = None

class UserAudioCatcher(FrameProcessor):
    def __init__(self, mixer: AudioMixer):
        super().__init__()
        self.mixer = mixer

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, InputAudioRawFrame):
            self.mixer.add_user_audio(frame)
        await self.push_frame(frame, direction)

class AIAudioCatcher(FrameProcessor):
    def __init__(self, mixer: AudioMixer):
        super().__init__()
        self.mixer = mixer

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, OutputAudioRawFrame):
            self.mixer.add_ai_audio(frame)
        await self.push_frame(frame, direction)

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# --- 1. ФУНКЦИИ БАЗЫ ДАННЫХ И УВЕДОМЛЕНИЙ ---
async def get_client_data(client_id: str):
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("❌ ОШИБКА: В переменных окружения отсутствуют ключи SUPABASE_URL sau SUPABASE_KEY.", flush=True)
        return None

    clean_url = SUPABASE_URL.replace("/rest/v1", "").rstrip("/")
    url = f"{clean_url}/rest/v1/saas_clients?id=eq.{client_id}&select=company_name,business_context,tone,bot_goal,subscription_status_assistent,system_message,tg_chat_id_notify,google_calendar_id"
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}

    async with httpx.AsyncClient() as client:
        try:
            print(f"🔄 Отправляем запрос к Supabase pentru ID: {client_id}...", flush=True)
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            
            if len(data) > 0:
                print(f"✅ Supabase a returnat datele companiei: {data[0].get('company_name')}", flush=True)
                return data[0]
                
            print(f"⚠️ ОШИБКА: Supabase a răspuns 200 OK, dar a returnat o listă goală. ID-ul {client_id} nu există.", flush=True)
            return None
        except Exception as e:
            print(f"❌ ОШИБКА СВЯЗИ С SUPABASE: {e}", flush=True)
            return None

async def send_tg_alert(chat_id: str, message: str):
    """Отправляет уведомление об ошибке в ТГ клиенту (или администратору)"""
    if not TG_BOT_TOKEN or not chat_id:
        print("⚠️ Notificare TG anulată: lipsește token-ul sau chat_id-ul.", flush=True)
        return
    
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
    
    async with httpx.AsyncClient() as client:
        try:
            await client.post(url, json=payload, timeout=5.0)
            print(f"📲 Alerta TG a fost trimisă cu succes la {chat_id}.", flush=True)
        except Exception as e:
            print(f"❌ EROARE la trimiterea alertei TG: {e}", flush=True)

async def generate_summary(transcript: str) -> str:
    """Генерирует саммари с анализом в формате JSON."""
    if not transcript or len(transcript.strip()) < 10:
        return "{}"
    
    try:
        client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        
        prompt = (
            "Analizează transcriptul. Returnează un obiect JSON valid "
            "(fără formatare markdown, doar JSON pur) cu următoarele chei:\n"
            "\"client_name\": Numele clientului (sau null),\n"
            "\"client_phone\": Numărul de telefon (sau null),\n"
            "\"summary\": Esența apelului,\n"
            "\"sentiment\": Starea emoțională și obiecțiile,\n"
            "\"language\": Limba principală a clientului din dialog (ex: 'Română', 'Русский', 'English'),\n"
            "\"next_step\": Ce trebuie de făcut.\n\n"
            f"Transcript:\n{transcript}"
        )
        
        response = await client.aio.models.generate_content(
            model="gemini-2.5-pro",
            contents=prompt,
            config=genai.types.GenerateContentConfig(
                response_mime_type="application/json",
            )
        )
        return response.text
    
    except Exception as e:
        print(f"❌ Ошибка генерации саммари: {e}", flush=True)
        return "{}"

async def upload_audio_to_supabase(client_id: str, filepath: str) -> str | None:
    print(f"🎧 Начинаем сохранение аудио. Проверяем файл: {filepath}", flush=True)
    
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("❌ ОШИБКА АУДИО: Не найден SUPABASE_URL или SUPABASE_KEY", flush=True)
        return None
        
    if not os.path.exists(filepath):
        print(f"❌ ОШИБКА АУДИО: Файл {filepath} не создался на диске!", flush=True)
        return None
        
    try:
        clean_supa_url = SUPABASE_URL.replace("/rest/v1", "").rstrip("/")
        supabase: Client = create_client(clean_supa_url, SUPABASE_KEY)
        bucket_name = "call-recordings"
        file_name = os.path.basename(filepath)
        storage_path = f"records/{client_id}/{file_name}"
        
        def _upload():
            with open(filepath, 'rb') as f:
                supabase.storage.from_(bucket_name).upload(
                    path=storage_path,
                    file=f,
                    file_options={"content-type": "audio/wav"}
                )
            return supabase.storage.from_(bucket_name).get_public_url(storage_path)
            
        audio_url = await asyncio.to_thread(_upload)
        print(f"✅ Аудио успешно загружено в Supabase: {audio_url}", flush=True)
        return audio_url
    except Exception as e:
        print(f"❌ Ошибка при отправке файла в Supabase Storage: {e}", flush=True)
        return None

async def send_final_report_to_n8n(client_id: str, transcript: str, summary: str, audio_url: str):
    """Отправляет итоговый отчет в n8n webhook."""
    payload = {
        "client_id": client_id,
        "transcript": transcript,
        "summary": summary,
        "audio_url": audio_url
    }
    async with httpx.AsyncClient() as http_client:
        try:
            await http_client.post(
                "https://n8n.labupgrade.in/webhook/post-call-summary", 
                json=payload,
                timeout=10.0
            )
            print("✅ Отчет успешно отправлен в n8n", flush=True)
        except Exception as e:
            print(f"❌ Ошибка отправки финального отчета в n8n: {e}", flush=True)

# --- 2. ГЛАВНЫЙ WEBSOCKET ---
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, client_id: str = Query(None)):
    
    print(f"--- ВХОДЯЩИЙ ЗВОНОК | client_id: {client_id} ---", flush=True)

    if not client_id:
        print("❌ ОТКАЗ (403): client_id lipsește din URL.", flush=True)
        await websocket.close(code=1008, reason="Missing client_id")
        return

    client_data = await get_client_data(client_id)
    if not client_data:
        print("❌ ОТКАЗ (403): get_client_data a returnat None. Închidem conexiunea.", flush=True)
        await websocket.close(code=1008, reason="Client not found")
        return

    sub_status = str(client_data.get("subscription_status_assistent", "")).strip().lower()
    print(f"🔍 Statutul abonamentului: '{sub_status}'", flush=True)

    if sub_status == "false":
        print("❌ ОТКАЗ (403): Abonamentul este inactiv (false).", flush=True)
        await websocket.close(code=1008, reason="Subscription expired")
        return

    print("🟢 TOATE VERIFICĂRILE AU TRECUT! Ridicăm apelul.", flush=True)
    await websocket.accept()

    # --- 3. ПОДГОТОВКА СИСТЕМНОГО ПРОМПТА ---
    raw_prompt = client_data.get("system_message", "Ești un asistent virtual.")
    
    tz = pytz.timezone('Europe/Chisinau')
    current_time = datetime.datetime.now(tz).strftime('%A, %d %B %Y, %H:%M')
    office_status = "Open" 

    system_prompt = raw_prompt.replace("{company_name}", client_data.get("company_name") or "Compania noastră")
    system_prompt = system_prompt.replace("{business_context}", client_data.get("business_context") or "")
    system_prompt = system_prompt.replace("{bot_goal}", client_data.get("bot_goal") or "")
    system_prompt = system_prompt.replace("{tone}", client_data.get("tone") or "friendly")
    system_prompt = system_prompt.replace("{current_datetime}", current_time or "")
    system_prompt = system_prompt.replace("{office_status}", office_status or "")


    # 🟢 ДОБАВЛЯЕМ ЖЕСТКИЕ ПРАВИЛА ПОВЕДЕНИЯ К ПРОМПТУ
     
    behavior_rules = """
    \n\nREGULI STRICTE DE CONVERSAȚIE (URMEAZĂ-LE CU STRICTEȚE):
    1. LIMBA: Răspunde MEREU în limba clientului. Dacă primul cuvânt este scurt, distorsionat sau nu ești sigur de limbă (ex: se aude doar zgomot sau un scurt "alo"/"bună"), folosește IMPLICIT limba Română.
    2. PAUZELE: Dacă pui o întrebare de confirmare (ex: "Corect?", "Sunteți de acord?", "Verific?"), OPREȘTE-TE imediat din vorbit și așteaptă răspunsul clientului. NU continua fraza și NU apela nicio funcție până nu auzi răspunsul.
    3. FĂRĂ HALUCINAȚII LA ID-URI: Pentru acțiunile 'reschedule' sau 'cancel', folosește STRICT event_id real returnat de webhook-ul 'lookup'. ESTE STRICT INTERZIS să inventezi ID-uri de test precum "event_123456". Dacă nu ai primit încă ID-ul real de la sistem, AȘTEAPTĂ! Nu apela 'reschedule' în orb.
    """
    system_prompt += behavior_rules


    # --- 4. ОПРЕДЕЛЕНИЕ ИНСТРУМЕНТОВ (TOOLS) ---
    tools = [
        {
            "function_declarations": [
                                {
                    "name": "save_lead",
                    "description": "Salvează datele de contact și motivul apelului în CRM.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "client_name": {"type": "string"},
                            "client_phone": {"type": "string"},
                            "request_summary": {"type": "string"},
                            "event_id": {"type": "string", "description": "ID-ul evenimentului din calendar (dacă a fost creat)"}
                        },
                        "required": ["client_name", "client_phone", "request_summary"]
                    }
                },

                 {
        "name": "Booking_tool",
        "description": "Gestionează calendarul: verifică, rezervă, anulează sau reprogramează.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["check", "book", "lookup", "reschedule", "cancel"], "description": "Tipul acțiunii"},
                "phone": {"type": "string", "description": "Telefonul clientului"},
                "client_name": {"type": "string", "description": "Numele clientului (obligatoriu pentru 'book')"},
                "request_summary": {"type": "string", "description": "Motivul programării sau scurtă descriere (ex: 'Consultație automatizare')"},
                "start_time": {"type": "string", "description": "ISO 8601 start"},
                "end_time": {"type": "string", "description": "ISO 8601 end"},
                "event_id": {"type": "string", "description": "ID-ul REAL al evenimentului obținut exclusiv din acțiunea 'lookup'."}
            },
            "required": ["action"]
        }
    }
            ]
        }
    ]

    # --- 5. НАСТРОЙКА СЕРВИСОВ PIPECAT ---
    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True, audio_out_enabled=True, add_wav_header=False, serializer=RawPCMFrameSerializer() 
        )
    )

    context = LLMContext(messages=[{"role": "system", "content": system_prompt}])
    context_aggregator = LLMContextAggregatorPair(context=context)

    llm = GeminiLiveLLMService(
        api_key=os.getenv("GEMINI_API_KEY"),
        tools=tools,
        settings=GeminiLiveLLMService.Settings(
            model="gemini-3.1-flash-live-preview",
            voice="Enceladus",
            system_instruction=system_prompt
        )
    )

    # --- 6. РЕАЛИЗАЦИЯ ЛОГИКИ ИНСТРУМЕНТОВ ---
    async def process_save_lead(params: FunctionCallParams):
        tg_chat_id = client_data.get("tg_chat_id_notify", "")
        company_name = client_data.get("company_name", "Necunoscut")
        async with httpx.AsyncClient() as http_client:
            try:
                response = await http_client.post(
                    f"https://n8n.labupgrade.in/webhook/save_lead?client_id={client_id}&tg_chat_id={tg_chat_id}",
                    json=params.arguments,
                    timeout=5.0
                )
                response.raise_for_status()
                await params.result_callback(response.json())
            except asyncio.CancelledError:
                print("⚠️ Вызов save_lead прерван (клиент перебил бота). Защита активирована.", flush=True)
                try:
                    await params.result_callback({"status": "cancelled", "message": "Client interrupted. Await client input."})
                except Exception: pass
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
                    f"https://n8n.labupgrade.in/webhook/booking?client_id={client_id}&google_calendar_id={cal_id}",
                    json=params.arguments,
                    timeout=10.0 
                )
                response.raise_for_status()
                await params.result_callback(response.json())
            except asyncio.CancelledError:
                print("⚠️ Вызов Booking_tool прерван (клиент перебил бота). Защита активирована.", flush=True)
                try:
                    await params.result_callback({"status": "cancelled", "message": "Client interrupted the tool call. Stop and listen."})
                except Exception: pass
                raise
            except Exception as e:
                error_msg = f"⚠️ <b>Eroare API (Booking_tool)</b>\n🏢 Companie: {company_name}\n🔧 Detalii eroare: <code>{str(e)}</code>\nN8N nu a procesat rezervarea!"
                await send_tg_alert(tg_chat_id, error_msg)
                await params.result_callback({"status": "error", "message": f"Sistemul de rezervări nu răspunde: {str(e)}"})

    # Регистрируем инструменты
    llm.register_function("save_lead", process_save_lead)
    llm.register_function("Booking_tool", process_booking_tool)

    # 🟢 Инициализируем наш умный микшер
    wav_filename = f"record_{client_id}_{uuid.uuid4().hex[:8]}.wav"
    audio_mixer = AudioMixer(wav_filename)
    user_catcher = UserAudioCatcher(audio_mixer)
    ai_catcher = AIAudioCatcher(audio_mixer)

   
            # --- 7. ЗАПУСК ПАЙПЛАЙНА ---
    pipeline = Pipeline([
        transport.input(), 
        user_catcher,         # <--- Слушает 16кГц микрофон
        context_aggregator.user(), 
        llm, 
        ai_catcher,           # <--- Слушает 24кГц ответы Gemini
        transport.output(), 
        context_aggregator.assistant()
    ])
    task = PipelineTask(pipeline, params=PipelineParams(allow_interruptions=True))

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        context.add_message({
            "role": "system", 
            "content": "Clientul s-a conectat. Salută-l imediat și prezintă-te ca Grigorii. REGULĂ STRICTĂ: Vorbește în limba clientului. Dacă primul lui cuvânt e prea scurt sau neclar, începe dialogul în Română."
        })
        await task.queue_frames([LLMRunFrame()])

    # 🟢 ФУНКЦИЯ ТАЙМЕРА ДЛЯ ТЕСТОВОГО ЗВОНКА
    async def enforce_call_limit(current_task: PipelineTask, current_context: LLMContext):
        try:
            await asyncio.sleep(110) # Ждем 1 минуту 50 секунд
            
            # Впрыскиваем скрытую команду ассистенту, чтобы он попрощался
            current_context.add_message({
                "role": "user", 
                "content": "SYSTEM COMMAND: Apelul de test se încheie în 10 secunde. Te rog să-ți iei la revedere scurt și politicos chiar acum, fără să menționezi că e o comandă de sistem."
            })
            await current_task.queue_frames([LLMRunFrame()])
            
            await asyncio.sleep(10) # Ждем еще 10 секунд
            
            # Жестко завершаем звонок (это корректно закроет сокет и запустит пост-обработку)
            await current_task.queue_frames([EndFrame()])
        except asyncio.CancelledError:
            pass # Если клиент повесил трубку сам, таймер просто тихо отменится

    # Возвращаем правильный отступ!
    runner = PipelineRunner()
    timer_task = None 
    
    try:
        # Принудительно проталкиваем фрейм, чтобы запустить разговор
        await task.queue_frames([LLMRunFrame()])
        
        # 🟢 ЕСЛИ ЭТО ТЕСТОВЫЙ КЛИЕНТ — ЗАПУСКАЕМ ТАЙМЕР В ФОНЕ
        test_uuid = "07e1d002-20a3-47f8-b8cb-8736a60dc1f4"
        if client_id == test_uuid:
            timer_task = asyncio.create_task(enforce_call_limit(task, context))
        
        await runner.run(task)
    except Exception as e:
        print(f"❌ Ошибка пайплайна: {e}", flush=True)
    finally:
        # 🟢 ЕСЛИ ТАЙМЕР БЫЛ ЗАПУЩЕН, НО ЗВОНОК ЗАВЕРШИЛСЯ РАНЬШЕ — ОТМЕНЯЕМ ЕГО
        if timer_task and not timer_task.done():
            timer_task.cancel()

        # === ПОСТ-ОБРАБОТКА (START) ===
        print("📞 Звонок завершен. Начинаем фоновые задачи...", flush=True)

        # 🟢 Закрываем микшер и финализируем файл на диске
        audio_mixer.close()

        messages = context.messages
        full_transcript = ""
        for msg in messages:
            if msg.get("role") in ["user", "assistant"] and msg.get("content"):
                # Игнорируем наши скрытые системные команды в транскрипте, чтобы они не попали в n8n
                if "SYSTEM COMMAND:" not in msg["content"]:
                    role = "Client" if msg["role"] == "user" else "AI"
                    full_transcript += f"{role}: {msg['content']}\n"

        summary = await generate_summary(full_transcript)
        audio_url = await upload_audio_to_supabase(client_id, wav_filename)
        await send_final_report_to_n8n(client_id, full_transcript, summary, audio_url)

        if os.path.exists(wav_filename):
            os.remove(wav_filename)
            
        print("✅ Пост-обработка завершена успешно.", flush=True)
        # === ПОСТ-ОБРАБОТКА (END) ===
