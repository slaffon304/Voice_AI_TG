import os
import httpx
from fastapi import FastAPI, Query, Response
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

from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair

# Ключи доступа
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")

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
# УМНЫЙ МИКШЕР "НА ЛЕТУ"
# ==========================================
class AudioMixer:
    def __init__(self, output_path: str):
        self.output_path = output_path
        self._wav_file = None
        self.target_rate = 24000
        self.ai_buffer = np.array([], dtype=np.int16)

    def add_ai_audio(self, frame: OutputAudioRawFrame):
        chunk = np.frombuffer(frame.audio, dtype=np.int16)
        self.ai_buffer = np.concatenate((self.ai_buffer, chunk))

    def add_user_audio(self, frame: InputAudioRawFrame):
        self._init_wav()
        user_chunk = np.frombuffer(frame.audio, dtype=np.int16)
        num_samples = int(len(user_chunk) * (self.target_rate / frame.sample_rate))
        x = np.arange(len(user_chunk))
        x_new = np.linspace(0, len(user_chunk) - 1, num_samples)
        user_resampled = np.interp(x_new, x, user_chunk).astype(np.int16)
        
        ai_samples = np.zeros(num_samples, dtype=np.int16)
        if len(self.ai_buffer) > 0:
            take_len = min(num_samples, len(self.ai_buffer))
            ai_samples[:take_len] = self.ai_buffer[:take_len]
            self.ai_buffer = self.ai_buffer[take_len:] 
            
        mixed_chunk = np.clip(
            user_resampled.astype(np.int32) + ai_samples.astype(np.int32), 
            -32768, 32767
        ).astype(np.int16)
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

class AudioSocketWriter(FrameProcessor):
    def __init__(self, writer):
        super().__init__()
        self._writer = writer
    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, OutputAudioRawFrame):
            try:
                header = b'\x01' + len(frame.audio).to_bytes(2, byteorder='big')
                self._writer.write(header + frame.audio)
                await self._writer.drain()
            except Exception: pass
        return frame

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# --- 1. ФУНКЦИИ БАЗЫ ДАННЫХ ---
async def get_client_data(client_id: str):
    if not SUPABASE_URL or not SUPABASE_KEY: return None
    clean_url = SUPABASE_URL.replace("/rest/v1", "").rstrip("/")
    url = f"{clean_url}/rest/v1/saas_clients?id=eq.{client_id}&select=*"
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers)
            data = response.json()
            return data[0] if data else None
        except Exception: return None

async def send_tg_alert(chat_id: str, message: str):
    if not TG_BOT_TOKEN or not chat_id: return
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
    async with httpx.AsyncClient() as client:
        try: await client.post(url, json=payload, timeout=5.0)
        except Exception: pass

async def generate_summary(transcript: str) -> str:
    if not transcript or len(transcript.strip()) < 10: return "{}"
    try:
        client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        prompt = f"Analizează transcriptul și returnează un JSON pur:\n{transcript}"
        response = await client.aio.models.generate_content(model="gemini-2.5-pro", contents=prompt, config=genai.types.GenerateContentConfig(response_mime_type="application/json"))
        return response.text
    except Exception: return "{}"

async def upload_audio_to_supabase(client_id: str, filepath: str) -> str | None:
    if not SUPABASE_URL or not os.path.exists(filepath): return None
    try:
        clean_supa_url = SUPABASE_URL.replace("/rest/v1", "").rstrip("/")
        supabase: Client = create_client(clean_supa_url, SUPABASE_KEY)
        file_name = os.path.basename(filepath)
        storage_path = f"records/{client_id}/{file_name}"
        def _upload():
            with open(filepath, 'rb') as f:
                supabase.storage.from_("call-recordings").upload(path=storage_path, file=f, file_options={"content-type": "audio/wav"})
            return supabase.storage.from_("call-recordings").get_public_url(storage_path)
        return await asyncio.to_thread(_upload)
    except Exception: return None

async def send_final_report_to_n8n(client_id: str, transcript: str, summary: str, audio_url: str):
    payload = {"client_id": client_id, "transcript": transcript, "summary": summary, "audio_url": audio_url}
    async with httpx.AsyncClient() as http_client:
        try: await http_client.post("https://n8n.labupgrade.in/webhook/post-call-summary", json=payload, timeout=10.0)
        except Exception: pass

# --- 2. ГЛАВНЫЙ ОБРАБОТЧИК ---
async def handle_asterisk_conn(reader, writer):
    print("--- ВХОДЯЩИЙ ЗВОНОК ---", flush=True)
    audio_mixer = None
    wav_filename = None
    timer_task = None
    try:
        header = await reader.readexactly(3)
        id_len = int.from_bytes(header[1:], byteorder='big')
        uuid_bytes = await reader.readexactly(id_len)
        client_id = str(uuid.UUID(bytes=uuid_bytes)) if id_len == 16 else uuid_bytes.decode('utf-8', errors='ignore').strip()
        
        client_data = await get_client_data(client_id)
        if not client_data or str(client_data.get("subscription_status_assistent")).lower() == "false":
            writer.close(); return

        raw_prompt = client_data.get("system_message", "Ești un asistent virtual.")
        tz = pytz.timezone('Europe/Chisinau')
        current_time = datetime.datetime.now(tz).strftime('%A, %d %B %Y, %H:%M')
        system_prompt = raw_prompt.replace("{company_name}", client_data.get("company_name") or "Compania noastră").replace("{current_datetime}", current_time)
        system_prompt += "\n\n1. Răspunde MEREU în limba clientului (Română implicit). 2. PAUZELE: Așteaptă răspunsul clientului."

        tools = [{"function_declarations": [{"name": "save_lead", "parameters": {"type": "object", "properties": {"client_name": {"type": "string"}}, "required": ["client_name"]}}]}]
        
        context = LLMContext(messages=[{"role": "system", "content": system_prompt}])
        context_aggregator = LLMContextAggregatorPair(context=context)
        llm = GeminiLiveLLMService(api_key=os.getenv("GEMINI_API_KEY"), model_id="gemini-2.0-flash-exp", system_instruction=system_prompt)

        async def process_save_lead(params: FunctionCallParams):
            async with httpx.AsyncClient() as http_client:
                await http_client.post(f"https://n8n.labupgrade.in/webhook/save_lead?client_id={client_id}", json=params.arguments)
                await params.result_callback({"status": "success"})

        llm.register_function("save_lead", process_save_lead)

        wav_filename = f"record_{client_id}_{uuid.uuid4().hex[:8]}.wav"
        audio_mixer = AudioMixer(wav_filename)
        user_catcher = UserAudioCatcher(audio_mixer)
        ai_catcher = AIAudioCatcher(audio_mixer)
        socket_writer = AudioSocketWriter(writer)

        pipeline = Pipeline([user_catcher, context_aggregator.user(), llm, ai_catcher, socket_writer, context_aggregator.assistant()])
        task = PipelineTask(pipeline, params=PipelineParams(allow_interruptions=True))

        async def read_audio():
            while True:
                data = await reader.read(640)
                if not data: break
                if len(data) > 3:
                    await task.queue_frames([InputAudioRawFrame(data[3:] if data[0] == 1 else data, 16000, 1)])
            await task.queue_frames([EndFrame()])

        asyncio.create_task(read_audio())
        runner = PipelineRunner()
        await runner.run(task)

    except Exception as e: print(f"❌ Ошибка: {e}", flush=True)
    finally:
        writer.close(); await writer.wait_closed()
        if audio_mixer:
            audio_mixer.close()
            full_transcript = "".join([f"{m['role']}: {m['content']}\n" for m in context.messages if "SYSTEM" not in str(m.get("content"))])
            summary = await generate_summary(full_transcript)
            audio_url = await upload_audio_to_supabase(client_id, wav_filename)
            await send_final_report_to_n8n(client_id, full_transcript, summary, audio_url)
            if os.path.exists(wav_filename): os.remove(wav_filename)

@app.on_event("startup")
async def startup_event():
    server = await asyncio.start_server(handle_asterisk_conn, '0.0.0.0', 8085)
    asyncio.create_task(server.serve_forever())

@app.get("/get_uuid")
async def get_client_uuid(sip_login: str):
    clean_url = SUPABASE_URL.replace("/rest/v1", "").rstrip("/")
    url = f"{clean_url}/rest/v1/saas_clients?sip_login=eq.{sip_login}&select=id"
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, headers=headers)
            data = resp.json()
            return Response(content=str(data[0].get("id")) if data else "not_found", media_type="text/plain")
        except Exception: return Response(content="error", media_type="text/plain")

@app.get("/")
async def health(): return {"status": "online"}
