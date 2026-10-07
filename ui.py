from __future__ import annotations

import os
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, simpledialog
from tkinter.scrolledtext import ScrolledText

from app.gui_backend import ChatBackend
from app.version import VERSION

BASE_DIR = Path(__file__).resolve().parent
BG, SIDE, INPUT, TEXT = "#212121", "#171717", "#2f2f2f", "#ececec"
MUTED, ACCENT, SELECT = "#a8a8a8", "#10a37f", "#2a2a2a"


class XemAiApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("XemAi")
        self.geometry("1180x760")
        self.minsize(880, 580)
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

        self._build()
        self._refresh_chats()
        self.after(100, self._poll)
        self.after(500, self._startup)
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _build(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        side = tk.Frame(self, bg=SIDE, width=260)
        side.grid(row=0, column=0, sticky="nsew")
        side.grid_propagate(False)
        side.grid_rowconfigure(2, weight=1)
        side.grid_columnconfigure(0, weight=1)

        self.brand = tk.Label(
            side, text=self.backend.config.get("assistant_name", "XemAi"),
            bg=SIDE, fg=TEXT, font=("Segoe UI Semibold", 18),
            anchor="w", padx=16, pady=14
        )
        self.brand.grid(row=0, column=0, sticky="ew")

        self.new_btn = tk.Button(
            side, text="+  New chat", command=self._new_chat,
            bg=SIDE, fg=TEXT, activebackground=SELECT, activeforeground=TEXT,
            relief="solid", bd=1, font=("Segoe UI", 10),
            anchor="w", padx=12, pady=8
        )
        self.new_btn.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 10))

        self.chat_list = tk.Listbox(
            side, bg=SIDE, fg=TEXT, selectbackground=SELECT,
            selectforeground=TEXT, bd=0, highlightthickness=0,
            activestyle="none", font=("Segoe UI", 10)
        )
        self.chat_list.grid(row=2, column=0, sticky="nsew", padx=8)
        self.chat_list.bind("<<ListboxSelect>>", self._select_chat)

        bottom = tk.Frame(side, bg=SIDE)
        bottom.grid(row=3, column=0, sticky="ew", padx=10, pady=10)
        for c in (0, 1):
            bottom.grid_columnconfigure(c, weight=1)

        tk.Button(
            bottom, text="Capabilities", command=self._capabilities,
            bg=SIDE, fg=MUTED, relief="flat"
        ).grid(row=0, column=0, sticky="ew")
        tk.Button(
            bottom, text="Settings", command=self._settings,
            bg=SIDE, fg=MUTED, relief="flat"
        ).grid(row=0, column=1, sticky="ew")
        tk.Button(
            bottom, text=f"Update · v{VERSION}", command=self._check_update,
            bg=SIDE, fg=MUTED, relief="flat"
        ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(5, 0))

        main = tk.Frame(self, bg=BG)
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)

        head = tk.Frame(main, bg=BG, height=54)
        head.grid(row=0, column=0, sticky="ew")
        head.grid_propagate(False)
        head.grid_columnconfigure(0, weight=1)
        self.title_label = tk.Label(
            head, text="", bg=BG, fg=TEXT,
            font=("Segoe UI Semibold", 12), anchor="w", padx=24
        )
        self.title_label.grid(row=0, column=0, sticky="nsew")
        self.status = tk.Label(
            head, text="Ready", bg=BG, fg=MUTED,
            font=("Segoe UI", 9), padx=18
        )
        self.status.grid(row=0, column=1)

        self.view = ScrolledText(
            main, wrap="word", bg=BG, fg=TEXT, bd=0,
            highlightthickness=0, padx=65, pady=20,
            font=("Segoe UI", 11)
        )
        self.view.grid(row=1, column=0, sticky="nsew")
        self.view.configure(state="disabled")
        self.view.tag_configure("user", foreground="#ffffff",
                                font=("Segoe UI Semibold", 10), spacing1=14)
        self.view.tag_configure("ai", foreground=ACCENT,
                                font=("Segoe UI Semibold", 10), spacing1=14)
        self.view.tag_configure("body", foreground=TEXT,
                                font=("Segoe UI", 11), spacing3=9)
        self.view.tag_configure("code", foreground="#dddddd",
                                background="#111111", font=("Consolas", 10))

        outer = tk.Frame(main, bg=BG)
        outer.grid(row=2, column=0, sticky="ew", padx=65, pady=(6, 18))
        outer.grid_columnconfigure(0, weight=1)
        box = tk.Frame(outer, bg=INPUT, highlightbackground="#3b3b3b",
                       highlightthickness=1)
        box.grid(row=0, column=0, sticky="ew")
        box.grid_columnconfigure(0, weight=1)
        self.input = tk.Text(
            box, height=4, wrap="word", bg=INPUT, fg=TEXT,
            insertbackground=TEXT, bd=0, padx=12, pady=10,
            font=("Segoe UI", 11)
        )
        self.input.grid(row=0, column=0, sticky="ew")
        self.input.bind("<Return>", self._enter)
        self.send_btn = tk.Button(
            box, text="Send", command=self._send,
            bg=ACCENT, fg="white", relief="flat",
            font=("Segoe UI Semibold", 10), padx=16, pady=7
        )
        self.send_btn.grid(row=0, column=1, padx=9, pady=9, sticky="s")
        tk.Label(
            outer, text="Enter to send · Shift+Enter for new line",
            bg=BG, fg=MUTED, font=("Segoe UI", 8)
        ).grid(row=1, column=0, pady=(5, 0))

    def _refresh_chats(self, select_id=None):
        rows = self.backend.chats()
        if not rows:
            rows = [self.backend.create_chat()]
        self.chat_list.delete(0, "end")
        self.chat_ids = []
        chosen = 0
        for i, row in enumerate(rows):
            self.chat_ids.append(row["id"])
            self.chat_list.insert("end", row["title"])
            if row["id"] == select_id:
                chosen = i
        self.chat_list.selection_set(chosen)
        self.current_chat_id = self.chat_ids[chosen]
        self._load_chat(self.current_chat_id)

    def _load_chat(self, chat_id):
        chat = self.backend.get_chat(chat_id)
        self.title_label.configure(text=chat["title"])
        self.view.configure(state="normal")
        self.view.delete("1.0", "end")
        rows = self.backend.messages(chat_id)
        if not rows:
            self._append("assistant",
                         f"Hi {self.backend.user['name']}. What would you like to work on?")
        else:
            for row in rows:
                if row["role"] in {"user", "assistant"}:
                    self._append(row["role"], row["content"])
        self.view.configure(state="disabled")
        self.view.see("end")

    def _append(self, role, text):
        self.view.configure(state="normal")
        name = (self.backend.user["name"] if role == "user"
                else self.backend.config.get("assistant_name", "XemAi"))
        self.view.insert("end", name + "\n", "user" if role == "user" else "ai")
        code = False
        for line in text.splitlines():
            if line.strip().startswith("```"):
                code = not code
                continue
            self.view.insert("end", line + "\n", "code" if code else "body")
        self.view.insert("end", "\n")
        self.view.configure(state="disabled")
        self.view.see("end")

    def _new_chat(self):
        if self.busy:
            return
        chat = self.backend.create_chat()
        self._refresh_chats(chat["id"])
        self.input.focus_set()

    def _select_chat(self, _=None):
        if self.busy:
            return
        sel = self.chat_list.curselection()
        if sel:
            self.current_chat_id = self.chat_ids[sel[0]]
            self._load_chat(self.current_chat_id)

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
        self.status.configure(text=text or ("XemAi is thinking..." if value else "Ready"))

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
        threading.Thread(target=self._send_worker,
                         args=(chat_id, text), daemon=True).start()

    def _send_worker(self, chat_id, text):
        try:
            answer = self.backend.send(
                chat_id, text,
                status_callback=lambda s: self.events.put(("status", s))
            )
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
                    messagebox.showinfo(
                        "XemAi", f"Updated to v{event[1]}. Restarting now.",
                        parent=self
                    )
                    self._restart()
                    return
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _capabilities(self):
        messagebox.showinfo(
            "XemAi capabilities",
            "\n".join("• " + x for x in self.backend.capabilities()),
            parent=self
        )

    def _settings(self):
        win = tk.Toplevel(self)
        win.title("Settings")
        win.geometry("440x300")
        win.configure(bg=BG)
        win.transient(self)
        win.grab_set()

        fields = [
            ("AI name", self.backend.config.get("assistant_name", "XemAi"), False),
            ("Ollama model", self.backend.config.get("model", "qwen3:8b"), False),
            ("New web API key (optional)", "", True),
        ]
        entries = []
        for i, (label, value, secret) in enumerate(fields):
            tk.Label(win, text=label, bg=BG, fg=TEXT,
                     anchor="w").grid(row=i*2, column=0, sticky="w",
                                      padx=20, pady=(14, 4))
            e = tk.Entry(win, bg=INPUT, fg=TEXT, insertbackground=TEXT,
                         relief="flat", show="•" if secret else "")
            e.insert(0, value)
            e.grid(row=i*2+1, column=0, sticky="ew", padx=20, ipady=6)
            entries.append(e)

        def save():
            try:
                self.backend.save_settings(
                    assistant_name=entries[0].get(),
                    model=entries[1].get(),
                    api_key=entries[2].get(),
                )
                self.brand.configure(
                    text=self.backend.config.get("assistant_name", "XemAi")
                )
                win.destroy()
                self._load_chat(self.current_chat_id)
            except Exception as e:
                messagebox.showerror("Settings", str(e), parent=win)

        tk.Button(win, text="Test web",
                  command=lambda: messagebox.showinfo(
                      "Web search", self.backend.web_test()[1], parent=win
                  ), bg=SELECT, fg=TEXT, relief="flat").grid(
                      row=6, column=0, sticky="w", padx=20, pady=18)
        tk.Button(win, text="Save", command=save, bg=ACCENT, fg="white",
                  relief="flat", padx=18).grid(
                      row=6, column=0, sticky="e", padx=20, pady=18)
        win.grid_columnconfigure(0, weight=1)

    def _startup(self):
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
                self.events.put(("update", manifest) if manifest
                                else ("uptodate",))
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
        script = BASE_DIR / "XemAi.pyw"
        exe = Path(sys.executable)
        pythonw = exe.with_name("pythonw.exe")
        chosen = pythonw if pythonw.exists() else exe
        os.execv(str(chosen), [str(chosen), str(script)])

    def _close(self):
        if self.busy and not messagebox.askyesno(
            "Close XemAi", "XemAi is still working. Close anyway?", parent=self
        ):
            return
        self.backend.close()
        self.destroy()


def main():
    app = XemAiApp()
    app.mainloop()


if __name__ == "__main__":
    main()
