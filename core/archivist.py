"""Shared Core Archivist: пост-обработка звонков, генерация CRM-саммари и интеграция с n8n."""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import hmac
import json
import os
from typing import Any

from google import genai
from google.genai import types

from core.config import (
    ARCHIVIST_MODELS,
    GEMINI_API_KEY,
    N8N_BASE_URL,
    N8N_WEBHOOK_SECRET,
    log,
    tz_for,
)
from core.db import ensure_end_client, http, sb_rpc


async def run_archivist_and_notify_n8n(
    client_id: str,
    phone: str,
    client_name: str,
    old_memory: dict,
    chat_history: str,
    audio_url: str,
    sys_length: int,
    direction: str,
    call_status: str,
    tz_name: str,
    usage_stats: dict | None = None,
    audio_path: str | None = None,
    project_id: str = "",
    web_id: str = "",
    platform: str = "gsm_voice",
    visitor_meta: dict | None = None,
    lead_saved: bool = True,
    tg_chat: str = "",
) -> None:
    """Генерация структурированного отчёта по звонку и отправка в n8n / Supabase."""
    if not chat_history.strip() or phone == "Necunoscut":
        return

    audio_part = None
    if audio_path:
        try:
            if await asyncio.to_thread(os.path.exists, audio_path):
                size = await asyncio.to_thread(os.path.getsize, audio_path)
                if 0 < size <= 18_000_000:
                    wav_bytes = await asyncio.to_thread(lambda: open(audio_path, "rb").read())
                    audio_part = types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav")
                else:
                    log.warning("[archivist] recording %d bytes — too big, using subtitles", size)
        except Exception as exc:
            log.warning("[archivist] cannot attach recording (%s), using subtitles", exc)

    today = dt.datetime.now(tz_for(tz_name)).strftime("%Y-%m-%d")
    clean_phone = "".join(filter(str.isdigit, str(phone)))
    razgovor_gol = call_status in ("inbound_dropped", "outbound_short_call")

    prompt = f"""Ты ИИ-архивариус. Обнови память клиента и составь резюме звонка для CRM.
Дата звонка: {today}. Направление: {direction}.

СТАРАЯ ПАМЯТЬ:
CORE IDENTITY: {old_memory.get('core') or 'Нет данных'}
SHORT TERM: {old_memory.get('short') or 'Нет данных'}
LONG TERM: {old_memory.get('long') or 'Нет данных'}

{"АУДИОЗАПИСЬ РАЗГОВОРА ПРИЛОЖЕНА. Реплики бота (AI) в субтитрах ниже точные. Реплики клиента (Client) в субтитрах часто искажены и могут быть на случайных языках — ИГНОРИРУЙ их текст и слушай, что клиент реально сказал в записи. В записи может быть ФОН: телевизор, радио, чужие разговоры рядом с клиентом. Признаки фона: речь не обращена к боту, не в тему разговора, на другом языке, чем говорит клиент, или бот на неё не отреагировал. Фон — НЕ реплики клиента: не включай его в транскрипт, в резюме и в память." if audio_part else "Аудиозаписи нет, работай по субтитрам."}

СУБТИТРЫ ЗВОНКА:
{chat_history}

ПРАВИЛА:
- Пиши только то, что реально прозвучало. Ничего не додумывай: если бот не спросил имя — не пиши, что спросил; если клиент не назвал задачу — так и напиши.
- summary, sentiment и next_step пиши на том языке, на котором шёл разговор.

ИНСТРУКЦИЯ (выведи СТРОГО JSON, без markdown):
1. core_identity: обнови, если клиент сообщил фундаментальный факт.
2. short_term_context: факты старше 3 дней перенеси в long_term. Новые пиши как "[{today}]: факт".
3. long_term_context: сжатая история прошлых обращений.
4. summary: суть текущего звонка для менеджера.
5. sentiment: настрой и возражения.
6. next_step: следующий шаг (перезвонить, отправить КП и т.д.).
7. language: язык, на котором РЕАЛЬНО говорил клиент (ro/ru/en). Если клиент почти ничего не сказал или язык по записи не ясен — пустая строка.
8. client_name: имя клиента, если он его назвал. Иначе пустая строка.
9. transcript: расшифровка разговора по записи, в формате "Client: ..." / "AI: ...", на языке оригинала каждой реплики. Только реплики бота и слова клиента, обращённые к боту; фон (телевизор, посторонние разговоры) пропускай. Если записи нет — верни субтитры, убрав из них строки Client, которые явно не в тему разговора.
10. callback_phone: номер телефона, который клиент САМ продиктовал в этом разговоре, чтобы с ним связались, — только цифры. Если не диктовал — пустая строка.

{{"core_identity":"...","short_term_context":"...","long_term_context":"...","summary":"...","sentiment":"...","next_step":"...","language":"...","client_name":"...","transcript":"...","callback_phone":"..."}}
"""

    data: dict[str, Any] = {}
    client = genai.Client(api_key=GEMINI_API_KEY)
    if razgovor_gol:
        data = {
            "core_identity": old_memory.get("core", ""),
            "short_term_context": old_memory.get("short", ""),
            "long_term_context": old_memory.get("long", ""),
            "summary": "Разговор не состоялся: собеседник не сказал ни слова.",
            "sentiment": "—",
            "next_step": "—",
            "language": "",
        }
    else:
        for attempt, model in enumerate(ARCHIVIST_MODELS):
            try:
                response = await client.aio.models.generate_content(
                    model=model,
                    contents=[audio_part, prompt] if audio_part else prompt,
                    config=types.GenerateContentConfig(response_mime_type="application/json"),
                )
                data = json.loads(response.text.strip())
                break
            except Exception as exc:
                log.warning("archivist model %s failed: %s", model, exc)
                if attempt < len(ARCHIVIST_MODELS) - 1:
                    await asyncio.sleep(2)
        else:
            data = {
                "core_identity": old_memory.get("core", ""),
                "short_term_context": old_memory.get("short", ""),
                "long_term_context": old_memory.get("long", ""),
                "summary": "Ошибка генерации саммари: все модели недоступны.",
                "sentiment": "Неизвестно",
                "next_step": "Связаться вручную",
                "language": "",
            }

    try:
        if razgovor_gol:
            log.info("[archivist] пустой звонок — память не трогаем")
        elif web_id:
            await sb_rpc(
                "person_memory_upsert_web",
                {
                    "p_client_id": client_id,
                    "p_web_id": web_id,
                    "p_phone": phone or "",
                    "p_name": str(data.get("client_name") or client_name or "").strip(),
                    "p_core": data.get("core_identity", ""),
                    "p_short": data.get("short_term_context", ""),
                    "p_long": data.get("long_term_context", ""),
                },
                timeout=5.0,
            )
        else:
            await sb_rpc(
                "person_memory_upsert",
                {
                    "p_client_id": client_id,
                    "p_phone": phone,
                    "p_core": data.get("core_identity", ""),
                    "p_short": data.get("short_term_context", ""),
                    "p_long": data.get("long_term_context", ""),
                    "p_channel": "voice",
                },
                timeout=5.0,
            )
        if not razgovor_gol:
            log.info("[archivist] memory saved for %s", clean_phone or f"web {web_id[:12]}")
    except Exception as exc:
        log.error("[archivist] memory save failed: %s", exc)

    # Страховка заявки
    telefon_zayavki = "".join(filter(str.isdigit, str(data.get("callback_phone") or "")))
    if web_id and not lead_saved and len(telefon_zayavki) >= 8 and N8N_BASE_URL:
        try:
            resp = await http().post(
                f"{N8N_BASE_URL}/save_lead",
                params={"client_id": client_id, "tg_chat_id": tg_chat or ""},
                json={
                    "client_name": str(data.get("client_name") or client_name or "").strip(),
                    "client_phone": telefon_zayavki,
                    "request_summary": str(data.get("summary") or "").strip(),
                },
                timeout=5.0,
            )
            resp.raise_for_status()
            log.info("[archivist] заявку сохранили после звонка — бот её не сохранил")
        except Exception as exc:
            log.error("[archivist] страховочная заявка не ушла: %s", exc)

    learned_name = str(data.get("client_name") or "").strip()
    if learned_name and not web_id:
        await ensure_end_client(client_id, phone, learned_name, "")

    if not N8N_BASE_URL:
        return

    payload = {
        "client_id": client_id,
        "project_id": project_id,
        "web_id": web_id,
        "end_client_name": client_name,
        "end_client_phone": phone,
        "status": call_status,
        "transcript": (data.get("transcript") or "").strip() or chat_history,
        "summary": json.dumps(
            {
                "client_name": client_name,
                "summary": data.get("summary", ""),
                "sentiment": data.get("sentiment", ""),
                "next_step": data.get("next_step", ""),
                "language": data.get("language", ""),
            },
            ensure_ascii=False,
        ),
        "audio_url": audio_url,
        "system_instructions_length": sys_length,
        "platform": platform,
        "direction": direction,
        **(visitor_meta or {}),
        **(usage_stats or {}),
    }
    try:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if N8N_WEBHOOK_SECRET:
            sig = hmac.new(N8N_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
            headers["X-Signature"] = f"sha256={sig}"
        await http().post(f"{N8N_BASE_URL}/post-call-summary", content=body, headers=headers, timeout=10.0)
        log.info("[archivist] report sent to n8n")
    except Exception as exc:
        log.error("[archivist] n8n post failed: %s", exc)
