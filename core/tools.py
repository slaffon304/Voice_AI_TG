"""Shared Core Tools: схемы инструментов (Function Calling) и взаимодействие с n8n / CRM."""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import re
from typing import Any

from core.config import N8N_BASE_URL, tz_for
from core.db import http

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")

FRAZA_INAINTE = (
    " Înainte de a apela instrumentul, spune cu voce tare o frază scurtă în limba "
    "conversației — de exemplu «O secundă, verific.» sau «Секунду, проверяю.» — "
    "și abia apoi apelează-l."
)

DURATA_INTALNIRE_MIN = 30


def _parse_timp(val: Any, tz_name: str) -> dt.datetime | None:
    """Время от модели: ISO с поясом или без. Без пояса — пояс клиента."""
    s = str(val or "").strip()
    if not s:
        return None
    try:
        t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=tz_for(tz_name))
    return t


def normalizeaza_timp(args: dict, tz_name: str) -> None:
    """Начало и конец встречи — всегда оба и всегда с поясом."""
    start = _parse_timp(args.get("start_time"), tz_name)
    if not start:
        return
    end = _parse_timp(args.get("end_time"), tz_name)
    if not end or end <= start:
        end = start + dt.timedelta(minutes=DURATA_INTALNIRE_MIN)
    args["start_time"] = start.isoformat(timespec="seconds")
    args["end_time"] = end.isoformat(timespec="seconds")


def telefon_valid(phone: Any) -> bool:
    """Номер, по которому можно перезвонить: не меньше 8 цифр."""
    return len("".join(filter(str.isdigit, str(phone or "")))) >= 8


TELEFON_INCOMPLET = {
    "status": "error",
    "message": (
        "Numărul de telefon lipsește sau este incomplet — nu am salvat nimic. "
        "Cere-i clientului numărul complet, repetă-l cifră cu cifră, așteaptă "
        "confirmarea și abia apoi încearcă din nou."
    ),
}

FARA_PROGRAMARE = {
    "status": "error",
    "message": (
        "Clientul nu are o programare cunoscută. Întreabă-l pe ce număr de telefon "
        "s-a programat, apelează Booking_tool cu action='lookup' și acel număr, "
        "apoi reîncearcă."
    ),
}


def slot_liber(result: Any) -> bool:
    """Ответ проверки n8n: «СЛОТЫ ПОЛНОСТЬЮ СВОБОДНЫ»."""
    return "СВОБОДН" in json.dumps(result, ensure_ascii=False).upper()


def id_din_lookup(result: Any) -> str:
    """Номер записи из ответа n8n на 'lookup'."""
    if isinstance(result, list):
        result = result[0] if result else {}
    if isinstance(result, dict):
        return str(result.get("event_id") or "").strip()
    return ""


_ID_ZAPISI = re.compile(r"ID записи:\s*([A-Za-z0-9_\-]+)")


def id_zapisi(result: Any) -> str:
    """Номер созданной записи из ответа Booking. Нет номера — пустая строка."""
    if not result:
        return ""
    m = _ID_ZAPISI.search(json.dumps(result, ensure_ascii=False))
    return m.group(1) if m else ""


async def send_tg_alert(chat_id: str | None, message: str) -> None:
    if not TG_BOT_TOKEN or not chat_id:
        return
    with contextlib.suppress(Exception):
        await http().post(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
            timeout=5.0,
        )


async def call_n8n(path: str, params: dict, arguments: dict, timeout: float = 10.0) -> Any:
    """Универсальный вызов вебхука n8n."""
    url = f"{N8N_BASE_URL}/{path}"
    resp = await http().post(url, params=params, json=arguments, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def build_tools(client_data: dict, readable_hours: str, web: bool = False) -> list[dict]:
    """Инструменты бота: save_lead, Booking_tool, send_sms, end_call."""
    tools = [
        {
            "name": "save_lead",
            "description": (
                "Salvează datele de contact și motivul apelului în CRM. "
                + (
                    "Înainte de apel repetă numărul de telefon al vizitatorului cifră cu "
                    "cifră și așteaptă confirmarea lui."
                    if web else
                    "Dacă clientul a dat un ALT număr decât cel de pe care sună, repetă-l "
                    "cifră cu cifră și așteaptă confirmarea înainte de apel."
                )
                + FRAZA_INAINTE
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "client_name": {"type": "string"},
                    "client_phone": {
                        "type": "string",
                        "description": (
                            "Numărul vizitatorului NU este cunoscut: pe site nu se vede "
                            "niciun număr de telefon. Cere-i numărul și scrie-l aici."
                            if web else
                            "Doar dacă clientul cere să fie contactat pe ALT număr. "
                            "Numărul de la care sună este deja cunoscut — nu-l întreba."
                        ),
                    },
                    "request_summary": {"type": "string"},
                    "event_id": {
                        "type": "string",
                        "description": (
                            "ID-ul programării din răspunsul Booking_tool la 'book', dacă "
                            "ai programat ceva în această convorbire. Altfel lasă gol."
                        ),
                    },
                },
                "required": ["client_name", "request_summary"],
            },
        },
        {
            "name": "Booking_tool",
            "description": (
                "Verifică sau creează programări în calendarul companiei. "
                f"Program de lucru: {readable_hours}. "
                "Reguli obligatorii: "
                "1. Înainte de a propune un interval, apelează cu action='check'. "
                "Nu inventa ore libere! "
                "2. start_time și end_time trebuie să fie în format ISO 8601 "
                "(ex: 2026-05-15T14:00:00). Durata standard este de 30 de minute. "
                "3. Pentru 'check' sunt obligatorii doar start_time și end_time. "
                "4. Pentru 'book' sunt obligatorii start_time, end_time, client_name, "
                "phone și request_summary. "
                "5. 'lookup' caută programarea existentă a clientului după phone. "
                "6. 'cancel' anulează programarea după event_id. "
                "7. 'reschedule' mută programarea la start_time/end_time noi după event_id."
                + FRAZA_INAINTE
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["check", "book", "lookup", "cancel", "reschedule"],
                        "description": "Acțiunea dorită în calendar",
                    },
                    "start_time": {
                        "type": "string",
                        "description": "Începutul intervalului în format ISO 8601",
                    },
                    "end_time": {
                        "type": "string",
                        "description": "Sfârșitul intervalului în format ISO 8601",
                    },
                    "client_name": {"type": "string", "description": "Numele clientului"},
                    "phone": {"type": "string", "description": "Numărul de telefon"},
                    "request_summary": {"type": "string", "description": "Motivul programării"},
                    "event_id": {
                        "type": "string",
                        "description": "ID-ul evenimentului (pentru cancel sau reschedule)",
                    },
                },
                "required": ["action"],
            },
        },
        {
            "name": "send_sms",
            "description": (
                "Trimite un SMS clientului cu un link sau confirmare. "
                "Folosește-l doar dacă clientul cere explicit informații prin SMS."
                + FRAZA_INAINTE
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "phone": {"type": "string", "description": "Numărul destinatarului"},
                    "text": {"type": "string", "description": "Textul mesajului SMS"},
                },
                "required": ["phone", "text"],
            },
        },
        {
            "name": "end_call",
            "description": (
                "Încheie apelul când conversația s-a terminat natural "
                "(după ce ți-ai luat rămas bun)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Motivul încheierii apelului",
                    }
                },
                "required": ["reason"],
            },
        },
    ]
    return tools
