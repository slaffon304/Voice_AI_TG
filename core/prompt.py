"""Shared Core Prompt: единая сборка system instruction для GSM и WebRTC."""

from __future__ import annotations

import datetime as dt
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

WEB_CHANNEL_RULES = """<CHANNEL>
Voice session on the company website (WebRTC + Generative UI widget).
You lead. You are not a passive FAQ bot. Speak only the language given in <LANG>.

UI FIRST: prices, packages, cases, forms live on screen. Call control_website_ui
(or update_roi_calculator / morph_ui_for_sentiment) before long explanations.
Voice = short; screen = detail. Never invent numbers not shown or confirmed by tools.

ANTI-DICTATION: never ask the visitor to dictate a phone digit by digit.
Need a phone → open booking_widget / verify UI and wait for SYSTEM UI EVENT.

ESCAPE: if SYSTEM UI EVENT says the visitor chose "don't want to talk", stop the
voice track immediately. Do not argue.

ABUSE: we limit open voice access because of competitors and bad-faith visitors.
Never say "demo", "trial ended", or "free minutes are over". If verification is
required, say honestly that identity must be confirmed to continue, and point to
the on-screen form. After verified abuse continues, the system will block them.

SESSION: this voice session is time-limited. Be concise. Move toward a concrete
next step (qualified interest, booking, or verified contact) without a hard-sell script.

DWELL / ROI / AUDIT / SENTIMENT / DOM / AGENT STATE: one short spoken line;
UI does the heavy lifting. Prefer control_website_ui section=... ; components only in concept mode.
AGENT STATE: set_agent_state for longer actions; return to breathing/idle when done.
</CHANNEL>"""


def _safe(value: Any, fallback: str = "") -> str:
    return str(value or fallback).replace("{", "").replace("}", "")


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

    if channel == "web" and len(prompt) > WEB_PROMPT_CLIENT_MAX_CHARS:
        prompt = (
            prompt[:WEB_PROMPT_CLIENT_MAX_CHARS].rstrip()
            + "\n\n[Truncated. Full pricing and long FAQ are on the website UI — "
            "use control_website_ui / tools; do not invent missing details.]"
        )

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

    blocks: list[str] = [build_personality_block(persona, lang), "", client_prompt, ""]

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
        blocks.append(WEB_CHANNEL_RULES)
        blocks.append("")
        if landing_url or referrer:
            blocks.append("<ARRIVAL>")
            if landing_url:
                blocks.append(f"Landing URL: {landing_url}")
            if referrer:
                blocks.append(f"Referrer: {referrer}")
            blocks.append("</ARRIVAL>")
            blocks.append("")
        if caller_name:
            blocks.append(f"Visitor name (if known): {caller_name}.")
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
            blocks.append(f"LONG TERM: {long_m}")
        blocks.append("</CALLER_MEMORY>")
        blocks.append("")

    full = "\n".join(b for b in blocks if b is not None)
    return full, readable_hours
