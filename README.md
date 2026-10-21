# Voice_AI_TG

Голосовой агент LabUpgrade: **GSM (Asterisk)** + **web (WebRTC / RTVI)** на Pipecat и Gemini Live.

| Контур | Транспорт | Назначение |
|--------|-----------|------------|
| Legacy | Asterisk AudioSocket, `/ws` | Телефония, старый web-виджет |
| Сайт Будущего | `POST /api/offer` → WebRTC + RTVI | Голос на сайте, Generative UI |

Оба контура делят **Shared Core** (`core/`). Менять Legacy только при явной необходимости.

---

## Структура

```
main.py                 # FastAPI: GSM, /ws, health; подключает webrtc router
core/                   # БД, audio, persona, tools, prompt, protection, archivist…
transports/webrtc_rtvi.py   # Изолированный WebRTC + RTVI (не трогает GSM)
docs/FRONTEND_RTVI_CONTRACT.md
widget/widget_skeleton.js
Dockerfile
requirements.txt
```

---

## Быстрый старт

1. Заполнить env (минимум):

   | Переменная | Назначение |
   |------------|------------|
   | `GEMINI_API_KEY` | Gemini Live |
   | `SUPABASE_URL` / `SUPABASE_KEY` | Клиенты, каналы, blocklist |
   | `REDIS_URL` | Лимиты web-сессий |
   | `N8N_BASE_URL` / `N8N_WEBHOOK_SECRET` | CRM, booking, SMS |
   | `TURNSTILE_SECRET_KEY` | Cloudflare (опционально per-channel) |
   | `CORS_ORIGINS` | Разрешённые origin |

2. Сборка и запуск:

```bash
docker build -t voice-ai-tg .
docker run --env-file .env -p 8000:8000 -p 8085:8085 voice-ai-tg
```

Или локально: `uvicorn main:app --host 0.0.0.0 --port 8000`.

3. Проверка: `GET /health`.

AudioSocket (Asterisk) слушает порт **8085** (см. `Dockerfile` / env).

---

## HTTP / realtime

| Метод | Путь | Кто |
|-------|------|-----|
| WebSocket | `/ws` | Legacy web voice |
| POST | `/api/offer` | WebRTC SDP offer → answer |
| GET | `/health` | Liveness |
| GET | `/widget/config` | Ключ виджета / Turnstile site key |

### WebRTC offer (кратко)

Тело: `sdp`, `type`, `key` (виджет из `bot_channels`, platform=web), `t` (Turnstile), `visitor_id`, опционально `lang`, `landing_url`, `referrer`.

Ответ: `sdp`, `type`, `session_index`, `max_session_seconds`.

Защита: origin, blacklist, Turnstile, суточный budget (прогрессивная длина сессии).

Полный UI-контракт: **[docs/FRONTEND_RTVI_CONTRACT.md](docs/FRONTEND_RTVI_CONTRACT.md)**.

---

## Фазы (ориентир)

| Фаза | Статус | Содержание |
|------|--------|------------|
| 1 Shared Core | Сделано | `core/`, Legacy на импортах |
| 2 WebRTC + RTVI | Бэкенд готов | `/api/offer`, tools, UI frames |
| 3 GenUI-механики | Контракты на бэкенде | Анти-диктовка, dwell, ROI, audit, morph, abuse, soft deadline |
| 4 Виджет + evals | В работе | Фронт по контракту, тесты, чистка дублей в `main.py` |

Оценки «% готовности» без E2E-фронта условны: **серверные контракты ≠ готовый продукт на сайте**.

---

## Правила разработки

1. **Не ломать GSM / `/ws`** ради web-фич. Новый контур — в `transports/`.
2. Общая логика — только в `core/`. Избегать копипаста в `main.py` (там ещё есть legacy-дубли; вычищать осторожно).
3. Web-промпт: UI-first, без простыней прайсов в сокете (`core/prompt.py`).
4. Тексты пользователю: без «демо закончилось»; абьюз — честно (конкуренты / лимиты).
5. После заметных изменений — коротко дописать этот README и контракт фронта.

---

## Связанные документы

- `docs/FRONTEND_RTVI_CONTRACT.md` — команды RTVI и события UI  
- `widget/widget_skeleton.js` — каркас auto-connect / escape  
- Исследование «Сайт Будущего» и implementation plan — вне репо / в `.aistudio` при наличии  

---

## Лицензия / доступ

Приватный репозиторий LabUpgrade. Не публиковать ключи и `.env`.
