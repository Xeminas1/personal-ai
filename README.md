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
