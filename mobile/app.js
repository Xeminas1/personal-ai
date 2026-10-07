const state = {
  bootstrap: null,
  chats: [],
  chatId: null,
  busy: false,
};

const $ = (id) => document.getElementById(id);
const els = {
  brand: $("brand"),
  status: $("status"),
  menuBtn: $("menuBtn"),
  newBtn: $("newBtn"),
  drawerNewBtn: $("drawerNewBtn"),
  drawer: $("drawer"),
  closeDrawerBtn: $("closeDrawerBtn"),
  scrim: $("scrim"),
  chatList: $("chatList"),
  chatTitle: $("chatTitle"),
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
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error(`XemAi server returned HTTP ${response.status}`);
  }
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || `HTTP ${response.status}`);
  }
  return data;
}

function setStatus(text) {
  els.status.textContent = text;
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

function setBusy(value, label = null) {
  state.busy = value;
  els.input.disabled = value;
  els.sendBtn.disabled = value;
  els.newBtn.disabled = value;
  els.drawerNewBtn.disabled = value;
  els.thinking.classList.toggle("hidden", !value);
  setStatus(label || (value ? "Thinking…" : "Ready"));
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

function appendMessage(role, text) {
  const wrap = document.createElement("article");
  wrap.className = `message ${role}`;
  const name = role === "user"
    ? state.bootstrap.user.name
    : state.bootstrap.assistant_name;
  wrap.innerHTML = `
    <div class="message-name">${escapeHtml(name)}</div>
    <div class="message-body">${renderBody(text)}</div>
  `;
  els.messages.appendChild(wrap);
}

function scrollBottom() {
  requestAnimationFrame(() => window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" }));
}

async function bootstrap() {
  try {
    const data = await api("/api/bootstrap");
    state.bootstrap = data;
    els.brand.textContent = data.assistant_name;
    document.title = data.assistant_name;
    await refreshChats();
    setStatus(`Connected · v${data.version}`);
  } catch (err) {
    setStatus("Disconnected");
    showModal("Connection problem", String(err.message || err));
  }
}

async function refreshChats(preferredId = null) {
  const data = await api("/api/chats");
  state.chats = data.chats || [];
  renderChats();

  if (!state.chats.length) {
    const created = await api("/api/chats", {
      method: "POST",
      body: JSON.stringify({}),
    });
    state.chats = [created.chat];
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
    btn.textContent = chat.title;
    btn.addEventListener("click", async () => {
      if (state.busy) return;
      await loadChat(chat.id);
      closeDrawer();
    });
    els.chatList.appendChild(btn);
  }
}

async function loadChat(chatId) {
  const data = await api(`/api/chats/${chatId}/messages`);
  state.chatId = chatId;
  els.chatTitle.textContent = data.chat.title;
  els.messages.innerHTML = "";

  if (!data.messages.length) {
    appendMessage("assistant", `Hi ${state.bootstrap.user.name}. What would you like to work on?`);
  } else {
    for (const msg of data.messages) appendMessage(msg.role, msg.content);
  }
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
  if (state.busy || !state.chatId) return;

  const text = els.input.value.trim();
  if (!text) return;

  els.input.value = "";
  autoGrow();
  appendMessage("user", text);
  scrollBottom();
  setBusy(true);

  try {
    const data = await api(`/api/chats/${state.chatId}/messages`, {
      method: "POST",
      body: JSON.stringify({ text }),
    });
    appendMessage("assistant", data.answer);
    els.chatTitle.textContent = data.chat.title;
    await fetch("/api/chats").then((r) => r.json()).then((d) => {
      if (d.ok) {
        state.chats = d.chats || state.chats;
        renderChats();
      }
    });
    setBusy(false, `Connected · v${state.bootstrap.version}`);
    scrollBottom();
  } catch (err) {
    setBusy(false, "Error");
    appendMessage("assistant", `I hit an error: ${err.message || err}`);
    scrollBottom();
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

    state.busy = true;
    els.thinking.classList.add("hidden");
    await waitForUpdatedServer(data.installed);
  } catch (err) {
    setBusy(false, "Update failed");
    showModal("Update failed", err.message || String(err));
  }
}

async function checkMobileUpdate() {
  closeDrawer();
  setStatus("Checking for updates…");
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
els.newBtn.addEventListener("click", createChat);
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
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}

bootstrap();
