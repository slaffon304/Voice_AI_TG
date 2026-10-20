"""Shared Core Transcript: clean dialogue extraction from LLM context messages."""

from __future__ import annotations

from typing import Any


def build_transcript(messages: list[dict[str, Any]]) -> tuple[str, int]:
    """Транскрипт без служебных вставок.

    Возвращает (текст, число реплик клиента).

    Отфильтровывает SYSTEM EVENT / SYSTEM COMMAND / SYSTEM UI EVENT / SYSTEM:,
    чтобы в CRM и архивариус попадали только реальные реплики диалога.
    """
    markers = ("SYSTEM EVENT:", "SYSTEM COMMAND:", "SYSTEM UI EVENT", "SYSTEM:")
    lines: list[str] = []
    user_replies = 0
    for msg in messages:
        role = msg.get("role")
        if role not in ("user", "assistant"):
            continue
        content = msg.get("content")
        if isinstance(content, list):
            content = " ".join(
                p.get("text", "") for p in content if isinstance(p, dict)
            )
        content = (content or "").strip()
        if not content or any(m in content for m in markers):
            continue
        if role == "user":
            user_replies += 1
        lines.append(f"{'Client' if role == 'user' else 'AI'}: {content}")
    return "\n".join(lines), user_replies
