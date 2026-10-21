/**
 * LabUpgrade GenUI Voice Widget
 * Connects to POST /api/offer (WebRTC + RTVI data channel).
 * Implements docs/FRONTEND_RTVI_CONTRACT.md
 *
 * Embed:
 *   <div id="labupgrade-voice-widget"
 *        data-key="YOUR_WEB_CHANNEL_KEY"
 *        data-server="voice.labupgrade.in"></div>
 *   <script src="https://voice.labupgrade.in/widget-genui.js" defer></script>
 *
 * Optional: load thinking-orbs for rich agent state
 *   <script type="module">
 *     import { ThinkingOrb } from 'https://esm.sh/thinking-orbs';
 *     window.ThinkingOrb = ThinkingOrb;
 *   </script>
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

  function findSection(section) {
    if (!section) return null;
    return (
      $(section) ||
      qs('[data-section="' + section + '"]') ||
      qs('[data-lu-section="' + section + '"]') ||
      qs("#section-" + section) ||
      qs("." + section)
    );
  }

  function findTarget(ref, targetId) {
    if (targetId) {
      var byId = $(targetId) || qs('[data-id="' + targetId + '"]');
      if (byId) return byId;
    }
    if (ref) {
      return (
        qs('[data-ref="' + ref + '"]') ||
        qs('[data-a11y-ref="' + ref + '"]') ||
        $(ref)
      );
    }
    return null;
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

    if (!$("lu-voice-orb-wrap")) {
      var wrap = document.createElement("div");
      wrap.id = "lu-voice-orb-wrap";
      wrap.style.cssText =
        "position:fixed;right:20px;bottom:20px;z-index:99998;" +
        "display:flex;flex-direction:column;align-items:center;gap:6px;" +
        "pointer-events:none";
      var orbHost = document.createElement("div");
      orbHost.id = "lu-voice-orb";
      orbHost.style.cssText =
        "width:56px;height:56px;border-radius:50%;" +
        "background:radial-gradient(circle at 30% 30%,#5eead4,#1e1b4b);" +
        "box-shadow:0 8px 24px rgba(0,0,0,.35);transition:box-shadow .25s,transform .2s";
      var label = document.createElement("div");
      label.id = "lu-voice-orb-label";
      label.style.cssText =
        "font:600 11px/1.2 system-ui,sans-serif;color:#e2e8f0;" +
        "text-shadow:0 1px 3px rgba(0,0,0,.6);max-width:120px;text-align:center;" +
        "opacity:0;transition:opacity .2s";
      wrap.appendChild(orbHost);
      wrap.appendChild(label);
      document.body.appendChild(wrap);
      tryMountThinkingOrb("breathing");
    }
  }

  var _orbReactRoot = null;
  function tryMountThinkingOrb(orbState) {
    var host = $("lu-voice-orb");
    if (!host) return;
    if (window.ThinkingOrb && window.React && window.ReactDOM) {
      try {
        if (!_orbReactRoot && window.ReactDOM.createRoot) {
          _orbReactRoot = window.ReactDOM.createRoot(host);
        }
        if (_orbReactRoot) {
          _orbReactRoot.render(
            window.React.createElement(window.ThinkingOrb, {
              state: orbState === "idle" ? "breathing" : orbState,
              size: 56,
              theme: "auto",
            })
          );
          return;
        }
      } catch (e) {
        console.info("[LU GenUI] ThinkingOrb mount failed, fallback CSS", e);
      }
    }
    applyOrbCss(orbState);
  }

  function applyOrbCss(mode) {
    var orb = $("lu-voice-orb");
    if (!orb) return;
    var shadows = {
      connecting: "0 0 0 4px rgba(80,200,255,.45),0 8px 24px rgba(0,0,0,.35)",
      searching: "0 0 0 5px rgba(96,165,250,.5),0 8px 24px rgba(0,0,0,.35)",
      solving: "0 0 0 5px rgba(167,139,250,.5),0 8px 24px rgba(0,0,0,.35)",
      composing: "0 0 0 5px rgba(251,191,36,.45),0 8px 24px rgba(0,0,0,.35)",
      working: "0 0 0 4px rgba(52,211,153,.45),0 8px 24px rgba(0,0,0,.35)",
      listening: "0 0 0 4px rgba(45,212,191,.5),0 8px 24px rgba(0,0,0,.35)",
      live: "0 0 0 6px rgba(50,220,120,.45),0 8px 24px rgba(0,0,0,.35)",
      breathing: "0 0 0 4px rgba(94,234,212,.35),0 8px 24px rgba(0,0,0,.35)",
      error: "0 0 0 4px rgba(255,80,80,.5),0 8px 24px rgba(0,0,0,.35)",
      idle: "0 8px 24px rgba(0,0,0,.35)",
    };
    orb.style.boxShadow = shadows[mode] || shadows.idle;
  }

  function setAgentState(orbState, labelText) {
    state.agentState = orbState || "idle";
    tryMountThinkingOrb(state.agentState);
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
    var el = findSection(section);
    if (el && el.scrollIntoView) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    document.documentElement.setAttribute("data-lu-active-section", section || "");
    try {
      window.dispatchEvent(
        new CustomEvent("lu:navigate", {
          detail: {
            section: section,
            highlight: highlight,
            prefill: prefill,
            components: payload.components || null,
          },
        })
      );
    } catch (e) {}

    if (highlight) {
      var target =
        findTarget(null, highlight) ||
        (el && (qs("#" + highlight, el) || qs('[data-id="' + highlight + '"]', el)));
      if (target) flashHighlight(target, 2800);
    }

    if (prefill && typeof prefill === "object") {
      Object.keys(prefill).forEach(function (key) {
        var val = prefill[key];
        if (val == null) return;
        var field =
          qs('[name="' + key + '"]') ||
          qs("#" + key) ||
          qs('[data-field="' + key + '"]') ||
          (el && (qs('[name="' + key + '"]', el) || qs("#" + key, el)));
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
      el.scrollIntoView({ behavior: "smooth", block: "center" });
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
    var section = findSection("roi_calculator");
    if (section && section.scrollIntoView) {
      section.scrollIntoView({ behavior: "smooth", block: "start" });
    }
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

  function getTurnstileToken() {
    if (!state.turnstileSiteKey) return Promise.resolve("");
    return loadTurnstile().then(function () {
      return new Promise(function (resolve, reject) {
        var host = document.createElement("div");
        host.style.cssText =
          "position:fixed;left:-9999px;width:1px;height:1px;overflow:hidden";
        document.body.appendChild(host);
        var wid = window.turnstile.render(host, {
          sitekey: state.turnstileSiteKey,
          size: "invisible",
          callback: function (token) {
            try {
              window.turnstile.remove(wid);
            } catch (e) {}
            host.remove();
            resolve(token || "");
          },
          "error-callback": function () {
            try {
              window.turnstile.remove(wid);
            } catch (e) {}
            host.remove();
            reject(new Error("turnstile"));
          },
        });
        try {
          window.turnstile.execute(wid);
        } catch (e) {}
      });
    });
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
      loadTurnstile().catch(function () {});
    }

    setupDwellObservers();

    var started = false;
    function tryStart() {
      if (started || state.escaped) return;
      started = true;
      window.removeEventListener("pointerdown", tryStart, true);
      window.removeEventListener("keydown", tryStart, true);
      startSession();
    }
    window.addEventListener("pointerdown", tryStart, true);
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
