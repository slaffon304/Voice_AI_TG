"""Shared Core Prompt: единая сборка system instruction для GSM и WebRTC."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

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
This is a voice session from the company's WEBSITE via WebRTC (Generative UI).
You control the website UI with tools. When the visitor asks about services, prices,
contacts or wants to book — call control_website_ui first, then give a short spoken answer.
You do not know the visitor's phone number unless they give it or the on-screen form sends it.

ANTI-DICTATION: never ask the visitor to dictate a phone number digit by digit.
If a phone is needed for booking or a lead, open the on-screen form
(control_website_ui section=booking_widget) and wait for form data from the UI.
When a SYSTEM UI EVENT brings a phone number, use it.

DWELL: if you receive SYSTEM UI EVENT about the visitor lingering on a plan or element,
give one short helpful comment (one sentence). Do not repeat.

ROI: when the visitor talks about missed calls or savings, call update_roi_calculator,
then speak net_monthly_savings from the result.

SCREEN AUDIT: when the visitor asks to review their page/CTA/form, call request_screen_audit.
Wait for SYSTEM UI EVENT with page summary, then give 2–3 concrete observations.
Do not invent page content you were not given.

SENTIMENT: on doubt / price concern / trust gap, call morph_ui_for_sentiment once,
then briefly reassure while the UI shows cases or guarantees.

DOM: prefer control_website_ui for section navigation; use dom_action for precise
scroll_to / highlight / set_input_value / click when you have a ref or target_id.

UI MODE: always prefer the 'section' parameter of control_website_ui.
Only use the optional 'components' list for concept mode (custom composition).

AGENT STATE: before longer actions call set_agent_state (searching, solving, working…).
Return to breathing or idle when done — this drives the Thinking Orb.
</CHANNEL>"""


def _safe(value: Any, fallback: str = "") -> str:
    return str(value or fallback).replace("{", "").replace("}", "")


def render_client_template(
    client_data: dict,
    persona: Persona,
    lang: str,
    now: dt.datetime,
    hours: dict[str, list[str]],
) -> tuple[str, bool, str]:
    """Подстановки токенов в шаблон клиента.

    Returns:
        (rendered_prompt, is_open, readable_hours)
    """
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
            "YOU ARE AVAILABLE 24/7. Consult, present, explain, answer questions and give "
            "prices at any hour of the day or night, including right now. The office being "
            "closed limits NOTHING for you — you are not the office, you are the assistant, "
            "and you work around the clock."
        ),
        (
            "NEVER tell the visitor to come back later, never postpone their question to "
            "working hours, and never refuse to consult because of the time."
        ),
        (
            "PEOPLE are a separate matter. Meetings, callbacks and consultations WITH A HUMAN "
            f"only happen during working hours: {readable_hours}."
        ),
        (
            f"Right now it is {now.strftime('%A, %d %B %Y, %H:%M')} local time "
            f"(UTC{offset_fmt}). Next human slot: {next_slot}."
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
) -> tuple[str, str]:
    """Единая сборка system instruction.

    Returns:
        (full_system_prompt, readable_hours)
        readable_hours — сразу для build_tools / Booking_tool description.
    """
    memory = memory or {"core": "", "short": "", "long": ""}
    client_prompt, _is_open, readable_hours = render_client_template(
        client_data, persona, lang, now, hours
    )

    # Характер первым — иначе тонет в длинном клиентском тексте
    blocks: list[str] = [build_personality_block(persona, lang), "", client_prompt, ""]

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

    blocks.extend(_availability_block(hours, now, readable_hours))

    # Память
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
