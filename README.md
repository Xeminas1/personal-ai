# Personal AI

Local-first personal AI project.

Current prototype: **v0.1.3**.

Core goals include truth-first reasoning, anti-sycophancy, persistent cross-chat memory, user profiles, local logging, 0-10 chat-level feedback, continual learning, swappable model backends, and an eventual capability target comparable to frontier GPT/Codex systems.

## Privacy

Personal data stays local. The repository must not contain `data/`, local databases, conversation logs, API keys, or user-specific configuration.

## Updates

The app includes a built-in updater. Release packages are stored under `releases/`, and `update_manifest.json` describes the current release.


## v0.1.7

Web reliability update:
- `/websetup` now validates an Ollama API key before saving it
- `/webtest` performs a real one-result search using the saved key
- `/tools` now says `configured` rather than pretending an untested key is connected
- HTTP 401 now produces a clear "API key rejected" message
- explicit requests such as "search the web" and "latest news" are deterministically routed through web search instead of relying entirely on the local model to choose the tool
- the model is explicitly forbidden from claiming an old training cutoff when live web search is available


## v0.1.8

Update experience:
- successful `/update` installs now restart Personal AI automatically
- the existing command window is reused
- there is no need to close Command Prompt or reopen `run.bat`
- the database is closed cleanly immediately before the process is replaced
- the new Python process reloads all updated modules from disk


## v0.1.9

Auto-update restart validation:
- small release intended to verify that v0.1.8 can install an update and relaunch Personal AI automatically in the same command window
- no database, memory, profile, feedback, API-key, or configuration migration is required


## v0.2.0

Identity and readability update:
- the personal AI now has a visible name: `XemAi`
- responses are displayed as `XemAi > ...` instead of `AI > ...`
- the system prompt gives the assistant a stable identity as XemAi
- `/ainame` shows the current AI name
- `/ainame Xeminas` or `/ainame XemAi` changes the name without editing code
- the chosen name is stored in local `config.json` and survives normal updates


## v0.2.1

Self-knowledge update:
- XemAi now receives an explicit snapshot of the Personal AI app's real capabilities on every turn
- adds `/capabilities` for a deterministic, non-model-generated capability report
- prevents generic Qwen disclaimers from contradicting enabled features
- explicitly identifies persistent chat history and cross-chat memory as enabled
- explicitly identifies live web search, webpage fetching, calculator, time, feedback and workspace tools
- explicitly identifies current limitations such as no arbitrary shell, unrestricted computer control, native vision or native audio/video analysis
- forbids invented training-cutoff years unless a verified cutoff is actually supplied
- distinguishes sandboxed workspace access from unrestricted filesystem access


## v0.2.2

Recovery and update-safety release:
- repairs the malformed `/ainame` f-strings published in v0.2.1
- verifies every staged Python file compiles before replacing any live application file
- ZIP-based updates receive the same pre-install Python syntax validation
- self-test now compiles the full project, including `main.py`, before reporting success
- preserves the XemAi identity and self-knowledge features introduced in v0.2.1


## v0.3.0

Desktop frontend release:
- adds a native dark-mode XemAi desktop chat interface
- launches from `run.bat` without leaving a command console open
- `XemAi.pyw` can also be opened directly
- left sidebar lists persistent chats and supports creating/switching chats
- central conversation view shows Reece and XemAi labels clearly
- ChatGPT-style composer with Enter-to-send and Shift+Enter for new lines
- settings window for AI name, Ollama model and web-search API key
- capabilities dialog
- graphical update checks/install flow with automatic GUI restart
- background response generation keeps the window responsive
- new chats are automatically titled from the first message
- `console.bat` keeps the old command-line interface available for troubleshooting
- adds shared capability reporting in `app/capabilities.py`


## v0.3.1

Authoritative self-knowledge update:
- detects questions about XemAi's own capabilities, limitations, version and iterative updates
- injects authoritative runtime self-data immediately before those questions
- supplies a concise release history so XemAi can genuinely recognise what has been added over time
- removes known-stale assistant self-descriptions from context for self-knowledge questions
- explicitly separates the underlying Qwen model from XemAi as the complete app + model + tools + memory + UI
- corrects false claims such as "no web search", "no memory", "each chat is independent" and invented 2023 cutoffs
- documents real remaining gaps such as no unrestricted shell/computer control, no native vision/audio/video, simple memory retrieval, and feedback that does not yet fine-tune model weights


## v0.4.0

Shared PC + Android release:
- adds a local XemAi mobile HTTP server on `127.0.0.1:8765`
- adds an Android-friendly progressive web app in `mobile/`
- Windows and Android use the same SQLite database, chats, memories, feedback and learning state
- mobile can create/switch chats, read shared history, message XemAi, view capabilities and rate chats
- sensitive desktop/admin controls such as API-key management and updater installation are not exposed through the mobile API
- adds WAL mode and SQLite busy timeouts for safer concurrent desktop/mobile access
- adds `XemAiServer.pyw` background server and automatic server startup with the Windows app
- closing the desktop window does not intentionally stop the separate mobile server process
- adds a `Mobile` button to the desktop UI with connection guidance
- adds `mobile_tailscale_setup.bat` for private Tailscale Serve routing to the localhost server
- mobile server remains loopback-only by default; it is not exposed to the LAN or public internet
- mobile PWA supports home-screen installation when accessed through HTTPS (for example via Tailscale Serve)


## v0.4.1

Mobile update control:
- adds `Update XemAi` to the Android/mobile drawer
- phone can check the official configured XemAi update channel
- phone can install a newer release without opening the Windows desktop UI
- the mobile API re-checks the update manifest server-side; the phone cannot supply arbitrary update URLs or files
- SHA verification and staged Python compile validation remain enforced by the normal updater
- after a mobile update, the XemAi mobile server restarts itself using the newly installed code
- the phone waits for the server to return and reloads automatically
- API-key management, model settings and arbitrary PC configuration remain unavailable from mobile
- if the Windows desktop app is open during a phone update, its in-memory code remains the old version until the desktop app is restarted


## v0.4.2

Android mobile cache fix:
- fixes the mobile Update XemAi button appearing without working when Android combined new HTML with cached old JavaScript
- version-tags mobile JavaScript and CSS URLs
- mobile HTML, JavaScript, CSS and service-worker responses now use no-store caching
- the service worker removes stale XemAi app caches and always fetches current same-origin UI code
- preserves phone-based official update checking/install from v0.4.1


## v0.4.3

Mobile-server lifecycle fix:
- fixes the phone showing `XemAi server returned HTTP 200` when the frontend was newer than the still-running background server
- desktop startup now checks the actual `/api/health` server version and replaces an older XemAi mobile-server process
- desktop updates restart the background mobile server before relaunching the desktop UI
- new mobile-server processes write a local PID/version state file for safe targeted restarts
- includes a Windows legacy-process recovery path for v0.4.0-v0.4.2 servers that did not write PID files
- the legacy recovery only targets Python processes whose command line contains this installation's exact `XemAiServer.pyw` path
- unknown `/api/...` routes now return JSON 404 instead of falling through to the HTML app with HTTP 200
- mobile API parse errors now explicitly report frontend/server version mismatch
- adds `restart_mobile_server.bat` as a manual recovery tool


## v0.4.4

Verified republish of the mobile-server lifecycle fix:
- supersedes the rejected v0.4.3 update manifest
- keeps the version-aware background mobile-server restart logic
- keeps JSON 404 responses for unknown mobile API routes
- keeps explicit frontend/server mismatch diagnostics
- release publication now verifies every manifest SHA against the frozen GitHub release content before making the manifest live


## v0.4.5

Exact-source republish:
- supersedes the rejected v0.4.3 and abandoned v0.4.4 publishing attempts
- publishes the exact locally tested mobile-server lifecycle source
- keeps SHA verification mandatory
- freezes release content first, then computes the live manifest hashes from that frozen GitHub branch
