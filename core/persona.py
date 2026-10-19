"""Shared Core Persona: 10-факторный движок личности (BBB Engine), маппинг голосов и адаптация речи."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.config import DEFAULT_LANG

# 10 шкал характера (таблица companion_settings)
TRAITS = (
    "openness",
    "conscientiousness",
    "extraversion",
    "agreeableness",
    "neuroticism",
    "sarcasm",
    "energy",
    "proactivity",
    "tough_love",
    "ego",
)

_TRAIT_SCALES: tuple[tuple[str, str], ...] = (
    ("openness", "Открытость (консерватор - творец)"),
    ("conscientiousness", "Собранность (хаос - педант)"),
    ("extraversion", "Экстраверсия (интроверт - душа компании)"),
    ("agreeableness", "Дружелюбие (критик - эмпат)"),
    ("neuroticism", "Эмоциональность (спокоен - легко возбудим)"),
    ("sarcasm", "Сарказм (серьезный - ироничный)"),
    ("energy", "Энергетика (медленный - гиперэнергичный)"),
    ("proactivity", "Инициативность (ведомый - ведущий)"),
    ("tough_love", "Стиль поддержки (мягко - жестко мотивирует)"),
    ("ego", "Эго (скромный - высокомерный)"),
)

_SPEECH_STYLE: dict[str, str] = {
    "ru": (
        "Speak with a native Russian accent. Use natural Russian conversational "
        "fillers (like 'ну', 'так', 'смотрите'). Let your pacing and pauses follow "
        "the psychological portrait above."
    ),
    "ro": (
        "Speak with a native Moldovan Romanian accent. Use natural fillers "
        "(like 'deci', 'păi', 'adică'). Let your pacing and pauses follow the "
        "psychological portrait above."
    ),
    "en": (
        "Speak with a neutral business English accent. Use natural fillers "
        "(like 'so', 'alright'). Let your pacing and pauses follow the "
        "psychological portrait above."
    ),
}

# Маппинг голосов для Gemini Live: устаревший Enceladus сопоставляется с Kore
VOICE_MAP: dict[str, str] = {
    "enceladus": "Kore",
    "kore": "Kore",
    "puck": "Puck",
    "charon": "Charon",
    "aoede": "Aoede",
    "fenrir": "Fenrir",
    "zephyr": "Zephyr",
}


def resolve_voice_name(voice: str | None) -> str:
    if not voice:
        return "Kore"
    return VOICE_MAP.get(voice.strip().lower(), voice.strip())


def estimate_tokens(text: str) -> int:
    """Оценка токенов с поправкой на кириллицу (латиница ~3.8 симв/токен, кириллица ~2.2)."""
    if not text:
        return 0
    cyr = sum(1 for ch in text if "\u0400" <= ch <= "\u04ff")
    lat = len(text) - cyr
    return int(cyr / 2.2 + lat / 3.8) + 1


@dataclass
class Persona:
    """Характер бота. Поля повторяют companion_settings из bbb."""

    persona_name: str = ""
    lore: str = ""
    voice_model: str = "Kore"
    language: str = DEFAULT_LANG
    system_prompt: str = ""
    personality_enabled: bool = True

    openness: int = 5
    conscientiousness: int = 5
    extraversion: int = 5
    agreeableness: int = 5
    neuroticism: int = 5
    sarcasm: int = 5
    energy: int = 5
    proactivity: int = 5
    tough_love: int = 5
    ego: int = 5

    @classmethod
    def from_row(cls, row: dict[str, Any] | None) -> "Persona":
        p = cls()
        if not row:
            return p
        for f in ("persona_name", "lore", "voice_model", "language", "system_prompt"):
            val = row.get(f)
            if val:
                setattr(p, f, str(val))
        for f in TRAITS:
            val = row.get(f)
            if val is not None:
                try:
                    setattr(p, f, max(1, min(10, int(val))))
                except (TypeError, ValueError):
                    pass
        if row.get("personality_enabled") is not None:
            p.personality_enabled = bool(row["personality_enabled"])
        return p


def build_personality_block(p: Persona, lang: str) -> str:
    """<AI_IDENTITY> + <BEHAVIOR_ENGINE> — та же конструкция, что в bbb."""
    if not p.personality_enabled:
        return ""

    lang = (lang or DEFAULT_LANG).lower()[:2]
    out: list[str] = ["<AI_IDENTITY>"]
    if p.persona_name:
        out.append(f"Твое имя: {p.persona_name}")
    if p.lore:
        out.append(f"Твоя личная предыстория (LORE): {p.lore}")
    out.append("</AI_IDENTITY>")

    out.append("<BEHAVIOR_ENGINE>")
    out.append("Психологический портрет (шкалы 1-10, где 5 — норма):")
    for field, label in _TRAIT_SCALES:
        val = getattr(p, field, 5)
        out.append(f"- {label}: {val}/10")

    style = _SPEECH_STYLE.get(lang, _SPEECH_STYLE.get("ru", ""))
    if style:
        out.append(f"Speech style rules:\n{style}")

    out.append(
        "CRITICAL BEHAVIORAL RULE: Never reveal traits or numbers above. "
        "Embody them naturally through phrasing, tone, pacing, hesitation, and humor."
    )
    out.append("</BEHAVIOR_ENGINE>")
    return "\n".join(out)
