# Personal AI v0.1

## v0.9.12 chat options and deletion

The top three-dot button opens Chat options with New chat, Rate this chat and
Delete chat, plus Capabilities, Live support and Update XemAi. Capabilities now
opens only when selected. The menu and confirmation work on phone and desktop;
Escape dismisses the dialog and deletion initially focuses Cancel.

Select a chat, open the three-dot menu and choose Delete chat. Confirmation names
the selected chat and explains that its messages and attachments are removed
while saved memories remain. Deletion also removes that chat's ratings and
answer-source metadata. Cancelling or a rejected deletion preserves the draft.
An attachment cleanup failure is reported separately from a successful chat
deletion. No real user chats are changed by installing this update.

Deletion is scoped to the current user and requires a same-origin JSON request;
read-only support credentials cannot delete chats. The shared web server blocks
deletion while reply generation or its background memory work is active and
serializes deletion with sends, retries, uploads and ratings. These activity
guards apply to the shared web desktop and phone, not a separately running
legacy Tk/console process.

Clients recover when another device deletes their selected chat, and stale
loads or polling responses cannot restore the old selection. Deleting the last
chat leaves a New chat action instead of creating another chat during polling.
Browser regressions cover both layouts, confirmation and focus, drafts, deletion
errors, shared-list recovery and delayed responses; SQLite/HTTP tests cover
data preservation, ownership, attachments and concurrent deletion requests.

## v0.9.11 clearer evidence and source references

Research supplies bounded topical passages with nearby qualifications instead
of the beginning of a page. Short direct quotations must be complete source
sentences, so a word limit cannot silently cut off a negative conclusion.
Source records distinguish fetched pages from search snippets, and the answer's
source list says which pages were read. Reading a page or verifying its wording
does not establish that a factual claim is supported.

Comparable research results prefer distinct hosts without replacing stronger
topic relevance or source authority. Exact hostname handling also fixes official
sources such as WHO and W3C being misclassified. Selection remains a lexical
and domain heuristic, not independent verification of a publisher or claim.

Each chat turn has a source catalog with stable IDs across automatic research,
model-requested research, ordinary search and page fetching. Repeating the same
research query reuses that turn's evidence instead of fetching it again. The
catalog is capped at twelve sources and does not persist between turns.

Numbered citations and URLs explicitly presented as sources are checked against
material retrieved in that turn, including research attempts with no usable
sources. Clearly invalid references trigger at most one additional, tool-free
model correction. If correction fails, the original draft is retained with an
explicit unverified-reference notice and its original answering model label.
Code, indexing, common array/vector notation and ordinary navigation links are
excluded from this check. Valid references alone do not establish factual
accuracy, and clean references incur no extra review inference.

An explicit no-web request hides and blocks search, page-fetch and research
tools for the current reply. Factual questions receive topical memories plus a
small set of high-confidence preferences rather than unrelated stored facts.
Explicit personal-memory, project and preference recall remains available.
Stored memories, chats, model choices and hybrid fallback are preserved.

Prompt guidance asks for the actual question to be answered first, distinguishes
subjective rankings from objective facts, and requires attention to evidence
scope and caveats. Offline regressions verify these application behaviors; no
live-model accuracy score or improvement on a particular PC is claimed.

## v0.9.10 fallback overhead and reply source

A failed worker health check now selects local fallback once for that chat
turn, including tool rounds, answer retries and memory extraction. The next
turn checks the worker again so a PC that has come back online can recover.
Worker health also avoids a duplicate local Ollama inventory request.

The phone header reports current availability. Each newly saved answer records
the model and host or worker that actually produced it, before memory extraction
can change the route. Application-generated fallback text has its own label;
older answers remain unlabeled because their source was not recorded. An
additive SQLite table preserves existing chats, messages and memories.

Chat, LLM and hybrid connection events share a random turn identifier. Hybrid
events retain only typed connection categories, HTTP status and OS error codes,
without URLs, credentials, response bodies or chat content. The read-only support
report retains these fields to distinguish a timeout from authentication, DNS,
TLS or connection failures.

The supplied timing report measured a laptop Qwen3:1.7B reply saved after 138
seconds, followed by another 99 seconds of memory work. Its extra answer and
memory delays were consistent with repeated fallback checks. This release
removes that redundant work; it does not establish why the PC connection failed
or change slow local generation, model thinking or GPU configuration. Current
PC health does not establish its availability during the measured reply.

Let both installations update, then restart the stronger PC once to load the
worker health change. Refresh the phone interface to load the new reply labels.

## v0.9.9 contextual factual research

Factual questions beginning with `What's`, `What’s` or `whats` now follow the
same research routing as `What is`. Explicit no-web requests also suppress
automatic forced search.

Generic source and verification follow-ups use bounded recent user topic text
and related corrections instead of searching the follow-up's literal wording.
Assistant claims and attachment contents are excluded from that search context;
the current user message remains unchanged in the model conversation. Retry
also identifies the current user row when an error message follows it.

Research now considers topic relevance before source authority and excludes
results without meaningful query overlap. Relevant pages still need to support
the actual claim: a reputable domain alone does not establish relevance or
truth. Prompt guidance asks for short answers to simple questions and for
related claims to be reassessed when a user requests verification or corrects
an error.

These changes address the missed pirate-question research and unrelated
AI-citation search demonstrated in a pasted conversation. They do not guarantee
error-free model answers or diagnose the reported reply delay. Research uses
lexical relevance checks, which can miss sources phrased differently. Topic
recovery adds no model inference call; live research still takes time. Existing
worker routing, fallback, credentials and timing diagnostics are preserved.

## v0.9.8 reply timing and worker overhead

Worker inference requests that already specify a model now validate installed
Qwen models without repeating running-model discovery. Requests without a model
still use the worker's recommendation. Authentication, routing and fallback
behavior are unchanged.

New troubleshooting events separate host preparation, routing, research, answer
generation, validation retries and background memory extraction. Ollama events
record request elapsed time, model loading, prompt processing, generation time,
token counts and thinking character counts. Worker events separate model checks,
queue waits and inference. Missing model metrics appear as `-1`. These events
contain no prompt, answer, internal reasoning text or credentials, and the
read-only support report retains their typed fields.

The answer timing ends when the assistant message is saved, before automatic
memory extraction. Phone display polling can add a small delay after that point.
This release helps diagnose long replies; it does not establish the cause of a
reported three-minute answer or change model thinking, hardware use or streaming.
After both PCs update, restart the stronger PC once to replace any older running
worker process, then repeat the question to collect current timing events.

## v0.9.7 slow worker connections

Hybrid worker discovery, pairing and health checks now allow 15 seconds per
request. A reachable worker previously took about 4.2 seconds to respond and
exceeded the shorter discovery and runtime health limits, leaving the laptop
on its local fallback model. TLS verification and authentication are unchanged.

Regression coverage uses a real delayed HTTP worker and checks discovery,
pending-credential reuse, remote selection, local fallback and recovery. An
unavailable worker can now take longer to fall back, and scanning several
offline peers can take more than one request timeout.

The local validation report confirmed real 8B worker inference, 1.7B fallback,
shared chat lists and desktop forwarding. The historical authenticated HTTP 400
was not reproduced. An older already-running PC worker process still requires
separate inspection; updating application files does not replace that process.

## v0.9.6 live read-only support

Run `live_support.bat` on the PC whose installation needs inspection, or choose
Live support in the chat menu. Enable read-only access to create a separate key
that expires in 24 hours; Turn off access revokes it immediately. Keys are shown
only when created and are stored locally as hashes. Re-enabling rotates the key.

The authenticated `/api/support/files`, `/api/support/file?path=...`, and
`/api/support/report` endpoints expose allowed source files, filtered settings,
structured troubleshooting events and current installation/version metadata.
Raw logs, keys, chat databases, attachments, workspace files and arbitrary paths
are excluded. The support key cannot change application files or settings.
The local mobile server and inference worker share this temporary support state.

The agent needs a supported private network connection to your Tailscale network
and a secure secret binding for the support key. Do not paste keys in chats or
put them in URLs. Enabling support does not send files or grant connectivity.
This release creates no public tunnel. After updating, restart the PCs once so
any older inference-worker process is replaced before using its support endpoint.

When connecting an agent through a VPN, restrict its Tailscale permissions to the
support endpoint's worker port (8766 on the stronger PC). The normal mobile UI is
still intended for trusted devices in the tailnet and has its existing chat and
update controls; a support connection should use only the authenticated support
API, not the ordinary chat UI.

For the stronger PC, the cloud environment binding is `XEMAI_PC_SUPPORT_KEY`
and the endpoint is `https://reece-pc.tail52254c.ts.net:8766/api/support`.
Enter the key securely in environment settings; save and publish the cloud
configuration. This does not itself establish private-network routing.

## v0.9.5 hybrid startup recovery

Hybrid setup now rechecks the host/worker role while Tailscale starts and retries
after temporary setup failures. It no longer stops checking after an initial
worker setup result. Logs identify missing Tailscale identity, missing host Serve
route, unavailable local Qwen models, and unreachable worker candidates without
printing tokens. The model badge still reports the route actually selected; a
local model remains available while the worker cannot be reached.

## v0.9.4 hybrid pairing and shared chats

- Paired worker PCs open the central laptop's chat interface on desktop and phone.
- Private Tailscale model requests bypass Windows HTTP proxies while retaining TLS verification.
- Host setup tries automatic pairing before asking for a token. Manual pairing now registers the laptop identity on the worker.
- Worker setup retries incomplete startup instead of treating a launch attempt as success.
- Manual setup rejects malformed pasted tokens before sending authentication headers.

Update both PCs, leave the laptop server running, and open XemAi on the stronger
PC. Approve worker setup if prompted. Automatic discovery retries while the
worker starts. The laptop retains all shared chats; old worker-local chats are
preserved separately. If automatic pairing is unavailable, run
`hybrid_host_setup.bat` on the laptop; `--manual` explicitly selects manual mode.

### Shared desktop and phone chats on a paired worker

Once the stronger PC's inference worker is paired with the always-on laptop,
opening the normal XemAi desktop app on the stronger PC forwards its chat
interface to the laptop, just like a phone visit. Both interfaces then use the
laptop's shared chats and compute routing; the stronger PC remains an inference
worker. The laptop must be online and reachable through Tailscale.

Chats previously created in the stronger PC's local database are preserved but
are not automatically copied to the laptop. An unpaired PC still opens its local
interface. The legacy native desktop and console interfaces also remain local.

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


## v0.9.3

Hybrid handoff and setup clarity:
- when a phone opens the worker PC’s XemAi address, it forwards the phone to the paired central host automatically
- direct desktop app visits on the worker PC remain local
- the normal worker setup now explains automatic pairing and no longer tells you to copy a URL/token; explicit `--manual` keeps the legacy fallback

## v0.9.2

Hybrid worker startup fix:
- fixes the worker launcher so Windows can start the background worker process
- verifies both `.py` and `.pyw` source files before installing future updates

## v0.9.1

Hybrid setup automation:
- the always-on laptop discovers an available XemAi worker on its private Tailscale tailnet
- the laptop and worker exchange a generated pairing token over Tailscale HTTPS; the user no longer needs to copy the URL or token
- a worker starts automatically on an XemAi installation that has Tailscale signed in and an installed Qwen model
- Windows still asks for administrator approval the first time Tailscale Serve is configured
- the worker accepts only its original paired host, and manual setup scripts remain available as a fallback
- automatic setup waits when prerequisites are missing; XemAi falls back to local Ollama until pairing succeeds

Both PCs need v0.9.1, Tailscale installed and signed in to the same private tailnet, and to be online. The stronger PC must already have XemAi, Ollama and a Qwen model installed; XemAi does not install third-party software or download a model during automatic setup. Open XemAi there once so its updater can install the release and the worker can start. Approve the Windows prompt when it appears. The laptop's existing Tailscale Serve route for phone access is used to identify it as the central host. Automatic discovery trusts devices already admitted to that tailnet, so use a tailnet you control.
