/**
 * LabUpgrade Voice Widget — Series (client sites)
 * POST /api/offer (WebRTC + RTVI). Auto-maps page sections; optional data-lu-section.
 * Thinking Orb (thinking-orbs) = site "mouth" — bottom center.
 *
 * Embed:
 *   <div id="labupgrade-voice-widget"
 *        data-key="YOUR_WEB_CHANNEL_KEY"
 *        data-server="voice.labupgrade.in"></div>
 *   <script src="https://voice.labupgrade.in/widget-genui.js" defer></script>
 *
 * Optional anchors on the page:
 *   <section data-lu-section="pricing">...</section>
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

  var serverAttr = (container.getAttribute("data-server") || "")
    .trim()
    .toLowerCase()
    .replace(/^(https?|wss?):\/\//, "")
    .replace(/[/?#].*$/, "");
  var voiceServer = /^[a-z0-9-]+(\.[a-z0-9-]+)+$/.test(serverAttr)
    ? serverAttr
    : "voice.labupgrade.in";
  var apiBase = "https://" + voiceServer;

  var ICE = [{ urls: "stun:stun.l.google.com:19302" }];

  var visitorId = "";
  try {
    visitorId = localStorage.getItem("lu_visitor_id") || "";
    if (!visitorId) {
      visitorId =
        window.crypto && crypto.randomUUID
          ? crypto.randomUUID()
          : "v" + Date.now().toString(36) + Math.random().toString(36).slice(2, 12);
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

  var state = {
    turnstileSiteKey: "",
    voiceEnabled: true,
    pc: null,
    localStream: null,
    remoteAudio: null,
    dc: null,
    connecting: false,
    connected: false,
    escaped: false,
    agentState: "idle",
    dwellSeen: {},
    dwellTimers: {},
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

  // —— Section map (series): explicit data-lu-section wins, else heuristics ——
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
    ],
    booking_widget: [
      "booking",
      "book",
      "schedule",
      "calendar",
      "programare",
      "запис",
      "appointment",
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

  state.sectionMap = {};

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
        cur.matches("section,article,[data-section],[data-lu-section],.section,.t-section,main > div")
      ) {
        return cur;
      }
      cur = cur.parentElement;
    }
    return el;
  }

  function scanPageSections() {
    var map = {};
    // Explicit anchors
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
      var byId = document.getElementById(key) || document.getElementById("section-" + key);
      if (byId) map[key] = nearestSectionRoot(byId);
    });

    // Heuristic via headings
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

    // Forms → booking/contacts
    if (!map.booking_widget) {
      var form =
        document.querySelector("form[data-lu-section='booking_widget']") ||
        document.querySelector("form input[type='tel']") ||
        document.querySelector("form input[name*='phone' i]");
      if (form) map.booking_widget = nearestSectionRoot(form.closest("form") || form);
    }
    if (!map.contacts) {
      var mail = document.querySelector("a[href^='mailto:']");
      if (mail) map.contacts = nearestSectionRoot(mail);
    }

    state.sectionMap = map;
    console.info(
      "[LU] sections",
      Object.keys(map).map(function (k) {
        return k;
      })
    );
    return map;
  }

  function findSection(section) {
    if (!section) return null;
    var key = String(section).trim().toLowerCase();
    if (state.sectionMap && state.sectionMap[key]) return state.sectionMap[key];
    return (
      document.querySelector('[data-lu-section="' + key + '"]') ||
      document.querySelector('[data-section="' + key + '"]') ||
      document.getElementById(key) ||
      document.getElementById("section-" + key)
    );
  }

  function focusSection(section, highlight) {
    /* Series: no page scrolling. Pin attention near the orb ("mouth") or highlight in place. */
    var el = findSection(section);
    document.documentElement.setAttribute("data-lu-active-section", section || "");

    var target = null;
    if (highlight) {
      target =
        findTarget(null, highlight) ||
        (el &&
          (el.querySelector("#" + highlight) ||
            el.querySelector('[data-id="' + highlight + '"]') ||
            el.querySelector('[data-lu-id="' + highlight + '"]')));
    }
    if (!target) target = el;

    showSectionDock(section, el, target);

    if (target) flashHighlight(target, 2800);
    else if (el) flashHighlight(el, 1800);

    try {
      window.dispatchEvent(
        new CustomEvent("lu:navigate", {
          detail: { section: section, highlight: highlight || null, mode: "series_dock" },
        })
      );
    } catch (e) {}
    return el;
  }

  function showSectionDock(section, sourceEl, highlightEl) {
    var dock = $("lu-section-dock");
    if (!dock) {
      dock = document.createElement("div");
      dock.id = "lu-section-dock";
      dock.style.cssText =
        "position:fixed;left:50%;bottom:96px;transform:translateX(-50%);" +
        "z-index:99997;width:min(440px,calc(100vw - 24px));max-height:42vh;" +
        "overflow:auto;border-radius:16px;padding:12px 14px;" +
        "background:#fff;color:#0f172a;box-shadow:0 12px 40px rgba(0,0,0,.22);" +
        "border:1px solid rgba(15,23,42,.08);display:none;font:14px/1.4 system-ui,sans-serif";
      document.body.appendChild(dock);
    }
    dock.innerHTML = "";
    var head = document.createElement("div");
    head.style.cssText =
      "display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:8px";
    var title = document.createElement("div");
    title.style.cssText = "font:700 13px/1.2 system-ui";
    title.textContent = String(section || "section").replace(/_/g, " ");
    var close = document.createElement("button");
    close.type = "button";
    close.textContent = "✕";
    close.style.cssText =
      "border:0;background:#f1f5f9;width:28px;height:28px;border-radius:8px;cursor:pointer";
    close.onclick = function () {
      dock.style.display = "none";
    };
    head.appendChild(title);
    head.appendChild(close);
    dock.appendChild(head);

    if (sourceEl) {
      var clone = sourceEl.cloneNode(true);
      clone.querySelectorAll("script").forEach(function (s) {
        s.remove();
      });
      clone.style.maxHeight = "none";
      clone.style.overflow = "visible";
      var body = document.createElement("div");
      body.style.cssText = "max-height:calc(42vh - 40px);overflow:auto";
      body.appendChild(clone);
      dock.appendChild(body);
    } else {
      var miss = document.createElement("p");
      miss.style.opacity = "0.7";
      miss.textContent =
        "Section not found on page. Add data-lu-section=\"" +
        String(section || "") +
        "\" for a precise match.";
      dock.appendChild(miss);
    }
    dock.style.display = "block";
  }

  function ensureChrome() {
    if (!$("lu-escape-voice")) {
      var btn = document.createElement("button");
      btn.id = "lu-escape-voice";
      btn.type = "button";
      btn.textContent = "Не хочу говорить";
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

    // Site "mouth": Thinking Orb — bottom center
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
        "pointer-events:auto;cursor:default";
      var label = document.createElement("div");
      label.id = "lu-voice-orb-label";
      label.style.cssText =
        "font:600 11px/1.2 system-ui,sans-serif;color:#0f172a;" +
        "background:rgba(255,255,255,.88);padding:2px 8px;border-radius:999px;" +
        "max-width:160px;text-align:center;opacity:0;transition:opacity .2s;" +
        "box-shadow:0 2px 8px rgba(0,0,0,.12)";
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

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.src = src;
      s.async = true;
      s.onload = function () {
        resolve();
      };
      s.onerror = function () {
        reject(new Error(src));
      };
      document.head.appendChild(s);
    });
  }

  function loadModule(src) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.type = "module";
      s.textContent =
        'import * as M from "' +
        src +
        '"; window.__LU_ORB_MOD = M; window.dispatchEvent(new Event("lu-orb-mod"));';
      var done = false;
      function onEvt() {
        if (done) return;
        done = true;
        window.removeEventListener("lu-orb-mod", onEvt);
        resolve(window.__LU_ORB_MOD);
      }
      window.addEventListener("lu-orb-mod", onEvt);
      s.onerror = function () {
        if (done) return;
        done = true;
        reject(new Error("module " + src));
      };
      document.head.appendChild(s);
      setTimeout(function () {
        if (!done) {
          done = true;
          reject(new Error("module timeout"));
        }
      }, 12000);
    });
  }

  function loadThinkingOrbs() {
    if (window.ThinkingOrb && window.React && window.ReactDOM && window.ReactDOM.createRoot) {
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
        if (!window.ThinkingOrb) {
          console.warn("[LU] thinking-orbs not on window after load");
        } else {
          console.info("[LU] thinking-orbs ready");
        }
        resolve();
      }
      window.addEventListener("lu-orbs-ready", finish, { once: true });
      s.onerror = function () {
        console.warn("[LU] thinking-orbs module script failed");
        finish();
      };
      document.head.appendChild(s);
      setTimeout(finish, 15000);
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
      } catch (e) {
        console.info("[LU] ThinkingOrb mount failed", e);
      }
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

  function flashHighlight(el, durationMs) {
    if (!el) return;
    var prev = el.style.outline;
    var prevOffset = el.style.outlineOffset;
    var prevTransition = el.style.transition;
    el.style.transition = "outline 0.2s ease";
    el.style.outline = "3px solid #22d3ee";
    el.style.outlineOffset = "4px";
    setTimeout(function () {
      el.style.outline = prev;
      el.style.outlineOffset = prevOffset;
      el.style.transition = prevTransition;
    }, durationMs || 2000);
  }

  function handleNavigateAndRender(payload) {
    payload = payload || {};
    var section = payload.section;
    var highlight = payload.highlight || payload.highlight_element;
    var prefill = payload.prefill || payload.prefill_data || {};
    if (!Object.keys(state.sectionMap || {}).length) scanPageSections();
    focusSection(section, highlight);
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
      console.info("[LU GenUI] DOM target not found", command, payload);
      return;
    }
    if (command === "scroll_to") {
      /* series: no page scroll — highlight only */
      flashHighlight(el, 2000);
    } else if (command === "highlight") {
      flashHighlight(el, payload.duration_ms || 2000);
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
    try {
      window.dispatchEvent(new CustomEvent("lu:roi", { detail: payload }));
    } catch (e) {}
    var map = {
      "roi-missed": payload.missed_calls_per_month,
      "roi-cost": payload.cost_per_missed_lead,
      "roi-ai-cost": payload.ai_monthly_cost,
      "roi-capture": payload.capture_rate,
      "roi-recovered": payload.recovered_leads_per_month,
      "roi-gross": payload.gross_monthly_savings,
      "roi-net": payload.net_monthly_savings,
      "roi-payback": payload.payback_days,
      "roi-result": payload.net_monthly_savings,
    };
    Object.keys(map).forEach(function (id) {
      var el = $(id);
      if (el && map[id] != null) {
        if ("value" in el) el.value = map[id];
        else el.textContent = String(map[id]);
      }
    });
    if (!Object.keys(state.sectionMap || {}).length) scanPageSections();
    focusSection("roi_calculator", null);
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
        var t = (n.innerText || n.value || n.getAttribute("aria-label") || n.tagName || "")
          .replace(/\s+/g, " ")
          .trim()
          .slice(0, 80);
        return t ? n.tagName.toLowerCase() + ": " + t : "";
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
      "position:fixed;inset:0;z-index:100000;background:rgba(0,0,0,.55);" +
      "display:flex;align-items:center;justify-content:center;padding:16px";
    var box = document.createElement("div");
    box.style.cssText =
      "background:#fff;color:#111;max-width:360px;width:100%;border-radius:16px;" +
      "padding:20px;font:14px/1.4 system-ui,sans-serif";
    var msg =
      (payload && payload.message) ||
      "Подтвердите номер на экране, чтобы продолжить. Мы ограничиваем открытый доступ из‑за злоупотреблений.";
    box.innerHTML =
      "<p style='margin:0 0 12px'>" +
      String(msg).replace(/</g, "&lt;") +
      "</p>" +
      "<input id='lu-verify-phone' type='tel' placeholder='+373...' " +
      "style='width:100%;padding:10px;border:1px solid #ccc;border-radius:8px;box-sizing:border-box'/>" +
      "<button id='lu-verify-ok' type='button' style='margin-top:12px;width:100%;padding:10px;" +
      "border:0;border-radius:8px;background:#111;color:#fff;font-weight:600;cursor:pointer'>Подтвердить</button>";
    wrap.appendChild(box);
    document.body.appendChild(wrap);
    $("lu-verify-ok").onclick = function () {
      var phone = ($("lu-verify-phone").value || "").trim();
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
        "box-shadow:0 8px 24px rgba(0,0,0,.3)";
      document.body.appendChild(el);
    }
    el.textContent = "Сессия скоро закончится (~" + sec + " с)";
    el.style.display = "block";
    setTimeout(function () {
      if (el) el.style.display = "none";
    }, 8000);
  }

  function sendClientMessage(obj) {
    if (!state.dc || state.dc.readyState !== "open") {
      console.info("[LU GenUI] dc not open", obj && obj.type);
      return;
    }
    try {
      state.dc.send(JSON.stringify(obj));
    } catch (e) {
      console.warn("[LU GenUI] dc send failed", e);
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

    var command =
      msg.command ||
      (msg.data && msg.data.command) ||
      msg.type ||
      (msg.payload && msg.payload.command);
    var payload = msg.payload || msg.data || msg || {};

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
    } else {
      console.info("[LU GenUI] server msg", command, payload);
    }
  }

  function setupDwellObservers() {
    if (!window.IntersectionObserver) return;
    var candidates = document.querySelectorAll(
      "[data-lu-dwell], [data-section], #pricing, #services, #cases, #hero, #contacts, #roi_calculator, #booking_widget"
    );
    if (!candidates.length) return;

    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          var el = entry.target;
          var key =
            el.id ||
            el.getAttribute("data-section") ||
            el.getAttribute("data-lu-dwell") ||
            "el";
          if (entry.isIntersecting && entry.intersectionRatio >= 0.45) {
            if (state.dwellTimers[key] || state.dwellSeen[key]) return;
            state.dwellTimers[key] = setTimeout(function () {
              state.dwellTimers[key] = null;
              if (state.dwellSeen[key]) return;
              state.dwellSeen[key] = true;
              sendClientMessage({
                type: "ui_user_interaction",
                data: {
                  interaction: "dwell",
                  element_id: el.id || key,
                  section: el.getAttribute("data-section") || el.id || "",
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

  function loadConfig() {
    return fetch(apiBase + "/widget-config?key=" + encodeURIComponent(widgetKey), {
      cache: "no-store",
    })
      .then(function (r) {
        return r.json();
      })
      .then(function (d) {
        if (!d) return null;
        state.turnstileSiteKey = d.turnstile_site_key || "";
        if (d.voice_enabled === false || d.voice === false) state.voiceEnabled = false;
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
      s.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
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

  /**
   * Obtain a real Turnstile token. Never resolves with "" when sitekey is set.
   * 1) invisible + execute (same user-gesture tick as startSession)
   * 2) if that fails — visible managed widget the user can complete
   */
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

        // --- attempt 1: invisible ---
        var host1 = document.createElement("div");
        host1.setAttribute("aria-hidden", "true");
        host1.style.cssText =
          "position:fixed;left:-9999px;width:1px;height:1px;overflow:hidden";
        document.body.appendChild(host1);
        var wid1 = null;
        var timer1 = setTimeout(function () {
          cleanupTurnstileHost(host1, wid1);
          showManagedChallenge(ok, fail);
        }, 5000);

        try {
          wid1 = window.turnstile.render(host1, {
            sitekey: state.turnstileSiteKey,
            size: "invisible",
            appearance: "execute",
            retry: "auto",
            "retry-interval": 2000,
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
      "position:fixed;inset:0;z-index:100001;background:rgba(0,0,0,.55);" +
      "display:flex;align-items:center;justify-content:center;padding:16px";
    var box = document.createElement("div");
    box.style.cssText =
      "background:#fff;color:#111;max-width:340px;width:100%;border-radius:16px;" +
      "padding:20px;font:14px/1.4 system-ui,sans-serif;text-align:center";
    box.innerHTML =
      "<p style='margin:0 0 14px;font-weight:600'>Подтвердите, что вы человек</p>" +
      "<div id='lu-turnstile-slot' style='display:flex;justify-content:center;min-height:65px'></div>" +
      "<button type='button' id='lu-turnstile-cancel' style='margin-top:14px;border:0;background:transparent;" +
      "color:#666;font:13px system-ui;cursor:pointer'>Отмена</button>";
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
        theme: "light",
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

  function stopSession(reason) {
    console.info("[LU GenUI] stop", reason || "");
    state.connected = false;
    state.connecting = false;
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
      state.localStream.getTracks().forEach(function (t) {
        t.stop();
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
      setTimeout(finish, 4000);
    });
  }

  async function startSession() {
    if (state.escaped || state.connecting || state.connected) return;
    state.connecting = true;
    setAgentState("connecting");

    try {
      var token = "";
      try {
        token = await getTurnstileToken();
      } catch (e) {
        console.warn("[LU GenUI] turnstile", e);
        setAgentState("error");
        stopSession("turnstile");
        alert("Не удалось пройти проверку безопасности. Обновите страницу и попробуйте снова.");
        return;
      }
      if (state.turnstileSiteKey && (!token || token.length < 20)) {
        setAgentState("error");
        stopSession("turnstile_empty");
        alert("Проверка безопасности не завершена. Попробуйте ещё раз.");
        return;
      }

      state.localStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
        video: false,
      });

      var pc = new RTCPeerConnection({ iceServers: ICE });
      state.pc = pc;

      state.localStream.getTracks().forEach(function (track) {
        pc.addTrack(track, state.localStream);
      });

      try {
        state.dc = pc.createDataChannel("rtvi-ai");
        state.dc.onmessage = onDataMessage;
        state.dc.onopen = function () {
          console.info("[LU GenUI] datachannel open");
        };
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
        if (p && p.catch) p.catch(function () {});
        setAgentState("listening");
      };

      pc.onconnectionstatechange = function () {
        var s = pc.connectionState;
        console.info("[LU GenUI] pc state", s);
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
        }),
      });

      var body = await res.json().catch(function () {
        return {};
      });
      if (!res.ok) {
        console.warn("[LU GenUI] offer refused", res.status, body);
        setAgentState("error");
        stopSession("offer_" + res.status);
        if (res.status === 429) {
          alert("Лимит голосовых сессий на сегодня. Попробуйте завтра.");
        }
        return;
      }

      await pc.setRemoteDescription({
        sdp: body.sdp,
        type: body.type || "answer",
      });
      console.info("[LU GenUI] session", {
        session_index: body.session_index,
        max_session_seconds: body.max_session_seconds,
      });
    } catch (err) {
      console.error("[LU GenUI] start failed", err);
      setAgentState("error");
      stopSession("error");
      if (err && err.name === "NotAllowedError") {
        alert("Нужен доступ к микрофону.");
      }
    } finally {
      state.connecting = false;
    }
  }

  async function boot() {
    ensureChrome();
    scanPageSections();
    setTimeout(scanPageSections, 1500);
    setTimeout(scanPageSections, 4000);
    var cfg = await loadConfig();
    console.info("[LU GenUI] boot", {
      key: widgetKey.slice(0, 8) + "…",
      server: voiceServer,
      turnstile: !!state.turnstileSiteKey,
      voice: state.voiceEnabled,
      config: !!cfg,
    });
    if (!state.voiceEnabled) return;

    if (state.turnstileSiteKey) {
      // Only load script early; do not render widgets until user gesture
      loadTurnstile().catch(function () {});
    }

    setupDwellObservers();

    var started = false;
    function tryStart() {
      if (started || state.escaped || state.connecting || state.connected) return;
      started = true;
      window.removeEventListener("pointerdown", tryStart, true);
      window.removeEventListener("touchstart", tryStart, true);
      window.removeEventListener("click", tryStart, true);
      window.removeEventListener("keydown", tryStart, true);
      startSession().catch(function () {
        // Allow one more user gesture if first start failed early
        started = false;
        window.addEventListener("pointerdown", tryStart, true);
        window.addEventListener("touchstart", tryStart, true);
        window.addEventListener("click", tryStart, true);
      });
    }
    window.addEventListener("pointerdown", tryStart, true);
    window.addEventListener("touchstart", tryStart, true);
    window.addEventListener("click", tryStart, true);
    window.addEventListener("keydown", tryStart, true);

    if (navigator.permissions && navigator.permissions.query) {
      navigator.permissions
        .query({ name: "microphone" })
        .then(function (status) {
          if (status.state === "granted") {
            setTimeout(function () {
              if (!started && !state.escaped) tryStart();
            }, 600);
          }
        })
        .catch(function () {});
    }

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
    setAgentState: setAgentState,
    stop: stopSession,
  };
})();
