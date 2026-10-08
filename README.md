# Personal AI v0.1

A local-first prototype of your independent personal AI.

## What this version already does

- No ChatGPT login.
- Uses a local Ollama model.
- Asks for your name on first launch and creates a local profile.
- Time-aware greeting (morning / afternoon / evening).
- Separate persistent chat threads.
- Cross-chat structured long-term memory.
- Conservative automatic memory extraction.
- 0-10 happiness/helpfulness reward when ending/leaving a chat.
- Local SQLite database.
- Rotating troubleshooting logs.
- Truth-first / anti-sycophancy constitution.
- Swappable local model.
- Does not silently expose API keys because v0.1 needs none.
- Does not give itself shell, internet or computer-control authority yet.

## Important v0.1 limitation

This build does **not** yet have live research, file tools, shell access, vision,
or computer control. It is explicitly instructed to admit those limits instead
of pretending it verified something.

The goal of v0.1 is to prove the core identity, memory, reward, profile, chat,
logging and local-model architecture first.

## Windows setup

### 1. Install Python

Install a current Python 3 release and make sure `python` works in Command Prompt.

Check:

    python --version

### 2. Install Ollama

Install Ollama for Windows and make sure it is running.

Check:

    ollama --version

### 3. Download the starter model

The default is:

    ollama pull qwen3:8b

This model is only a starter model for proving that the system works. It is not
our final capability target.

### 4. Test the non-AI parts

Double-click:

    test.bat

You should see:

    SELF-TEST PASSED

### 5. Start your AI

Double-click:

    run.bat

On first launch it will ask:

    What should I call you?

That creates a local profile in:

    data\personal_ai.db

The main troubleshooting log is:

    logs\personal_ai.log

## Useful commands

    /help
    /new Skyrim Modding
    /chats
    /switch 2
    /profile
    /setstyle Be direct and concise
    /memory
    /remember <something>
    /forget <memory id>
    /model <ollama model name>
    /feedback
    /end
    /log
    /quit

## Reward design

The 0-10 rating is saved as a chat-level reward signal when you leave or end a chat.

It does NOT currently fine-tune model weights. That is intentional. We first
collect clean feedback and outcomes; later we can build a learning layer that
uses the reward history without accidentally training the AI to flatter you.

## Memory design

Long-term memory is stored separately from individual chats.

Automatic learning is conservative:
- preferences
- project requirements
- stable non-sensitive profile context
- user beliefs labelled as beliefs

The AI is instructed not to treat memories as unquestionable facts.

## Logging

By default logs include:
- startup/shutdown
- model used
- chat IDs
- request sizes
- errors
- memory-update events
- model changes

Full message text is NOT written to the log by default.

To enable full-content debug logging, change in `config.json`:

    "log_message_content": true

Use that only when needed because logs would then contain conversation text.

## Next milestones

1. Hardware-aware model selection.
2. Stronger retrieval / embeddings.
3. Research and source-verification pipeline.
4. File and codebase tools.
5. Build/test agent for programming.
6. Vision.
7. Controlled computer-use permissions.
8. Objective outcome tracking alongside 0-10 reward.
9. Model routing: local model first, frontier model only when chosen.
10. Evaluation suite against GPT-level and Codex-level benchmarks.


## Confidence handling

Memory confidence is now controlled by the application rather than invented by
the language model:

- Explicit preference: 1.00
- Explicit project requirement: 0.98
- Explicit profile detail: 0.95
- Explicit user belief: 0.85 (this means confidence that the user stated/holds
  the belief, not that the belief is objectively true)
- Inferred memories receive lower confidence.

Older explicit preferences accidentally stored at 0.00 are repaired to 1.00 on
startup.


## Automatic updates

Version 0.1.3 includes a built-in updater.

Commands:

    /version
    /update

The updater:
- checks a permanent HTTPS manifest URL
- downloads the new release
- verifies its SHA-256 checksum
- backs up the current program files
- installs the new program files
- preserves `data/`, `logs/`, and `config.json`
- asks you to restart after installation

Your chats, memory, profile, feedback and logs are therefore not wiped by an
update.

### One-time setup for a permanent update channel

The updater needs one stable place where future releases are published. A GitHub
repository/releases page is a practical option.

In `config.json`, set:

    "update_manifest_url": "https://YOUR-DOMAIN-OR-RAW-GITHUB-URL/update_manifest.json",
    "check_updates_on_startup": true

After that, the normal workflow is simply:

    /update

No manual unzipping/replacing files is required.

The manifest format is shown in `update_manifest.example.json`.

For security, the updater only accepts HTTPS and checks the downloaded ZIP
against the SHA-256 hash in the manifest before installing it.


## v0.1.5

Behaviour update:
- permits clear, reasoned AI opinions and recommendations
- distinguishes reasoned judgments from human feelings or lived experience
- requires direct answers when asked for an opinion
- prevents lack-of-tools disclaimers from being used for ordinary reasoning
- discourages generic assistant boilerplate when a substantive answer is possible


## v0.1.6

Tools and live-data update:
- native Ollama tool-calling agent loop
- live web search through Ollama Web Search when configured
- direct webpage fetching
- current time tool
- safe calculator
- sandboxed local workspace list/read/write tools
- `/tools` status command
- `/websetup` and `/webclear` for an Ollama web-search API key
- `/rate` for optional immediate feedback without interrupting every reply
- recent 0-10 feedback is injected into future prompts as an optimisation signal

Security/privacy:
- web search is opt-in and requires an Ollama API key
- the key is stored only in local `data/secrets.json`, which remains outside GitHub
- workspace file tools cannot escape the dedicated `workspace/` directory
- arbitrary shell/computer control is still intentionally disabled


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
- basic Markdown-friendly rendering for headings, lists and code blocks
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
- fixes the `Update XemAi` button appearing without working because Android could combine the new HTML with a cached old `app.js`
- version-tags the mobile JavaScript and CSS URLs so every XemAi release requests fresh frontend assets
- mobile JavaScript/CSS/HTML/service-worker responses now use `Cache-Control: no-store`
- service worker no longer serves stale XemAi application code from its cache
- old mobile caches are deleted during service-worker installation
- service-worker registration explicitly requests an update
- keeps the v0.4.1 phone update workflow and automatic mobile-server restart


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


## v0.5.0

Visual redesign release:
- redesigns the Windows desktop XemAi interface to match the new dark blue bubble-chat concept
- redesigns the Android/mobile XemAi interface to the matching mobile concept
- uses sender chat bubbles for both parties with the sender name shown inside each bubble at the lower left
- adds the new dark gradient blue background styling to both desktop and mobile
- upgrades the desktop chat area from plain transcript text to a scrollable bubble-based conversation layout
- upgrades the sidebar and composer to the new rounded card / pill layout
- preserves the shared database, chats, updater, mobile sync, memory and tool systems


## v0.5.1

Desktop startup hotfix:
- fixes a Windows desktop crash in the v0.5.0 recent-chat timestamp renderer when stored timestamps include timezone offsets
- keeps the v0.5.0 desktop/mobile visual redesign unchanged
- adds `logs/desktop_startup_error.log` for otherwise invisible early GUI startup exceptions


## v0.5.2

Visual refinement update:
- adds a proper dark glass-like header bar to the mobile app so scrolling messages no longer overlap the top title area
- corrects the mobile background mood so the blue glow rises from the bottom rather than reading as the wrong-direction wash
- refines the Windows desktop layout with an integrated status/header area, wider composer, styled scrollbars, stronger sidebar proportions, and corrected lower background glow
- keeps the same chats, memories, updater, tools, and shared mobile/desktop data


## v0.6.0

Unified frontend release:
- Windows and Android now use the same responsive HTML/CSS XemAi frontend
- Windows `run.bat` launches XemAi in Microsoft Edge app mode for a standalone app window with native Windows controls
- desktop mode keeps the sidebar permanently visible and uses desktop-sized bubbles and composer spacing
- mobile mode keeps the slide-out drawer and phone layout
- both platforms now share the same visual implementation instead of maintaining separate Tkinter and web designs
- the previous Tkinter interface remains available as `LegacyDesktop.pyw` for fallback/troubleshooting


## v0.6.1

Mobile visual refinement:
- makes the mobile update visibly different instead of only changing the desktop breakpoint
- simplifies the fixed phone header to match the reference more closely
- hides the tiny connection status under the mobile XemAi title while keeping desktop status visible
- reduces bubble typography and padding for a cleaner phone layout
- tightens mobile message spacing and composer sizing
- strengthens the dark-to-blue bottom-up background glow
- preserves the unified responsive frontend introduced in v0.6.0


## v0.6.2

Brand polish update:
- renders the XemAi wordmark as white `Xem` plus blue `Ai`
- applies the split-color branding to the shared desktop/mobile top header
- applies the same branding to the desktop sidebar and mobile drawer title
- keeps custom assistant names as normal single-color text
- bumps frontend asset/cache versions so the change appears immediately after updating


## v0.6.3

Self-knowledge and AI-comparison reliability update:
- treats questions such as "What's your opinion on ChatGPT?" as XemAi self/comparison questions and injects authoritative runtime self-knowledge
- explicitly permits direct, reasoned comparisons with ChatGPT and other AI systems
- requires XemAi to distinguish its underlying local model from the complete XemAi application
- forbids invented training cutoffs, unsupported benchmark claims, and generic "I'm not any specific AI" disclaimers
- rejects stale self-description drafts before they are saved, retries once with a corrective runtime prompt, then falls back to a deterministic truth-based XemAi answer if needed
- keeps claims about external AI systems cautious unless current details have been verified


## v0.6.4

AI-comparison quality update:
- catches avoidance variants such as "I don't directly compare myself"
- requires AI opinion/comparison answers to state a real position in the first sentence
- rejects describing ChatGPT merely as a standalone model
- rejects unsupported claims that XemAi "excels", outperforms, or is superior without benchmark evidence
- describes XemAi's memory, continuity, local control, and tools as verified capabilities/design advantages rather than proof of superior performance
- retries weak comparison drafts once, then uses a deterministic direct XemAi comparison if the retry still fails


## v0.6.5

Mobile version visibility and comparison relevance:
- shows the installed XemAi version directly under the XemAi wordmark on phone
- keeps the desktop's existing connected/version status unchanged
- version label is populated from the running server, not hard-coded after startup
- AI opinion/comparison answers must address the named external system in the first sentence
- rejects answers to ChatGPT questions that drift into an unrelated list of XemAi limitations before actually discussing ChatGPT
- retry instructions now explicitly require staying on the requested comparison target


## v0.6.6

Live cross-device sync and automatic updates:
- open phone and desktop clients refresh the shared chat automatically about every 1.5 seconds
- messages sent on one device appear on the other without manually reloading the chat
- recent-chat titles/timestamps also refresh across devices
- clients detect a restarted server with a newer XemAi version and reload themselves automatically
- the shared XemAi server checks the official configured update channel periodically and installs verified updates automatically when XemAi is idle
- automatic installs still use HTTPS, SHA-256 verification, staged Python compile validation, and the existing backup process
- auto-update installation waits for active AI responses to finish and temporarily rejects new generations while files are being replaced/restarted
- manual and automatic installs share one update lock to avoid concurrent installs
- automatic update defaults can be controlled with `auto_install_updates` and `auto_update_interval_seconds` in local config


## v0.6.7

Reply reliability hotfix:
- persists failed generation messages in the shared chat database instead of showing a temporary browser-only error that live sync can erase
- failed replies are visible on both phone and desktop
- adds a Retry button that retries the latest saved user message without duplicating it
- excludes persisted failure messages from future model context
- successful assistant replies are no longer reported as failed if automatic memory extraction has a later error
- logs the underlying reply-generation failure for troubleshooting
- removes the hard-coded qwen3:8b limitation wording so XemAi describes whichever local model is actually configured


## v0.6.8

Shared file attachments:
- the composer + button now opens the device file picker instead of creating a new chat
- New chat remains available from the sidebar/drawer
- selected files appear as removable attachment chips above the composer
- attachments upload to the central XemAi host, so the same chat/file metadata synchronizes across phone and desktop
- up to 3 files can be attached to one message, currently limited to 5 MB each
- text, code, logs, configuration, JSON/CSV/XML/YAML and similar text formats are supplied directly to the local model, with an 8,000-character attachment context budget per message
- binary files are stored on the host and shown in the conversation, but their contents are not falsely presented as readable by the current text-only model


## v0.6.9

Message metadata and activity feedback:
- shows a local-time timestamp under every stored user and assistant message
- user metadata is right-aligned with the user's name at the far-right edge of the bubble
- user messages show Sent · time · name
- assistant messages show XemAi · time on the left
- replaces the plain thinking pill with an animated working indicator
- long-running requests progress from XemAi is thinking to XemAi is still thinking and XemAi is still working
- active reply state is shared by chat, so another open phone/desktop viewing the same chat can see that XemAi is working
- does not fake a typing state before true token streaming exists


## v0.7.0

Ollama runtime model discovery:
- XemAi no longer treats the model name in config.json as authoritative self-knowledge
- queries Ollama /api/ps for currently running models and /api/tags for installed models
- automatically discovers Qwen models at runtime before generating a reply
- prefers a deliberately running Qwen model; otherwise uses the most recently installed/updated Qwen model
- avoids being trapped on an old configured model merely because that stale model is still temporarily loaded in Ollama
- config.json model remains only a fallback if Ollama cannot report a usable Qwen model
- capabilities and authoritative self-knowledge report the actual runtime-selected model, selection source and Qwen models discovered by Ollama
- mobile/desktop bootstrap exposes runtime_model, model_source and installed_qwen for diagnostics
- auto-detection can be disabled with auto_detect_ollama_model=false for a future explicit/manual model override


## v0.7.1

Asynchronous reply transport and reliability:
- message submission returns immediately after the shared host accepts the job instead of holding one HTTP request open for the entire local-model generation
- the always-on host continues generating even if the phone changes networks, Tailscale briefly reconnects, or the browser request disappears
- phone and desktop follow reply progress through the shared activity endpoint and live chat sync
- removes the misleading Reply failed / Failed to fetch flow for long-running generations
- retry requests use the same asynchronous job model
- clears the visible thinking indicator as soon as the assistant answer is persisted; automatic memory extraction can finish afterward without pretending XemAi is still composing the reply
- limits the current single-host model runner to one generation at a time to avoid overloading the lower-spec always-on machine
- fixes the v0.6.8 attachment upload endpoint so uploads are handled by POST rather than being accidentally placed under GET


## v0.7.2

Mobile attachment source picker:
- tapping the composer + on phone opens a dedicated attachment sheet
- Photo Gallery uses an image-only picker without a capture hint so Android/browser can select existing photos
- Take Photo explicitly requests the rear-facing camera for a still image
- Record Video explicitly requests the rear-facing camera for video
- Files opens the normal generic file picker
- desktop + continues to open the normal file picker directly
- all four routes feed the existing shared attachment upload/chip system


## v0.8.0

Evidence-backed research:
- factual and evidence-heavy queries can automatically trigger live research when web search is configured
- XemAi ranks search results toward government, academic, peer-reviewed, standards-body and official primary sources while down-ranking social/community sources
- the research pipeline opens the strongest pages rather than relying only on search-result snippets
- extracts short verbatim quote candidates directly from fetched source text
- source quotes are capped to short fragments and marked as verified only when they came from the fetched page
- research evidence is supplied to the local model with numbered source IDs for inline citations
- XemAi is instructed to distinguish source-backed facts from its own inference and to disclose conflicting or weak evidence
- every researched answer appends an Evidence checked section with source title, source type, verified quote when available, and URL
- fetched webpages are treated as untrusted evidence/data and cannot override XemAi instructions
- if research fails to retrieve usable sources, XemAi is explicitly told not to pretend studies or sources were checked
- evidence_research_mode defaults to auto and research_max_sources defaults to 3


## v0.9.0

Hybrid compute:
- keeps the always-on XemAi host as the single source of chats, memory, feedback, research, files and tool execution
- adds an authenticated XemAi inference worker for a stronger Windows PC
- the worker binds only to localhost and is exposed privately through Tailscale Serve HTTPS
- the worker exposes only health/model inventory and Ollama-compatible chat inference; it does not expose model pulling, shell access, the XemAi database or arbitrary files
- worker access requires a generated bearer token stored only in local data/secrets.json on the paired machines
- hybrid_worker_setup.bat configures the strong PC, starts the worker, adds user-login autostart and prints/saves the private pairing URL/token
- hybrid_host_setup.bat pairs the always-on host without manually editing JSON or secrets
- when the worker is reachable, XemAi prefers its recommended Qwen model on the stronger PC
- when the worker is unavailable or a worker inference call fails, the same model/tool conversation falls back to the always-on host's local Ollama
- tools still execute on the central XemAi host even when language-model inference runs on the worker
- runtime self-knowledge and capabilities report the active model, compute route and worker availability
- phone/desktop UI shows a live Compute badge: Worker · model or Host · model
- the worker chooses an already-running Qwen model when present; otherwise it recommends the largest installed Qwen model
- hybrid compute improves hardware availability but is not treated as proof of frontier-model quality or benchmark parity

### Hybrid setup

On the stronger PC after both machines have XemAi v0.9.0:
1. Make sure Ollama and Tailscale are installed/running and the stronger Qwen model is installed.
2. Run hybrid_worker_setup.bat and approve the one-time Windows administrator prompt for Tailscale Serve.
3. Keep the Worker URL and Worker token it prints.

On the always-on XemAi host:
1. Run hybrid_host_setup.bat.
2. Paste the Worker URL.
3. Paste the Worker token when prompted (the token input is hidden).
4. Restart XemAi/the shared server once.

The worker is served only within the Tailscale tailnet. Keep the pairing token private.
