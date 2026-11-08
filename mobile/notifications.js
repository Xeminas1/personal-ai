/* Reply sounds stay in this browser. No audio file or external service is used. */
(() => {
  "use strict";

  const PREFERENCE_KEY = "xemai.replySound";
  const MAX_CHATS = 128;
  const TONES = [[880, 0], [1174.66, 0.13]];
  const TONE_LENGTH = 0.16;
  const PEAK = 0.25;
  const latestIds = new Map();
  const playing = new Set();
  let enabled = true;
  let context = null;
  let resuming = null;
  let pending = false;
  let pendingChat = null;

  try { enabled = localStorage.getItem(PREFERENCE_KEY) !== "false"; } catch { /* Private browsing may deny storage. */ }

  function numericId(value) {
    if (typeof value === "string" && /^[1-9]\d*$/.test(value)) value = Number(value);
    return typeof value === "number" && Number.isSafeInteger(value) && value > 0 ? value : null;
  }

  function stopSounds() {
    for (const nodes of playing) {
      try { nodes.oscillator.stop(); } catch { /* Already ended. */ }
      try { nodes.oscillator.disconnect(); nodes.gain.disconnect(); } catch { /* Audio can be unavailable. */ }
    }
    playing.clear();
  }

  function chime() {
    // One short sound also covers replies that arrive while it is playing.
    if (playing.size) return;
    const start = context.currentTime + 0.005;
    try {
      // Small phone speakers barely reproduce tones below ~600 Hz, and the old
      // 0.035 peak was close to inaudible, so use A5/D6 at a clear but gentle level.
      for (const [frequency, offset] of TONES) {
        const oscillator = context.createOscillator();
        const gain = context.createGain();
        const nodes = { oscillator, gain };
        playing.add(nodes);
        oscillator.type = "sine";
        oscillator.frequency.setValueAtTime(frequency, start + offset);
        gain.gain.setValueAtTime(0, start + offset);
        gain.gain.linearRampToValueAtTime(PEAK, start + offset + 0.015);
        gain.gain.linearRampToValueAtTime(0, start + offset + TONE_LENGTH - 0.005);
        oscillator.connect(gain);
        gain.connect(context.destination);
        oscillator.onended = () => {
          playing.delete(nodes);
          try { oscillator.disconnect(); gain.disconnect(); } catch { /* Already disconnected. */ }
        };
        oscillator.start(start + offset);
        oscillator.stop(start + offset + TONE_LENGTH);
      }
    } catch {
      stopSounds();
    }
  }

  function flushPending() {
    if (!enabled || !pending || !context || context.state !== "running") return;
    pending = false;
    pendingChat = null;
    chime();
  }

  function unlock() {
    if (!enabled) return Promise.resolve(false);
    try {
      if (!context || context.state === "closed") {
        const Audio = window.AudioContext || window.webkitAudioContext;
        if (!Audio) return Promise.resolve(false);
        context = new Audio();
        context.addEventListener("statechange", flushPending);
      }
      if (context.state === "running") {
        flushPending();
        return Promise.resolve(true);
      }
      const current = context;
      // Retry resume during each gesture: a promise from an earlier blocked
      // autoplay attempt can remain pending until a trusted gesture retries it.
      const attempt = Promise.resolve(current.resume());
      if (resuming) {
        attempt.catch(() => {});
        return resuming;
      }
      resuming = attempt.then(() => {
        flushPending();
        return current.state === "running";
      }).catch(() => false).finally(() => { resuming = null; });
      return resuming;
    } catch {
      return Promise.resolve(false);
    }
  }

  // Play one chime right now (used when the owner switches sounds on, which is
  // itself a user gesture, so the browser allows audio and they hear it works).
  function preview() {
    if (!enabled) return Promise.resolve(false);
    pending = true;
    pendingChat = null;
    return unlock();
  }

  function setEnabled(value) {
    enabled = value === true;
    if (!enabled) {
      pending = false;
      pendingChat = null;
      stopSounds();
    }
    try { localStorage.setItem(PREFERENCE_KEY, String(enabled)); } catch { /* Session preference still works. */ }
    return enabled;
  }

  function observe(chatId, messages, { baseline = false } = {}) {
    const chat = numericId(chatId);
    if (chat === null || !Array.isArray(messages)) return false;
    const known = latestIds.has(chat);
    const previous = latestIds.get(chat) || 0;
    let latest = previous;
    let replyArrived = false;
    for (const message of messages) {
      if (!message || typeof message !== "object") continue;
      const id = numericId(message.id);
      if (id === null) continue;
      latest = Math.max(latest, id);
      if (id > previous && message.role === "assistant") replyArrived = true;
    }
    // Keep only a high-water mark, never message text or an unbounded ID set.
    latestIds.delete(chat);
    latestIds.set(chat, latest);
    while (latestIds.size > MAX_CHATS) forgetChat(latestIds.keys().next().value);
    if (!known || baseline || !replyArrived) return false;
    if (enabled) {
      // Mobile browsers can suspend audio in the background. Retain only one
      // chime and try again on the next gesture or audio/visibility recovery.
      pending = true;
      pendingChat = chat;
      flushPending();
    }
    return true;
  }

  function forgetChat(id) {
    const chat = numericId(id);
    if (chat === null) return;
    latestIds.delete(chat);
    if (pendingChat === chat) {
      pending = false;
      pendingChat = null;
    }
  }

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) flushPending();
  });

  window.XemAiNotifications = Object.freeze({
    unlock, preview, setEnabled, isEnabled: () => enabled, observe,
    forgetChat,
  });
})();
