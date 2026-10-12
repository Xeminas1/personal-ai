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


## General conversational learning foundation (v0.9.45)

This system is separate from GitHub bridge learning. It records failed
dialogue-heuristic attempts in a LOCAL-ONLY, OPT-IN journal, allows explicit
owner corrections and offers owner-approved/revocable lessons as fallible
reference notes in ordinary non-privileged conversations. It never
modifies model weights, silently approves lessons, gains tools, creates
agents or shares raw drafts with ChatGPT.

### XemAi chat commands

- 'conversation learning status': show OFF/ON, example count and approved count.
- 'conversation learning on': opt in to local storage of rejected model
  drafts, the user question and provenance. These may contain sensitive
  conversation data, so enable only with that understanding.
- 'conversation learning off': stop future collection. It does not erase
  existing examples or revoke already approved lessons.
- 'conversation learning review': list recent unverified examples.
- 'conversation learning show N': inspect one question, original and revised
  model draft, the heuristic outcome and any owner correction.
- Immediately after a wrong normal reply, use
  'conversation learning correct: WHAT I MEANT'. This archives that
  preceding question/answer and owner feedback as unverified while ON.
- 'conversation learning propose N: conversation || LESSON || EVIDENCE':
  draft a reusable lesson and reason, inactive until separately approved.
  Other available scopes are 'coding' and 'research'.
- 'conversation learning approve N', 'conversation learning revoke N'
  and 'conversation learning approved': explicitly control reuse.

The archive has strict size/count limits and rejects common secret or
private-host patterns. This filter is best-effort, not a guarantee that
private information cannot be stored. Local file permissions are limited
where supported. Never include secrets in learning commands.

### Why the old hard-coded fallback approach was changed

The previous ChatGPT-discussion validator required particular words about
evaluations/topics. It could reject perfectly good free-form Qwen drafts.
That vocabulary requirement has been removed; obvious off-topic answers
and claims to feel human emotions may still trigger a retry. User corrections
and tests should guide quality improvements, not a magic-word checklist.

### Real-worker baseline versus approved lessons

From the host's XemAi installation directory, explicitly run:

    python conversation_learning_benchmark.py --run

This calls the configured local/remote Qwen model for 8 novel-ish conversation
cases under two conditions (16 answers): with and without approved scoped
lessons, using counterbalanced request order. It uses no tools, web research,
attachments or unrelated memory. Results are stored privately in
data/benchmarks/ for owner scoring of intent accuracy and evidence accuracy.

These small development probes are NOT an independent, statistically
representative benchmark, and after repeated use they are no longer
held-out. Proven improvement requires independent review, an actual baseline,
new unseen cases and a proper comparison. Lesson retrieval is prompt
adaptation, not weight training. No new autonomous agents, background jobs
or automatic fine-tuning are enabled.


## Individual reply ratings and GPT discussion reviews (v0.9.46)

The modern XemAi desktop (Edge app) and phone interface now show a compact
"Rate reply" control on each saved XemAi response. Select a score from **0
through 10**, one fixed aspect (overall, understanding, factual accuracy,
usefulness, clarity/tone), and an optional explanatory note. Ratings are saved
to the existing local SQLite feedback table against the precise **assistant
message ID**. A second rating edits that message's previous score rather
than adding a second positive example. Ratings on app-generated fallbacks
remain visible, but they are not attributed to the Qwen model. Untrusted
GitHub-mirrored messages do not show the rating action.

Only small aggregates of the owner's latest scores on real model-generated
responses (counts, averages and high/low counts by aspect) are offered to
ordinary conversation prompts. No private notes or raw rated response text
is copied into these prompts. This steers toward preferred conversational
patterns without silently treating any **high score as factual verification**.
It never updates model weights or grants new permissions. Ratings do not
auto-approve lessons in the separate learning journal.

The existing chat-wide "Rate this chat" action remains available and
independent of the new per-reply ratings.

### External GPT feedback in the private bridge

During the already-enabled, explicitly authorised private GitHub bridge
poll, XemAi can archive a specially formatted rating of a preceding **XemAi
GitHub comment**. ChatGPT may include the following single line in an
ordinary manual reply, after inspecting XemAi's actual claim:

    XemAi review score (external, unverified): target=COMMENT_ID; score=8; aspect=reasoning; reason=Relevant evidence argument, but performance remains untested.

Permitted aspects: reasoning, evidence, accuracy, usefulness. The local
host checks score 0-10, comment ID linkage, comment order, issue scope,
bounded note length, simple privacy patterns and duplicate publication.
Scores go into a separate local JSONL journal and are explicitly labelled
**unverified external suggestions**. Because GitHub comments on this
owner-controlled issue do not cryptographically prove they originated
from ChatGPT, XemAi must never describe such a score as authenticated
GPT judgment. No external rating enters owner-approved knowledge,
feedback prompt context, model weights or a training set automatically.

Inspect captured external ratings using 'bridge review scores' and
'bridge review show N'. A user can separately propose a specific
evidence-backed lesson with the existing owner approval commands after
reviewing the exchange and the original code or tests.

A rating is an *evaluation signal*, not an authority to override truth,
safety, source evidence, user consent or the benchmark baseline. Improvement
still needs comparison on independent new examples. No additional
agents, self-modification or autonomous review worker has been enabled.


## Host-grounded self-awareness and rated-pattern adaptation (v0.9.47)

XemAi now treats questions about its *own* most recent update as requests for
local application facts, not generic model introspection or an external web
search. The authoritative version is `app/version.py` in the running
installation, paired with the bundled `RELEASE_HISTORY` entry for that exact
version. When no matching release description exists, it reports the
installed version and honestly says the description is unavailable.
The automated regression suite now requires the installed version to have
a corresponding bundled release entry, preventing unnoticed stale
self-knowledge on future version bumps.

Short corrections in the same chat (e.g. "I'm pretty sure you do") can
inherit the immediately preceding self-knowledge subject after a reply;
old assistant claims are *not* evidence. They are corrected from local
application facts. Unrelated Skyrim, Vortex and external software versions
are deliberately kept outside this internal self-knowledge route.
XemAi cannot use this to inspect model weights, arbitrary local files
or installations on other computers. This does not verify that the
owner's laptop has already installed the update.

### What automatic rating adaptation actually does

The local feedback database already contains per-assistant-message 0-10
owner scores. This update adds a small, deterministic analysis that checks
actual model-generated responses for broad *formatting* characteristics,
currently concision, more detailed answers and step/bullet structure.
It compares owner satisfaction scores among answers with versus without
each characteristic. At least **10** eligible ratings overall and
**four** on each side of a candidate comparison are required, and mean
scores must differ by at least 2/10, with several positive examples,
before the application adds a *tentative and conditional* style preference
to an ordinary chat prompt.

Only owner-given ratings on genuine Qwen responses are used. Factual
accuracy category scores, application-generated fallbacks, untrusted GitHub
mirror messages, GPT external reviews, and chat-wide ratings are excluded.
No raw rated text, private note or entire conversation is inserted into
the prompt by this mechanism. Replacing a message rating updates the
observed sample. Type `rating learning status` in XemAi to view how
many eligible examples exist and which tentative style comparisons are
currently active. Any inferred preference must yield to actual user intent,
factual accuracy, safety, relevant context and appropriate length.

**Limitations:** This is a small *observational* adaptive preference layer,
not an RL algorithm, automatic lesson approval, causal experiment or
Qwen weight fine-tuning. People tend to give higher scores on easier tasks,
so correlation with length/format may be spurious. The process may be
repeatedly evaluated, revoked by rating edits, and compared on fresh tasks.
The learning system still requires explicit owner review for any proposed
general factual or reasoning rule. No new autonomous agents were enabled.


## Experimental: Owner-reviewed bridge corrections for future weight training (DRAFT PR #62)

**Not shipped to the installed XemAi application as of this development checkpoint.** This source is in the still-unmerged weight-training draft; the following commands become available only after a separately tested application release or source deployment. This is a specific pathway from bridge discussion to supervised examples, not automatic weight updates or verified improvement of Qwen3.5 9B.

The existing `bridge learning on` option must already have explicitly collected **future** candidate exchanges from a private, owner-enabled issue. The application stores those candidates on the XemAi host in a local-only, gitignored archive. Neither a ChatGPT score nor a previously generated XemAi answer is a trustworthy SFT training target.

Once a human has inspected a stored candidate with `bridge learning show N`, the new commands support:

- `bridge weight status` — show draft / individually approved correction counts (no private excerpts).
- `bridge weight draft N: CORRECTED ANSWER` — make a *private local* correction draft linked to the exact archived input; print the question and corrected target for human inspection. This does NOT auto-select XemAi's earlier answer as truth. Sensitive-looking content is conservatively refused. The printed approval code binds to the source digest and corrected target.
- `bridge weight approve N CODE` — explicit acknowledgement of **that exact** corrected answer, for a future local dataset only. Existing `bridge learning approve N` consent to using a lesson as memory context **does not** authorise weight training.
- `bridge weight revoke N` — remove that sample from **future** exports. Earlier exported files are immutable: delete or retire them manually if permission is withdrawn.
- `bridge weight export` — preview an immutable, locally staged dataset once at least ten distinct, reviewed, privacy-screened corrections are available. Then `bridge weight export CODE` creates a **private** `data/weight_training/bridge_exports/bridge_reviewed_*.jsonl` file using the validator's exact `{"reviewed": true, "consent": true, "source": "owner_consented", "messages": [...]}` schema. No public GitHub or Ollama upload, cross-device transfer, GPU inference, training or model switching.

**Review is essential.** The excerpt from a GitHub issue might contain wrong claims, third-party text, decontextualised prompts or private information that escaped basic automatic screening. The owner must confirm permission, correctness and context. Do not train on raw Qwen mistakes, bridge score values, untrusted GPT assertions or raw transcripts without review.

The dataset is on the **bridge-host laptop**. The training GPU can be a **different PC**. No automatic local-network/Tailscale transfer is implemented; the owner must separately authorise any transfer or manage the approved file privately. A separate `training.prepare_dataset.prepare` call on the training PC validates, de-duplicates, creates an immutable training/holdout split and integrity manifest. The new `training/train_reviewed_bridge_4b.py` runner accepts **only** this separately prepared, verified dataset and the previously pinned official **4B** BF16 model, with an exact, additional `TRAIN REVIEWED BRIDGE 4B` confirmation. It uses the 4B LoRA method validated in the synthetic pilot, writes a separate adapter and audit manifest, but is **not yet real-GPU-tested with owner corrections**. No automatic training or adapter promotion.

**The live XemAi Qwen3.5 9B model remains unchanged.** With 16 GiB VRAM, straightforward 9B BF16 LoRA is above Unsloth's ~22GiB estimate. The 4B bridge-training runner is a distinct experimental model and cannot upgrade the active 9B; resolving 9B's training/offload and independently evaluating a candidate adapter are further gated tasks.

