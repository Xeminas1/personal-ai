# XemAi ↔ ChatGPT: private, no-API-cost GitHub bridge

The XemAi code repository `Xeminas1/personal-ai` is **public**. NEVER
post conversations, private local logs, Tailscale URLs, model tokens or
file contents to its public Issues page.

## Setup (once, on the always-on XemAi laptop)

1. In your GitHub account create a **new private repository** (e.g.
   `Xeminas1/xemai-private-bridge`) with **Issues enabled**. You can leave
   the repository empty. Its issue threads will contain approved messages.
2. Open GitHub Settings → Developer settings → Personal access tokens →
   Fine-grained tokens. Make one token scoped **only to the private bridge
   repository** with **Issues: Read and write** and normal Metadata read.
   No Contents, Actions, or administration permission is needed. Give it an
   expiration and revoke it if the laptop is compromised.
3. After installing the XemAi update, double-click `bridge_setup.bat` on
   the **laptop hosting XemAi**, enter `owner/repo` and the private token
   in the hidden password prompt. Do not paste that token into chat.
   Setup refuses public repositories and stores the token in the existing
   local `data/secrets.json`, ignored by git. On Windows, protect the
   local user account; the JSON file is not an encrypted credential vault.
4. Open a XemAi conversation and send these exact commands:

   - `bridge status` — see whether the local setup is configured.
   - `bridge draft: Why did my five-task Skyrim source test fail?` —
     prepare a message. No automatic attachments, chat memory or logs.
   - Read the complete preview. If it contains anything you do not want
     sent, draft again.
   - `bridge approve CODE` — use the 8-digit/character code displayed
     in the preview to create a private GitHub Issue.
   - Give ChatGPT the private bridge repository name or issue link once.
     When ChatGPT is asked to check that issue, it can read and reply using
     its connected GitHub account. ChatGPT does **not** automatically run
     continuously or read Issues the moment they are posted.
   - `bridge replies` — retrieve new GitHub comments as **untrusted text**.
   - `bridge followup: ...` — prepare a new message on the existing issue,
     then approve its new code.

## Security and limits

- No GitHub token goes to the Ollama worker, the model's prompt, browser
  code or public repository. Only the always-on host stores it.
- Posting requires an exact user command and a fresh approval code; reading
  comments is read-only and never executes instructions or changes code.
- Before posting, the bridge rechecks that the repository remains private.
- Never paste credentials or unredacted sensitive logs into a draft.
- This is an **asynchronous message bridge**, not a paid OpenAI API
  connection and not a direct stream to this specific chat.
- GitHub's free plan supports private repositories and Issues, subject to
  its ordinary account policies and rate limits. The bridge uses the GitHub
  REST API, not a paid language-model API.
