"""Shared Core Hours: рабочие часы клиента из БД → парсинг и человекочитаемый вид."""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

_DAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_DEFAULT_HOURS = {d: ["09:00", "17:00"] for d in _DAY_KEYS[:5]}


def parse_working_hours(raw: Any) -> dict[str, list[str]]:
    """Разбор jsonb/dict рабочих часов из saas_clients.working_hours."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = None
    if not isinstance(raw, dict) or not raw:
        return dict(_DEFAULT_HOURS)
    out: dict[str, list[str]] = {}
    for day, val in raw.items():
        key = str(day).lower()[:3]
        if key in _DAY_KEYS and isinstance(val, (list, tuple)) and len(val) == 2:
            out[key] = [str(val[0]), str(val[1])]
    return out or dict(_DEFAULT_HOURS)


def next_open_slot(hours: dict[str, list[str]], now: dt.datetime) -> str:
    """Ближайшее время, когда с клиентом сможет говорить человек."""
    for day_offset in range(0, 8):
        day = now + dt.timedelta(days=day_offset)
        window = hours.get(_DAY_KEYS[day.weekday()])
        if not window:
            continue
        try:
            sh, sm = (int(x) for x in window[0].split(":")[:2])
            eh, em = (int(x) for x in window[1].split(":")[:2])
        except (ValueError, IndexError):
            continue
        start = day.replace(hour=sh, minute=sm, second=0, microsecond=0)
        end = day.replace(hour=eh, minute=em, second=0, microsecond=0)
        if day_offset == 0 and now < end:
            when = max(now, start)
            return when.strftime("%A %d %B, %H:%M")
        if day_offset > 0:
            return start.strftime("%A %d %B, %H:%M")
    return "нет доступного окна"


def office_state(hours: dict[str, list[str]], now: dt.datetime) -> tuple[bool, str]:
    """Возвращает (открыто_сейчас, человекочитаемое расписание).

    Порядок дней фиксированный (mon…sun), иначе jsonb отдаёт хаотичный порядок
    и модель читает его вслух как есть.
    """
    key = _DAY_KEYS[now.weekday()]
    is_open = False
    window = hours.get(key)
    if window:
        try:
            start_h, start_m = (int(x) for x in window[0].split(":")[:2])
            end_h, end_m = (int(x) for x in window[1].split(":")[:2])
            start = now.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
            end = now.replace(hour=end_h, minute=end_m, second=0, microsecond=0)
            is_open = start <= now <= end
        except (ValueError, IndexError):
            is_open = False
    readable = ", ".join(
        f"{d.capitalize()} {hours[d][0]}-{hours[d][1]}" for d in _DAY_KEYS if d in hours
    )
    return is_open, readable or "Mon-Fri 09:00-17:00"
