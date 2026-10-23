/**
 * LabUpgrade Voice Widget — Series & Adaptive Workspace Engine
 * POST /api/offer (WebRTC + RTVI).
 *
 * Modes (via data-mode attribute on #labupgrade-voice-widget):
 *   - "workspace" (default, Mode B): Isolated Shadow DOM Adaptive Workspace over dimmed site.
 *   - "navigator" (Mode A): Native DOM spotlight + smooth scroll; Workspace only for ROI, Booking & missing sections.
 *
 * Embed:
 *   <div id="labupgrade-voice-widget"
 *        data-key="YOUR_WEB_CHANNEL_KEY"
 *        data-server="voice.labupgrade.in"
 *        data-mode="workspace"></div>
 *   <script src="https://voice.labupgrade.in/widget-genui.js" defer></script>
 */
(function () {
  "use strict";

  var container =
    document.getElementById("labupgrade-voice-widget") ||
    document.getElementById("labupgrade-widget");
  if (!container) return;

  var widgetKey = (container.getAttribute("data-key") || "").trim();
  if (!widgetKey) {
    console.error("[LU GenUI] missing data-key");
    return;
  }

  var uiMode = (container.getAttribute("data-mode") || "workspace")
    .trim()
    .toLowerCase();

  var serverAttr = (container.getAttribute("data-server") || "")
    .trim()
    .toLowerCase()
    .replace(/^(https?|wss?):\/\//, "")
    .replace(/[/?#].*$/, "");
  var voiceServer = /^[a-z0-9-]+(\.[a-z0-9-]+)+$/.test(serverAttr)
    ? serverAttr
    : "voice.labupgrade.in";
  var apiBase = "https://" + voiceServer;

  var DEFAULT_ICE = [{ urls: "stun:stun.l.google.com:19302" }];

  var visitorId = "";
  try {
    visitorId = localStorage.getItem("lu_visitor_id") || "";
    if (!visitorId) {
      visitorId =
        window.crypto && crypto.randomUUID
          ? crypto.randomUUID()
          : "v" +
            Date.now().toString(36) +
            Math.random().toString(36).slice(2, 12);
      localStorage.setItem("lu_visitor_id", visitorId);
    }
  } catch (e) {
    visitorId = "v" + Date.now().toString(36);
  }

  var lang = (
    container.getAttribute("data-lang") ||
    document.documentElement.lang ||
    navigator.language ||
    "en"
  )
    .toLowerCase()
    .slice(0, 8);

  function pageLocale() {
    var l = (
      container.getAttribute("data-lang") ||
      document.documentElement.getAttribute("lang") ||
      navigator.language ||
      "en"
    ).toLowerCase();
    if (l.indexOf("ro") === 0) return "ro";
    if (l.indexOf("ru") === 0) return "ru";
    return "en";
  }

  var I18N = {
    ru: {
      escape: "Не хочу говорить",
      tapToStart: "Нажмите, чтобы включить голос",
      minimize: "Свернуть к сайту",
      openWorkspace: "Открыть панель",
      section_hero: "О компании",
      section_services: "Услуги и решения",
      section_pricing: "Тарифы и форматы",
      section_cases: "Кейсы и результаты",
      section_roi_calculator: "Расчёт окупаемости (ROI)",
      section_booking_widget: "Запись и контакт",
      section_contacts: "Контакты",
      roiKicker: "Живой расчёт",
      roiTitle: "Сколько вы теряете на упущенных обращениях",
      roiSub: "Назовите ваши цифры голосом или подвиньте ползунки — я пересчитаю выгоду на лету.",
      roiMissed: "Упущенных обращений в месяц",
      roiLeadCost: "Средняя ценность лида (€/$)",
      roiCapture: "Доля возврата ИИ-агентом",
      roiRecovered: "Спасённых лидов в месяц",
      roiAiCost: "Стоимость ИИ в месяц",
      roiNet: "Чистая выгода в месяц",
      roiPayback: "Окупаемость",
      roiDays: "дн.",
      roiCta: "Зафиксировать расчёт и обсудить внедрение",
      bookKicker: "Без диктовки по буквам",
      bookTitle: "Оставьте контакт для подтверждения",
      bookSub: "Впишите номер на экране — я сразу закреплю за вами время или пришлю материалы.",
      bookName: "Ваше имя",
      bookNamePh: "Например, Александр",
      bookPhone: "Номер телефона *",
      bookPhonePh: "+373 ...",
      bookSlot: "Желаемое время / задача",
      bookSlotPh: "Например: завтра в 11:00, интеграция с CRM",
      bookSubmit: "Подтвердить на экране",
      bookSent: "Готово! Передаю данные ассистенту…",
      verifyTitle: "Подтверждение доступа",
      verifyDefault: "Подтвердите номер на экране, чтобы продолжить консультацию.",
      verifyBtn: "Подтвердить",
      endingSoon: "Сессия завершится через ~{sec} с",
      selectItem: "Обсудить этот вариант",
      recommended: "Рекомендуем под вашу задачу",
      checkTitle: "Проверка безопасности",
      verifyText: "Из-за недобросовестных посетителей мы подтверждаем номер. Это займёт несколько секунд.",
      verifyPhoneLabel: "Ваш номер телефона",
      verifyGetCode: "Получить код по SMS",
      verifyCodeLabel: "Код из SMS",
      verifyConfirm: "Подтвердить",
      verifyChange: "Изменить номер",
      verifyResend: "Отправить код ещё раз",
      vs_code_sent: "Код отправлен на {phone}",
      vs_bad_phone: "Нужен молдавский номер: +373 …",
      vs_bad_code: "Неверный код. Осталось попыток: {n}",
      vs_expired: "Код устарел — запросите новый",
      vs_limit: "Лимит SMS на сегодня исчерпан",
      vs_sms_failed: "SMS не отправилось, попробуйте ещё раз",
      vs_wait: "Повторно можно через {sec} с",
      vs_verified: "Номер подтверждён",
      micPaused: "Микрофон на паузе — подтвердите номер",
      bookCheckTitle: "Проверьте запись",
      bookCheckSub: "Если всё верно — подтвердите на экране или скажите «да».",
      bookPhoneRo: "Телефон",
      bookTime: "Дата и время",
      bookNote: "Задача",
      bookAskTime: "Назовите голосом удобные день и время — я проверю календарь.",
      bookConfirmBtn: "Подтвердить запись",
      bookConfirmed: "Отправлено, подтверждаю запись…",
      cancel: "Отмена",
    },
    ro: {
      escape: "Nu vreau să vorbesc",
      tapToStart: "Apăsați pentru a activa vocea",
      minimize: "Înapoi la site",
      openWorkspace: "Deschide panoul",
      section_hero: "Despre companie",
      section_services: "Servicii și soluții",
      section_pricing: "Pachete și prețuri",
      section_cases: "Studii de caz",
      section_roi_calculator: "Calculator ROI (Economie)",
      section_booking_widget: "Programare rapidă",
      section_contacts: "Contacte",
      roiKicker: "Calcul în timp real",
      roiTitle: "Cât pierdeți din apelurile și mesajele ratate",
      roiSub: "Spuneți cifrele cu voce tare sau ajustați mai jos — recalculez imediat pe ecran.",
      roiMissed: "Solicitări pierdute / lună",
      roiLeadCost: "Valoarea medie a unui lead (€/$)",
      roiCapture: "Rata de recuperare prin AI",
      roiRecovered: "Lead-uri recuperate / lună",
      roiAiCost: "Cost lunar AI",
      roiNet: "Câștig net lunar",
      roiPayback: "Recuperare investiție",
      roiDays: "zile",
      roiCta: "Salvează calculul și programează o discuție",
      bookKicker: "Fără dictare pe cifre",
      bookTitle: "Confirmați datele pe ecran",
      bookSub: "Introduceți numărul mai jos — rezerv imediat intervalul în calendar.",
      bookName: "Numele dvs.",
      bookNamePh: "Ex: Alexandru",
      bookPhone: "Număr de telefon *",
      bookPhonePh: "+373 ...",
      bookSlot: "Intervalul dorit / detalii",
      bookSlotPh: "Ex: mâine la 11:00, automatizare CRM",
      bookSubmit: "Confirmă pe ecran",
      bookSent: "Trimis! Continuați conversația…",
      verifyTitle: "Verificare acces",
      verifyDefault: "Confirmați numărul pe ecran pentru a continua.",
      verifyBtn: "Confirmă",
      endingSoon: "Sesiunea se încheie în ~{sec} s",
      selectItem: "Discută această opțiune",
      recommended: "Recomandat pentru dvs.",
      checkTitle: "Verificare",
      verifyText: "Din cauza vizitatorilor rău intenționați confirmăm numărul. Durează câteva secunde.",
      verifyPhoneLabel: "Numărul dvs. de telefon",
      verifyGetCode: "Primește codul prin SMS",
      verifyCodeLabel: "Codul din SMS",
      verifyConfirm: "Confirmă",
      verifyChange: "Schimbă numărul",
      verifyResend: "Retrimite codul",
      vs_code_sent: "Codul a fost trimis la {phone}",
      vs_bad_phone: "Este nevoie de un număr din Moldova: +373 …",
      vs_bad_code: "Cod greșit. Încercări rămase: {n}",
      vs_expired: "Codul a expirat — cereți unul nou",
      vs_limit: "Limita de SMS pentru azi a fost atinsă",
      vs_sms_failed: "SMS-ul nu a plecat, încercați din nou",
      vs_wait: "Puteți retrimite peste {sec} s",
      vs_verified: "Număr confirmat",
      micPaused: "Microfonul e în pauză — confirmați numărul",
      bookCheckTitle: "Verificați programarea",
      bookCheckSub: "Dacă totul este corect — confirmați pe ecran sau spuneți «da».",
      bookPhoneRo: "Telefon",
      bookTime: "Data și ora",
      bookNote: "Detalii",
      bookAskTime: "Spuneți cu voce ziua și ora dorite — verific calendarul.",
      bookConfirmBtn: "Confirmă programarea",
      bookConfirmed: "Trimis, confirm programarea…",
      cancel: "Anulează",
    },
    en: {
      escape: "I don't want to talk",
      tapToStart: "Tap to enable voice",
      minimize: "Back to website",
      openWorkspace: "Open workspace",
      section_hero: "Overview",
      section_services: "Services & Solutions",
      section_pricing: "Pricing & Plans",
      section_cases: "Case Studies",
      section_roi_calculator: "Live ROI Calculator",
      section_booking_widget: "Book & Confirm",
      section_contacts: "Contacts",
      roiKicker: "Live estimate",
      roiTitle: "What you may be leaving on the table",
      roiSub: "Say your numbers aloud or adjust the sliders — I recalculate live.",
      roiMissed: "Missed inquiries / month",
      roiLeadCost: "Assumed value per lead (€/$)",
      roiCapture: "AI capture rate",
      roiRecovered: "Recovered leads / month",
      roiAiCost: "Monthly AI cost",
      roiNet: "Net monthly impact",
      roiPayback: "Payback period",
      roiDays: "days",
      roiCta: "Lock estimate & book a slot",
      bookKicker: "No phone dictation needed",
      bookTitle: "Confirm your contact on screen",
      bookSub: "Type your phone below — I will lock the calendar slot right away.",
      bookName: "Your name",
      bookNamePh: "e.g. Alex",
      bookPhone: "Phone number *",
      bookPhonePh: "+373 ...",
      bookSlot: "Preferred time / note",
      bookSlotPh: "e.g. tomorrow 11:00, CRM integration",
      bookSubmit: "Confirm on screen",
      bookSent: "Confirmed! Sending to assistant…",
      verifyTitle: "Security check",
      verifyDefault: "Please confirm your phone on screen to continue.",
      verifyBtn: "Confirm",
      endingSoon: "Session ends in ~{sec}s",
      selectItem: "Select this option",
      recommended: "Recommended for you",
      checkTitle: "Check",
      verifyText: "Because of bad-faith visitors we confirm the phone number. It takes a few seconds.",
      verifyPhoneLabel: "Your phone number",
      verifyGetCode: "Get SMS code",
      verifyCodeLabel: "Code from SMS",
      verifyConfirm: "Confirm",
      verifyChange: "Change number",
      verifyResend: "Send the code again",
      vs_code_sent: "Code sent to {phone}",
      vs_bad_phone: "A Moldovan number is required: +373 …",
      vs_bad_code: "Wrong code. Attempts left: {n}",
      vs_expired: "The code expired — request a new one",
      vs_limit: "SMS limit for today reached",
      vs_sms_failed: "SMS was not sent, please try again",
      vs_wait: "You can resend in {sec}s",
      vs_verified: "Number confirmed",
      micPaused: "Microphone paused — confirm your number",
      bookCheckTitle: "Check your booking",
      bookCheckSub: "If everything is right — confirm on screen or say “yes”.",
      bookPhoneRo: "Phone",
      bookTime: "Date and time",
      bookNote: "Details",
      bookAskTime: "Say the day and time that suit you — I will check the calendar.",
      bookConfirmBtn: "Confirm booking",
      bookConfirmed: "Sent, confirming your booking…",
      cancel: "Cancel",
    },
  };

  function t(key) {
    var loc = pageLocale();
    var dict = I18N[loc] || I18N.en;
    return dict[key] || I18N.en[key] || key;
  }

  var state = {
    turnstileSiteKey: "",
    iceServers: DEFAULT_ICE,
    voiceEnabled: true,
    pc: null,
    localStream: null,
    remoteAudio: null,
    dc: null,
    connecting: false,
    connected: false,
    escaped: false,
    agentState: "idle",
    agentLabel: "",
    activeSection: "services",
    activeHighlight: null,
    activePrefill: {},
    workspaceOpen: false,
    dwellSeen: {},
    dwellTimers: {},
    sectionMap: {},
    catalog: null,
    lastRoi: {
      missed_calls_per_month: 120,
      cost_per_missed_lead: 50,
      ai_monthly_cost: 299,
      capture_rate: 0.35,
      recovered_leads_per_month: 42,
      net_monthly_savings: 1801,
      payback_days: 4.3,
    },
    theme: {
      fontSans: "system-ui, -apple-system, sans-serif",
      fontDisplay: "system-ui, -apple-system, sans-serif",
      accent: "#10b981",
      isDark: true,
    },
  };

  function $(id) {
    return document.getElementById(id);
  }

  function qs(sel, root) {
    try {
      return (root || document).querySelector(sel);
    } catch (e) {
      return null;
    }
  }

  function escapeHtml(str) {
    return String(str == null ? "" : str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // —— 1. Host Theme Extraction ——
  function _rgbLum(rgb) {
    try {
      var m = String(rgb || "").match(/(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
      if (!m) return 0.5;
      var r = +m[1] / 255, g = +m[2] / 255, b = +m[3] / 255;
      return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    } catch (e) {
      return 0.5;
    }
  }

  function extractHostTheme() {
    try {
      var bodyStyle = window.getComputedStyle(document.body);
      if (bodyStyle && bodyStyle.fontFamily) {
        state.theme.fontSans = bodyStyle.fontFamily;
      }
      /* Prefer readable body/section text — not hero H1 (often white on gradient) */
      var textSrc =
        qs("#services p, #pricing p, section.section-pad p, main p") ||
        document.body;
      var ts = window.getComputedStyle(textSrc);
      if (ts && ts.color) state.theme.text = ts.color;
      var headSrc = qs("#services h2, #pricing h2, section.section-pad h2, h2") || qs("h1");
      if (headSrc) {
        var hs = window.getComputedStyle(headSrc);
        if (hs.fontFamily) state.theme.fontDisplay = hs.fontFamily;
        if (hs.color) state.theme.heading = hs.color;
      }
      if (!state.theme.heading) state.theme.heading = state.theme.text;
      var surfaceSrc = qs("#services, section.section-pad, main") || document.body;
      var ss = window.getComputedStyle(surfaceSrc);
      if (ss && ss.backgroundColor && ss.backgroundColor !== "rgba(0, 0, 0, 0)" && ss.backgroundColor !== "transparent") {
        state.theme.surface = ss.backgroundColor;
      }
      /* If text still too light (hero leak), force readable dark/light by luminance */
      var lum = _rgbLum(state.theme.text);
      if (lum > 0.72) {
        state.theme.text = "rgb(15, 23, 42)";
        state.theme.heading = "rgb(15, 23, 42)";
      } else if (lum < 0.18 && _rgbLum(state.theme.surface || "rgb(255,255,255)") > 0.7) {
        state.theme.text = "rgb(15, 23, 42)";
        state.theme.heading = "rgb(15, 23, 42)";
      }
      var cta = qs("a.pill, a.btn, a.button, button[type='submit'], [class*='cta']");
      if (cta) {
        var bg = window.getComputedStyle(cta).backgroundColor;
        if (bg && bg !== "rgba(0, 0, 0, 0)" && bg !== "transparent") {
          state.theme.accent = bg;
        }
      }
    } catch (e) {}
  }

  // —— 2. Section Map & DOM Catalog Extraction ——
  var SECTION_KEYS = [
    "hero",
    "services",
    "pricing",
    "cases",
    "booking_widget",
    "contacts",
    "roi_calculator",
  ];

  var SECTION_HINTS = {
    hero: ["hero", "banner", "intro", "главн", "bun venit", "welcome"],
    services: [
      "services",
      "servicii",
      "услуги",
      "solutions",
      "soluții",
      "what we do",
      "ce facem",
      "направления",
    ],
    pricing: [
      "pricing",
      "prices",
      "price",
      "тариф",
      "цен",
      "preț",
      "pret",
      "plans",
      "pachete",
      "пакет",
      "стоимость",
    ],
    cases: [
      "cases",
      "case study",
      "portfolio",
      "проекты",
      "кейсы",
      "lucrări",
      "clients",
      "rezultate",
      "отзывы",
    ],
    booking_widget: [
      "booking",
      "book",
      "schedule",
      "calendar",
      "programare",
      "запис",
      "appointment",
      "заявк",
    ],
    contacts: [
      "contact",
      "contacts",
      "контакт",
      "reach us",
      "scrie-ne",
      "get in touch",
    ],
    roi_calculator: ["roi", "calculator", "окупаем", "econom", "savings"],
  };

  function scoreText(hay, hints) {
    hay = (hay || "").toLowerCase();
    var s = 0;
    for (var i = 0; i < hints.length; i++) {
      if (hay.indexOf(hints[i]) !== -1) s += hints[i].length > 4 ? 3 : 2;
    }
    return s;
  }

  function nearestSectionRoot(el) {
    var cur = el;
    for (var i = 0; i < 8 && cur && cur !== document.body; i++) {
      if (
        cur.matches &&
        cur.matches(
          "section,article,[data-section],[data-lu-section],.section,.t-section,main > div"
        )
      ) {
        return cur;
      }
      cur = cur.parentElement;
    }
    return el;
  }

  function scanPageSections() {
    var map = {};
    document.querySelectorAll("[data-lu-section]").forEach(function (el) {
      var key = (el.getAttribute("data-lu-section") || "").trim().toLowerCase();
      if (SECTION_KEYS.indexOf(key) !== -1) map[key] = el;
    });
    document.querySelectorAll("[data-section]").forEach(function (el) {
      var key = (el.getAttribute("data-section") || "").trim().toLowerCase();
      if (SECTION_KEYS.indexOf(key) !== -1 && !map[key]) map[key] = el;
    });
    SECTION_KEYS.forEach(function (key) {
      if (map[key]) return;
      var byId =
        document.getElementById(key) ||
        document.getElementById("section-" + key);
      if (byId) map[key] = nearestSectionRoot(byId);
    });
    if (!map.contacts && document.getElementById("contact")) {
      map.contacts = nearestSectionRoot(document.getElementById("contact"));
    }
    if (!map.hero && document.getElementById("top")) {
      map.hero = nearestSectionRoot(document.getElementById("top"));
    }
    if (!map.booking_widget && document.getElementById("contactForm")) {
      map.booking_widget = nearestSectionRoot(
        document.getElementById("contactForm")
      );
    }

    var heads = document.querySelectorAll("h1,h2,h3,.t-title,.t-sectiontitle");
    var best = {};
    heads.forEach(function (h) {
      var text = (h.textContent || "").trim();
      if (text.length < 2 || text.length > 80) return;
      SECTION_KEYS.forEach(function (key) {
        if (map[key]) return;
        var sc = scoreText(text, SECTION_HINTS[key] || []);
        if (sc <= 0) return;
        if (!best[key] || sc > best[key].score) {
          best[key] = { score: sc, el: nearestSectionRoot(h) };
        }
      });
    });
    Object.keys(best).forEach(function (key) {
      if (!map[key] && best[key].score >= 2) map[key] = best[key].el;
    });

    if (!map.booking_widget) {
      var form =
        document.querySelector("form[data-lu-section='booking_widget']") ||
        document.querySelector("form input[type='tel']") ||
        document.querySelector("form input[name*='phone' i]");
      if (form)
        map.booking_widget = nearestSectionRoot(form.closest("form") || form);
    }
    if (!map.contacts) {
      var mail = document.querySelector("a[href^='mailto:']");
      if (mail) map.contacts = nearestSectionRoot(mail);
    }

    state.sectionMap = map;
    return map;
  }

  function extractCardsFromSection(rootEl, fallbackItems) {
    if (!rootEl) return fallbackItems || [];
    var items = [];
    var seen = {};
    var headings = rootEl.querySelectorAll("h3, h4, .card-title, [class*='title']");
    headings.forEach(function (h) {
      if (items.length >= 6) return;
      var title = (h.textContent || "").replace(/\s+/g, " ").trim();
      if (title.length < 3 || title.length > 75 || seen[title]) return;
      var card =
        h.closest("article, .card, [class*='card'], [class*='item'], [class*='col'], li, div") ||
        h.parentElement;
      if (!card || card === rootEl) return;
      var p = card.querySelector("p, .desc, [class*='desc'], [class*='text'], ul");
      var desc = p ? (p.textContent || "").replace(/\s+/g, " ").trim().slice(0, 160) : "";
      var priceEl = card.querySelector("[class*='price'], [class*='cost'], strong");
      var badge = priceEl && priceEl !== h ? (priceEl.textContent || "").trim().slice(0, 32) : "";
      if (desc || badge) {
        seen[title] = 1;
        items.push({
          id: card.id || card.getAttribute("data-id") || "item-" + (items.length + 1),
          title: title,
          description: desc,
          badge: badge,
        });
      }
    });
    return items.length >= 2 ? items : (fallbackItems || []);
  }

  function getDefaultCatalog() {
    var loc = pageLocale();
    if (loc === "ro") {
      return {
        services: [
          {
            id: "voice-ai",
            title: "Agenți vocali AI 24/7",
            description:
              "Preluare apeluri GSM și consultare pe site în timp real — fără coadă, cu rezumat după fiecare conversație.",
            badge: "Live",
          },
          {
            id: "chat-omni",
            title: "Chat & Call Center AI",
            description:
              "Vânzări, suport și programări pe site, Telegram, WhatsApp — memorie unică a clientului.",
            badge: "Omnichannel",
          },
          {
            id: "crm-suite",
            title: "CRM / ERP / MIS unificat",
            description:
              "Un sistem inteligent care adună vânzările, contabilitatea și managementul într-un singur flux.",
            badge: "Platformă",
          },
        ],
        pricing: [
          {
            id: "pilot",
            title: "Pilot rapid",
            description:
              "Un canal (voce sau chat), calificare lead-uri, notificări în Telegram — lansare în zile, nu luni.",
            badge: "Start",
          },
          {
            id: "growth",
            title: "Growth",
            description:
              "Voce + chat, calendar, CRM, înregistrare și sumarizare — flux complet de vânzări.",
            badge: "Recomandat",
          },
          {
            id: "enterprise",
            title: "Enterprise",
            description:
              "Omnichannel, integrări personalizate, SLA și agent digital sub brandul companiei.",
            badge: "Scale",
          },
        ],
        cases: [
          {
            id: "missed-calls",
            title: "0 apeluri ratate",
            description:
              "Producție și servicii: agentul preia lead-urile noaptea și în weekend, managerul primește rezumatul dimineața.",
            badge: "Impact",
          },
          {
            id: "speed-to-lead",
            title: "Răspuns în secunde",
            description:
              "Mesajele din social și de pe site nu mai stau în coadă — calificare și programare pe loc.",
            badge: "Conversie",
          },
        ],
      };
    }
    if (loc === "ru") {
      return {
        services: [
          {
            id: "voice-ai",
            title: "Голосовые AI-агенты 24/7",
            description:
              "GSM и сайт: приём звонков и консультация посетителя в реальном времени, с записью и саммари для менеджера.",
            badge: "Live",
          },
          {
            id: "chat-omni",
            title: "Чат и AI Call Center",
            description:
              "Продажи, поддержка и запись на услуги на сайте и в мессенджерах — одна память о клиенте.",
            badge: "Omnichannel",
          },
          {
            id: "crm-suite",
            title: "CRM / ERP / MIS",
            description:
              "Единая система: продажи, учёт и процессы без разрозненных таблиц и потерянных заявок.",
            badge: "Платформа",
          },
        ],
        pricing: [
          {
            id: "pilot",
            title: "Пилот",
            description:
              "Один канал (голос или чат), квалификация лидов, уведомления в Telegram — запуск за дни.",
            badge: "Старт",
          },
          {
            id: "growth",
            title: "Growth",
            description:
              "Голос + чат, календарь, CRM, запись и суммаризация — полный цикл до встречи с менеджером.",
            badge: "Рекомендуем",
          },
          {
            id: "enterprise",
            title: "Enterprise",
            description:
              "Omnichannel, свои интеграции, SLA и цифровой сотрудник под брендом компании.",
            badge: "Масштаб",
          },
        ],
        cases: [
          {
            id: "missed-calls",
            title: "Ноль упущенных обращений",
            description:
              "Производство и сервис: агент забирает лиды ночью и в выходные, утром у менеджера уже саммари.",
            badge: "Эффект",
          },
          {
            id: "speed-to-lead",
            title: "Ответ за секунды",
            description:
              "Заявки с сайта и из соцсетей не копятся в очереди — квалификация и слот в календаре сразу.",
            badge: "Конверсия",
          },
        ],
      };
    }
    return {
      services: [
        {
          id: "voice-ai",
          title: "Voice AI agents 24/7",
          description:
            "GSM and website: live calls and on-site consults with recording and manager summaries.",
          badge: "Live",
        },
        {
          id: "chat-omni",
          title: "Chat & AI call center",
          description:
            "Sales, support and booking on the site and messengers — one memory per visitor.",
          badge: "Omnichannel",
        },
        {
          id: "crm-suite",
          title: "CRM / ERP / MIS",
          description:
            "One system for sales, ops and follow-up — fewer lost leads and spreadsheets.",
          badge: "Platform",
        },
      ],
      pricing: [
        {
          id: "pilot",
          title: "Pilot",
          description:
            "One channel (voice or chat), lead qualification, Telegram alerts — live in days.",
          badge: "Start",
        },
        {
          id: "growth",
          title: "Growth",
          description:
            "Voice + chat, calendar, CRM, recording and summaries — full path to a booked meeting.",
          badge: "Recommended",
        },
        {
          id: "enterprise",
          title: "Enterprise",
          description:
            "Omnichannel, custom integrations, SLA and a digital employee under your brand.",
          badge: "Scale",
        },
      ],
      cases: [
        {
          id: "missed-calls",
          title: "Zero missed inquiries",
          description:
            "After-hours and weekend demand captured; managers get a clean summary in the morning.",
          badge: "Impact",
        },
        {
          id: "speed-to-lead",
          title: "Reply in seconds",
          description:
            "Site and social leads qualified and booked without a human in the first response.",
          badge: "Conversion",
        },
      ],
    };
  }


  function buildCatalog() {
    /* Series Adaptive Workspace: ONLY ui_catalog from server (flow_config). No invented defaults, no DOM scrape. */
    var custom =
      (state.catalog && typeof state.catalog === "object" ? state.catalog : null) ||
      (window.LU_CATALOG && typeof window.LU_CATALOG === "object" ? window.LU_CATALOG : null) ||
      {};
    function pick(key) {
      return Array.isArray(custom[key]) ? custom[key] : [];
    }
    return {
      services: pick("services"),
      pricing: pick("pricing"),
      cases: pick("cases"),
    };
  }

  function findSection(section) {
    if (!section) return null;
    var key = String(section).trim().toLowerCase();
    var aliases = {
      contacts: ["contacts", "contact"],
      contact: ["contact", "contacts"],
      booking_widget: ["booking_widget", "booking", "contactForm", "contact"],
      hero: ["hero", "top"],
      roi_calculator: ["roi_calculator"],
    };
    var keys = aliases[key] || [key];
    for (var i = 0; i < keys.length; i++) {
      var k = keys[i];
      if (state.sectionMap && state.sectionMap[k]) return state.sectionMap[k];
    }
    for (var j = 0; j < keys.length; j++) {
      var k2 = keys[j];
      var el =
        document.querySelector('[data-lu-section="' + k2 + '"]') ||
        document.querySelector('[data-section="' + k2 + '"]') ||
        document.getElementById(k2) ||
        document.getElementById("section-" + k2);
      if (el) return el;
    }
    return null;
  }

  function findTarget(ref, targetId) {
    var id = targetId || ref;
    if (!id) return null;
    id = String(id).trim();
    return (
      document.getElementById(id) ||
      qs('[data-id="' + id + '"]') ||
      qs('[data-lu-ref="' + id + '"]') ||
      qs('[data-field="' + id + '"]') ||
      qs('[name="' + id + '"]')
    );
  }

  function flashHighlight(el, durationMs) {
    if (!el) return;
    var prev = el.style.outline;
    var prevOffset = el.style.outlineOffset;
    var prevTransition = el.style.transition;
    el.style.transition = "outline 0.25s ease, box-shadow 0.25s ease";
    el.style.outline = "3px solid #22d3ee";
    el.style.outlineOffset = "6px";
    setTimeout(function () {
      el.style.outline = prev;
      el.style.outlineOffset = prevOffset;
      el.style.transition = prevTransition;
    }, durationMs || 2400);
  }

  // —— 3. Isolated Adaptive Workspace (Shadow DOM) ——
  var _wsRoot = null;
  var _wsHost = null;

  function ensureWorkspace() {
    if (_wsRoot && document.getElementById("lu-ws-backdrop")) return _wsRoot;

    /* Design tokens from the host site stylesheet — not invented */
    var paper = "var(--paper, #f8f7f3)";
    var ink = "var(--ink, #0a0a0a)";
    var muted = "var(--muted, #747474)";
    var line = "var(--line, #deddd9)";
    var soft = "var(--soft, #eeede8)";
    var accent = "var(--accent, #ff6b55)";
    var font = "var(--font-sans, Urbanist, Arial, sans-serif)";

    if (!$("lu-ws-css")) {
      var style = document.createElement("style");
      style.id = "lu-ws-css";
      style.textContent = [
        "#lu-ws-backdrop{position:fixed;inset:0;z-index:99990;display:none;flex-direction:column;",
        "background:" + paper + ";color:" + ink + ";font-family:" + font + ";box-sizing:border-box}",
        "#lu-ws-backdrop.lu-open{display:flex}",
        "#lu-ws-backdrop .lu-stage{flex:1;min-height:0;width:100%;max-width:720px;margin:0 auto;",
        "padding:max(64px,env(safe-area-inset-top)) 20px 120px;overflow-y:auto;-webkit-overflow-scrolling:touch}",
        "#lu-ws-backdrop .lu-top{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:22px}",
        "#lu-ws-backdrop .lu-kicker{display:none}",
        "#lu-ws-backdrop .lu-scene-title{margin:0;font-weight:500;font-size:clamp(1.6rem,5vw,2.1rem);",
        "letter-spacing:-.04em;line-height:1.1;color:" + ink + "}",
        "#lu-ws-backdrop .lu-min-btn{border:0;background:transparent;color:" + muted + ";font:600 13px/1.2 " + font + ";",
        "cursor:pointer;padding:6px 0;opacity:.85}",
        "#lu-ws-backdrop .lu-tabs{display:none!important}",
        "#lu-ws-backdrop .lu-body{display:flex;flex-direction:column;gap:14px}",
        /* Catalog cards — same language as .service-card / .price-card on the site */
        "#lu-ws-backdrop .lu-acc{display:flex;flex-direction:column;gap:12px}",
        "#lu-ws-backdrop .lu-acc-item{",
        "border:1px solid " + line + ";border-radius:22px;background:#fff;overflow:hidden;",
        "transition:border-color .2s,box-shadow .2s}",
        "#lu-ws-backdrop .lu-acc-item.is-open{",
        "border-color:" + ink + ";box-shadow:0 12px 40px rgba(10,10,10,.06)}",
        "#lu-ws-backdrop .lu-acc-head{",
        "display:flex;align-items:center;gap:12px;width:100%;padding:16px 18px;border:0;",
        "background:transparent;color:" + ink + ";font:inherit;text-align:left;cursor:pointer}",
        "#lu-ws-backdrop .lu-acc-badge{",
        "flex-shrink:0;font:700 10px/1.2 " + font + ";letter-spacing:.08em;text-transform:uppercase;",
        "padding:6px 10px;border-radius:999px;background:" + soft + ";color:" + ink + "}",
        "#lu-ws-backdrop .lu-acc-item.is-open .lu-acc-badge{background:" + ink + ";color:#fff}",
        "#lu-ws-backdrop .lu-acc-title{",
        "flex:1;margin:0;font:650 1.05rem/1.25 " + font + ";letter-spacing:-.02em;color:" + ink + "}",
        "#lu-ws-backdrop .lu-acc-item:not(.is-open) .lu-acc-title{font-weight:600;opacity:.78}",
        "#lu-ws-backdrop .lu-acc-body{",
        "display:none;padding:0 18px 18px;font:400 15px/1.55 " + font + ";color:" + muted + "}",
        "#lu-ws-backdrop .lu-acc-item.is-open .lu-acc-body{display:block}",
        /* ROI / booking — same paper language */
        "#lu-ws-backdrop .lu-roi-grid,#lu-ws-backdrop .lu-form{display:grid;gap:12px}",
        "#lu-ws-backdrop .lu-control-group,#lu-ws-backdrop .lu-roi-out{",
        "padding:14px 16px;border:1px solid " + line + ";border-radius:16px;background:#fff}",
        "#lu-ws-backdrop .lu-control-head{display:flex;justify-content:space-between;gap:8px;margin-bottom:8px;",
        "font:600 13px/1.2 " + font + "}",
        "#lu-ws-backdrop input[type=range]{width:100%}",
        "#lu-ws-backdrop input[type=text],#lu-ws-backdrop input[type=tel]{",
        "width:100%;box-sizing:border-box;padding:12px 14px;border:1px solid " + line + ";",
        "border-radius:12px;background:#fff;color:" + ink + ";font:inherit}",
        "#lu-ws-backdrop .lu-primary{",
        "margin-top:8px;border:0;border-radius:999px;min-height:48px;padding:0 22px;",
        "font:650 15px/1 " + font + ";cursor:pointer;background:" + ink + ";color:#fff}",
        "#lu-ws-backdrop .lu-sub{color:" + muted + ";margin:0 0 12px;font-size:15px;line-height:1.5}",
        "#lu-ws-backdrop .lu-title{margin:0 0 8px;font:500 1.4rem/1.15 " + font + ";letter-spacing:-.03em}",
        "#lu-ws-backdrop .lu-field{display:flex;flex-direction:column;gap:6px}",
        "#lu-ws-backdrop .lu-field label{font:600 13px/1.2 " + font + ";color:" + muted + "}",
        "#lu-ws-backdrop .lu-book-row{display:flex;justify-content:space-between;gap:12px;padding:14px 16px;",
        "border:1px solid " + line + ";border-radius:16px;background:#fff;font:500 15px/1.4 " + font + "}",
        "#lu-ws-backdrop .lu-book-row span{color:" + muted + "}",
        "#lu-ws-backdrop .lu-book-row strong{text-align:right}",
        "#lu-ws-backdrop .lu-primary:disabled{opacity:.5;cursor:default}",
      ].join("");
      document.head.appendChild(style);
    }

    if (!$("lu-ws-backdrop")) {
      var backdrop = document.createElement("div");
      backdrop.id = "lu-ws-backdrop";
      backdrop.innerHTML =
        "<div class='lu-stage'>" +
        "  <div class='lu-top'>" +
        "    <div>" +
        "      <p class='lu-kicker' id='lu-ws-kicker'></p>" +
        "      <h2 class='lu-scene-title' id='lu-ws-title'></h2>" +
        "    </div>" +
        "    <button type='button' class='lu-min-btn' id='lu-ws-min'>" +
        escapeHtml(t("minimize")) +
        "</button>" +
        "  </div>" +
        "  <div class='lu-tabs' id='lu-ws-tabs' hidden></div>" +
        "  <div class='lu-body' id='lu-ws-body'></div>" +
        "</div>";
      document.body.appendChild(backdrop);
      document.getElementById("lu-ws-min").addEventListener("click", function () {
        closeWorkspace();
      });
    }

    _wsRoot = {
      getElementById: function (id) { return document.getElementById(id); },
      querySelector: function (sel) {
        var root = document.getElementById("lu-ws-backdrop");
        return root ? root.querySelector(sel) : null;
      },
      querySelectorAll: function (sel) {
        var root = document.getElementById("lu-ws-backdrop");
        return root ? root.querySelectorAll(sel) : [];
      },
    };
    _wsHost = document.getElementById("lu-ws-backdrop");
    return _wsRoot;
  }

  function openWorkspace() {
    ensureWorkspace();
    state.workspaceOpen = true;
    var bd = document.getElementById("lu-ws-backdrop");
    if (bd) bd.classList.add("lu-open");
    var reopenBtn = $("lu-reopen-ws");
    if (reopenBtn) reopenBtn.style.display = "none";
    console.info("[LU] workspace open", state.activeSection);
  }

  function closeWorkspace() {
    state.workspaceOpen = false;
    var bd = document.getElementById("lu-ws-backdrop");
    if (bd) bd.classList.remove("lu-open");
    if (state.connected && !state.escaped) {
      ensureReopenPill();
    }
  }

  function ensureReopenPill() {
    var btn = $("lu-reopen-ws");
    if (!btn) {
      btn = document.createElement("button");
      btn.id = "lu-reopen-ws";
      btn.type = "button";
      btn.textContent = t("openWorkspace");
      btn.style.cssText =
        "position:fixed;bottom:24px;right:20px;z-index:99995;" +
        "padding:9px 14px;border-radius:999px;border:1px solid rgba(255,255,255,.2);" +
        "background:#0f172a;color:#f8fafc;font:600 12px/1.2 system-ui,sans-serif;" +
        "cursor:pointer;box-shadow:0 8px 24px rgba(0,0,0,.28)";
      btn.addEventListener("click", function () {
        renderWorkspaceScene(
          state.activeSection || "services",
          state.activeHighlight,
          state.activePrefill
        );
      });
      document.body.appendChild(btn);
    }
    btn.style.display = "block";
  }

  function renderTabs(activeKey) {
    if (!_wsRoot) return;
    var tabsHost = _wsRoot.getElementById("lu-ws-tabs");
    if (!tabsHost) return;
    var tabs = [
      ["services", t("section_services")],
      ["roi_calculator", t("section_roi_calculator")],
      ["cases", t("section_cases")],
      ["pricing", t("section_pricing")],
      ["booking_widget", t("section_booking_widget")],
    ];
    tabsHost.innerHTML = tabs
      .map(function (pair) {
        var k = pair[0];
        var label = pair[1];
        var cls = "lu-tab" + (k === activeKey ? " active" : "");
        return (
          "<button type='button' class='" +
          cls +
          "' data-tab='" +
          k +
          "'>" +
          escapeHtml(label) +
          "</button>"
        );
      })
      .join("");

    tabsHost.querySelectorAll("[data-tab]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var targetSec = btn.getAttribute("data-tab");
        renderWorkspaceScene(targetSec, null, state.activePrefill);
        sendClientMessage({
          type: "ui_user_interaction",
          data: {
            interaction: "tab_switch",
            section: targetSec,
            description: "Visitor switched workspace tab to " + targetSec,
          },
        });
      });
    });
  }

  function renderCardDeckHtml(sectionKey, items, highlightId) {
    items = items || [];
    var hi = (highlightId || state.activeHighlight || "").toLowerCase();
    var openId = null;
    if (hi) {
      for (var i = 0; i < items.length; i++) {
        var it = items[i];
        if (
          String(it.id).toLowerCase() === hi ||
          String(it.id).toLowerCase().indexOf(hi) !== -1 ||
          String(it.title).toLowerCase().indexOf(hi) !== -1
        ) {
          openId = it.id;
          break;
        }
      }
    }
    if (!openId && items.length) openId = items[0].id;
    state.activeHighlight = openId;

    var html = items
      .map(function (item) {
        var isOpen = String(item.id) === String(openId);
        return (
          "<div class='lu-acc-item" +
          (isOpen ? " is-open" : "") +
          "' data-card-id='" +
          escapeHtml(item.id) +
          "'>" +
          "<button type='button' class='lu-acc-head' data-acc-id='" +
          escapeHtml(item.id) +
          "' data-select-title='" +
          escapeHtml(item.title) +
          "'>" +
          (item.badge
            ? "<span class='lu-acc-badge'>" + escapeHtml(item.badge) + "</span>"
            : "") +
          "<span class='lu-acc-title'>" +
          escapeHtml(item.title) +
          "</span>" +
          "</button>" +
          "<div class='lu-acc-body'>" +
          escapeHtml(item.description) +
          "</div>" +
          "</div>"
        );
      })
      .join("");

    return "<div class='lu-acc' data-section='" + escapeHtml(sectionKey) + "'>" + html + "</div>";
  }

  function renderRoiHtml(fig) {
    fig = fig || state.lastRoi || {};
    var missed = Number(fig.missed_calls_per_month || 120);
    var cost = Number(fig.cost_per_missed_lead || 50);
    var capture = Math.round(Number(fig.capture_rate || 0.35) * 100);
    var aiCost = Number(fig.ai_monthly_cost || 299);
    var recovered = Math.round(missed * (capture / 100));
    var gross = recovered * cost;
    var net = Math.round(gross - aiCost);
    var payback = gross > 0 ? Math.max(1, Math.round((aiCost / (gross / 30)) * 10) / 10) : "—";

    return (
      "<div>" +
      "<p class='lu-kicker'>" +
      escapeHtml(t("roiKicker")) +
      "</p>" +
      "<h2 class='lu-title'>" +
      escapeHtml(t("roiTitle")) +
      "</h2>" +
      "<p class='lu-sub'>" +
      escapeHtml(t("roiSub")) +
      "</p>" +
      "<div class='lu-roi-grid'>" +
      "  <div class='lu-roi-controls'>" +
      "    <div class='lu-control-group'>" +
      "      <div class='lu-control-head'><span>" +
      escapeHtml(t("roiMissed")) +
      "</span><strong id='lu-roi-val-missed'>" +
      missed +
      "</strong></div>" +
      "      <input type='range' class='lu-range' id='lu-roi-in-missed' min='10' max='1000' step='10' value='" +
      missed +
      "'/>" +
      "    </div>" +
      "    <div class='lu-control-group'>" +
      "      <div class='lu-control-head'><span>" +
      escapeHtml(t("roiLeadCost")) +
      "</span><strong id='lu-roi-val-cost'>" +
      cost +
      "</strong></div>" +
      "      <input type='range' class='lu-range' id='lu-roi-in-cost' min='10' max='500' step='5' value='" +
      cost +
      "'/>" +
      "    </div>" +
      "    <div class='lu-control-group'>" +
      "      <div class='lu-control-head'><span>" +
      escapeHtml(t("roiCapture")) +
      "</span><strong id='lu-roi-val-cap'>" +
      capture +
      "%</strong></div>" +
      "      <input type='range' class='lu-range' id='lu-roi-in-cap' min='15' max='80' step='5' value='" +
      capture +
      "'/>" +
      "    </div>" +
      "  </div>" +
      "  <div class='lu-roi-summary'>" +
      "    <div class='lu-roi-row'><span>" +
      escapeHtml(t("roiRecovered")) +
      "</span><strong id='lu-roi-out-rec'>" +
      recovered +
      "</strong></div>" +
      "    <div class='lu-roi-row'><span>" +
      escapeHtml(t("roiAiCost")) +
      "</span><strong>" +
      aiCost +
      "</strong></div>" +
      "    <div class='lu-roi-row'><span>" +
      escapeHtml(t("roiPayback")) +
      "</span><strong id='lu-roi-out-pay'>" +
      payback +
      " " +
      escapeHtml(t("roiDays")) +
      "</strong></div>" +
      "    <div class='lu-roi-row hi'><span>" +
      escapeHtml(t("roiNet")) +
      "</span><strong id='lu-roi-out-net'>+" +
      net.toLocaleString("en-US") +
      "</strong></div>" +
      "    <button type='button' class='lu-cta-btn' id='lu-roi-to-book' style='width:100%;margin-top:14px'>" +
      escapeHtml(t("roiCta")) +
      "</button>" +
      "  </div>" +
      "</div>" +
      "</div>"
    );
  }

  function formatPhone(raw) {
    var d = String(raw || "").replace(/\D/g, "");
    if (d.length === 11 && d.indexOf("373") === 0) {
      return "+373 " + d.slice(3, 5) + " " + d.slice(5, 8) + " " + d.slice(8);
    }
    return raw ? String(raw) : "";
  }

  function formatSlot(iso) {
    if (!iso) return "";
    try {
      var dte = new Date(iso);
      if (isNaN(dte.getTime())) return String(iso);
      var loc = pageLocale();
      var tag = loc === "ro" ? "ro-RO" : loc === "ru" ? "ru-RU" : "en-GB";
      return dte.toLocaleString(tag, {
        weekday: "long",
        day: "numeric",
        month: "long",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch (e) {
      return String(iso);
    }
  }

  /* Booking card: name, verified phone, slot chosen by voice. Visitor confirms on screen or says "yes". */
  function renderBookingHtml(prefill) {
    prefill = prefill || {};
    var nameVal = prefill.client_name || prefill.name || "";
    var phoneVal = formatPhone(prefill.phone || prefill.client_phone || "");
    var startVal = prefill.start_time || "";
    var noteVal = prefill.request_summary || "";
    var slotText = formatSlot(startVal);
    return (
      "<div>" +
      "<h2 class='lu-title'>" +
      escapeHtml(t("bookCheckTitle")) +
      "</h2>" +
      "<p class='lu-sub'>" +
      escapeHtml(startVal ? t("bookCheckSub") : t("bookAskTime")) +
      "</p>" +
      "<form class='lu-form' id='lu-ws-book-form'>" +
      "  <div class='lu-field'>" +
      "    <label for='lu-book-name'>" +
      escapeHtml(t("bookName")) +
      "</label>" +
      "    <input type='text' name='client_name' id='lu-book-name' autocomplete='name' placeholder='" +
      escapeHtml(t("bookNamePh")) +
      "' value='" +
      escapeHtml(nameVal) +
      "'/>" +
      "  </div>" +
      "  <div class='lu-book-row'><span>" +
      escapeHtml(t("bookPhoneRo")) +
      "</span><strong id='lu-book-phone-ro'>" +
      escapeHtml(phoneVal || "—") +
      "</strong></div>" +
      "  <div class='lu-book-row'><span>" +
      escapeHtml(t("bookTime")) +
      "</span><strong id='lu-book-time'>" +
      escapeHtml(slotText || "—") +
      "</strong></div>" +
      (noteVal
        ? "  <div class='lu-book-row'><span>" +
          escapeHtml(t("bookNote")) +
          "</span><strong>" +
          escapeHtml(noteVal) +
          "</strong></div>"
        : "") +
      "  <button type='submit' class='lu-primary' id='lu-book-submit'" +
      (startVal && phoneVal ? "" : " disabled") +
      ">" +
      escapeHtml(t("bookConfirmBtn")) +
      "</button>" +
      "</form>" +
      "</div>"
    );
  }

  function renderConceptComponents(components) {
    // Reserved for labupgrade.ai Concept showcase mode
    return (
      "<div class='lu-grid'>" +
      components
        .map(function (c) {
          var p = c.props || {};
          return (
            "<div class='lu-card'>" +
            "<span class='lu-badge'>" +
            escapeHtml(c.type || "Component") +
            "</span>" +
            "<h3>" +
            escapeHtml(p.title || p.label || c.type) +
            "</h3>" +
            "<p>" +
            escapeHtml(p.description || p.text || "") +
            "</p>" +
            "</div>"
          );
        })
        .join("") +
      "</div>"
    );
  }

  function bindWorkspaceEvents(sectionKey) {
    if (!_wsRoot) return;
    var body = _wsRoot.getElementById("lu-ws-body");
    if (!body) return;

    body.querySelectorAll("[data-acc-id]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var id = btn.getAttribute("data-acc-id");
        var itemTitle = btn.getAttribute("data-select-title") || id;
        var root = body.querySelector(".lu-acc");
        if (root) {
          root.querySelectorAll(".lu-acc-item").forEach(function (el) {
            if (el.getAttribute("data-card-id") === id) el.classList.add("is-open");
            else el.classList.remove("is-open");
          });
        }
        state.activeHighlight = id;
        sendClientMessage({
          type: "ui_user_interaction",
          data: {
            interaction: "item_selected",
            section: sectionKey,
            item: itemTitle,
            item_id: id,
            description: "Visitor focused option: " + itemTitle,
          },
        });
      });
    });

    if (sectionKey === "roi_calculator") {
      var inMissed = _wsRoot.getElementById("lu-roi-in-missed");
      var inCost = _wsRoot.getElementById("lu-roi-in-cost");
      var inCap = _wsRoot.getElementById("lu-roi-in-cap");
      function recalcLocal() {
        var m = Number(inMissed.value || 120);
        var c = Number(inCost.value || 50);
        var cap = Number(inCap.value || 35);
        var ai = Number((state.lastRoi && state.lastRoi.ai_monthly_cost) || 299);
        var rec = Math.round(m * (cap / 100));
        var gross = rec * c;
        var net = Math.round(gross - ai);
        var pay =
          gross > 0 ? Math.max(1, Math.round((ai / (gross / 30)) * 10) / 10) : "—";
        _wsRoot.getElementById("lu-roi-val-missed").textContent = String(m);
        _wsRoot.getElementById("lu-roi-val-cost").textContent = String(c);
        _wsRoot.getElementById("lu-roi-val-cap").textContent = cap + "%";
        _wsRoot.getElementById("lu-roi-out-rec").textContent = String(rec);
        _wsRoot.getElementById("lu-roi-out-pay").textContent =
          pay + " " + t("roiDays");
        _wsRoot.getElementById("lu-roi-out-net").textContent =
          (net >= 0 ? "+" : "") + net.toLocaleString("en-US");
        state.lastRoi = {
          missed_calls_per_month: m,
          cost_per_missed_lead: c,
          capture_rate: cap / 100,
          ai_monthly_cost: ai,
          recovered_leads_per_month: rec,
          net_monthly_savings: net,
          payback_days: pay,
        };
      }
      [inMissed, inCost, inCap].forEach(function (inp) {
        if (!inp) return;
        inp.addEventListener("input", recalcLocal);
        inp.addEventListener("change", function () {
          recalcLocal();
          sendClientMessage({
            type: "ui_user_interaction",
            data: {
              interaction: "roi_adjusted",
              description:
                "Visitor adjusted ROI sliders on screen: missed=" +
                state.lastRoi.missed_calls_per_month +
                ", lead_value=" +
                state.lastRoi.cost_per_missed_lead +
                ", net_savings=" +
                state.lastRoi.net_monthly_savings,
            },
          });
        });
      });
      var toBook = _wsRoot.getElementById("lu-roi-to-book");
      if (toBook) {
        toBook.addEventListener("click", function () {
          renderWorkspaceScene("booking_widget", "phone", state.activePrefill);
          sendClientMessage({
            type: "ui_user_interaction",
            data: {
              interaction: "open_booking_from_roi",
              description: "Visitor clicked CTA on ROI calculator to book a call",
            },
          });
        });
      }
    }

    if (sectionKey === "booking_widget") {
      var form = _wsRoot.getElementById("lu-ws-book-form");
      if (form) {
        form.addEventListener("submit", function (ev) {
          ev.preventDefault();
          var pf = state.activePrefill || {};
          if (!pf.start_time) return;
          var nameVal = (_wsRoot.getElementById("lu-book-name").value || "").trim();
          var btn = _wsRoot.getElementById("lu-book-submit");
          if (btn) {
            btn.disabled = true;
            btn.textContent = t("bookConfirmed");
          }
          state.activePrefill.client_name = nameVal;
          sendClientMessage({
            type: "ui_user_interaction",
            data: {
              interaction: "booking_confirmed",
              client_name: nameVal,
              start_time: pf.start_time || "",
              end_time: pf.end_time || "",
              request_summary: pf.request_summary || "",
              description: "Visitor confirmed the booking card on screen",
            },
          });
        });
      }
    }
  }

  function sectionTitle(key) {
    var cat = state.catalog || {};
    var sample = "";
    try {
      var arr = cat[key] || cat.services || [];
      if (arr[0]) sample = String(arr[0].title || arr[0].description || "");
    } catch (e) {}
    var cyr = /[а-яА-ЯёЁ]/.test(sample);
    if (cyr) {
      var ru = {
        services: "Услуги и решения",
        pricing: "Тарифы и форматы",
        cases: "Кейсы и результаты",
        roi_calculator: "Расчёт окупаемости",
        booking_widget: "Запись и контакт",
        contacts: "Контакты",
        hero: "О компании",
      };
      return ru[key] || t("section_" + key);
    }
    return t("section_" + key) || key;
  }

  function renderWorkspaceScene(sectionKey, highlight, prefill, components) {
    ensureWorkspace();
    var key = (sectionKey || "services").toLowerCase();
    if (key === "hero" || key === "contacts") {
      key = key === "contacts" ? "booking_widget" : "services";
    }
    /* Empty catalog section: do not open an empty workspace, keep current view */
    var hasComponents = Array.isArray(components) && components.length > 0;
    if (!hasComponents && (key === "services" || key === "pricing" || key === "cases")) {
      var catCheck = buildCatalog();
      if (!catCheck[key] || !catCheck[key].length) {
        console.info("[LU] section has no catalog items, workspace not opened:", key);
        return;
      }
    }
    state.activeSection = key;
    state.activeHighlight = highlight || null;
    if (prefill && typeof prefill === "object") {
      Object.keys(prefill).forEach(function (k) {
        if (prefill[k] != null) state.activePrefill[k] = prefill[k];
      });
    }

    renderTabs(key);
    var titleEl = _wsRoot.getElementById("lu-ws-title");
    var kickEl = _wsRoot.getElementById("lu-ws-kicker");
    if (titleEl) titleEl.textContent = sectionTitle(key);
    if (kickEl) kickEl.textContent = "";
    var body = _wsRoot.getElementById("lu-ws-body");
    var cat = buildCatalog();

    if (Array.isArray(components) && components.length > 0) {
      body.innerHTML = renderConceptComponents(components);
    } else if (key === "roi_calculator") {
      body.innerHTML = renderRoiHtml(state.lastRoi);
    } else if (key === "booking_widget") {
      body.innerHTML = renderBookingHtml(state.activePrefill);
    } else if (key === "pricing") {
      body.innerHTML = renderCardDeckHtml("pricing", cat.pricing, highlight);
    } else if (key === "cases") {
      body.innerHTML = renderCardDeckHtml("cases", cat.cases, highlight);
    } else {
      body.innerHTML = renderCardDeckHtml("services", cat.services, highlight);
    }

    bindWorkspaceEvents(key);
    openWorkspace();
  }

  // —— 4. Scene Orchestrator (Mode A Navigator vs Mode B Workspace) ——
  function focusSection(section, highlight, prefill, components) {
    section = (section || "").trim();
    if (!section) return null;
    if (!Object.keys(state.sectionMap || {}).length) scanPageSections();
    var key = section.toLowerCase();
    document.documentElement.setAttribute("data-lu-active-section", key);

    /* Series Adaptive Workspace (default): always render from ui_catalog. No scroll_to landing. */
    var el = findSection(key);
    var seriesSections = {
      services: 1, pricing: 1, cases: 1, roi_calculator: 1,
      booking_widget: 1, contacts: 1, hero: 1
    };
    var forceWorkspace =
      uiMode !== "navigator" ||
      seriesSections[key] ||
      key === "roi_calculator" ||
      key === "booking_widget" ||
      !el ||
      (Array.isArray(components) && components.length > 0);

    if (forceWorkspace) {
      renderWorkspaceScene(key, highlight, prefill, components);
    } else if (el) {
      /* navigator mode only — still no scroll if policy forbids; soft focus without scroll */
      closeWorkspace();
      if (highlight) {
        var tEl =
          el.querySelector("#" + highlight) ||
          el.querySelector('[data-id="' + highlight + '"]');
        if (tEl) flashHighlight(tEl, 3000);
        else flashHighlight(el, 2600);
      } else {
        flashHighlight(el, 2600);
      }
    }

    try {
      window.dispatchEvent(
        new CustomEvent("lu:navigate", {
          detail: { section: key, mode: forceWorkspace ? "workspace" : "site_dom", found: !!el },
        })
      );
    } catch (e) {}
    return el;
  }

  // —— 5. Permanent Chrome & Thinking Orb ——
  function ensureChrome() {
    if (!$("lu-escape-voice")) {
      var btn = document.createElement("button");
      btn.id = "lu-escape-voice";
      btn.type = "button";
      btn.textContent = t("escape");
      btn.setAttribute("aria-label", "Stop voice assistant");
      btn.style.cssText =
        "position:fixed;top:12px;left:50%;transform:translateX(-50%);z-index:99999;" +
        "padding:8px 14px;border-radius:999px;border:0;cursor:pointer;" +
        "background:#111;color:#fff;font:600 13px/1.2 system-ui,sans-serif;" +
        "box-shadow:0 4px 16px rgba(0,0,0,.25)";
      btn.addEventListener("click", function () {
        state.escaped = true;
        sendClientMessage({
          type: "ui_user_interaction",
          data: { interaction: "escape" },
        });
        stopSession("escape");
        btn.style.display = "none";
        document.documentElement.classList.add("lu-voice-off");
      });
      document.body.appendChild(btn);
    }

    if (!$("lu-voice-orb-wrap")) {
      var wrap = document.createElement("div");
      wrap.id = "lu-voice-orb-wrap";
      wrap.style.cssText =
        "position:fixed;left:50%;bottom:max(16px, env(safe-area-inset-bottom));" +
        "transform:translateX(-50%);z-index:99998;" +
        "display:flex;flex-direction:column;align-items:center;gap:6px;" +
        "pointer-events:none";
      var orbHost = document.createElement("div");
      orbHost.id = "lu-voice-orb";
      orbHost.style.cssText =
        "width:64px;height:64px;display:flex;align-items:center;justify-content:center;" +
        "pointer-events:auto;cursor:pointer";
      orbHost.addEventListener("click", function () {
        if (!state.connected && !state.connecting && !state.escaped) {
          startSession().catch(function () {});
        } else if (state.connected && !state.workspaceOpen) {
          renderWorkspaceScene(state.activeSection || "services", null, state.activePrefill);
        }
      });
      var label = document.createElement("div");
      label.id = "lu-voice-orb-label";
      label.style.cssText =
        "font:600 11px/1.2 system-ui,sans-serif;color:#0f172a;" +
        "background:rgba(255,255,255,.92);padding:4px 10px;border-radius:999px;" +
        "max-width:220px;text-align:center;opacity:0;transition:opacity .2s;" +
        "box-shadow:0 2px 10px rgba(0,0,0,.18);pointer-events:auto;cursor:pointer";
      label.addEventListener("click", function () {
        if (!state.connected && !state.connecting && !state.escaped) {
          startSession().catch(function () {});
        }
      });
      wrap.appendChild(orbHost);
      wrap.appendChild(label);
      document.body.appendChild(wrap);
      loadThinkingOrbs().then(function () {
        tryMountThinkingOrb(state.agentState || "breathing");
      });
    }
  }

  var _orbReactRoot = null;
  var _orbsLoading = null;

  function loadThinkingOrbs() {
    if (
      window.ThinkingOrb &&
      window.React &&
      window.ReactDOM &&
      window.ReactDOM.createRoot
    ) {
      return Promise.resolve();
    }
    if (_orbsLoading) return _orbsLoading;
    _orbsLoading = new Promise(function (resolve) {
      var s = document.createElement("script");
      s.type = "module";
      s.textContent = [
        "import React from 'https://esm.sh/react@18.3.1';",
        "import { createRoot } from 'https://esm.sh/react-dom@18.3.1/client';",
        "import { ThinkingOrb } from 'https://esm.sh/thinking-orbs@0.3.2?deps=react@18.3.1';",
        "window.React = React;",
        "window.ReactDOM = { createRoot: createRoot };",
        "window.ThinkingOrb = ThinkingOrb;",
        "window.dispatchEvent(new Event('lu-orbs-ready'));",
      ].join("\n");
      var finished = false;
      function finish() {
        if (finished) return;
        finished = true;
        resolve();
      }
      window.addEventListener("lu-orbs-ready", finish, { once: true });
      s.onerror = function () {
        finish();
      };
      document.head.appendChild(s);
      setTimeout(finish, 8000);
    });
    return _orbsLoading;
  }

  function tryMountThinkingOrb(orbState) {
    var host = $("lu-voice-orb");
    if (!host) return;
    var st = orbState === "idle" ? "breathing" : orbState || "breathing";
    var allowed = {
      working: 1,
      searching: 1,
      solving: 1,
      listening: 1,
      connecting: 1,
      weaving: 1,
      composing: 1,
      breathing: 1,
      shaping: 1,
    };
    if (!allowed[st]) st = "breathing";

    if (window.ThinkingOrb && window.React && window.ReactDOM) {
      try {
        if (!_orbReactRoot && window.ReactDOM.createRoot) {
          _orbReactRoot = window.ReactDOM.createRoot(host);
        }
        if (_orbReactRoot) {
          _orbReactRoot.render(
            window.React.createElement(window.ThinkingOrb, {
              state: st,
              size: 64,
              theme: "auto",
            })
          );
          return;
        }
      } catch (e) {}
    }
    applyOrbCss(st);
  }

  function applyOrbCss(mode) {
    var orb = $("lu-voice-orb");
    if (!orb) return;
    orb.innerHTML = "";
    orb.style.width = "64px";
    orb.style.height = "64px";
    orb.style.borderRadius = "50%";
    orb.style.background =
      "radial-gradient(circle at 35% 30%,#e2e8f0 0%,#64748b 45%,#0f172a 100%)";
    var shadows = {
      connecting: "0 0 0 4px rgba(80,200,255,.45),0 8px 24px rgba(0,0,0,.2)",
      searching: "0 0 0 5px rgba(96,165,250,.45),0 8px 24px rgba(0,0,0,.2)",
      solving: "0 0 0 5px rgba(167,139,250,.45),0 8px 24px rgba(0,0,0,.2)",
      composing: "0 0 0 5px rgba(251,191,36,.4),0 8px 24px rgba(0,0,0,.2)",
      working: "0 0 0 4px rgba(52,211,153,.4),0 8px 24px rgba(0,0,0,.2)",
      listening: "0 0 0 4px rgba(45,212,191,.45),0 8px 24px rgba(0,0,0,.2)",
      weaving: "0 0 0 5px rgba(244,114,182,.4),0 8px 24px rgba(0,0,0,.2)",
      breathing: "0 0 0 3px rgba(148,163,184,.35),0 8px 24px rgba(0,0,0,.15)",
      error: "0 0 0 4px rgba(255,80,80,.5),0 8px 24px rgba(0,0,0,.2)",
      idle: "0 8px 24px rgba(0,0,0,.15)",
    };
    orb.style.boxShadow = shadows[mode] || shadows.breathing;
  }

  function setAgentState(orbState, labelText) {
    state.agentState = orbState || "breathing";
    state.agentLabel = labelText || "";
    loadThinkingOrbs().then(function () {
      tryMountThinkingOrb(state.agentState);
    });
    var label = $("lu-voice-orb-label");
    if (label) {
      if (labelText) {
        label.textContent = String(labelText).slice(0, 80);
        label.style.opacity = "1";
      } else {
        label.textContent = "";
        label.style.opacity = "0";
      }
    }
  }

  // —— 6. RTVI Command Handlers ——
  function handleNavigateAndRender(payload) {
    payload = payload || {};
    var section = payload.section || "services";
    var highlight = payload.highlight || payload.highlight_element;
    var prefill = payload.prefill || payload.prefill_data || {};
    var components = payload.components;

    if (!Object.keys(state.sectionMap || {}).length) scanPageSections();
    focusSection(section, highlight, prefill, components);

    if (prefill && typeof prefill === "object") {
      Object.keys(prefill).forEach(function (key) {
        var val = prefill[key];
        if (val == null) return;
        var root = findSection(section) || document;
        var field =
          root.querySelector('[name="' + key + '"]') ||
          root.querySelector("#" + key) ||
          root.querySelector('[data-field="' + key + '"]') ||
          document.querySelector('[name="' + key + '"]');
        if (field && "value" in field) {
          field.value = String(val);
          try {
            field.dispatchEvent(new Event("input", { bubbles: true }));
            field.dispatchEvent(new Event("change", { bubbles: true }));
          } catch (e) {}
        }
      });
    }
  }

  function handleDomCommand(command, payload) {
    payload = payload || {};
    var el = findTarget(payload.ref, payload.target_id);
    if (!el) {
      if (command === "highlight" && payload.target_id && state.workspaceOpen) {
        renderWorkspaceScene(state.activeSection, payload.target_id, state.activePrefill);
      }
      return;
    }
    if (command === "scroll_to" || command === "highlight") {
      flashHighlight(el, payload.duration_ms || 2200);
    } else if (command === "set_input_value") {
      if ("value" in el) {
        el.value = payload.value != null ? String(payload.value) : "";
        try {
          el.dispatchEvent(new Event("input", { bubbles: true }));
          el.dispatchEvent(new Event("change", { bubbles: true }));
        } catch (e) {}
      }
    } else if (command === "click" || command === "focus") {
      try {
        if (command === "focus" && el.focus) el.focus();
        else el.click();
      } catch (e) {}
    }
  }

  function handleUpdateRoi(payload) {
    payload = payload || {};
    state.lastRoi = Object.assign({}, state.lastRoi, payload);
    try {
      window.dispatchEvent(new CustomEvent("lu:roi", { detail: state.lastRoi }));
    } catch (e) {}
    focusSection("roi_calculator", null, state.lastRoi);
  }

  function collectPageSummary(focus) {
    var parts = [];
    var title = document.title || "";
    if (title) parts.push("title: " + title);
    var h1 = qs("h1");
    if (h1) parts.push("h1: " + (h1.textContent || "").trim().slice(0, 120));
    var meta = qs('meta[name="description"]');
    if (meta && meta.content) parts.push("description: " + meta.content.slice(0, 200));

    var selectors = {
      full_page: "h1,h2,h3,a[href],button,input,textarea,select,[role='button']",
      cta: "a.btn,a.button,button,[class*='cta'],[data-cta]",
      form: "form input,form textarea,form select,form button",
      pricing: "[data-section='pricing'],#pricing,.pricing,[class*='price']",
      hero: "[data-section='hero'],#hero,.hero,header",
      mobile: "body",
    };
    var sel = selectors[focus] || selectors.full_page;
    var nodes = [];
    try {
      nodes = Array.prototype.slice.call(document.querySelectorAll(sel), 0, 40);
    } catch (e) {}
    var labels = nodes
      .map(function (n) {
        var txt = (n.innerText || n.value || n.getAttribute("aria-label") || n.tagName || "")
          .replace(/\s+/g, " ")
          .trim()
          .slice(0, 80);
        return txt ? n.tagName.toLowerCase() + ": " + txt : "";
      })
      .filter(Boolean)
      .slice(0, 25);
    if (labels.length) parts.push("elements: " + labels.join(" | "));
    return parts.join("; ").slice(0, 2500);
  }

  function handleStartScreenAudit(payload) {
    payload = payload || {};
    var focus = payload.focus || "full_page";
    var summary = collectPageSummary(focus);
    sendClientMessage({
      type: "ui_user_interaction",
      data: {
        interaction: "screen_audit",
        page_summary: summary,
        issues: [],
        url: String(location.href || "").slice(0, 500),
        focus: focus,
      },
    });
  }

  /* SMS phone verification: number via phone autofill, code via SMS autofill. Server decides. */
  var _otpAbort = null;

  function setMicEnabled(on) {
    try {
      if (state.localStream) {
        state.localStream.getAudioTracks().forEach(function (tr) {
          tr.enabled = !!on;
        });
      }
    } catch (e) {}
  }

  function closeVerifyModal() {
    try {
      if (_otpAbort) _otpAbort.abort();
    } catch (e) {}
    _otpAbort = null;
    var m = $("lu-verify-modal");
    if (m) m.remove();
  }

  function verifyStatus(text, isError) {
    var el = $("lu-verify-status");
    if (!el) return;
    el.textContent = text || "";
    el.style.color = isError ? "#fca5a5" : "#86efac";
  }

  function verifyStage(stage) {
    var ph = $("lu-verify-step-phone");
    var cd = $("lu-verify-step-code");
    if (ph) ph.style.display = stage === "phone" ? "block" : "none";
    if (cd) cd.style.display = stage === "code" ? "block" : "none";
    var focusEl = stage === "code" ? $("lu-verify-code") : $("lu-verify-phone");
    if (focusEl) {
      setTimeout(function () {
        try {
          focusEl.focus();
        } catch (e) {}
      }, 80);
    }
  }

  function submitVerifyCode() {
    var code = (($("lu-verify-code") || {}).value || "").replace(/\D/g, "");
    if (code.length < 4) return;
    var btn = $("lu-verify-code-btn");
    if (btn) btn.disabled = true;
    sendClientMessage({
      type: "ui_user_interaction",
      data: { interaction: "verify_submit_code", code: code },
    });
  }

  function listenSmsCode() {
    /* Android Chrome: reads the code from the SMS by itself (needs the "@domain #code" line) */
    if (!("OTPCredential" in window) || !navigator.credentials) return;
    try {
      if (_otpAbort) _otpAbort.abort();
      _otpAbort = new AbortController();
      navigator.credentials
        .get({ otp: { transport: ["sms"] }, signal: _otpAbort.signal })
        .then(function (otp) {
          if (!otp || !otp.code) return;
          var inp = $("lu-verify-code");
          if (inp) inp.value = otp.code;
          submitVerifyCode();
        })
        .catch(function () {});
    } catch (e) {}
  }

  function showVerifyModal(payload) {
    if ($("lu-verify-modal")) return;
    /* Microphone paused while the number is confirmed (the server also stops audio to the model) */
    setMicEnabled(false);
    setAgentState("breathing", t("micPaused"));
    var wrap = document.createElement("div");
    wrap.id = "lu-verify-modal";
    wrap.style.cssText =
      "position:fixed;inset:0;z-index:100002;background:rgba(0,0,0,.65);" +
      "display:flex;align-items:center;justify-content:center;padding:16px;backdrop-filter:blur(8px)";
    var box = document.createElement("div");
    box.style.cssText =
      "background:#0f172a;color:#f8fafc;max-width:360px;width:100%;border-radius:18px;" +
      "padding:22px;font:14px/1.45 system-ui,sans-serif;border:1px solid rgba(255,255,255,.15)";
    var inputCss =
      "width:100%;padding:12px;border:1px solid rgba(255,255,255,.2);background:#1e293b;color:#fff;" +
      "border-radius:10px;box-sizing:border-box;font:16px system-ui,sans-serif";
    var btnCss =
      "margin-top:12px;width:100%;padding:12px;border:0;border-radius:10px;background:#10b981;" +
      "color:#fff;font-weight:600;font-size:15px;cursor:pointer";
    var linkCss =
      "margin-top:10px;border:0;background:transparent;color:#94a3b8;font:13px system-ui,sans-serif;" +
      "cursor:pointer;padding:4px 0";
    box.innerHTML =
      "<h3 style='margin:0 0 8px;font-size:16px'>" +
      escapeHtml(t("verifyTitle")) +
      "</h3>" +
      "<p style='margin:0 0 14px;color:#cbd5e1;font-size:13px'>" +
      escapeHtml(t("verifyText")) +
      "</p>" +
      "<form id='lu-verify-step-phone' autocomplete='on'>" +
      "<label for='lu-verify-phone' style='display:block;margin-bottom:6px;color:#cbd5e1;font-size:12px'>" +
      escapeHtml(t("verifyPhoneLabel")) +
      "</label>" +
      "<input id='lu-verify-phone' name='tel' type='tel' inputmode='tel' autocomplete='tel' " +
      "placeholder='+373 …' style='" + inputCss + "'/>" +
      "<button id='lu-verify-phone-btn' type='submit' style='" + btnCss + "'>" +
      escapeHtml(t("verifyGetCode")) +
      "</button>" +
      "</form>" +
      "<form id='lu-verify-step-code' style='display:none' autocomplete='on'>" +
      "<label for='lu-verify-code' style='display:block;margin-bottom:6px;color:#cbd5e1;font-size:12px'>" +
      escapeHtml(t("verifyCodeLabel")) +
      "</label>" +
      "<input id='lu-verify-code' name='one-time-code' type='text' inputmode='numeric' " +
      "autocomplete='one-time-code' maxlength='6' pattern='[0-9]*' style='" + inputCss +
      ";letter-spacing:.3em;text-align:center'/>" +
      "<button id='lu-verify-code-btn' type='submit' style='" + btnCss + "'>" +
      escapeHtml(t("verifyConfirm")) +
      "</button>" +
      "<div style='display:flex;justify-content:space-between;gap:8px'>" +
      "<button id='lu-verify-change' type='button' style='" + linkCss + "'>" +
      escapeHtml(t("verifyChange")) +
      "</button>" +
      "<button id='lu-verify-resend' type='button' style='" + linkCss + "'>" +
      escapeHtml(t("verifyResend")) +
      "</button>" +
      "</div>" +
      "</form>" +
      "<p id='lu-verify-status' style='margin:12px 0 0;min-height:18px;font-size:13px'></p>";
    wrap.appendChild(box);
    document.body.appendChild(wrap);

    function requestCode() {
      var phone = (($("lu-verify-phone") || {}).value || "").trim();
      if (phone.replace(/\D/g, "").length < 8) {
        verifyStatus(t("vs_bad_phone"), true);
        return;
      }
      var btn = $("lu-verify-phone-btn");
      if (btn) btn.disabled = true;
      verifyStatus("", false);
      sendClientMessage({
        type: "ui_user_interaction",
        data: { interaction: "verify_request_code", phone: phone },
      });
    }

    $("lu-verify-step-phone").addEventListener("submit", function (ev) {
      ev.preventDefault();
      requestCode();
    });
    $("lu-verify-step-code").addEventListener("submit", function (ev) {
      ev.preventDefault();
      submitVerifyCode();
    });
    $("lu-verify-code").addEventListener("input", function () {
      var v = ($("lu-verify-code").value || "").replace(/\D/g, "");
      if (v.length === 6) submitVerifyCode();
    });
    $("lu-verify-change").addEventListener("click", function () {
      verifyStatus("", false);
      var b1 = $("lu-verify-phone-btn");
      if (b1) b1.disabled = false;
      verifyStage("phone");
    });
    $("lu-verify-resend").addEventListener("click", function () {
      requestCode();
    });
    verifyStage("phone");
  }

  function handleVerifyState(payload) {
    payload = payload || {};
    var st = String(payload.state || "");
    if (!$("lu-verify-modal")) {
      if (st === "verified") return;
      showVerifyModal({});
    }
    var b1 = $("lu-verify-phone-btn");
    var b2 = $("lu-verify-code-btn");
    if (b1) b1.disabled = false;
    if (b2) b2.disabled = false;
    if (st === "code_sent") {
      verifyStage("code");
      var ci = $("lu-verify-code");
      if (ci) ci.value = "";
      verifyStatus(t("vs_code_sent").replace("{phone}", formatPhone(payload.phone || "")), false);
      listenSmsCode();
    } else if (st === "verified") {
      verifyStatus(t("vs_verified"), false);
      setMicEnabled(true);
      setAgentState("breathing");
      setTimeout(closeVerifyModal, 700);
    } else if (st === "bad_code") {
      verifyStatus(t("vs_bad_code").replace("{n}", String(payload.attempts_left != null ? payload.attempts_left : "")), true);
      var ci2 = $("lu-verify-code");
      if (ci2) {
        ci2.value = "";
        try { ci2.focus(); } catch (e) {}
      }
    } else if (st === "expired") {
      verifyStatus(t("vs_expired"), true);
    } else if (st === "bad_phone") {
      verifyStage("phone");
      verifyStatus(t("vs_bad_phone"), true);
    } else if (st === "limit") {
      verifyStatus(t("vs_limit"), true);
    } else if (st === "wait") {
      verifyStatus(t("vs_wait").replace("{sec}", String(payload.seconds || 30)), true);
    } else if (st === "sms_failed") {
      verifyStage("phone");
      verifyStatus(t("vs_sms_failed"), true);
    }
  }

  function showEndingSoon(payload) {
    payload = payload || {};
    var sec = payload.remaining_seconds || 30;
    var el = $("lu-session-warn");
    if (!el) {
      el = document.createElement("div");
      el.id = "lu-session-warn";
      el.style.cssText =
        "position:fixed;bottom:90px;right:20px;z-index:99997;padding:10px 14px;" +
        "border-radius:12px;background:#0f172a;color:#f8fafc;font:600 12px/1.3 system-ui;" +
        "box-shadow:0 8px 24px rgba(0,0,0,.3);border:1px solid rgba(255,255,255,.14)";
      document.body.appendChild(el);
    }
    el.textContent = t("endingSoon").replace("{sec}", String(sec));
    el.style.display = "block";
    setTimeout(function () {
      if (el) el.style.display = "none";
    }, 8000);
  }

  function sendClientMessage(obj) {
    if (!state.dc || state.dc.readyState !== "open") return;
    try {
      var type = (obj && (obj.t || obj.type)) || "ui_user_interaction";
      var data = (obj && obj.data) || obj || {};
      var msgId =
        window.crypto && crypto.randomUUID
          ? crypto.randomUUID()
          : "m" + Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
      var wire = {
        id: msgId,
        label: "rtvi-ai",
        type: "client-message",
        data: {
          t: type,
          d: data,
        },
      };
      state.dc.send(JSON.stringify(wire));
    } catch (e) {
      console.warn("[LU GenUI] dc send failed", e);
    }
  }

  function unwrapRtvi(msg) {
    if (!msg || typeof msg !== "object") return { command: "", payload: {} };
    var command =
      msg.command ||
      (msg.data && msg.data.command) ||
      (msg.payload && msg.payload.command) ||
      "";
    var payload = {};
    if (msg.payload && typeof msg.payload === "object" && !msg.payload.command) {
      payload = msg.payload;
    } else if (
      msg.data &&
      msg.data.payload &&
      typeof msg.data.payload === "object"
    ) {
      payload = msg.data.payload;
      if (!command) command = msg.data.command || "";
    } else if (msg.data && typeof msg.data === "object") {
      payload = msg.data;
      if (!command) command = msg.data.command || msg.type || "";
    } else {
      payload = msg;
    }
    if (
      !command &&
      msg.type &&
      msg.type !== "ui-command" &&
      msg.type !== "server-message"
    ) {
      command = msg.type;
    }
    if (msg.type === "ui-command" || msg.type === "ui_command") {
      command =
        command || (msg.data && msg.data.command) || "navigate_and_render";
    }
    return { command: String(command || ""), payload: payload || {} };
  }

  function dispatchCommand(command, payload) {
    if (command === "navigate_and_render") {
      handleNavigateAndRender(payload);
    } else if (command === "update_roi") {
      handleUpdateRoi(payload);
    } else if (command === "start_screen_audit") {
      handleStartScreenAudit(payload);
    } else if (command === "set_agent_state") {
      setAgentState(payload.state || "breathing", payload.label);
    } else if (
      command === "scroll_to" ||
      command === "highlight" ||
      command === "set_input_value" ||
      command === "click" ||
      command === "focus"
    ) {
      handleDomCommand(command, payload);
    } else if (command === "require_phone_verification") {
      showVerifyModal(payload);
    } else if (command === "verify_state") {
      handleVerifyState(payload);
    } else if (command === "session_ending_soon") {
      showEndingSoon(payload);
    } else if (command === "session_ended" || command === "session_blocked") {
      stopSession(command);
    }
  }

  function onDataMessage(ev) {
    var msg = null;
    try {
      msg = typeof ev.data === "string" ? JSON.parse(ev.data) : ev.data;
    } catch (e) {
      return;
    }
    if (!msg) return;

    var u = unwrapRtvi(msg);
    if (u.command) {
      dispatchCommand(u.command, u.payload || {});
    } else if (msg.data && (msg.data.command || msg.data.payload)) {
      var u2 = unwrapRtvi(msg.data);
      if (u2.command) dispatchCommand(u2.command, u2.payload || {});
    }
  }

  function setupDwellObservers() {
    if (!window.IntersectionObserver) return;
    var candidates = document.querySelectorAll(
      "[data-lu-dwell], [data-lu-section], [data-section], #pricing, #services, #cases, #hero, #contacts"
    );
    if (!candidates.length) return;

    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          var el = entry.target;
          var key =
            el.getAttribute("data-lu-section") ||
            el.getAttribute("data-section") ||
            el.id ||
            "el";
          if (entry.isIntersecting && entry.intersectionRatio >= 0.45) {
            if (state.dwellTimers[key] || state.dwellSeen[key]) return;
            state.dwellTimers[key] = setTimeout(function () {
              state.dwellTimers[key] = null;
              if (state.dwellSeen[key] || state.workspaceOpen) return;
              state.dwellSeen[key] = true;
              sendClientMessage({
                type: "ui_user_interaction",
                data: {
                  interaction: "dwell",
                  element_id: el.id || key,
                  section: key,
                  dwell_ms: 3500,
                },
              });
            }, 3500);
          } else if (state.dwellTimers[key]) {
            clearTimeout(state.dwellTimers[key]);
            state.dwellTimers[key] = null;
          }
        });
      },
      { threshold: [0.45] }
    );

    candidates.forEach(function (el) {
      observer.observe(el);
    });
  }

  // —— 7. Turnstile & Config ——
  function loadConfig() {
    return fetch(
      apiBase + "/widget-config?key=" + encodeURIComponent(widgetKey),
      { cache: "no-store" }
    )
      .then(function (r) {
        return r.json();
      })
      .then(function (d) {
        if (!d) return null;
        state.turnstileSiteKey = d.turnstile_site_key || "";
        if (Array.isArray(d.ice_servers) && d.ice_servers.length) {
          state.iceServers = d.ice_servers;
        }
        if (d.ui_catalog && typeof d.ui_catalog === "object") {
          state.catalog = d.ui_catalog;
        }
        if (d.company_name) {
          state.companyName = String(d.company_name);
        }
        if (d.voice_enabled === false || d.voice === false)
          state.voiceEnabled = false;
        return d;
      })
      .catch(function () {
        return null;
      });
  }

  function loadTurnstile() {
    if (window.turnstile) return Promise.resolve();
    return new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.src =
        "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
      s.async = true;
      s.onload = function () {
        resolve();
      };
      s.onerror = function () {
        reject(new Error("turnstile_script"));
      };
      document.head.appendChild(s);
    });
  }

  function cleanupTurnstileHost(host, wid) {
    try {
      if (wid != null && window.turnstile) window.turnstile.remove(wid);
    } catch (e) {}
    try {
      if (host && host.parentNode) host.parentNode.removeChild(host);
    } catch (e) {}
  }

  function getTurnstileToken() {
    if (!state.turnstileSiteKey) return Promise.resolve("");

    return loadTurnstile().then(function () {
      return new Promise(function (resolve, reject) {
        var settled = false;
        function ok(token) {
          if (settled) return;
          if (!token || token.length < 20) return;
          settled = true;
          resolve(token);
        }
        function fail(reason) {
          if (settled) return;
          settled = true;
          reject(new Error(reason || "turnstile_failed"));
        }

        var host1 = document.createElement("div");
        host1.setAttribute("aria-hidden", "true");
        host1.style.cssText =
          "position:fixed;left:-9999px;width:1px;height:1px;overflow:hidden";
        document.body.appendChild(host1);
        var wid1 = null;
        var timer1 = setTimeout(function () {
          cleanupTurnstileHost(host1, wid1);
          showManagedChallenge(ok, fail);
        }, 4500);

        try {
          wid1 = window.turnstile.render(host1, {
            sitekey: state.turnstileSiteKey,
            size: "invisible",
            appearance: "execute",
            retry: "auto",
            "retry-interval": 1500,
            callback: function (token) {
              clearTimeout(timer1);
              cleanupTurnstileHost(host1, wid1);
              ok(token);
            },
            "error-callback": function () {
              clearTimeout(timer1);
              cleanupTurnstileHost(host1, wid1);
              showManagedChallenge(ok, fail);
            },
            "timeout-callback": function () {
              clearTimeout(timer1);
              cleanupTurnstileHost(host1, wid1);
              showManagedChallenge(ok, fail);
            },
            "unsupported-callback": function () {
              clearTimeout(timer1);
              cleanupTurnstileHost(host1, wid1);
              showManagedChallenge(ok, fail);
            },
          });
          window.turnstile.execute(wid1);
        } catch (e) {
          clearTimeout(timer1);
          cleanupTurnstileHost(host1, wid1);
          showManagedChallenge(ok, fail);
        }
      });
    });
  }

  function showManagedChallenge(ok, fail) {
    if (document.getElementById("lu-turnstile-modal")) return;
    var wrap = document.createElement("div");
    wrap.id = "lu-turnstile-modal";
    wrap.style.cssText =
      "position:fixed;inset:0;z-index:100001;background:rgba(0,0,0,.35);" +
      "display:flex;align-items:center;justify-content:center;padding:16px";
    /* Only the CF widget strip — no black top/bottom chrome */
    var box = document.createElement("div");
    box.style.cssText =
      "background:#f3f4f6;max-width:320px;width:100%;border-radius:8px;" +
      "padding:10px;box-shadow:0 8px 28px rgba(0,0,0,.18)";
    box.innerHTML =
      "<div id='lu-turnstile-slot' style='display:flex;justify-content:center;min-height:65px'></div>" +
      "<button type='button' id='lu-turnstile-cancel' style='display:block;margin:8px auto 0;border:0;" +
      "background:transparent;color:#64748b;font:12px system-ui;cursor:pointer'>" +
      escapeHtml(t("cancel")) +
      "</button>";
    wrap.appendChild(box);
    document.body.appendChild(wrap);

    var closed = false;
    function close() {
      if (closed) return;
      closed = true;
      try { wrap.remove(); } catch (e) {}
    }
    document.getElementById("lu-turnstile-cancel").onclick = function () {
      close();
      fail("turnstile_cancelled");
    };
    var slot = document.getElementById("lu-turnstile-slot");
    var wid = null;
    try {
      wid = window.turnstile.render(slot, {
        sitekey: state.turnstileSiteKey,
        size: "normal",
        theme: "light",
        language: pageLocale(),
        callback: function (token) {
          close();
          ok(token);
        },
        "error-callback": function () {
          close();
          fail("turnstile_widget_error");
        },
        "expired-callback": function () {
          try {
            if (wid != null) window.turnstile.reset(wid);
          } catch (e) {}
        },
      });
    } catch (e) {
      close();
      fail("turnstile_render_error");
    }
  }


  // —— 8. WebRTC Session Lifecycle ——
  function stopSession(reason) {
    state.connected = false;
    state.connecting = false;
    /* Always restore the page: any end reason, not only escape */
    closeWorkspace();
    var reopen = $("lu-reopen-ws");
    if (reopen) reopen.style.display = "none";
    setAgentState("idle");
    try {
      if (state.dc) state.dc.close();
    } catch (e) {}
    state.dc = null;
    try {
      if (state.pc) state.pc.close();
    } catch (e) {}
    state.pc = null;
    if (state.localStream) {
      state.localStream.getTracks().forEach(function (tr) {
        tr.stop();
      });
      state.localStream = null;
    }
    if (state.remoteAudio) {
      try {
        state.remoteAudio.pause();
        state.remoteAudio.srcObject = null;
        state.remoteAudio.remove();
      } catch (e) {}
      state.remoteAudio = null;
    }
    var warn = $("lu-session-warn");
    if (warn) warn.style.display = "none";
    closeVerifyModal();
  }

  function waitIceComplete(pc) {
    if (pc.iceGatheringState === "complete") return Promise.resolve();
    return new Promise(function (resolve) {
      var done = false;
      function finish() {
        if (done) return;
        done = true;
        resolve();
      }
      pc.addEventListener("icegatheringstatechange", function () {
        if (pc.iceGatheringState === "complete") finish();
      });
      setTimeout(finish, 3000);
    });
  }

  async function startSession() {
    if (state.escaped || state.connecting || state.connected) return;
    state.connecting = true;
    setAgentState("connecting");

    try {
      var tokenPromise = getTurnstileToken();
      state.localStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
        video: false,
      });

      var token = "";
      try {
        token = await tokenPromise;
      } catch (e) {
        stopSession("turnstile");
        setAgentState("breathing", t("tapToStart"));
        return;
      }
      if (state.turnstileSiteKey && (!token || token.length < 20)) {
        stopSession("turnstile_empty");
        setAgentState("breathing", t("tapToStart"));
        return;
      }

      var pc = new RTCPeerConnection({ iceServers: state.iceServers });
      state.pc = pc;

      state.localStream.getTracks().forEach(function (track) {
        pc.addTrack(track, state.localStream);
      });

      try {
        state.dc = pc.createDataChannel("rtvi-ai");
        state.dc.onmessage = onDataMessage;
      } catch (e) {}

      pc.ondatachannel = function (ev) {
        state.dc = ev.channel;
        state.dc.onmessage = onDataMessage;
      };

      pc.ontrack = function (ev) {
        var stream = ev.streams && ev.streams[0];
        if (!stream) return;
        var audio = document.createElement("audio");
        audio.autoplay = true;
        audio.setAttribute("playsinline", "true");
        audio.srcObject = stream;
        audio.style.display = "none";
        document.body.appendChild(audio);
        state.remoteAudio = audio;
        var p = audio.play();
        if (p && p.catch) {
          p.catch(function () {
            setAgentState("breathing", t("tapToStart"));
          });
        }
        setAgentState("listening");
      };

      pc.onconnectionstatechange = function () {
        var s = pc.connectionState;
        if (s === "failed" || s === "closed" || s === "disconnected") {
          if (state.connected) stopSession(s);
        }
        if (s === "connected") {
          state.connected = true;
          state.connecting = false;
          setAgentState("breathing");
        }
      };

      var offer = await pc.createOffer({
        offerToReceiveAudio: true,
        offerToReceiveVideo: false,
      });
      await pc.setLocalDescription(offer);
      await waitIceComplete(pc);

      var local = pc.localDescription;
      var res = await fetch(apiBase + "/api/offer", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sdp: local.sdp,
          type: local.type || "offer",
          key: widgetKey,
          turnstile_token: token,
          t: token,
          visitor_id: visitorId,
          lang: lang,
          landing_url: String(location.href || "").slice(0, 500),
          referrer: String(document.referrer || "").slice(0, 500),
          available_sections: Object.keys(state.sectionMap || {}),
        }),
      });

      var body = await res.json().catch(function () {
        return {};
      });
      if (!res.ok) {
        stopSession("offer_" + res.status);
        return;
      }

      await pc.setRemoteDescription({
        sdp: body.sdp,
        type: body.type || "answer",
      });
    } catch (err) {
      stopSession("error");
      // Honest non-blocking prompt instead of browser alert()
      setAgentState("breathing", t("tapToStart"));
    } finally {
      state.connecting = false;
    }
  }

  async function boot() {
    ensureChrome();
    extractHostTheme();
    scanPageSections();
    setTimeout(scanPageSections, 1200);

    var cfg = await loadConfig();
    /* Site stays untouched on load. Workspace opens only when the agent shows the first scene. */

    if (!state.voiceEnabled) return;

    if (state.turnstileSiteKey) {
      loadTurnstile().catch(function () {});
    }

    setupDwellObservers();

    var started = false;
    function tryStart() {
      if (started || state.escaped || state.connecting || state.connected)
        return;
      started = true;
      startSession().catch(function () {
        started = false;
      });
    }

    tryStart();

    window.addEventListener(
      "pointerdown",
      function () {
        if (state.remoteAudio && state.remoteAudio.paused) {
          state.remoteAudio.play().catch(function () {});
        }
        if (!state.connected && !state.connecting && !state.escaped) {
          started = false;
          tryStart();
        }
      },
      true
    );

    window.addEventListener("pagehide", function () {
      stopSession("pagehide");
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }

  window.LUGenUI = {
    sendUi: function (data) {
      sendClientMessage({ type: "ui_user_interaction", data: data || {} });
    },
    openWorkspace: function (sec) {
      renderWorkspaceScene(sec || "services", null, state.activePrefill);
    },
    closeWorkspace: closeWorkspace,
    setAgentState: setAgentState,
    stop: stopSession,
  };
})();
