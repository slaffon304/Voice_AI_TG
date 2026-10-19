"""Shared Core Protection: blacklist, Turnstile, суточные лимиты web/WebRTC."""

from __future__ import annotations

import contextlib
import datetime as dt

from core.config import (
    DEFAULT_TZ,
    TURNSTILE_SECRET_KEY,
    WEB_MAX_CALLS_PER_IP,
    WEB_MAX_CALLS_PER_VISITOR,
    log,
    tz_for,
)
from core.db import http, redis_client, sb_insert, sb_select


async def propusk_valabil(token: str, ip: str, secret: str = "") -> bool:
    cheie = secret or TURNSTILE_SECRET_KEY
    if not cheie:
        return True
    if not token:
        return False
    try:
        resp = await http().post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={"secret": cheie, "response": token},
            timeout=5.0,
        )
        raspuns = resp.json()
        if not raspuns.get("success"):
            log.warning("turnstile a refuzat: %s", raspuns.get("error-codes"))
        return bool(raspuns.get("success"))
    except Exception as exc:
        log.warning("turnstile nu raspunde: %s", exc)
        return True


async def este_blocat(visitor_id: str, ip: str) -> bool:
    conditii = []
    if visitor_id:
        conditii.append(f"visitor_id.eq.{visitor_id}")
    if ip:
        conditii.append(f"ip.eq.{ip}")
    if not conditii:
        return False
    randuri = await sb_select(
        "voice_blocklist",
        {"or": "(" + ",".join(conditii) + ")", "select": "until", "limit": "5"},
        timeout=2.0,
    )
    acum = dt.datetime.now(dt.timezone.utc)
    for rand in randuri:
        pana = rand.get("until")
        if not pana:
            return True
        with contextlib.suppress(Exception):
            if dt.datetime.fromisoformat(str(pana).replace("Z", "+00:00")) > acum:
                return True
    return False


async def blocheaza(client_id: str, visitor_id: str, ip: str, motiv: str) -> None:
    await sb_insert(
        "voice_blocklist",
        {
            "client_id": client_id or None,
            "visitor_id": visitor_id or None,
            "ip": ip or None,
            "reason": motiv,
        },
    )
    log.warning("blocat: visitor=%s ip=%s motiv=%s", (visitor_id or "")[:12], ip, motiv)


async def peste_limita(visitor_id: str, ip: str) -> str:
    if not redis_client:
        return ""
    acum = dt.datetime.now(tz_for(DEFAULT_TZ))
    start_zi = acum.replace(hour=5, minute=0, second=0, microsecond=0)
    if acum < start_zi:
        start_zi -= dt.timedelta(days=1)
    ttl = int((start_zi + dt.timedelta(days=1) - acum).total_seconds()) + 3600
    zi = start_zi.strftime("%Y%m%d")
    for cheie, valoare, limita, nume in (
        (f"web_calls:v:{zi}:{visitor_id}", visitor_id, WEB_MAX_CALLS_PER_VISITOR, "visitor"),
        (f"web_calls:i:{zi}:{ip}", ip, WEB_MAX_CALLS_PER_IP, "ip"),
    ):
        if not valoare:
            continue
        try:
            numar = await redis_client.incr(cheie)
            if numar == 1:
                await redis_client.expire(cheie, ttl)
            if numar > limita:
                return f"{nume} {valoare[:16]}"
        except Exception as exc:
            log.warning("limita zilnica: Redis nu raspunde: %s", exc)
            return ""
    return ""


def origin_permis(origin: str, allowed_origins: str | None) -> bool:
    allowed = [d.strip().lower() for d in str(allowed_origins or "").split(",") if d.strip()]
    if not allowed:
        return True
    origin = (origin or "").lower()
    host = origin.split("://")[-1].split("/")[0].split(":")[0]
    return host in allowed
