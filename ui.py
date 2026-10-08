from __future__ import annotations

import datetime as dt
import os
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, simpledialog

from app.gui_backend import ChatBackend
from app.mobile_runtime import (
    ensure_mobile_server_current,
    mobile_local_url,
    mobile_server_version,
    restart_mobile_server_process,
)
from app.version import VERSION

BASE_DIR = Path(__file__).resolve().parent
BG, PANEL, PANEL_2 = "#03070c", "#07111b", "#0a1826"
TEXT, MUTED = "#ecf2f8", "#8ea4bb"
USER_BUBBLE, USER_TEXT = "#ece9df", "#16396b"
AI_BUBBLE, AI_BUBBLE_2 = "#173455", "#1f4a73"
INPUT_BG, INPUT_BORDER = "#07121d", "#2f5377"
ACTIVE_ITEM = "#15304c"
ACCENT = "#8ec3ff"


class ScrollableFrame(tk.Frame):
    def __init__(self, master, bg: str, **kwargs):
        super().__init__(master, bg=bg, **kwargs)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.scrollbar = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self.window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.inner.bind("<Configure>", self._sync_scrollregion)
        self.canvas.bind("<Configure>", self._resize_inner)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _sync_scrollregion(self, _=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _resize_inner(self, event):
        self.canvas.itemconfigure(self.window, width=event.width)

    def _on_mousewheel(self, event):
        if self.winfo_ismapped():
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def scroll_bottom(self):
        self.update_idletasks()
        self.canvas.yview_moveto(1.0)


class BubbleMessage(tk.Frame):
    def __init__(self, master, role: str, sender: str, text: str):
        super().__init__(master, bg=master.cget("bg"))
        self.role = role
        self.sender = sender
        self.text = text
        self.body = None
        self._build()
        self.set_wrap(760)

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        bubble_bg = USER_BUBBLE if self.role == "user" else AI_BUBBLE
        fg = USER_TEXT if self.role == "user" else TEXT
        sub_fg = "#5f7894" if self.role == "user" else "#9fc0e4"

        row = tk.Frame(self, bg=self.cget("bg"))
        row.grid(row=0, column=0, sticky="ew", padx=18, pady=10)
        if self.role == "user":
            row.grid_columnconfigure(0, weight=1)
            row.grid_columnconfigure(1, weight=0)
            row.grid_columnconfigure(2, weight=0)
        else:
            row.grid_columnconfigure(0, weight=0)
            row.grid_columnconfigure(1, weight=0)
            row.grid_columnconfigure(2, weight=1)

        tail = tk.Canvas(
            row,
            width=26,
            height=26,
            bg=row.cget("bg"),
            highlightthickness=0,
            bd=0,
        )
        if self.role == "assistant":
            tail.grid(row=0, column=0, sticky="sw", padx=(0, 0), pady=(0, 12))
            tail.create_polygon(4, 24, 24, 12, 24, 24, fill=bubble_bg, outline=bubble_bg)

        bubble = tk.Frame(
            row,
            bg=bubble_bg,
            highlightthickness=1,
            highlightbackground="#2b4c6f" if self.role == "assistant" else "#d9d5ca",
            bd=0,
            padx=18,
            pady=14,
        )
        bubble.grid(row=0, column=1, sticky="w" if self.role == "assistant" else "e")

        self.body = tk.Label(
            bubble,
            text=self.text,
            justify="left",
            anchor="w",
            bg=bubble_bg,
            fg=fg,
            font=("Segoe UI", 16),
            wraplength=620,
        )
        self.body.grid(row=0, column=0, sticky="w")
        tk.Label(
            bubble,
            text=self.sender,
            justify="left",
            anchor="w",
            bg=bubble_bg,
            fg=sub_fg,
            font=("Segoe UI", 11),
            pady=6,
        ).grid(row=1, column=0, sticky="w")

        if self.role == "user":
            tail.grid(row=0, column=2, sticky="se", padx=(0, 0), pady=(0, 12))
            tail.create_polygon(2, 12, 2, 24, 22, 24, fill=bubble_bg, outline=bubble_bg)

    def set_wrap(self, width: int):
        if self.body is not None:
            self.body.configure(wraplength=max(220, width))


class XemAiApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("XemAi")
        self.geometry("1360x820")
        self.minsize(1080, 680)
        self.configure(bg=BG)

        self.backend = ChatBackend()
        if self.backend.user is None:
            name = simpledialog.askstring(
                "Welcome to XemAi", "What should I call you?", parent=self
            ) or "User"
            self.backend.ensure_user(name)
        else:
            self.backend.ensure_user(self.backend.user["name"])

        self.events = queue.Queue()
        self.busy = False
        self.chat_ids = []
        self.current_chat_id = None
        self.chat_buttons: list[tk.Widget] = []
        self.message_widgets: list[BubbleMessage] = []

        self._build()
        self._refresh_chats()
        self.after(100, self._poll)
        self.after(500, self._startup)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.bind("<Configure>", self._on_resize)

    def _build(self):
        self.bg_canvas = tk.Canvas(self, bg=BG, highlightthickness=0, bd=0)
        self.bg_canvas.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.bg_canvas.bind("<Configure>", self._draw_gradient)

        self.shell = tk.Frame(self, bg="#04101a", highlightthickness=1, highlightbackground="#2a4965")
        self.shell.place(relx=0.5, rely=0.5, relwidth=0.93, relheight=0.9, anchor="center")
        self.shell.grid_columnconfigure(1, weight=1)
        self.shell.grid_rowconfigure(0, weight=1)

        # Sidebar
        self.sidebar = tk.Frame(self.shell, bg="#06111a", width=300, highlightthickness=1, highlightbackground="#17324a")
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)
        self.sidebar.grid_columnconfigure(0, weight=1)
        self.sidebar.grid_rowconfigure(3, weight=1)

        tk.Label(
            self.sidebar,
            text=self.backend.config.get("assistant_name", "XemAi"),
            bg=self.sidebar.cget("bg"),
            fg=TEXT,
            font=("Segoe UI Light", 30),
            anchor="w",
            padx=24,
            pady=24,
        ).grid(row=0, column=0, sticky="ew")

        new_holder = tk.Frame(self.sidebar, bg=self.sidebar.cget("bg"))
        new_holder.grid(row=1, column=0, sticky="ew", padx=22, pady=(0, 18))
        new_holder.grid_columnconfigure(1, weight=1)
        plus = tk.Label(new_holder, text="＋", bg="#15304a", fg="#a8d1ff", font=("Segoe UI", 22), width=2)
        plus.grid(row=0, column=0, padx=(0, 10), pady=0)
        self.new_btn = tk.Button(
            new_holder,
            text="New Chat",
            command=self._new_chat,
            bg="#15304a",
            fg=TEXT,
            activebackground="#214363",
            activeforeground=TEXT,
            relief="flat",
            bd=0,
            font=("Segoe UI", 14),
            padx=14,
            pady=14,
            anchor="w",
        )
        self.new_btn.grid(row=0, column=1, sticky="ew")

        divider = tk.Frame(self.sidebar, bg="#1a3248", height=1)
        divider.grid(row=2, column=0, sticky="ew", padx=28, pady=(0, 18))

        list_wrap = tk.Frame(self.sidebar, bg=self.sidebar.cget("bg"))
        list_wrap.grid(row=3, column=0, sticky="nsew", padx=18)
        list_wrap.grid_columnconfigure(0, weight=1)
        list_wrap.grid_rowconfigure(1, weight=1)
        tk.Label(
            list_wrap,
            text="Recent Chats",
            bg=list_wrap.cget("bg"),
            fg=MUTED,
            font=("Segoe UI", 14),
            anchor="w",
            pady=8,
        ).grid(row=0, column=0, sticky="ew")

        self.chat_scroll = ScrollableFrame(list_wrap, bg=list_wrap.cget("bg"))
        self.chat_scroll.grid(row=1, column=0, sticky="nsew")

        bottom = tk.Frame(self.sidebar, bg=self.sidebar.cget("bg"))
        bottom.grid(row=4, column=0, sticky="ew", padx=22, pady=16)
        for c in range(2):
            bottom.grid_columnconfigure(c, weight=1)
        actions = [
            ("Capabilities", self._capabilities),
            ("Settings", self._settings),
            ("Mobile", self._mobile),
            (f"Update · v{VERSION}", self._check_update),
        ]
        for i, (label, command) in enumerate(actions):
            tk.Button(
                bottom,
                text=label,
                command=command,
                bg=self.sidebar.cget("bg"),
                fg=MUTED,
                activebackground="#102131",
                activeforeground=TEXT,
                relief="flat",
                bd=0,
                font=("Segoe UI", 10),
                padx=10,
                pady=6,
            ).grid(row=i // 2, column=i % 2, sticky="ew", padx=4, pady=4)

        # Main area
        self.main = tk.Frame(self.shell, bg="#03070c")
        self.main.grid(row=0, column=1, sticky="nsew")
        self.main.grid_columnconfigure(0, weight=1)
        self.main.grid_rowconfigure(1, weight=1)

        top = tk.Frame(self.main, bg="#03070c", height=70)
        top.grid(row=0, column=0, sticky="ew")
        top.grid_columnconfigure(0, weight=1)
        top.grid_columnconfigure(1, weight=1)
        top.grid_columnconfigure(2, weight=1)

        tk.Label(top, text="", bg=top.cget("bg")).grid(row=0, column=0)
        self.brand = tk.Label(
            top,
            text=self.backend.config.get("assistant_name", "XemAi"),
            bg=top.cget("bg"),
            fg=TEXT,
            font=("Segoe UI Light", 30),
        )
        self.brand.grid(row=0, column=1, pady=20)

        actions = tk.Frame(top, bg=top.cget("bg"))
        actions.grid(row=0, column=2, sticky="e", padx=22)
        tk.Button(actions, text="⌕", command=self._capabilities, bg=top.cget("bg"), fg=MUTED,
                  activebackground="#102131", activeforeground=TEXT, relief="flat", bd=0,
                  font=("Segoe UI Symbol", 20)).grid(row=0, column=0, padx=6)
        tk.Button(actions, text="⋯", command=self._settings, bg=top.cget("bg"), fg=MUTED,
                  activebackground="#102131", activeforeground=TEXT, relief="flat", bd=0,
                  font=("Segoe UI Symbol", 20)).grid(row=0, column=1, padx=6)

        self.messages = ScrollableFrame(self.main, bg="#03070c")
        self.messages.grid(row=1, column=0, sticky="nsew", padx=(26, 26), pady=(0, 12))
        self.messages.inner.grid_columnconfigure(0, weight=1)

        self.status = tk.Label(
            self.main,
            text="Ready",
            bg="#03070c",
            fg=MUTED,
            font=("Segoe UI", 10),
            anchor="center",
        )
        self.status.grid(row=2, column=0, sticky="ew", pady=(0, 2))

        composer_holder = tk.Frame(self.main, bg="#03070c")
        composer_holder.grid(row=3, column=0, sticky="ew", padx=26, pady=(0, 24))
        composer_holder.grid_columnconfigure(1, weight=1)

        self.composer = tk.Frame(
            composer_holder,
            bg=INPUT_BG,
            highlightthickness=1,
            highlightbackground=INPUT_BORDER,
            padx=16,
            pady=12,
        )
        self.composer.grid(row=0, column=0, sticky="ew")
        self.composer.grid_columnconfigure(1, weight=1)

        self.plus_btn = tk.Button(
            self.composer,
            text="＋",
            command=self._new_chat,
            bg="#17304a",
            fg="#9fc9ff",
            activebackground="#214363",
            activeforeground="#d3e6ff",
            relief="flat",
            bd=0,
            font=("Segoe UI", 24),
            width=2,
            pady=3,
        )
        self.plus_btn.grid(row=0, column=0, padx=(0, 12), sticky="s")

        self.input = tk.Text(
            self.composer,
            height=3,
            wrap="word",
            bg=INPUT_BG,
            fg=TEXT,
            insertbackground=TEXT,
            bd=0,
            highlightthickness=0,
            padx=8,
            pady=10,
            font=("Segoe UI", 16),
        )
        self.input.grid(row=0, column=1, sticky="ew")
        self.input.bind("<Return>", self._enter)

        self.send_btn = tk.Button(
            self.composer,
            text="➤",
            command=self._send,
            bg="#88bdf6",
            fg="white",
            activebackground="#a7d0ff",
            activeforeground="white",
            relief="flat",
            bd=0,
            font=("Segoe UI Symbol", 22),
            width=2,
            pady=3,
        )
        self.send_btn.grid(row=0, column=2, padx=(12, 0), sticky="s")

        self.hint = tk.Label(
            composer_holder,
            text="Enter to send · Shift+Enter for new line",
            bg="#03070c",
            fg=MUTED,
            font=("Segoe UI", 9),
        )
        self.hint.grid(row=1, column=0, sticky="w", pady=(6, 0))

    def _draw_gradient(self, event=None):
        w = self.bg_canvas.winfo_width()
        h = self.bg_canvas.winfo_height()
        if w < 2 or h < 2:
            return
        self.bg_canvas.delete("grad")
        top = (0x02, 0x05, 0x09)
        bottom = (0x07, 0x23, 0x39)
        for i in range(h):
            t = i / max(1, h - 1)
            r = int(top[0] + (bottom[0] - top[0]) * t)
            g = int(top[1] + (bottom[1] - top[1]) * t)
            b = int(top[2] + (bottom[2] - top[2]) * t)
            color = f"#{r:02x}{g:02x}{b:02x}"
            self.bg_canvas.create_line(0, i, w, i, fill=color, tags="grad")
        self.bg_canvas.create_oval(-w * 0.25, h * 0.45, w * 0.45, h * 1.35,
                                   fill="#0a2d48", outline="", stipple="gray25", tags="grad")
        self.bg_canvas.create_oval(w * 0.55, h * 0.55, w * 1.2, h * 1.45,
                                   fill="#123554", outline="", stipple="gray25", tags="grad")
        self.bg_canvas.tag_lower("grad")

    def _format_time(self, value: str | None) -> str:
        if not value:
            return ""
        try:
            stamp = dt.datetime.fromisoformat(value)
        except ValueError:
            return ""
        now = dt.datetime.now()
        delta = now - stamp
        if delta.total_seconds() < 90:
            return "Just now"
        if delta.total_seconds() < 3600:
            mins = int(delta.total_seconds() // 60)
            return f"{mins} min ago"
        if delta.total_seconds() < 86400:
            hrs = int(delta.total_seconds() // 3600)
            return f"{hrs} hour{'s' if hrs != 1 else ''} ago"
        days = delta.days
        return f"{days} day{'s' if days != 1 else ''} ago"

    def _make_chat_card(self, row, active: bool):
        card = tk.Button(
            self.chat_scroll.inner,
            bg=ACTIVE_ITEM if active else self.chat_scroll.inner.cget("bg"),
            activebackground="#173552",
            activeforeground=TEXT,
            relief="flat",
            bd=0,
            highlightthickness=0,
            padx=12,
            pady=10,
            command=lambda chat_id=row["id"]: self._select_chat_id(chat_id),
        )
        card.grid_columnconfigure(1, weight=1)
        icon = tk.Label(card, text="◌", bg=card.cget("bg"), fg="#93bde7", font=("Segoe UI Symbol", 18))
        icon.grid(row=0, column=0, rowspan=2, padx=(2, 10), sticky="n")
        title = tk.Label(card, text=row["title"], bg=card.cget("bg"), fg=TEXT,
                         font=("Segoe UI", 13), anchor="w", justify="left")
        title.grid(row=0, column=1, sticky="w")
        meta = tk.Label(card, text=self._format_time(row["updated_at"]), bg=card.cget("bg"), fg=MUTED,
                        font=("Segoe UI", 10), anchor="w")
        meta.grid(row=1, column=1, sticky="w")
        for widget in (icon, title, meta):
            widget.bind("<Button-1>", lambda _e, chat_id=row["id"]: self._select_chat_id(chat_id))
        return card

    def _refresh_chats(self, select_id=None):
        rows = self.backend.chats()
        if not rows:
            rows = [self.backend.create_chat()]
        for widget in self.chat_buttons:
            widget.destroy()
        self.chat_buttons.clear()
        self.chat_ids = []
        chosen = 0
        for i, row in enumerate(rows):
            self.chat_ids.append(row["id"])
            if row["id"] == select_id:
                chosen = i
            active = i == chosen if select_id is None else row["id"] == select_id
            card = self._make_chat_card(row, active)
            card.grid(row=i, column=0, sticky="ew", pady=6)
            self.chat_buttons.append(card)
        self.current_chat_id = self.chat_ids[chosen]
        self._load_chat(self.current_chat_id)

    def _clear_messages(self):
        for widget in self.message_widgets:
            widget.destroy()
        self.message_widgets.clear()

    def _load_chat(self, chat_id):
        chat = self.backend.get_chat(chat_id)
        self.title(chat["title"] + " · XemAi")
        self._clear_messages()
        rows = self.backend.messages(chat_id)
        if not rows:
            self._append("assistant", f"Hi {self.backend.user['name']}. What would you like to work on?")
        else:
            for row in rows:
                if row["role"] in {"user", "assistant"}:
                    self._append(row["role"], row["content"])
        self.messages.scroll_bottom()

    def _append(self, role, text):
        sender = self.backend.user["name"] if role == "user" else self.backend.config.get("assistant_name", "XemAi")
        bubble = BubbleMessage(self.messages.inner, role, sender, text)
        bubble.grid(row=len(self.message_widgets), column=0, sticky="ew")
        self.message_widgets.append(bubble)
        self._resize_bubbles()
        self.messages.scroll_bottom()

    def _resize_bubbles(self):
        available = max(440, self.messages.canvas.winfo_width())
        wrap = int(min(max(available * 0.55, 280), 650))
        for bubble in self.message_widgets:
            bubble.set_wrap(wrap)

    def _select_chat_id(self, chat_id: int):
        if self.busy:
            return
        self.current_chat_id = chat_id
        self._refresh_chats(chat_id)

    def _new_chat(self):
        if self.busy:
            return
        chat = self.backend.create_chat()
        self._refresh_chats(chat["id"])
        self.input.focus_set()

    def _enter(self, event):
        if event.state & 0x0001:
            return None
        self._send()
        return "break"

    def _busy(self, value, text=None):
        self.busy = value
        state = "disabled" if value else "normal"
        self.send_btn.configure(state=state)
        self.new_btn.configure(state=state)
        self.plus_btn.configure(state=state)
        self.input.configure(state=state)
        self.status.configure(text=text or ("XemAi is thinking..." if value else f"Connected · v{VERSION}"))

    def _send(self):
        if self.busy:
            return
        text = self.input.get("1.0", "end-1c").strip()
        if not text:
            return
        self.input.delete("1.0", "end")
        self._append("user", text)
        self._busy(True)
        chat_id = self.current_chat_id
        threading.Thread(target=self._send_worker, args=(chat_id, text), daemon=True).start()

    def _send_worker(self, chat_id, text):
        try:
            answer = self.backend.send(chat_id, text, status_callback=lambda s: self.events.put(("status", s)))
            self.events.put(("answer", chat_id, answer))
        except Exception as e:
            self.backend.logger.exception("GUI response failed")
            self.events.put(("error", str(e)))

    def _poll(self):
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "status":
                    self.status.configure(text=event[1])
                elif kind == "answer":
                    _, chat_id, answer = event
                    if chat_id == self.current_chat_id:
                        self._append("assistant", answer)
                    self._busy(False)
                    self._refresh_chats(self.current_chat_id)
                    self.input.focus_set()
                elif kind == "error":
                    self._busy(False, "Error")
                    messagebox.showerror("XemAi", event[1], parent=self)
                elif kind == "update":
                    self._offer_update(event[1])
                elif kind == "uptodate":
                    self.status.configure(text=f"Up to date · v{VERSION}")
                elif kind == "restart":
                    messagebox.showinfo("XemAi", f"Updated to v{event[1]}. Restarting now.", parent=self)
                    self._restart()
                    return
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _capabilities(self):
        messagebox.showinfo("XemAi capabilities", "\n".join("• " + x for x in self.backend.capabilities()), parent=self)

    def _settings(self):
        win = tk.Toplevel(self)
        win.title("Settings")
        win.geometry("480x320")
        win.configure(bg="#08131d")
        win.transient(self)
        win.grab_set()

        fields = [
            ("AI name", self.backend.config.get("assistant_name", "XemAi"), False),
            ("Ollama model", self.backend.config.get("model", "qwen3:8b"), False),
            ("New web API key (optional)", "", True),
        ]
        entries = []
        for i, (label, value, secret) in enumerate(fields):
            tk.Label(win, text=label, bg=win.cget("bg"), fg=TEXT, anchor="w", font=("Segoe UI", 11)).grid(
                row=i*2, column=0, sticky="w", padx=24, pady=(16, 4)
            )
            e = tk.Entry(win, bg="#0d1d2c", fg=TEXT, insertbackground=TEXT, relief="flat", show="•" if secret else "")
            e.insert(0, value)
            e.grid(row=i*2+1, column=0, sticky="ew", padx=24, ipady=8)
            entries.append(e)

        def save():
            try:
                self.backend.save_settings(
                    assistant_name=entries[0].get(),
                    model=entries[1].get(),
                    api_key=entries[2].get(),
                )
                self.brand.configure(text=self.backend.config.get("assistant_name", "XemAi"))
                win.destroy()
                self._load_chat(self.current_chat_id)
            except Exception as e:
                messagebox.showerror("Settings", str(e), parent=win)

        buttons = tk.Frame(win, bg=win.cget("bg"))
        buttons.grid(row=6, column=0, sticky="ew", padx=24, pady=22)
        buttons.grid_columnconfigure(0, weight=1)
        tk.Button(buttons, text="Test web", command=lambda: messagebox.showinfo("Web search", self.backend.web_test()[1], parent=win),
                  bg="#14283b", fg=TEXT, relief="flat", bd=0, padx=16, pady=8).grid(row=0, column=0, sticky="w")
        tk.Button(buttons, text="Save", command=save, bg="#88bdf6", fg="#08213c", relief="flat", bd=0, padx=18, pady=8).grid(row=0, column=1, sticky="e")
        win.grid_columnconfigure(0, weight=1)

    def _mobile(self):
        ensure_mobile_server_current()
        url = mobile_local_url()
        messagebox.showinfo(
            "XemAi Mobile",
            "XemAi's mobile server is running locally.\n\n"
            f"Local address on this PC:\n{url}\n\n"
            "For Android away from home, install Tailscale on the PC and phone, "
            "sign both into the same tailnet, then run mobile_tailscale_setup.bat once on the PC. "
            "It will show the private HTTPS address to open on your phone.\n\n"
            "The phone and PC use the same XemAi database, chats, memories and feedback.",
            parent=self,
        )

    def _startup(self):
        self.status.configure(text=f"Connected · v{VERSION}")
        if self.backend.config.get("mobile_server_autostart", True):
            if not ensure_mobile_server_current():
                self.backend.logger.warning(
                    "Could not bring mobile server to current version | app=%s server=%s",
                    VERSION, mobile_server_version(),
                )
        err = self.backend.health_error()
        if err:
            messagebox.showerror("XemAi", err, parent=self)
            self.status.configure(text="Ollama unavailable")
            return
        if self.backend.config.get("check_updates_on_startup"):
            self._check_update(silent=True)

    def _check_update(self, silent=False):
        self.status.configure(text="Checking for updates...")
        def work():
            try:
                manifest = self.backend.check_update()
                self.events.put(("update", manifest) if manifest else ("uptodate",))
            except Exception as e:
                if not silent:
                    self.events.put(("error", f"Update check failed: {e}"))
        threading.Thread(target=work, daemon=True).start()

    def _offer_update(self, manifest):
        notes = str(manifest.get("notes", "")).strip()
        text = f"XemAi v{manifest['version']} is available."
        if notes:
            text += "\n\n" + notes
        text += "\n\nInstall now?"
        if not messagebox.askyesno("XemAi update", text, parent=self):
            return
        self._busy(True, f"Installing v{manifest['version']}...")
        def work():
            try:
                version = self.backend.install_update(manifest)
                self.events.put(("restart", version))
            except Exception as e:
                self.events.put(("error", f"Update failed: {e}"))
        threading.Thread(target=work, daemon=True).start()

    def _restart(self):
        self.backend.close()
        restart_mobile_server_process()
        script = BASE_DIR / "XemAi.pyw"
        exe = Path(sys.executable)
        pythonw = exe.with_name("pythonw.exe")
        chosen = pythonw if pythonw.exists() else exe
        os.execv(str(chosen), [str(chosen), str(script)])

    def _on_resize(self, _event=None):
        self._resize_bubbles()

    def _close(self):
        if self.busy and not messagebox.askyesno("Close XemAi", "XemAi is still working. Close anyway?", parent=self):
            return
        self.backend.close()
        self.destroy()


def main():
    app = XemAiApp()
    app.mainloop()


if __name__ == "__main__":
    main()
