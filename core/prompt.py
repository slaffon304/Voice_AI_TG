"""Shared Core Prompt: единая сборка system instruction для GSM и WebRTC."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any, Literal

from core.config import WEB_PROMPT_CLIENT_MAX_CHARS
from core.hours import next_open_slot, office_state
from core.persona import Persona, build_personality_block

Channel = Literal["gsm", "web"]

TELEPHONY_RULES = """<CALL_RULES>
- This is a phone call. Never output markdown, emoji, lists or URLs — everything you say is spoken aloud.
- Pronounce phone numbers and codes digit by digit.
- If you need to send a link or an address, use the send_sms tool instead of reading it aloud.
- Never invent facts, prices, availability or dates. If you do not know, say so and offer a callback.
- If the caller asks whether you are a human or an AI assistant, answer honestly.
- If the line is noisy or the caller is unclear, ask them to repeat before guessing. A single unclear turn never changes what you do: keep the topic, keep the language, keep the call going.
</CALL_RULES>"""

# Компактный web-профиль: <100 строк правил. Детали цен/FAQ — на экране, не в сокете.
WEB_CHANNEL_RULES = """<CHANNEL>
Website voice (WebRTC + Generative UI). You lead. Not a passive FAQ bot.
Language: only <LANG>, unless the visitor clearly switches first.

ROLE
- You are a real digital employee of this company, not a script reader.
- First seconds: earn attention. Short. Direct. No corporate filler.
- Prefer showing over listing: call a UI tool, then one spoken line about what appeared.

UI FIRST
- Prices, packages, cases, forms, ROI live on screen.
- Before a long explanation → control_website_ui (or update_roi_calculator / morph_ui_for_sentiment).
- Voice = short; screen = detail. Never invent numbers not on screen or from tools.
- components[] only in concept/lab mode; series clients use section=...

ANTI-DICTATION
- Never ask to dictate a phone digit by digit.
- Need a phone → booking_widget / verify UI, wait for SYSTEM UI EVENT.

ESCAPE
- If visitor chose "don't want to talk" → stop voice immediately. Do not argue.

ABUSE
- Open voice is limited because of competitors and bad-faith visitors.
- Never say "demo", "trial ended", or "free minutes are over".
- If verification is required: say honestly that identity must be confirmed, point to the on-screen form.
- After verify, if abuse continues, the system blocks them — do not negotiate.

SESSION
- Time-limited. Be concise. Steer to a concrete next step: qualified interest, booking, or verified contact.
- No hard-sell script. No begging. Frame value; let the screen prove it.

TOOLS (one short line after each)
- dwell / ROI / audit / sentiment / DOM / set_agent_state: UI carries the weight.
- flag_session_abuse: only for clear bad faith (script reading, probing, spam).
</CHANNEL>"""


def _safe(value: Any, fallback: str = "") -> str:
    return str(value or fallback).replace("{", "").replace("}", "")


def _strip_bulk_sections(text: str) -> str:
    """Убирает типичные простыни прайсов/FAQ из client system_message для web."""
    if not text:
        return text
    # Вырезаем крупные markdown/plain блоки с ценами и FAQ, если размечены заголовками
    patterns = (
        r"(?is)\n+#+\s*(pricing|prices|тариф|пакет|plans?|faq|часто задаваемые).*$",
        r"(?is)\n+\*{0,2}(pricing|prices|тарифы|пакеты|faq)\*{0,2}\s*\n.*$",
    )
    out = text
    for pat in patterns:
        out = re.sub(pat, "\n", out)
    return out.strip()


def _compact_web_client_block(
    client_data: dict,
    persona: Persona,
    lang: str,
    now: dt.datetime,
    readable_hours: str,
    is_open: bool,
    raw_prompt: str,
) -> str:
    """
    Для WebRTC: структурированное ядро + ужатый client prompt.
    Полные прайсы/FAQ не тащим в сокет — они на UI.
    """
    lines = [
        "<COMPANY>",
        f"Name: {_safe(client_data.get('company_name'), 'Company')}",
    ]
    ctx = _safe(client_data.get("business_context"))
    if ctx:
        lines.append(f"Context: {ctx[:400]}")
    goal = _safe(client_data.get("bot_goal"))
    if goal:
        lines.append(f"Goal: {goal[:300]}")
    tone = _safe(client_data.get("tone"), "professional")
    lines.append(f"Tone: {tone}")
    lines.append(f"Persona: {_safe(persona.persona_name, 'Assistant')}")
    lines.append(
        f"Office (human meetings only): {readable_hours} — "
        f"{'open' if is_open else 'closed for humans; you stay available'}."
    )
    lines.append(f"Now: {now.strftime('%A, %d %B %Y, %H:%M')}")
    lines.append("</COMPANY>")

    cleaned = _strip_bulk_sections(raw_prompt)
    # Подстановка токенов уже сделана в render_client_template
    max_chars = min(WEB_PROMPT_CLIENT_MAX_CHARS, 1200)
    if len(cleaned) > max_chars:
        cleaned = (
            cleaned[:max_chars].rstrip()
            + "\n[Truncated. Pricing/FAQ are on the website UI — "
            "use control_website_ui; do not invent missing details.]"
        )
    if cleaned:
        lines.append("")
        lines.append("<CLIENT_NOTES>")
        lines.append(cleaned)
        lines.append("</CLIENT_NOTES>")
        lines.append(
            "If CLIENT_NOTES conflict with on-screen UI after a tool call, trust the screen/tools."
        )
    return "\n".join(lines)


def render_client_template(
    client_data: dict,
    persona: Persona,
    lang: str,
    now: dt.datetime,
    hours: dict[str, list[str]],
    *,
    channel: Channel = "gsm",
) -> tuple[str, bool, str]:
    raw = (
        persona.system_prompt
        or client_data.get("system_message")
        or "Ești un asistent virtual."
    )
    is_open, readable_hours = office_state(hours, now)

    prompt = raw
    for token, value in (
        ("{company_name}", _safe(client_data.get("company_name"), "Compania")),
        ("{business_context}", _safe(client_data.get("business_context"))),
        ("{bot_goal}", _safe(client_data.get("bot_goal"))),
        ("{tone}", _safe(client_data.get("tone"), "friendly")),
        ("{current_datetime}", now.strftime("%A, %d %B %Y, %H:%M")),
        (
            "{office_status}",
            "Open"
            if is_open
            else "Closed for human appointments only — you, the assistant, are available as always",
        ),
        ("{lang}", lang),
        ("{persona_name}", _safe(persona.persona_name, "Asistent")),
        ("{working_hours}", readable_hours),
    ):
        prompt = prompt.replace(token, value)

    if channel == "web":
        prompt = _compact_web_client_block(
            client_data, persona, lang, now, readable_hours, is_open, prompt
        )
    elif len(prompt) > WEB_PROMPT_CLIENT_MAX_CHARS * 2:
        # GSM: мягкий потолок, без агрессивной вырезки прайсов (там нет экрана)
        prompt = prompt[: WEB_PROMPT_CLIENT_MAX_CHARS * 2].rstrip() + "\n[Truncated.]"

    return prompt, is_open, readable_hours


def _availability_block(
    hours: dict[str, list[str]],
    now: dt.datetime,
    readable_hours: str,
) -> list[str]:
    next_slot = next_open_slot(hours, now)
    offset = now.strftime("%z")
    offset_fmt = f"{offset[:3]}:{offset[3:]}" if offset else "+00:00"
    blocks = [
        "<AVAILABILITY>",
        (
            "YOU ARE AVAILABLE 24/7 for voice consultation. Office hours only limit "
            f"meetings WITH A HUMAN: {readable_hours}."
        ),
        (
            f"Now: {now.strftime('%A, %d %B %Y, %H:%M')} (UTC{offset_fmt}). "
            f"Next human slot: {next_slot}."
        ),
        "</AVAILABILITY>",
        "",
    ]
    return blocks


def build_system_prompt(
    client_data: dict,
    persona: Persona,
    memory: dict | None,
    lang: str,
    now: dt.datetime,
    hours: dict[str, list[str]],
    *,
    channel: Channel = "gsm",
    caller_phone: str = "Necunoscut",
    caller_name: str = "",
    caller_card: dict | None = None,
    landing_url: str = "",
    referrer: str = "",
) -> tuple[str, str]:
    memory = memory or {"core": "", "short": "", "long": ""}
    client_prompt, _is_open, readable_hours = render_client_template(
        client_data, persona, lang, now, hours, channel=channel
    )

    blocks: list[str] = [build_personality_block(persona, lang), ""]

    blocks.append("<LANG>")
    blocks.append(
        f"Speak and think in this language for the whole session: {lang}. "
        "Do not switch unless the visitor clearly switches first."
    )
    blocks.append("</LANG>")
    blocks.append("")

    if channel == "gsm":
        blocks.append(TELEPHONY_RULES)
        blocks.append("")
        blocks.append(client_prompt)
        blocks.append("")
        blocks.append("<CALLER>")
        if caller_phone and caller_phone != "Necunoscut":
            blocks.append(f"The caller is phoning from: {caller_phone}")
            blocks.append(
                "You already have this number. Never ask the caller for their phone number. "
                "Use it directly when saving a lead or sending an SMS. Ask only if they want "
                "to be reached on a different number."
            )
        else:
            blocks.append(
                "The caller's number is hidden. Ask for it only if you need a callback."
            )
        if caller_name:
            blocks.append(
                f"The caller's name is {caller_name}. Use it naturally, do not re-ask."
            )
        else:
            blocks.append(
                "The contact card has no name. Check memory below: if a name is recorded, "
                "use it and do not ask again. Only if memory has no name: ask once how to "
                "address them, then use the name for the rest of the call."
            )
        blocks.append("</CALLER>")
        blocks.append("")
    else:
        # Web: правила канала ПЕРЕД client notes, чтобы не утонули в тексте из БД
        blocks.append(WEB_CHANNEL_RULES)
        blocks.append("")
        blocks.append(client_prompt)
        blocks.append("")
        if landing_url or referrer:
            blocks.append("<ARRIVAL>")
            if landing_url:
                blocks.append(f"Landing URL: {landing_url}")
            if referrer:
                blocks.append(f"Referrer: {referrer}")
            blocks.append(
                "If arrival context suggests a niche or campaign, reflect it once on screen "
                "(control_website_ui) — do not recite ad copy."
            )
            blocks.append("</ARRIVAL>")
            blocks.append("")
        if caller_name:
            blocks.append(f"Visitor name (if known): {caller_name}. Use it; do not re-ask.")
            blocks.append("")

    blocks.extend(_availability_block(hours, now, readable_hours))

    core = (memory.get("core") or "").strip()
    short = (memory.get("short") or "").strip()
    long_m = (memory.get("long") or "").strip()
    if core or short or long_m:
        blocks.append("<CALLER_MEMORY>")
        if core:
            blocks.append(f"CORE: {core}")
        if short:
            blocks.append(f"SHORT TERM: {short}")
        if long_m:
            # Web: длинную память режем — иначе снова раздуваем сокет
            if channel == "web" and len(long_m) > 500:
                long_m = long_m[:500].rstrip() + "…"
            blocks.append(f"LONG TERM: {long_m}")
        blocks.append("</CALLER_MEMORY>")
        blocks.append("")

    full = "\n".join(b for b in blocks if b is not None)
    return full, readable_hours
