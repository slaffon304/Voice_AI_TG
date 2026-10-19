"""Shared Core Database: доступ к Supabase, Redis и персистентному хранилищу."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import uuid
from typing import Any, Optional
from urllib.parse import quote

import httpx
import redis.asyncio as redis
from supabase import Client, create_client

from core.config import (
    PERSONA_CACHE_TTL,
    REDIS_URL,
    SUPABASE_KEY,
    SUPABASE_URL,
    log,
)
from core.persona import TRAITS, Persona

_http: Optional[httpx.AsyncClient] = None
redis_client = redis.from_url(REDIS_URL, decode_responses=True) if REDIS_URL else None


def http() -> httpx.AsyncClient:
    """Общий пул соединений HTTP."""
    global _http
    if _http is None:
        _http = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=3.0))
    return _http


def sb_headers() -> dict[str, str]:
    return {"apikey": SUPABASE_KEY or "", "Authorization": f"Bearer {SUPABASE_KEY or ''}"}


async def sb_select(table: str, params: dict[str, str], timeout: float = 5.0) -> list[dict]:
    """Чтение из PostgREST. Все значения экранируются — защита от инъекции в query."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return []
    query = "&".join(f"{k}={quote(str(v), safe='(),.*:+-')}" for k, v in params.items())
    url = f"{SUPABASE_URL}/rest/v1/{table}?{query}"
    try:
        resp = await http().get(url, headers=sb_headers(), timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else []
    except Exception as exc:
        log.warning("supabase select %s failed: %s", table, exc)
        return []


async def sb_insert(table: str, row: dict, timeout: float = 5.0) -> bool:
    """Запись строки в таблицу."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return False
    try:
        resp = await http().post(
            f"{SUPABASE_URL}/rest/v1/{table}",
            headers={**sb_headers(), "Content-Type": "application/json"},
            json=row,
            timeout=timeout,
        )
        resp.raise_for_status()
        return True
    except Exception as exc:
        log.warning("supabase insert %s failed: %s", table, exc)
        return False


async def sb_rpc(fn: str, payload: dict, timeout: float = 5.0) -> Any:
    """Вызов SQL-функции через PostgREST."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    resp = await http().post(
        f"{SUPABASE_URL}/rest/v1/rpc/{fn}",
        headers={**sb_headers(), "Content-Type": "application/json"},
        json=payload,
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


async def get_client_data(client_id: str) -> dict | None:
    """Извлечение настроек компании и проекта из saas_clients + saas_projects."""
    rows = await sb_select(
        "saas_clients",
        {
            "id": f"eq.{client_id}",
            "select": (
                "company_name,"
                "system_message,timezone,working_hours,"
                "crm_provider,crm_config,"
                "saas_projects(tg_chat_id_notify,google_calendar_id,"
                "project_name,business_context,bot_goal,tone,gsm_subs_status)"
            ),
        },
    )
    if not rows:
        return None
    rec = rows[0]
    projects = rec.get("saas_projects") or []
    first = projects[0] if projects else {}
    rec["tg_chat_id_notify"] = first.get("tg_chat_id_notify")
    rec["google_calendar_id"] = first.get("google_calendar_id")
    rec["gsm_subs_status"] = first.get("gsm_subs_status")

    for cheie_proiect, cheie_client in (
        ("project_name", "company_name"),
        ("business_context", "business_context"),
        ("bot_goal", "bot_goal"),
        ("tone", "tone"),
    ):
        valoare = (first.get(cheie_proiect) or "").strip()
        if valoare:
            rec[cheie_client] = valoare

    return rec


async def get_persona_row(client_id: str) -> dict | None:
    """Получение сырой строки характера из Redis или Supabase."""
    cache_key = f"persona:{client_id}"
    if redis_client:
        with contextlib.suppress(Exception):
            cached = await redis_client.get(cache_key)
            if cached:
                return json.loads(cached)

    cols = ",".join(
        ["system_prompt", "voice_model", "language", "persona_name", "lore",
         "personality_enabled", *TRAITS]
    )
    rows = await sb_select("companion_settings", {"client_id": f"eq.{client_id}", "select": cols})
    row = rows[0] if rows else None
    if redis_client and row is not None:
        with contextlib.suppress(Exception):
            await redis_client.set(cache_key, json.dumps(row), ex=PERSONA_CACHE_TTL)
    return row


async def get_persona(client_id: str) -> Persona:
    """Получение объекта Persona с кэшированием."""
    return Persona.from_row(await get_persona_row(client_id))


async def upload_audio_to_supabase(client_id: str, filepath: str) -> str | None:
    """Загрузка WAV-записи звонка в Supabase Storage бакет 'call-recordings'."""
    if not SUPABASE_URL or not SUPABASE_KEY or not filepath:
        return None
    if not await asyncio.to_thread(os.path.exists, filepath):
        return None
    try:
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        storage_path = f"records/{client_id}/record_{uuid.uuid4().hex[:8]}.wav"

        def _upload() -> str:
            with open(filepath, "rb") as f:
                supabase.storage.from_("call-recordings").upload(
                    path=storage_path, file=f, file_options={"content-type": "audio/wav"}
                )
            return supabase.storage.from_("call-recordings").get_public_url(storage_path)

        return await asyncio.to_thread(_upload)
    except Exception as exc:
        log.warning("audio upload failed: %s", exc)
        return None


async def ensure_end_client(client_id: str, phone: str, name: str, language: str) -> None:
    """Обновление имени клиента в CRM-карточке end_clients."""
    clean_phone = "".join(filter(str.isdigit, str(phone)))
    if not clean_phone or not client_id:
        return
    payload = {
        "p_client_id": client_id,
        "p_phone": clean_phone,
        "p_name": (name or "").strip(),
        "p_language": (language or "").strip(),
    }
    with contextlib.suppress(Exception):
        await sb_rpc("end_clients_upsert", payload, timeout=3.0)
