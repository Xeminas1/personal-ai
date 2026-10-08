const FRONTEND_VERSION = "0.9.4";
const REPLY_ERROR_PREFIX = "⚠️ XemAi couldn\'t complete that reply.";

const state = {
  bootstrap: null,
  chats: [],
  chatId: null,
  busy: false,
  lastMessageSignature: "",
  lastChatSignature: "",
  syncInFlight: false,
  syncCounter: 0,
  pendingAttachments: [],
  uploadingAttachments: 0,
  thinkingTimer: null,
  thinkingStartedAt: 0,
  remoteActivity: false,
};

const $ = (id) => document.getElementById(id);
const els = {
  brand: $("brand"),
  status: $("status"),
  versionBadge: $("versionBadge"),
  computeBadge: $("computeBadge"),
  menuBtn: $("menuBtn"),
  newBtn: $("newBtn"),
  galleryInput: $("galleryInput"),
  cameraPhotoInput: $("cameraPhotoInput"),
  cameraVideoInput: $("cameraVideoInput"),
  fileInput: $("fileInput"),
  attachmentTray: $("attachmentTray"),
  attachmentMenu: $("attachmentMenu"),
  attachmentMenuScrim: $("attachmentMenuScrim"),
  galleryBtn: $("galleryBtn"),
  cameraPhotoBtn: $("cameraPhotoBtn"),
  cameraVideoBtn: $("cameraVideoBtn"),
  filesBtn: $("filesBtn"),
  attachmentMenuCancel: $("attachmentMenuCancel"),
  moreBtn: $("moreBtn"),
  drawerNewBtn: $("drawerNewBtn"),
  drawer: $("drawer"),
  closeDrawerBtn: $("closeDrawerBtn"),
  scrim: $("scrim"),
  chatList: $("chatList"),
  messages: $("messages"),
  thinking: $("thinking"),
  composer: $("composer"),
  input: $("input"),
  sendBtn: $("sendBtn"),
  capabilitiesBtn: $("capabilitiesBtn"),
  updateBtn: $("updateBtn"),
  feedbackBtn: $("feedbackBtn"),
  modal: $("modal"),
  modalTitle: $("modalTitle"),
  modalBody: $("modalBody"),
  modalActions: $("modalActions"),
};

async function api(path, options = {}) {
  const opts = {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  };
  const response = await fetch(path, opts);
  const contentType = response.headers.get("content-type") || "";
  let data;
  try {
    data = await response.json();
  } catch {
    if (!contentType.includes("application/json")) {
      throw new Error(
        `Mobile server/API mismatch: frontend v${FRONTEND_VERSION} received ` +
        `${contentType || "non-JSON"} from ${path}. Restart the XemAi mobile server.`
      );
    }
    throw new Error(`XemAi server returned unreadable JSON (HTTP ${response.status})`);
  }
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || `HTTP ${response.status}`);
  }
  return data;
}

function setStatus(text) {
  els.status.textContent = text;
}

function isNetworkFetchError(err) {
  const message = String(err?.message || err || "");
  return /failed to fetch|networkerror|network request failed|load failed/i.test(message);
}

function setComputeBadge(data) {
  if (!els.computeBadge || !data) return;
  const isWorker = data.compute_source === "remote_worker";
  const route = isWorker ? "Worker" : "Host";
  const model = String(data.runtime_model || data.model || "unknown");
  els.computeBadge.textContent = `${route} · ${model}`;
  els.computeBadge.dataset.route = isWorker ? "worker" : "host";
}

function setBrand(name) {
  const displayName = String(name || "XemAi");
  const drawerTitle = document.querySelector(".drawer-title");

  if (displayName.toLowerCase() === "xemai") {
    const markup = '<span class="brand-xem">Xem</span><span class="brand-ai">Ai</span>';
    els.brand.innerHTML = markup;
    if (drawerTitle) drawerTitle.innerHTML = markup;
  } else {
    els.brand.textContent = displayName;
    if (drawerTitle) drawerTitle.textContent = displayName;
  }
}

function openDrawer() {
  els.drawer.classList.add("open");
  els.scrim.classList.add("open");
}
function closeDrawer() {
  els.drawer.classList.remove("open");
  els.scrim.classList.remove("open");
}

function autoGrow() {
  els.input.style.height = "auto";
  els.input.style.height = `${Math.min(180, els.input.scrollHeight)}px`;
}

function isMobileLayout() {
  return window.matchMedia("(max-width: 999px)").matches;
}

function openAttachmentMenu() {
  if (state.busy || state.remoteActivity || state.uploadingAttachments) return;
  if (!isMobileLayout()) {
    els.fileInput.click();
    return;
  }
  els.attachmentMenu.classList.remove("hidden");
  els.attachmentMenuScrim.classList.remove("hidden");
}

function closeAttachmentMenu() {
  els.attachmentMenu.classList.add("hidden");
  els.attachmentMenuScrim.classList.add("hidden");
}

function chooseAttachmentInput(input) {
  closeAttachmentMenu();
  if (!input) return;
  input.value = "";
  input.click();
}

function formatBytes(bytes) {
  const value = Number(bytes || 0);
  if (value < 1000) return `${value} B`;
  if (value < 1000000) return `${(value / 1000).toFixed(1)} KB`;
  return `${(value / 1000000).toFixed(1)} MB`;
}

function renderAttachmentTray() {
  if (!els.attachmentTray) return;
  els.attachmentTray.innerHTML = "";

  if (!state.pendingAttachments.length && !state.uploadingAttachments) {
    els.attachmentTray.classList.add("hidden");
    return;
  }

  els.attachmentTray.classList.remove("hidden");

  for (const [index, item] of state.pendingAttachments.entries()) {
    const chip = document.createElement("div");
    chip.className = "attachment-chip";
    chip.innerHTML = `
      <span class="attachment-icon">📎</span>
      <span class="attachment-info">
        <span class="attachment-name">${escapeHtml(item.name)}</span>
        <span class="attachment-size">${escapeHtml(formatBytes(item.size))}</span>
      </span>
      <button type="button" class="attachment-remove" aria-label="Remove attachment">×</button>
    `;
    chip.querySelector(".attachment-remove").addEventListener("click", () => {
      if (state.busy) return;
      state.pendingAttachments.splice(index, 1);
      renderAttachmentTray();
    });
    els.attachmentTray.appendChild(chip);
  }

  if (state.uploadingAttachments) {
    const chip = document.createElement("div");
    chip.className = "attachment-chip uploading";
    chip.innerHTML = `
      <span class="attachment-icon">↥</span>
      <span class="attachment-info">
        <span class="attachment-name">Uploading file…</span>
        <span class="attachment-size">Please wait</span>
      </span>
    `;
    els.attachmentTray.appendChild(chip);
  }
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error || new Error("Could not read file."));
    reader.onload = () => {
      const result = String(reader.result || "");
      const comma = result.indexOf(",");
      resolve(comma >= 0 ? result.slice(comma + 1) : result);
    };
    reader.readAsDataURL(file);
  });
}

async function uploadSelectedFiles(files) {
  if (!state.chatId || state.busy) return;

  const selected = Array.from(files || []);
  if (!selected.length) return;

  const remainingSlots = Math.max(0, 3 - state.pendingAttachments.length);
  if (!remainingSlots) {
    showModal("Attachment limit", "You can attach up to 3 files to one message.");
    return;
  }

  for (const file of selected.slice(0, remainingSlots)) {
    if (file.size > 5000000) {
      showModal(
        "File too large",
        `${file.name} is larger than the current 5 MB attachment limit.`
      );
      continue;
    }

    state.uploadingAttachments += 1;
    renderAttachmentTray();
    setStatus(`Uploading ${file.name}…`);

    try {
      const encoded = await fileToBase64(file);
      const data = await api(`/api/chats/${state.chatId}/attachments`, {
        method: "POST",
        body: JSON.stringify({
          name: file.name,
          mime: file.type || "application/octet-stream",
          data: encoded,
        }),
      });
      state.pendingAttachments.push(data.attachment);
    } catch (err) {
      showModal("Attachment failed", err.message || String(err));
    } finally {
      state.uploadingAttachments = Math.max(0, state.uploadingAttachments - 1);
      renderAttachmentTray();
      setStatus(`Connected · v${state.bootstrap.version}`);
    }
  }

  for (const input of [
    els.galleryInput,
    els.cameraPhotoInput,
    els.cameraVideoInput,
    els.fileInput,
  ]) {
    if (input) input.value = "";
  }
}

function extractAttachmentDisplay(text) {
  const attachments = [];
  const visibleLines = [];
  for (const line of String(text).split("\n")) {
    const trimmed = line.trim();
    if (trimmed.startsWith("[[XEMAI_ATTACHMENT:") && trimmed.endsWith("]]")) {
      const raw = trimmed.slice("[[XEMAI_ATTACHMENT:".length, -2);
      try {
        const item = JSON.parse(raw);
        if (item && typeof item === "object") {
          attachments.push(item);
          continue;
        }
      } catch {}
    }
    visibleLines.push(line);
  }
  return { attachments, text: visibleLines.join("\n").trim() };
}

function setBusy(value, label = null) {
  state.busy = value;
  els.input.disabled = value;
  els.sendBtn.disabled = value;
  els.newBtn.disabled = value || state.uploadingAttachments > 0;
  els.drawerNewBtn.disabled = value;
  els.thinking.classList.toggle("hidden", !value);

  if (value) {
    startThinkingProgress(
      label ? label.replace(/…$/, "") : "XemAi is thinking"
    );
  } else {
    stopThinkingProgress();
    if (!state.remoteActivity) {
      els.thinking.classList.add("hidden");
    }
  }

  setStatus(label || (value ? "XemAi is thinking…" : "Ready"));
}

function escapeHtml(text) {
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function linkify(text) {
  return text.replace(
    /(https?:\/\/[^\s<]+)/g,
    '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>'
  );
}

function messageSignature(messages) {
  return (messages || [])
    .map((msg) => `${msg.id ?? ""}:${msg.role ?? ""}`)
    .join("|");
}

function chatSignature(chats) {
  return (chats || [])
    .map((chat) => `${chat.id}:${chat.title}:${chat.updated_at ?? ""}`)
    .join("|");
}

function scrollContainer() {
  if (window.matchMedia("(min-width: 1000px)").matches) {
    return els.messages;
  }
  return document.scrollingElement || document.documentElement;
}

function isNearBottom() {
  const target = scrollContainer();
  return target.scrollHeight - target.scrollTop - target.clientHeight < 140;
}

function relativeTime(isoText) {
  const date = new Date(isoText);
  if (Number.isNaN(date.getTime())) return "";
  const diff = Date.now() - date.getTime();
  if (diff < 90000) return "Just now";
  if (diff < 3600000) return `${Math.max(1, Math.floor(diff / 60000))} min ago`;
  if (diff < 86400000) {
    const h = Math.max(1, Math.floor(diff / 3600000));
    return `${h} hour${h === 1 ? "" : "s"} ago`;
  }
  const d = Math.max(1, Math.floor(diff / 86400000));
  return `${d} day${d === 1 ? "" : "s"} ago`;
}

function formatMessageTime(isoText) {
  const date = isoText ? new Date(isoText) : new Date();
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function setThinkingText(text) {
  const label = els.thinking?.querySelector(".thinking-label");
  if (label) label.textContent = text;
}

function stopThinkingProgress() {
  if (state.thinkingTimer) {
    window.clearInterval(state.thinkingTimer);
    state.thinkingTimer = null;
  }
  state.thinkingStartedAt = 0;
}

function startThinkingProgress(initial = "XemAi is thinking") {
  stopThinkingProgress();
  state.thinkingStartedAt = Date.now();
  setThinkingText(initial);
  state.thinkingTimer = window.setInterval(() => {
    const elapsed = Date.now() - state.thinkingStartedAt;
    if (elapsed >= 60000) {
      setThinkingText("XemAi is still working");
    } else if (elapsed >= 20000) {
      setThinkingText("XemAi is still thinking");
    }
  }, 1000);
}

function setRemoteActivity(active, status = "XemAi is thinking") {
  const wasActive = state.remoteActivity;
  state.remoteActivity = Boolean(active);
  if (state.busy) return;

  if (state.remoteActivity) {
    els.thinking.classList.remove("hidden");
    const cleanStatus = String(status || "XemAi is thinking").replace(/…$/, "");
    if (!wasActive) {
      startThinkingProgress(cleanStatus);
    } else if (
      cleanStatus !== "XemAi is thinking"
      && cleanStatus !== "XemAi is still thinking"
      && cleanStatus !== "XemAi is still working"
    ) {
      setThinkingText(cleanStatus);
    }
    setStatus(cleanStatus + "…");
    els.sendBtn.disabled = true;
    els.newBtn.disabled = true;
  } else {
    stopThinkingProgress();
    els.thinking.classList.add("hidden");
    els.sendBtn.disabled = state.busy;
    els.newBtn.disabled = state.busy || state.uploadingAttachments > 0;
    setStatus(`Connected · v${state.bootstrap.version}`);
  }
}


function renderBody(text) {
  const parts = String(text).split(/```/);
  return parts.map((part, index) => {
    if (index % 2 === 1) {
      const cleaned = part.replace(/^[a-zA-Z0-9_+-]+\n/, "");
      return `<pre><code>${escapeHtml(cleaned)}</code></pre>`;
    }
    let safe = linkify(escapeHtml(part));
    safe = safe.replace(/^### (.+)$/gm, "<strong>$1</strong>");
    safe = safe.replace(/^## (.+)$/gm, "<strong>$1</strong>");
    safe = safe.replace(/^# (.+)$/gm, "<strong>$1</strong>");
    safe = safe.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    return `<span>${safe}</span>`;
  }).join("");
}

function appendMessage(role, text, createdAt = null, delivery = null) {
  const wrap = document.createElement("article");
  wrap.className = `message ${role}`;
  const name = role === "user"
    ? state.bootstrap.user.name
    : state.bootstrap.assistant_name;
  const parsed = role === "user"
    ? extractAttachmentDisplay(text)
    : { attachments: [], text: String(text) };
  const attachmentHtml = parsed.attachments.map((item) => `
    <div class="message-attachment">
      <span class="attachment-icon">📎</span>
      <span>
        <strong>${escapeHtml(item.name || "attachment")}</strong>
        <small>${escapeHtml(formatBytes(item.size || 0))}</small>
      </span>
    </div>
  `).join("");
  const retryable = (
    role === "assistant"
    && String(text).startsWith(REPLY_ERROR_PREFIX)
  );
  wrap.innerHTML = `
    <div class="bubble-wrap">
      ${role === "assistant" ? '<div class="tail"></div>' : ''}
      <div class="bubble">
        ${attachmentHtml}
        ${parsed.text ? `<div class="message-body">${renderBody(parsed.text)}</div>` : ""}
        ${retryable ? '<button type="button" class="retry-reply-btn">Retry</button>' : ''}
        <div class="message-meta">
          ${role === "user" ? `
            <span class="message-delivery">${escapeHtml(delivery || "Sent")}</span>
            <span class="message-time">${escapeHtml(formatMessageTime(createdAt))}</span>
            <span class="message-name">${escapeHtml(name)}</span>
          ` : `
            <span class="message-name">${escapeHtml(name)}</span>
            <span class="message-time">${escapeHtml(formatMessageTime(createdAt))}</span>
          `}
        </div>
      </div>
      ${role === "user" ? '<div class="tail"></div>' : ''}
    </div>
  `;
  const retryBtn = wrap.querySelector(".retry-reply-btn");
  if (retryBtn) retryBtn.addEventListener("click", retryLastMessage);
  els.messages.appendChild(wrap);
}

async function retryLastMessage() {
  if (state.busy || state.remoteActivity || !state.chatId) return;

  setBusy(true, "Sending retry…");
  try {
    const data = await api(`/api/chats/${state.chatId}/retry`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    setBusy(false, `Connected · v${state.bootstrap.version}`);
    setRemoteActivity(true, data.status || "XemAi is thinking");
    window.setTimeout(syncSharedState, 250);
  } catch (err) {
    if (isNetworkFetchError(err)) {
      setBusy(false, "Connection interrupted");
      setStatus("Connection interrupted · checking XemAi…");
      window.setTimeout(syncSharedState, 500);
      window.setTimeout(syncSharedState, 2000);
    } else {
      setBusy(false, "Retry not started");
      showModal("Retry not started", err.message || String(err));
    }
  }
}

function scrollBottom() {
  requestAnimationFrame(() => {
    const target = scrollContainer();
    target.scrollTo({ top: target.scrollHeight, behavior: "smooth" });
  });
}

function renderMessageList(messages) {
  els.messages.innerHTML = "";
  if (!messages.length) {
    appendMessage(
      "assistant",
      `Hi ${state.bootstrap.user.name}. What would you like to work on?`,
      new Date().toISOString()
    );
    return;
  }
  for (const msg of messages) {
    appendMessage(msg.role, msg.content, msg.created_at);
  }
}

async function syncSharedState() {
  if (!state.bootstrap || state.syncInFlight || state.busy || document.hidden) {
    return;
  }

  state.syncInFlight = true;
  try {
    const chatsData = await api("/api/chats");
    const nextChats = chatsData.chats || [];
    const nextChatSignature = chatSignature(nextChats);
    if (nextChatSignature !== state.lastChatSignature) {
      state.chats = nextChats;
      state.lastChatSignature = nextChatSignature;
      renderChats();
    }

    if (state.chatId) {
      const wasNearBottom = isNearBottom();
      const messageData = await api(`/api/chats/${state.chatId}/messages`);
      const nextMessageSignature = messageSignature(messageData.messages || []);
      if (nextMessageSignature !== state.lastMessageSignature) {
        state.lastMessageSignature = nextMessageSignature;
        renderMessageList(messageData.messages || []);
        if (wasNearBottom) scrollBottom();
      }
    }

    if (state.chatId && !state.busy) {
      const activity = await api(`/api/chats/${state.chatId}/activity`);
      setRemoteActivity(activity.active, activity.status);
    }

    state.syncCounter += 1;
    if (state.syncCounter % 10 === 0) {
      const compute = await api("/api/compute");
      setComputeBadge(compute);
    }
    if (state.syncCounter % 3 === 0) {
      const health = await api(`/api/health?t=${Date.now()}`);
      if (health.version && health.version !== state.bootstrap.version) {
        window.location.reload();
        return;
      }
    }

    if (!state.busy && !state.remoteActivity) {
      setStatus(`Connected · v${state.bootstrap.version}`);
    }
  } catch {
    // The shared server may be restarting for an automatic update. The next
    // sync tick will reconnect and reload once the new version is available.
    setStatus("Reconnecting…");
  } finally {
    state.syncInFlight = false;
  }
}

function startBackgroundSync() {
  window.setInterval(syncSharedState, 1500);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) syncSharedState();
  });
}

async function bootstrap() {
  try {
    const data = await api("/api/bootstrap");
    state.bootstrap = data;
    setBrand(data.assistant_name);
    if (els.versionBadge) els.versionBadge.textContent = `v${data.version}`;
    setComputeBadge(data);
    document.title = data.assistant_name;
    await refreshChats();
    setStatus(`Connected · v${data.version}`);
    startBackgroundSync();
  } catch (err) {
    setStatus("Disconnected");
    showModal("Connection problem", String(err.message || err));
  }
}

async function refreshChats(preferredId = null) {
  const data = await api("/api/chats");
  state.chats = data.chats || [];
  state.lastChatSignature = chatSignature(state.chats);
  renderChats();

  if (!state.chats.length) {
    const created = await api("/api/chats", {
      method: "POST",
      body: JSON.stringify({}),
    });
    state.chats = [created.chat];
    state.lastChatSignature = chatSignature(state.chats);
    renderChats();
  }

  const ids = new Set(state.chats.map((c) => c.id));
  let nextId = preferredId ?? state.chatId;
  if (!ids.has(nextId)) nextId = state.chats[0].id;
  await loadChat(nextId);
}

function renderChats() {
  els.chatList.innerHTML = "";
  for (const chat of state.chats) {
    const btn = document.createElement("button");
    btn.className = "chat-item" + (chat.id === state.chatId ? " active" : "");
    const updated = chat.updated_at ? relativeTime(chat.updated_at) : "";
    btn.innerHTML = `
      <span class="chat-title-text">${escapeHtml(chat.title)}</span>
      <span class="chat-time">${escapeHtml(updated)}</span>
    `;
    btn.addEventListener("click", async () => {
      if (state.busy) return;
      await loadChat(chat.id);
      closeDrawer();
    });
    els.chatList.appendChild(btn);
  }
}

async function loadChat(chatId) {
  if (state.chatId !== chatId) {
    state.pendingAttachments = [];
    renderAttachmentTray();
    setRemoteActivity(false);
  }
  const data = await api(`/api/chats/${chatId}/messages`);
  state.chatId = chatId;
  state.lastMessageSignature = messageSignature(data.messages || []);
  renderMessageList(data.messages || []);
  renderChats();
  scrollBottom();
}

async function createChat() {
  if (state.busy) return;
  const data = await api("/api/chats", {
    method: "POST",
    body: JSON.stringify({}),
  });
  await refreshChats(data.chat.id);
  closeDrawer();
  els.input.focus();
}

async function sendMessage(event) {
  event?.preventDefault();
  if (state.busy || state.remoteActivity || !state.chatId) return;

  const text = els.input.value.trim();
  if (!text && !state.pendingAttachments.length) return;
  if (state.uploadingAttachments) {
    showModal("Attachment uploading", "Wait for the file upload to finish before sending.");
    return;
  }

  const outgoingAttachments = [...state.pendingAttachments];
  els.input.value = "";
  autoGrow();
  const localAttachments = outgoingAttachments.map((item) =>
    `[[XEMAI_ATTACHMENT:${JSON.stringify(item)}]]`
  ).join("\n");
  appendMessage(
    "user",
    [localAttachments, text].filter(Boolean).join("\n"),
    new Date().toISOString(),
    "Sent"
  );
  scrollBottom();
  setBusy(true, "Sending…");

  try {
    const data = await api(`/api/chats/${state.chatId}/messages`, {
      method: "POST",
      body: JSON.stringify({
        text,
        attachments: outgoingAttachments,
      }),
    });
    state.pendingAttachments = [];
    renderAttachmentTray();
    setBusy(false, `Connected · v${state.bootstrap.version}`);
    setRemoteActivity(true, data.status || "XemAi is thinking");
    window.setTimeout(syncSharedState, 250);
  } catch (err) {
    // A dropped mobile/Tailscale connection does not prove generation failed.
    // The server may already have accepted the message and be working on it.
    if (isNetworkFetchError(err)) {
      setBusy(false, "Connection interrupted");
      setStatus("Connection interrupted · checking XemAi…");
      window.setTimeout(syncSharedState, 500);
      window.setTimeout(syncSharedState, 2000);
    } else {
      setBusy(false, "Message not accepted");
      showModal("Message not accepted", err.message || String(err));
    }
  }
}

function clearModal() {
  els.modalTitle.textContent = "";
  els.modalBody.innerHTML = "";
  els.modalActions.innerHTML = "";
}

function showModal(title, body) {
  clearModal();
  els.modalTitle.textContent = title;
  els.modalBody.textContent = body;
  const close = document.createElement("button");
  close.textContent = "Close";
  close.addEventListener("click", () => els.modal.close());
  els.modalActions.appendChild(close);
  els.modal.showModal();
}

async function showCapabilities() {
  try {
    const data = await api("/api/capabilities");
    showModal("XemAi capabilities", data.capabilities.map((x) => `• ${x}`).join("\n"));
  } catch (err) {
    showModal("Capabilities", err.message || String(err));
  }
}

async function waitForUpdatedServer(expectedVersion) {
  setStatus(`Restarting into v${expectedVersion}…`);
  const deadline = Date.now() + 45000;
  let sawOffline = false;

  while (Date.now() < deadline) {
    try {
      const response = await fetch(
        `/api/health?t=${Date.now()}`,
        { cache: "no-store" }
      );
      if (response.ok) {
        const data = await response.json();
        if (data.version === expectedVersion && (sawOffline || data.version !== state.bootstrap.version)) {
          window.location.reload();
          return;
        }
      }
    } catch {
      sawOffline = true;
    }
    await new Promise((resolve) => setTimeout(resolve, 900));
  }

  setStatus(`Update installed · reopen XemAi if needed`);
  showModal(
    "Update installed",
    `XemAi v${expectedVersion} was installed, but the phone could not reconnect automatically. Refresh the page in a moment.`
  );
}

async function installMobileUpdate(version) {
  try {
    els.modal.close();
    closeDrawer();
    setBusy(true, `Installing v${version}…`);
    const data = await api("/api/update/install", {
      method: "POST",
      body: JSON.stringify({}),
    });

    if (!data.restart) {
      setBusy(false, `Up to date · v${data.installed}`);
      return;
    }

    // Keep the composer disabled while the background server restarts.
    state.busy = true;
    els.thinking.classList.add("hidden");
    await waitForUpdatedServer(data.installed);
  } catch (err) {
    setBusy(false, "Update failed");
    showModal("Update failed", err.message || String(err));
  }
}

async function checkMobileUpdate() {
  setStatus("Checking for updates…");
  closeDrawer();
  try {
    const data = await api("/api/update");
    if (!data.enabled) {
      showModal(
        "Mobile updates disabled",
        "Mobile update installation is disabled in the PC configuration."
      );
      setStatus(`Connected · v${state.bootstrap.version}`);
      return;
    }

    if (!data.update) {
      showModal(
        "XemAi is up to date",
        `You are running XemAi v${data.current_version}.`
      );
      setStatus(`Up to date · v${data.current_version}`);
      return;
    }

    clearModal();
    els.modalTitle.textContent = `Update to v${data.update.version}?`;
    els.modalBody.textContent =
      data.update.notes || "A newer XemAi release is available.";

    const cancel = document.createElement("button");
    cancel.textContent = "Not now";
    cancel.addEventListener("click", () => {
      els.modal.close();
      setStatus(`Connected · v${state.bootstrap.version}`);
    });

    const install = document.createElement("button");
    install.textContent = "Install";
    install.addEventListener("click", () =>
      installMobileUpdate(data.update.version)
    );

    els.modalActions.append(cancel, install);
    els.modal.showModal();
  } catch (err) {
    setStatus("Update check failed");
    showModal("Update check failed", err.message || String(err));
  }
}

function showFeedback() {
  if (!state.chatId) return;
  clearModal();
  els.modalTitle.textContent = "Rate this chat";

  const intro = document.createElement("div");
  intro.textContent = "How helpful has XemAi been in this chat?";
  els.modalBody.appendChild(intro);

  const row = document.createElement("div");
  row.className = "rating-row";
  let selected = null;
  for (let i = 0; i <= 10; i++) {
    const btn = document.createElement("button");
    btn.textContent = String(i);
    btn.addEventListener("click", () => {
      selected = i;
      [...row.children].forEach((b) => b.style.borderColor = "");
      btn.style.borderColor = "var(--accent)";
    });
    row.appendChild(btn);
  }
  els.modalBody.appendChild(row);

  const note = document.createElement("textarea");
  note.className = "feedback-note";
  note.placeholder = "Optional note";
  els.modalBody.appendChild(note);

  const cancel = document.createElement("button");
  cancel.textContent = "Cancel";
  cancel.addEventListener("click", () => els.modal.close());

  const save = document.createElement("button");
  save.textContent = "Save";
  save.addEventListener("click", async () => {
    if (selected === null) return;
    try {
      await api(`/api/chats/${state.chatId}/feedback`, {
        method: "POST",
        body: JSON.stringify({ score: selected, note: note.value.trim() }),
      });
      els.modal.close();
      setStatus(`Feedback saved · ${selected}/10`);
    } catch (err) {
      showModal("Feedback error", err.message || String(err));
    }
  });

  els.modalActions.append(cancel, save);
  els.modal.showModal();
}

els.menuBtn.addEventListener("click", openDrawer);
els.closeDrawerBtn.addEventListener("click", closeDrawer);
els.scrim.addEventListener("click", closeDrawer);
els.newBtn.addEventListener("click", openAttachmentMenu);
els.attachmentMenuScrim.addEventListener("click", closeAttachmentMenu);
els.attachmentMenuCancel.addEventListener("click", closeAttachmentMenu);

els.galleryBtn.addEventListener("click", () =>
  chooseAttachmentInput(els.galleryInput)
);
els.cameraPhotoBtn.addEventListener("click", () =>
  chooseAttachmentInput(els.cameraPhotoInput)
);
els.cameraVideoBtn.addEventListener("click", () =>
  chooseAttachmentInput(els.cameraVideoInput)
);
els.filesBtn.addEventListener("click", () =>
  chooseAttachmentInput(els.fileInput)
);

for (const input of [
  els.galleryInput,
  els.cameraPhotoInput,
  els.cameraVideoInput,
  els.fileInput,
]) {
  input.addEventListener("change", () =>
    uploadSelectedFiles(input.files)
  );
}
els.moreBtn.addEventListener("click", showCapabilities);
els.drawerNewBtn.addEventListener("click", createChat);
els.capabilitiesBtn.addEventListener("click", showCapabilities);
els.updateBtn.addEventListener("click", checkMobileUpdate);
els.feedbackBtn.addEventListener("click", showFeedback);
els.composer.addEventListener("submit", sendMessage);
els.input.addEventListener("input", autoGrow);
els.input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendMessage(event);
  }
});

window.addEventListener("online", () => setStatus("Reconnecting…"));
window.addEventListener("offline", () => setStatus("Phone offline"));

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js?v=0.9.4")
    .then((registration) => registration.update())
    .catch(() => {});
}

bootstrap();
