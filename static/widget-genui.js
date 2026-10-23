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
  function extractHostTheme() {
    try {
      var bodyStyle = window.getComputedStyle(document.body);
      if (bodyStyle && bodyStyle.fontFamily) {
        state.theme.fontSans = bodyStyle.fontFamily;
      }
      var h1 = qs("h1, h2");
      if (h1) {
        var h1Style = window.getComputedStyle(h1);
        if (h1Style && h1Style.fontFamily) {
          state.theme.fontDisplay = h1Style.fontFamily;
        }
      }
      var cta = qs(
        "a.btn, a.button, button[type='submit'], [class*='cta'], header a[href*='#contact']"
      );
      if (cta) {
        var bg = window.getComputedStyle(cta).backgroundColor;
        if (
          bg &&
          bg !== "rgba(0, 0, 0, 0)" &&
          bg !== "transparent" &&
          bg !== "rgb(255, 255, 255)" &&
          bg !== "rgb(0, 0, 0)"
        ) {
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
    if (!rootEl) return fallbackItems;
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
    return items.length >= 2 ? items : fallbackItems;
  }

  function getDefaultCatalog() {
    var loc = pageLocale();
    if (loc === "ro") {
      return {
        services: [
          {
            id: "voice-ai",
            title: "Agenți Vocali AI 24/7 (GSM & WebRTC)",
            description: "Preluarea apelurilor și consultarea vizitatorilor pe site în timp real, fără timp de așteptare.",
            badge: "Live S2S",
          },
          {
            id: "crm-sync",
            title: "Integrare CRM & Google Calendar",
            description: "Calificarea lead-urilor, programări automate în calendar și rezumat după fiecare apel.",
            badge: "End-to-End",
          },
          {
            id: "omnichannel",
            title: "Automatizare Messengers & Chat",
            description: "Răspunsuri instantanee pe Telegram, WhatsApp, Instagram și site cu memorie unică a clientului.",
            badge: "Omnichannel",
          },
        ],
        pricing: [
          {
            id: "starter",
            title: "Start / Pilot",
            description: "Agent vocal sau chat pe un canal, calificare lead-uri și notificări în Telegram/CRM.",
            badge: "Lansare rapidă",
          },
          {
            id: "business",
            title: "Business System",
            description: "Telefonie GSM + Web GenUI + integrare completă cu CRM, Calendar și baza de cunoștințe.",
            badge: "Cel mai ales",
          },
          {
            id: "enterprise",
            title: "Custom / Enterprise",
            description: "Arhitectură dedicată, ERP/MIS custom și automatizarea proceselor interne complexe.",
            badge: "La cheie",
          },
        ],
        cases: [
          {
            id: "case-b2b",
            title: "Producție & B2B: 0 apeluri pierdute",
            description: "Preluarea a 100% din solicitările din afara orelor de program și creșterea conversiei în întâlniri cu +35%.",
            badge: "+35% conversie",
          },
          {
            id: "case-clinic",
            title: "Clinici & Servicii: Programare automată",
            description: "Agentul verifică sloturile libere în Google Calendar și confirmă programarea în 40 de secunde.",
            badge: "24/7 Booking",
          },
          {
            id: "case-auto",
            title: "Auto & Imobiliare: Calificare instantanee",
            description: "Filtrarea solicitărilor, calculul bugetului și transferul doar al clienților calificați către manageri.",
            badge: "ROI < 14 zile",
          },
        ],
      };
    }
    if (loc === "ru") {
      return {
        services: [
          {
            id: "voice-ai",
            title: "Голосовые ИИ-агенты 24/7 (GSM и Сайт)",
            description: "Живое общение по телефону и на сайте с мгновенной реакцией экрана, записью и суммаризацией.",
            badge: "Live Voice",
          },
          {
            id: "crm-sync",
            title: "Интеграция с CRM и Календарём",
            description: "Автоматическая квалификация лида, проверка свободных окон и бронь встреч без участия менеджера.",
            badge: "Авто-воронка",
          },
          {
            id: "omnichannel",
            title: "Омниканальные ИИ-сотрудники",
            description: "Единая память клиента между телефонией, сайтом, Telegram, WhatsApp и вашей CRM-системой.",
            badge: "360° Память",
          },
        ],
        pricing: [
          {
            id: "starter",
            title: "Старт / Пилот",
            description: "Запуск голосового или текстового агента, сбор квалифицированных заявок и передача в CRM / Telegram.",
            badge: "Быстрый старт",
          },
          {
            id: "business",
            title: "Бизнес-система",
            description: "Связка GSM-телефонии + интерактивного сайта + двусторонняя интеграция с CRM и Google Calendar.",
            badge: "Оптимальный",
          },
          {
            id: "enterprise",
            title: "Корпоративный / Custom",
            description: "Кастомная архитектура, собственные CRM/ERP-модули и глубокая автоматизация отделов продаж.",
            badge: "Под ключ",
          },
        ],
        cases: [
          {
            id: "case-b2b",
            title: "Производство и B2B: возврат упущенных заявок",
            description: "Мгновенная обработка 100% звонков и обращений в нерабочее время, рост конверсии в целевой созвон на 35%.",
            badge: "+35% к лидам",
          },
          {
            id: "case-clinic",
            title: "Клиники и сервис: запись без администратора",
            description: "Агент сам сверяет слоты в календаре, записывает клиента и отправляет SMS-подтверждение за 45 секунд.",
            badge: "24/7 Запись",
          },
          {
            id: "case-auto",
            title: "Недвижимость и Авто: квалификация до отдела продаж",
            description: "ИИ выявляет бюджет, сроки и задачу клиента, передавая менеджерам уже готовых к сделке покупателей.",
            badge: "Окупаемость < 14 дн.",
          },
        ],
      };
    }
    return {
      services: [
        {
          id: "voice-ai",
          title: "24/7 Voice AI Agents (GSM & Web)",
          description: "Real-time voice consultation on phone lines and your website with live screen orchestration.",
          badge: "Live S2S",
        },
        {
          id: "crm-sync",
          title: "CRM & Calendar Automation",
          description: "Automated lead qualification, real-time slot checking, and instant appointment booking.",
          badge: "End-to-End",
        },
        {
          id: "omnichannel",
          title: "Omnichannel Customer Memory",
          description: "Unified customer context across phone calls, web sessions, messengers, and your CRM.",
          badge: "360° Context",
        },
      ],
      pricing: [
        {
          id: "starter",
          title: "Starter / Pilot",
          description: "Single-channel AI agent with lead qualification and instant CRM/Telegram notifications.",
          badge: "Fast launch",
        },
        {
          id: "business",
          title: "Business Suite",
          description: "Full GSM + Web GenUI agent with live Google Calendar booking and CRM pipeline sync.",
          badge: "Most popular",
        },
        {
          id: "enterprise",
          title: "Enterprise Custom",
          description: "Bespoke multi-agent workflows, ERP/CRM integrations, and custom business logic.",
          badge: "Turnkey",
        },
      ],
      cases: [
        {
          id: "case-b2b",
          title: "Manufacturing & B2B: Zero Missed Demand",
          description: "Captured 100% of after-hours inquiries and increased qualified pipeline conversion by 35%.",
          badge: "+35% conversion",
        },
        {
          id: "case-clinic",
          title: "Healthcare & Services: Automated Booking",
          description: "Real-time calendar slot verification and booking completed in under 45 seconds.",
          badge: "24/7 Booking",
        },
        {
          id: "case-auto",
          title: "Real Estate & Auto: Instant Qualification",
          description: "Pre-qualifies budget and timeline by voice before handing over warm buyers to sales.",
          badge: "Payback < 14d",
        },
      ],
    };
  }

  function buildCatalog() {
    var def = getDefaultCatalog();
    var custom = window.LU_CATALOG || (state.catalog && state.catalog) || {};
    var map = state.sectionMap || {};
    return {
      services:
        custom.services || extractCardsFromSection(map.services, def.services),
      pricing:
        custom.pricing || extractCardsFromSection(map.pricing, def.pricing),
      cases: custom.cases || extractCardsFromSection(map.cases, def.cases),
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
    if (_wsRoot) return _wsRoot;
    extractHostTheme();
    _wsHost = document.getElementById("lu-workspace-host");
    if (!_wsHost) {
      _wsHost = document.createElement("div");
      _wsHost.id = "lu-workspace-host";
      document.body.appendChild(_wsHost);
    }
    _wsRoot = _wsHost.shadowRoot || _wsHost.attachShadow({ mode: "open" });
    var style = document.createElement("style");
    style.textContent = [
      ":host { all: initial; }",
      ".lu-backdrop {",
      "  position: fixed; inset: 0; z-index: 99990;",
      "  background: rgba(8, 12, 20, 0.72);",
      "  backdrop-filter: blur(18px); -webkit-backdrop-filter: blur(18px);",
      "  display: none; align-items: center; justify-content: center;",
      "  padding: 64px 16px 104px; box-sizing: border-box;",
      "  font-family: " + state.theme.fontSans + ";",
      "  color: #f8fafc; opacity: 0; transition: opacity 0.24s ease;",
      "}",
      ".lu-backdrop.open { display: flex; opacity: 1; }",
      ".lu-stage {",
      "  width: 100%; max-width: 880px; max-height: calc(100vh - 176px);",
      "  overflow-y: auto; border-radius: 24px;",
      "  background: linear-gradient(155deg, rgba(15, 23, 42, 0.94), rgba(9, 14, 26, 0.97));",
      "  border: 1px solid rgba(255, 255, 255, 0.14);",
      "  box-shadow: 0 28px 90px rgba(0, 0, 0, 0.55);",
      "  padding: 24px 28px 28px; box-sizing: border-box;",
      "}",
      ".lu-top {",
      "  display: flex; align-items: center; justify-content: space-between;",
      "  gap: 12px; padding-bottom: 16px; margin-bottom: 20px;",
      "  border-bottom: 1px solid rgba(255, 255, 255, 0.1);",
      "  flex-wrap: wrap;",
      "}",
      ".lu-tabs { display: flex; gap: 6px; flex-wrap: wrap; }",
      ".lu-tab {",
      "  padding: 7px 13px; border-radius: 999px; border: 1px solid rgba(255,255,255,0.12);",
      "  background: rgba(255,255,255,0.04); color: #cbd5e1;",
      "  font: 600 12px/1.2 inherit; cursor: pointer; transition: all .18s;",
      "}",
      ".lu-tab:hover { background: rgba(255,255,255,0.1); color: #fff; }",
      ".lu-tab.active {",
      "  background: " + state.theme.accent + "; color: #fff; border-color: transparent;",
      "}",
      ".lu-min-btn {",
      "  padding: 7px 12px; border-radius: 999px; border: 1px solid rgba(255,255,255,0.16);",
      "  background: transparent; color: #94a3b8; font: 500 12px/1.2 inherit; cursor: pointer;",
      "}",
      ".lu-min-btn:hover { color: #fff; border-color: rgba(255,255,255,0.35); }",
      ".lu-kicker {",
      "  font-size: 11px; letter-spacing: 0.14em; text-transform: uppercase;",
      "  color: #38bdf8; margin: 0 0 6px; font-weight: 700;",
      "}",
      ".lu-title {",
      "  font-family: " + state.theme.fontDisplay + ";",
      "  font-size: clamp(1.35rem, 2.6vw, 1.8rem); font-weight: 700;",
      "  margin: 0 0 6px; color: #fff; letter-spacing: -0.02em;",
      "}",
      ".lu-sub { font-size: 0.94rem; color: #94a3b8; margin: 0 0 20px; line-height: 1.45; }",
      ".lu-grid {",
      "  display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));",
      "  gap: 14px;",
      "}",
      ".lu-card {",
      "  padding: 18px; border-radius: 18px;",
      "  background: rgba(255, 255, 255, 0.04);",
      "  border: 1px solid rgba(255, 255, 255, 0.1);",
      "  display: flex; flex-direction: column; justify-content: space-between;",
      "  gap: 12px; transition: transform 0.2s, border-color 0.2s, box-shadow 0.2s;",
      "}",
      ".lu-card:hover { transform: translateY(-2px); border-color: rgba(255,255,255,0.24); }",
      ".lu-card.highlight {",
      "  border-color: #22d3ee; background: rgba(34, 211, 238, 0.08);",
      "  box-shadow: 0 0 0 2px rgba(34, 211, 238, 0.35);",
      "}",
      ".lu-badge {",
      "  display: inline-block; align-self: flex-start; padding: 3px 9px;",
      "  border-radius: 999px; font-size: 11px; font-weight: 600;",
      "  background: rgba(56, 189, 248, 0.16); color: #7dd3fc;",
      "}",
      ".lu-card h3 { margin: 4px 0 6px; font-size: 1.05rem; color: #fff; }",
      ".lu-card p { margin: 0; font-size: 0.88rem; color: #cbd5e1; line-height: 1.45; }",
      ".lu-card-btn {",
      "  margin-top: 6px; padding: 9px 12px; border-radius: 10px;",
      "  border: 1px solid rgba(255,255,255,0.16); background: rgba(255,255,255,0.06);",
      "  color: #fff; font: 600 12px/1.2 inherit; cursor: pointer; text-align: center;",
      "}",
      ".lu-card-btn:hover { background: " + state.theme.accent + "; border-color: transparent; }",
      ".lu-roi-grid {",
      "  display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));",
      "  gap: 18px; align-items: stretch;",
      "}",
      ".lu-roi-controls, .lu-roi-summary {",
      "  padding: 18px; border-radius: 18px; background: rgba(255,255,255,0.04);",
      "  border: 1px solid rgba(255,255,255,0.1);",
      "}",
      ".lu-control-group { margin-bottom: 14px; }",
      ".lu-control-group:last-child { margin-bottom: 0; }",
      ".lu-control-head { display: flex; justify-content: space-between; font-size: 0.86rem; margin-bottom: 6px; color: #cbd5e1; }",
      ".lu-control-head strong { color: #fff; font-size: 0.95rem; }",
      ".lu-range { width: 100%; accent-color: #22d3ee; cursor: pointer; }",
      ".lu-roi-row {",
      "  display: flex; justify-content: space-between; align-items: baseline;",
      "  padding: 11px 0; border-bottom: 1px solid rgba(255,255,255,0.08); font-size: 0.9rem;",
      "}",
      ".lu-roi-row:last-of-type { border-bottom: 0; }",
      ".lu-roi-row.hi strong { color: #34d399; font-size: 1.35rem; font-weight: 700; }",
      ".lu-form { display: grid; gap: 14px; max-width: 480px; }",
      ".lu-field label { display: block; font-size: 0.84rem; color: #cbd5e1; margin-bottom: 6px; }",
      ".lu-field input {",
      "  width: 100%; padding: 11px 14px; border-radius: 12px;",
      "  border: 1px solid rgba(255,255,255,0.18); background: rgba(15, 23, 42, 0.85);",
      "  color: #fff; font: 500 14px/1.3 inherit; box-sizing: border-box;",
      "}",
      ".lu-field input:focus { outline: 2px solid #22d3ee; border-color: transparent; }",
      ".lu-cta-btn {",
      "  padding: 12px 18px; border-radius: 12px; border: 0;",
      "  background: " + state.theme.accent + "; color: #fff;",
      "  font: 600 14px/1.3 inherit; cursor: pointer; margin-top: 6px;",
      "}",
      "@media (max-width: 640px) {",
      "  .lu-backdrop { padding: 54px 10px 92px; }",
      "  .lu-stage { padding: 18px 16px 22px; border-radius: 20px; }",
      "}",
    ].join("\n");

    var backdrop = document.createElement("div");
    backdrop.className = "lu-backdrop";
    backdrop.id = "lu-ws-backdrop";
    backdrop.innerHTML =
      "<div class='lu-stage'>" +
      "  <div class='lu-top'>" +
      "    <div class='lu-tabs' id='lu-ws-tabs'></div>" +
      "    <button type='button' class='lu-min-btn' id='lu-ws-min'>" +
      escapeHtml(t("minimize")) +
      "</button>" +
      "  </div>" +
      "  <div id='lu-ws-body'></div>" +
      "</div>";

    _wsRoot.appendChild(style);
    _wsRoot.appendChild(backdrop);

    _wsRoot.getElementById("lu-ws-min").addEventListener("click", function () {
      closeWorkspace();
    });

    return _wsRoot;
  }

  function openWorkspace() {
    ensureWorkspace();
    state.workspaceOpen = true;
    var bd = _wsRoot.getElementById("lu-ws-backdrop");
    if (bd) bd.classList.add("open");
    var reopenBtn = $("lu-reopen-ws");
    if (reopenBtn) reopenBtn.style.display = "none";
  }

  function closeWorkspace() {
    if (!_wsRoot) return;
    state.workspaceOpen = false;
    var bd = _wsRoot.getElementById("lu-ws-backdrop");
    if (bd) bd.classList.remove("open");
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
    var titleKey = "section_" + sectionKey;
    var hi = (highlightId || "").toLowerCase();
    var cardsHtml = (items || [])
      .map(function (item, idx) {
        var isHi =
          (hi &&
            (String(item.id).toLowerCase().indexOf(hi) !== -1 ||
              String(item.title).toLowerCase().indexOf(hi) !== -1)) ||
          (!hi && sectionKey === "pricing" && idx === 1);
        return (
          "<div class='lu-card" +
          (isHi ? " highlight" : "") +
          "' data-card-id='" +
          escapeHtml(item.id) +
          "'>" +
          "<div>" +
          (item.badge
            ? "<span class='lu-badge'>" +
              escapeHtml(isHi ? t("recommended") + " · " + item.badge : item.badge) +
              "</span>"
            : isHi
              ? "<span class='lu-badge'>" + escapeHtml(t("recommended")) + "</span>"
              : "") +
          "<h3>" +
          escapeHtml(item.title) +
          "</h3>" +
          "<p>" +
          escapeHtml(item.description) +
          "</p>" +
          "</div>" +
          "<button type='button' class='lu-card-btn' data-select-title='" +
          escapeHtml(item.title) +
          "'>" +
          escapeHtml(t("selectItem")) +
          "</button>" +
          "</div>"
        );
      })
      .join("");

    return (
      "<div>" +
      "<p class='lu-kicker'>LabUpgrade AI</p>" +
      "<h2 class='lu-title'>" +
      escapeHtml(t(titleKey)) +
      "</h2>" +
      "<div class='lu-grid'>" +
      cardsHtml +
      "</div>" +
      "</div>"
    );
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

  function renderBookingHtml(prefill) {
    prefill = prefill || {};
    var nameVal = prefill.client_name || prefill.name || "";
    var phoneVal = prefill.phone || prefill.client_phone || "";
    var slotVal =
      prefill.start_time ||
      prefill.slot ||
      prefill.request_summary ||
      "";
    return (
      "<div>" +
      "<p class='lu-kicker'>" +
      escapeHtml(t("bookKicker")) +
      "</p>" +
      "<h2 class='lu-title'>" +
      escapeHtml(t("bookTitle")) +
      "</h2>" +
      "<p class='lu-sub'>" +
      escapeHtml(t("bookSub")) +
      "</p>" +
      "<form class='lu-form' id='lu-ws-book-form'>" +
      "  <div class='lu-field'>" +
      "    <label>" +
      escapeHtml(t("bookName")) +
      "</label>" +
      "    <input type='text' name='client_name' id='lu-book-name' placeholder='" +
      escapeHtml(t("bookNamePh")) +
      "' value='" +
      escapeHtml(nameVal) +
      "'/>" +
      "  </div>" +
      "  <div class='lu-field'>" +
      "    <label>" +
      escapeHtml(t("bookPhone")) +
      "</label>" +
      "    <input type='tel' name='phone' id='lu-book-phone' required placeholder='" +
      escapeHtml(t("bookPhonePh")) +
      "' value='" +
      escapeHtml(phoneVal) +
      "'/>" +
      "  </div>" +
      "  <div class='lu-field'>" +
      "    <label>" +
      escapeHtml(t("bookSlot")) +
      "</label>" +
      "    <input type='text' name='request_summary' id='lu-book-slot' placeholder='" +
      escapeHtml(t("bookSlotPh")) +
      "' value='" +
      escapeHtml(slotVal) +
      "'/>" +
      "  </div>" +
      "  <button type='submit' class='lu-cta-btn' id='lu-book-submit'>" +
      escapeHtml(t("bookSubmit")) +
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

    body.querySelectorAll("[data-select-title]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var itemTitle = btn.getAttribute("data-select-title");
        sendClientMessage({
          type: "ui_user_interaction",
          data: {
            interaction: "item_selected",
            section: sectionKey,
            item: itemTitle,
            description: "Visitor clicked option: " + itemTitle,
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
      var phoneInput = _wsRoot.getElementById("lu-book-phone");
      if (phoneInput) {
        setTimeout(function () {
          try {
            phoneInput.focus();
          } catch (e) {}
        }, 120);
      }
      if (form) {
        form.addEventListener("submit", function (ev) {
          ev.preventDefault();
          var nameVal = (_wsRoot.getElementById("lu-book-name").value || "").trim();
          var phoneVal = (_wsRoot.getElementById("lu-book-phone").value || "").trim();
          var slotVal = (_wsRoot.getElementById("lu-book-slot").value || "").trim();
          if (!phoneVal || phoneVal.replace(/\D/g, "").length < 8) {
            phoneInput.style.outline = "2px solid #f87171";
            return;
          }
          var btn = _wsRoot.getElementById("lu-book-submit");
          if (btn) {
            btn.disabled = true;
            btn.textContent = t("bookSent");
          }
          sendClientMessage({
            type: "ui_user_interaction",
            data: {
              interaction: "phone_verified",
              phone: phoneVal,
              client_name: nameVal,
              request_summary: slotVal,
              description:
                "Visitor submitted booking form on screen: phone=" +
                phoneVal +
                (nameVal ? ", name=" + nameVal : "") +
                (slotVal ? ", note=" + slotVal : ""),
            },
          });
        });
      }
    }
  }

  function renderWorkspaceScene(sectionKey, highlight, prefill, components) {
    ensureWorkspace();
    var key = (sectionKey || "services").toLowerCase();
    if (key === "hero" || key === "contacts") {
      key = key === "contacts" ? "booking_widget" : "services";
    }
    state.activeSection = key;
    state.activeHighlight = highlight || null;
    if (prefill && typeof prefill === "object") {
      Object.keys(prefill).forEach(function (k) {
        if (prefill[k] != null) state.activePrefill[k] = prefill[k];
      });
    }

    renderTabs(key);
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

    // ROI, Booking without native form, or explicit Workspace mode → render in isolated Shadow DOM Workspace
    var el = findSection(key);
    var forceWorkspace =
      uiMode !== "navigator" ||
      key === "roi_calculator" ||
      key === "booking_widget" ||
      !el ||
      (Array.isArray(components) && components.length > 0);

    if (forceWorkspace) {
      renderWorkspaceScene(key, highlight, prefill, components);
    } else if (el) {
      closeWorkspace();
      try {
        el.scrollIntoView({ behavior: "smooth", block: "center" });
      } catch (e) {}
      flashHighlight(el, 2600);
      if (highlight) {
        var tEl =
          el.querySelector("#" + highlight) ||
          el.querySelector('[data-id="' + highlight + '"]');
        if (tEl) flashHighlight(tEl, 3000);
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

  function showVerifyModal(payload) {
    if ($("lu-verify-modal")) return;
    var wrap = document.createElement("div");
    wrap.id = "lu-verify-modal";
    wrap.style.cssText =
      "position:fixed;inset:0;z-index:100002;background:rgba(0,0,0,.65);" +
      "display:flex;align-items:center;justify-content:center;padding:16px;backdrop-filter:blur(8px)";
    var box = document.createElement("div");
    box.style.cssText =
      "background:#0f172a;color:#f8fafc;max-width:360px;width:100%;border-radius:18px;" +
      "padding:22px;font:14px/1.45 system-ui,sans-serif;border:1px solid rgba(255,255,255,.15)";
    var msg = (payload && payload.message) || t("verifyDefault");
    box.innerHTML =
      "<h3 style='margin:0 0 8px;font-size:16px'>" +
      escapeHtml(t("verifyTitle")) +
      "</h3>" +
      "<p style='margin:0 0 14px;color:#cbd5e1;font-size:13px'>" +
      escapeHtml(msg) +
      "</p>" +
      "<input id='lu-verify-phone' type='tel' placeholder='+373...' " +
      "style='width:100%;padding:11px;border:1px solid rgba(255,255,255,.2);background:#1e293b;color:#fff;border-radius:10px;box-sizing:border-box'/>" +
      "<button id='lu-verify-ok' type='button' style='margin-top:12px;width:100%;padding:11px;" +
      "border:0;border-radius:10px;background:#10b981;color:#fff;font-weight:600;cursor:pointer'>" +
      escapeHtml(t("verifyBtn")) +
      "</button>";
    wrap.appendChild(box);
    document.body.appendChild(wrap);
    $("lu-verify-ok").onclick = function () {
      var phone = ($("lu-verify-phone").value || "").trim();
      if (phone.replace(/\D/g, "").length < 8) return;
      sendClientMessage({
        type: "ui_user_interaction",
        data: { interaction: "phone_verified", phone: phone },
      });
      wrap.remove();
    };
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
    var L = pageLocale();
    var wrap = document.createElement("div");
    wrap.id = "lu-turnstile-modal";
    wrap.style.cssText =
      "position:fixed;inset:0;z-index:100001;background:rgba(0,0,0,.45);" +
      "display:flex;align-items:flex-end;justify-content:center;padding:16px 16px 100px";
    var box = document.createElement("div");
    box.style.cssText =
      "background:#0b0f14;color:#e5e7eb;max-width:300px;width:100%;border-radius:14px;" +
      "padding:12px;font:13px/1.35 system-ui,sans-serif;text-align:center;" +
      "border:1px solid rgba(255,255,255,.1);box-shadow:0 12px 40px rgba(0,0,0,.4)";
    box.innerHTML =
      "<p style='margin:0 0 10px;font-weight:600'>" +
      escapeHtml(t("checkTitle")) +
      "</p>" +
      "<div id='lu-turnstile-slot' style='display:flex;justify-content:center;min-height:65px'></div>" +
      "<button type='button' id='lu-turnstile-cancel' style='margin-top:8px;border:0;background:transparent;" +
      "color:#94a3b8;font:12px system-ui;cursor:pointer'>" +
      escapeHtml(t("cancel")) +
      "</button>";
    wrap.appendChild(box);
    document.body.appendChild(wrap);

    var closed = false;
    function close() {
      if (closed) return;
      closed = true;
      try {
        wrap.remove();
      } catch (e) {}
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
        theme: "dark",
        language: L,
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
    if (
      reason === "escape" ||
      reason === "pagehide" ||
      reason === "session_ended" ||
      reason === "session_blocked"
    ) {
      closeWorkspace();
      var reopen = $("lu-reopen-ws");
      if (reopen) reopen.style.display = "none";
    }
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
