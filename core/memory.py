"""Shared Core Memory: person_memory по телефону и по web visitor id."""

from __future__ import annotations

import datetime as dt
from typing import Any

from core.config import log
from core.db import sb_rpc


def _time_context_from(last_at: Any) -> str:
    if not last_at:
        return "first_time"
    try:
        last = dt.datetime.fromisoformat(str(last_at).replace("Z", "+00:00"))
        delta = (dt.datetime.now(dt.timezone.utc) - last).total_seconds() / 60
        return "very_recent" if delta < 15 else ("same_day" if delta < 1440 else "new_day")
    except ValueError:
        return "first_time"


async def get_caller_memory(client_id: str, phone: str) -> tuple[dict, str]:
    """Память по client_id + phone → таблица person_memory."""
    default: dict = {"core": "", "short": "", "long": ""}
    if not phone or phone == "Necunoscut":
        return default, "first_time"
    rows = await sb_rpc(
        "person_memory_get",
        {"p_client_id": client_id, "p_phone": phone},
        timeout=2.5,
    )
    if not rows:
        return default, "first_time"
    rec = rows[0] if isinstance(rows, list) else rows
    if not isinstance(rec, dict):
        return default, "first_time"
    memory = {
        "core": rec.get("core_identity") or "",
        "short": rec.get("short_term_context") or "",
        "long": rec.get("long_term_context") or "",
    }
    return memory, _time_context_from(rec.get("last_interaction_at"))


async def get_web_visitor_context(
    client_id: str, visitor_id: str
) -> tuple[dict, dict, str]:
    """Карточка и память посетителя по visitor_id (RPC person_memory_get_web).

    Returns:
        (contact, memory, time_context)
        contact: found, name, lang, phone, optional card/event_id
        memory: core / short / long — поля person_memory
    """
    contact: dict = {"found": False, "name": "", "lang": "", "phone": ""}
    memory: dict = {"core": "", "short": "", "long": ""}
    if not visitor_id:
        return contact, memory, "first_time"
    try:
        rows = await sb_rpc(
            "person_memory_get_web",
            {"p_client_id": client_id, "p_web_id": visitor_id},
            timeout=2.5,
        )
    except Exception as exc:
        log.warning("web visitor lookup failed: %s", exc)
        return contact, memory, "first_time"
    if not rows:
        return contact, memory, "first_time"
    rec = rows[0] if isinstance(rows, list) else rows
    if not isinstance(rec, dict):
        return contact, memory, "first_time"

    contact = {
        "found": bool(rec.get("end_client_id")),
        "name": rec.get("name") or "",
        "lang": rec.get("language") or "",
        "phone": rec.get("phone") or "",
    }
    memory = {
        "core": rec.get("core_identity") or "",
        "short": rec.get("short_term_context") or "",
        "long": rec.get("long_term_context") or "",
    }
    if contact["found"]:
        try:
            card = await sb_rpc(
                "end_client_card",
                {"p_client_id": client_id, "p_web_id": visitor_id},
                timeout=2.5,
            )
            if isinstance(card, dict) and card:
                contact["card"] = card
                contact["event_id"] = str(card.get("event_id") or "").strip()
        except Exception as exc:
            log.warning("web visitor card failed: %s", exc)
    return contact, memory, _time_context_from(rec.get("last_interaction_at"))
