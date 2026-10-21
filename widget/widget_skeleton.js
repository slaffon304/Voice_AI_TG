/**
 * Minimal «Сайт Будущего» widget skeleton (no bundler).
 * Wire to Pipecat JS / SmallWebRTC client in production.
 *
 * Required page config:
 *   window.LU_VOICE = { apiBase, widgetKey, turnstileSiteKey }
 */
(function () {
  const cfg = window.LU_VOICE || {};
  const apiBase = (cfg.apiBase || "").replace(/\/$/, "");
  const widgetKey = cfg.widgetKey || "";
  const STORAGE_VID = "lu_visitor_id";

  function visitorId() {
    let id = localStorage.getItem(STORAGE_VID);
    if (!id) {
      id = (crypto.randomUUID && crypto.randomUUID()) || String(Date.now());
      localStorage.setItem(STORAGE_VID, id);
    }
    return id.replace(/[^A-Za-z0-9_-]/g, "").slice(0, 64);
  }

  function ensureEscapeChip() {
    if (document.getElementById("lu-escape-voice")) return;
    const btn = document.createElement("button");
    btn.id = "lu-escape-voice";
    btn.type = "button";
    btn.textContent = "Не хочу говорить";
    btn.setAttribute(
      "style",
      "position:fixed;top:12px;left:50%;transform:translateX(-50%);z-index:99999;" +
        "padding:8px 14px;border-radius:999px;border:0;cursor:pointer;" +
        "background:#111;color:#fff;font:600 13px/1.2 system-ui,sans-serif;"
    );
    btn.addEventListener("click", () => {
      sendUi({ interaction: "escape" });
      stopVoiceChrome();
    });
    document.body.appendChild(btn);
  }

  let rtviSend = null; // set when RTVI client is connected
  let pc = null;

  function sendUi(data) {
    if (typeof rtviSend === "function") {
      rtviSend({ type: "ui_user_interaction", data });
    }
  }

  function stopVoiceChrome() {
    try {
      pc && pc.getSenders().forEach((s) => s.track && s.track.stop());
    } catch (_) {}
    document.documentElement.classList.add("lu-voice-off");
  }

  function handleServerCommand(msg) {
    const command = msg.command || msg.type;
    const payload = msg.payload || msg.data || {};
    switch (command) {
      case "navigate_and_render":
        // TODO: show section payload.section, highlight, prefill
        console.info("[LU] navigate", payload);
        break;
      case "update_roi":
        console.info("[LU] roi", payload);
        break;
      case "set_agent_state":
        console.info("[LU] orb", payload);
        break;
      case "require_phone_verification":
        // TODO: modal with payload.message; on success:
        // sendUi({ interaction: "phone_verified", phone: "..." })
        console.info("[LU] verify required", payload);
        break;
      case "session_ending_soon":
        console.info("[LU] ending soon", payload);
        break;
      case "session_ended":
      case "session_blocked":
        stopVoiceChrome();
        break;
      default:
        console.info("[LU] command", command, payload);
    }
  }

  /**
   * @param {string} turnstileToken from Turnstile callback
   * @param {(cmd: object) => void} onCommand
   * @param {(msg: object) => void} registerRtviSender — store send fn
   */
  async function startSession(turnstileToken, onCommand, registerRtviSender) {
    ensureEscapeChip();
    // Production: use @pipecat-ai/client-js + SmallWebRTC transport.
    // Here only the signalling contract is shown.
    const fakeOffer = { sdp: "v=0...", type: "offer" }; // replace with real RTCPeerConnection createOffer

    const res = await fetch(apiBase + "/api/offer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sdp: fakeOffer.sdp,
        type: "offer",
        key: widgetKey,
        t: turnstileToken,
        visitor_id: visitorId(),
        lang: navigator.language || "en",
        landing_url: location.href,
        referrer: document.referrer || "",
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      console.warn("[LU] offer refused", res.status, err);
      return null;
    }
    const answer = await res.json();
    // apply answer.sdp to peer connection; wire RTVI data channel
    // registerRtviSender(sendFn); onCommand for UI frames
    window.__LU_onCommand = onCommand || handleServerCommand;
    return answer;
  }

  // Dwell helper (call from IntersectionObserver)
  const dwellSeen = new Set();
  function reportDwell(elementId, section, dwellMs) {
    if (dwellMs < 3000) return;
    const key = elementId || section || "x";
    if (dwellSeen.has(key)) return;
    dwellSeen.add(key);
    sendUi({
      interaction: "dwell",
      element_id: elementId,
      section: section,
      dwell_ms: dwellMs,
    });
  }

  window.LUVoice = {
    startSession,
    sendUi,
    reportDwell,
    handleServerCommand,
    ensureEscapeChip,
    stopVoiceChrome,
  };

  // Auto chrome: escape chip as soon as DOM is ready (voice starts after Turnstile)
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", ensureEscapeChip);
  } else {
    ensureEscapeChip();
  }
})();
