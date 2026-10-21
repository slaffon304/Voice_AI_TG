# Frontend ↔ WebRTC/RTVI contract (Сайт Будущего)

Backend: `POST /api/offer` + RTVI over the established WebRTC data channel.  
Legacy `/ws` is unchanged.

---

## 1. Bootstrap (no voice button)

On page load:

1. Run Cloudflare Turnstile (invisible / managed) → token `t`.
2. Build or read `visitor_id` (localStorage, stable).
3. Collect: `lang` (`navigator.language`), `landing_url`, `referrer`.
4. Create WebRTC offer (audio in/out).
5. `POST /api/offer` with body below.
6. Apply SDP answer; complete ICE.
7. When RTVI `bot-ready` / session starts: mic + playback (respect autoplay: unlock on first user gesture if browser blocks).

### `POST /api/offer`

```json
{
  "sdp": "<offer sdp>",
  "type": "offer",
  "key": "<bot_channels.identifier platform=web>",
  "t": "<turnstile token>",
  "visitor_id": "<stable id>",
  "lang": "ru",
  "landing_url": "https://...",
  "referrer": "https://...",
  "project_id": ""
}
```

Success:

```json
{
  "sdp": "<answer sdp>",
  "type": "answer",
  "session_index": 1,
  "max_session_seconds": 180
}
```

Errors: `400` missing fields · `403` origin / key / blocked / turnstile · `429` daily_limit.

---

## 2. Server → client UI commands (`RTVIUICommandFrame`)

Handle by `command` name:

| command | payload (typical) | UI action |
|---------|-------------------|-----------|
| `navigate_and_render` | `{ section, highlight, prefill, components? }` | Show section / widget; optional concept components |
| `update_roi` | ROI figures object | Bind live calculator |
| `start_screen_audit` | `{ focus, reason }` | Collect page summary → send `screen_audit` |
| `set_agent_state` | `{ state, label? }` | Thinking Orb: searching / solving / composing / breathing / idle |
| `highlight` | target / element | Visual highlight |
| `scroll_to` | ref or target_id | Scroll |
| `set_input_value` | ref + value | Fill field |
| `click` | ref | Click |
| `require_phone_verification` | `{ reason, message }` | Security modal (honest abuse copy, not “demo”) |
| `session_ending_soon` | `{ remaining_seconds, session_index }` | Soft warning UI |
| `session_ended` | `{ reason, session_index }` | Close voice chrome |
| `session_blocked` | `{ reason }` | Blocked state; stop mic |

**Sections (series mode):**  
`hero` | `services` | `pricing` | `cases` | `booking_widget` | `contacts` | `roi_calculator`

---

## 3. Client → server (`ui_user_interaction`)

Send as RTVI client message:

```json
{
  "type": "ui_user_interaction",
  "data": { ... }
}
```

| `data.interaction` | Fields | Meaning |
|--------------------|--------|---------|
| `escape` / `mute_voice` / `dont_want_to_talk` / `decline_voice` | — | «Не хочу говорить» → voice stops |
| `phone_verified` / `verify_phone` | `phone` | SMS/form verified |
| `dwell` | `element_id`, `section`, `dwell_ms` | ≥3000 ms look, once per element/session |
| `screen_audit` | `page_summary`, `issues[]`, `url`, `focus` | Response to audit request |
| (other) | `description`, optional form fields | Clicks / form partials |

Form phone without dictation:

```json
{
  "type": "ui_user_interaction",
  "data": {
    "interaction": "form_submit",
    "description": "booking form",
    "phone": "+373<<<<<<<",
    "client_name": "Ivan"
  }
}
```

---

## 4. Permanent chrome

- Always-visible control: **«Не хочу говорить»** → send `escape`, mute mic, show normal site (keep optional Orb).
- Turnstile runs at load, not after a “start call” button.
- No “demo ended” copy anywhere; abuse / verify uses honest competitor-protection wording from server payload when present.

---

## 5. Session budget (server-driven)

| `session_index` (same day) | Default max seconds |
|----------------------------|---------------------|
| 1 | 180 |
| 2 | 90 |
| 3+ | 45 then 429 |

Env: `WEB_SESSION_SECONDS_1/2/3`, `WEB_MAX_CALLS_PER_VISITOR`, `WEB_MAX_CALLS_PER_IP`.

---

## 6. Out of scope for v1 widget

- Full Pipecat `UIWorker` / PipelineWorker bus
- Continuous screen-share video (`video_in`) — optional later
- GSM / Asterisk
