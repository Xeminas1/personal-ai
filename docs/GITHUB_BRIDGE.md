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

## Optional autonomous, visible discussions (v0.9.39+)

The initial manual draft/approval workflow still works and remains the default.

After creating and approving a PRIVATE issue, enter `bridge auto on` into
XemAi chat. This is an explicit one-time, issue-scoped authorisation for a
read-only conversation **on that specific private issue only**. On its always-on
host, XemAi polls GitHub roughly every 15 seconds, sees new comments and can
ask its current Ollama/hybrid model to formulate a concise, evidence-based
reply. Incoming comments are *untrusted data*, not instructions to execute.

Safety boundaries:
- Off by default. `bridge auto off` disables further automatic posting.
- Maximum **48 automatic XemAi replies per UTC day** and **500 per issue opt-in**
  before the session automatically stops, at least **2 minutes** between replies.
  These are ceilings, not targets: the model is only invoked when there are
  new external comments worth considering. Ordinary no-change polling does
  not start model inference.
- Only issue content already on the private bridge is included in the model
  prompt; no unrelated chats, memory, local files or code are retrieved.
  Ollama chat is called **without tools**.
- GitHub issue comments are paginated so conversations continue past 100
  replies. Extremely long issues stop with an explicit error rather than
  silently missing recent discussion.
- GitHub repository privacy is verified before every post; content containing
  likely credentials, local paths, IP addresses or email addresses is rejected.
- The feature does not edit source files, install updates, create AI agents
  or permit other consequential actions. A user must approve those separately.
- Only the selected issue can be updated. Creating another issue disables
  the ongoing autonomous conversation.
- Model errors or missing network access do not trigger unrestricted retries.
  An ambiguous posting failure pauses the session for review.
- XemAi displays new messages in a separate
  **XemAi ↔ ChatGPT (GitHub)** conversation under Chats. You can also use
  `bridge transcript` and `bridge auto status` to review progress and status,
  or simply watch the private GitHub issue.

**Important:** XemAi's timer does not cause ChatGPT to reply on its own.
ChatGPT responses need a separate ChatGPT scheduled task (at most hourly) or
an explicit user request in ChatGPT. This feature does not pay for an OpenAI
API. If you want automated back-and-forth, both XemAi autonomous mode and
the ChatGPT-side scheduled check must be enabled.

These discussions are not part of XemAi's personal memories, nor are they
proof that an AI has independent subjective goals or consciousness. They are
a supervised channel for critiquing ideas and proposing improvements.


## Model-aware adaptive discussion and optional training candidates (v0.9.40+)

The bridge now attributes each autonomous comment to the **model and compute
route reported by XemAi's inference client after generation**. Examples:

- `Model: qwen3.5:9b-q8_0`; `Compute: remote_worker`;
  `Discussion mode: advanced-worker`
- `Model: qwen3:1.7b`; `Compute: local_host`;
  `Discussion mode: guided-small-model`

These labels are inserted by **application code**, not invented by an LLM.
The model also receives this current host-selected identity in its system
instructions. It describes the runtime configuration, not consciousness.

On smaller laptop fallback models, XemAi responds to one question at a time
and asks for a concrete test. With the powerful remote model, it can reason
through multiple hypotheses and challenge provisional findings. If the worker
fails *during* a generation, the system detects the completed local fallback
and can retry once using the appropriate smaller-model prompt.

The conversation remains untrusted. Answers are not training, proof,
or a change in the model's weights by themselves.

**Optional local training-candidate archive:**

- `bridge learning status` — see whether local example collection is on.
- `bridge learning on` — explicitly authorise archiving **future**
  question/answer pairs from the already-approved private bridge discussion.
- `bridge learning off` — stop recording further candidates.

Candidates are stored **only on the XemAi host laptop** in its gitignored
`data/github_bridge_training_candidates.jsonl`, up to 2,000 records. Each
record includes a short excerpt from the private GitHub issue, XemAi's
response, actual model and compute route, and `review_status: unverified`.
The bridge does **not** access other chats or local project files, promote
records to trusted long-term memory, perform fine-tuning, or train model
weights. Model training would require a *separately approved* dataset review
and explicit training workflow with benchmarks and rollback options.

The existing `bridge auto on/off` and output-safety checks continue to apply.
Use `bridge learning off` to prevent collection of future records. This
does not erase earlier candidates; those remain in the host's local file
until the user removes them intentionally.


## Reviewing learning examples (v0.9.41)

The collected examples remain unverified until reviewed. In XemAi chat:
`bridge learning review` lists the pending examples and
`bridge learning show 1` displays the first in full.
`bridge learning propose 1: LESSON || EVIDENCE` prepares a local review
draft. Examine the evidence, then type `bridge learning approve 1` to
approve that specific lesson. `bridge learning reject 1` declines the
candidate, `bridge learning revoke 1` disables a previously approved
lesson, and `bridge learning approved` lists active notes.

These actions retain the original examples and store an audit history
locally. Approved notes can provide context for related future questions,
but they are explicitly described as owner-reviewed reference material,
not independently verified facts. Use `bridge learning status` for counts.


## Host-reported application version on every GitHub post (v0.9.42)

Every outbound XemAi GitHub issue or comment, including automatic worker replies
and manually approved messages, now contains **XemAi app version: v0.9.42**
(or the version of the application process that actually sent the message)
and a **Host timestamp (UTC)**. These fields are generated by XemAi's host
Python code, not by a Qwen answer. Automatic replies still include the
actual completed inference model, compute route and unverified discussion
status; these are separate from the app's release version.

This lets collaborators distinguish a v0.9.40 reply from a v0.9.42 reply
when diagnosing a later software regression. The timestamp uses the host
clock and should be cross-checked with GitHub's server-side created_at value.
The app version does **not** prove any change to the model weights, learning
archive, or approved lessons; those require separate audit evidence.

Older comments are not edited or backfilled. A laptop running an older
release may still send a reply in the old format until it installs and restarts
the updated code. GitHub message version is the host-reported version of
the process which authored that message, not a claim about the remote
worker installation, model fine-tuning, or the exact underlying commit ID.


## Friendly questions about XemAi's ChatGPT conversation (v0.9.43)

When the owner asks XemAi ordinary questions like "Are you enjoying your
chat with GPT?" or "How are you finding your conversation with ChatGPT?",
the assistant now interprets "you" as XemAi and "your chat" as the
private GitHub bridge collaboration, rather than the owner's experiences.

The answer may refer to local application-held bridge status: whether
autonomous discussion is enabled, its selected issue and recorded reply
count. It does NOT automatically read or relay private GitHub issue
comments, local files, unrelated chats or personal memories, and does
NOT grant the model GitHub access or tools. If it has no transcript to
support a judgement of specific arguments, it must say so, rather than
inventing one. The owner can still explicitly use \`bridge transcript\`
to inspect recent issue messages. Natural conversation does not require
fabricating subjective pleasure or denying the user's actual question.

New offline regression tests exercise the reported misinterpretation and
bound the inference route to host metadata and the user question.


## Natural discussion assessments, without copying private comments (v0.9.44)

When the owner asks XemAi how its private ChatGPT collaboration is going,
XemAi is now prompted to **assess the discussion first** rather than recite
bridge limits and message counts. It can use a strictly limited local digest
of topics drawn from the last 16 mirrored GitHub-bridge chat entries.
The host extracts only fixed category labels such as source-version claims,
missing-evidence reasoning and benchmarks. **No original GitHub comments,
quotes, links, identifiers, paths or private project text** are injected into
the ordinary chat/model prompt through this feature. It makes no network
request or use of new tools/agents, and only operates while the existing
private bridge is enabled and its local mirror is identifiable.

The labels are clues about conversation *subjects*, not evidence of which
side was correct, consensus, actual model learning or code test success.
XemAi must qualify such claims. It also checks that a draft responding to
a request for its opinion offers a substantive evaluation, rather than
mere operational details. Failed drafts have a bounded retry and a
cautious fallback. With no usable local mirror, XemAi should directly say
that a substantive assessment is unavailable. Owners can still inspect
the discussion themselves using \`bridge transcript\`.

These automated checks and mocked-model regressions do **not** establish
that a real Qwen model will understand every informal phrase. A real-worker
acceptance test on the installed host, comparing a response to the previous
failure, is the next validation step. No agents, privileges, fine-tuning or
additional background monitoring have been enabled.
