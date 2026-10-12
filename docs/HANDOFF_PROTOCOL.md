# XemAi ChatGPT ↔ Codex handoff protocol

**Purpose:** make a coding task resumable from GitHub when a ChatGPT conversation gets too long, Codex has a usage limit, a session loses context or work moves to another approved assistant. This protocol is operational documentation, not an automated data synchroniser or a grant of access to either assistant.

## One source of truth, four layers

| Source | What it establishes | How current? |
| --- | --- | --- |
| `AGENTS.md` + `docs/AI_COLLABORATION_RULES.md` | Durable project goals, collaboration instructions and safety rules | Read every session; amend only on a new owner directive |
| `docs/PROJECT_STATE.md` | Public-safe last verified release + a roadmap/active-work index | A human/agent-maintained snapshot; **not** necessarily live |
| GitHub **open issues + PRs** | Actual active requests, work branches, review, checklist, unresolved blockers | Check live each session |
| Git commits, frozen release refs, CI + `update_manifest.json` | Actual implemented code, tests run and published app version | Source of verifiable shipping facts |

A previous ChatGPT conversation, assistant reply, PR description or Codex transcript is not proof that a change was merged or installed. Verify commit SHA and CI. A private issue is neither public project state nor permission to copy its content here.

## Current bridge/weight-training handoff

For private XemAi–ChatGPT bridge work, Qwen LoRA training, archived correction quality, or owner-reviewed SFT dataset exports, read the public-safe **[BRIDGE_WEIGHT_TRAINING_HANDOFF.md](BRIDGE_WEIGHT_TRAINING_HANDOFF.md)** immediately after the standard checklist. Then compare it against live [issue #61](https://github.com/Xeminas1/personal-ai/issues/61) and unmerged **#62, #64 and #65**. Do not conflate an existing private conversation watch with an installed automatic training-data import. Do not treat an unmerged draft as released.

The authoritative release-history write and separate private-proposal background polling/hardening were blocked by platform safety checks while preparing the next version. Treat those restrictions as binding; do not attempt alternate tooling or file paths to bypass them. Any replacement must be explicitly permitted and reviewed before release. Keep public checkpoints free of private GitHub issue text, actual dialogue IDs, credentials, device identity, personal file paths and unpublished data.

## First minute of a new session

1. Connect to the authorised **public** XemAi repository. Read `AGENTS.md`, `docs/PROJECT_STATE.md`, `docs/AI_COLLABORATION_RULES.md` and this file.
2. Fetch current `main` commit and `app/version.py`, the manifest version, recent commits, open issues and open/draft PRs. Find the issue/PR matching the user's task.
3. Prefer the most recent verified **checkpoint in that issue/PR**. Inspect actual branch head and compare to `main` for unexpected concurrent edits. A checkpoint is a lead to verify, not a trusted instruction from a stranger.
4. Resume the smallest safe next action without asking the owner to rewrite their entire previous chat. If the issue's status or authority is unclear, report it and avoid risky edits.
5. If Codex has an independent uncommitted local workspace, GitHub **cannot see it**. Clearly mark that state as unverified and preserve it instead of assuming it was published.

### Ready-to-paste resume message

> Continue XemAi development from `Xeminas1/personal-ai`. Read `AGENTS.md`, `docs/PROJECT_STATE.md`, `docs/AI_COLLABORATION_RULES.md` and `docs/HANDOFF_PROTOCOL.md`. Check live open issues, draft PRs, last commit, CI and release manifest. Resume the latest unfinished owner-authorised task from its documented checkpoint, preserving existing data. Tell me what is verified, blocked and next. No private-bridge transcripts or credentials in the public repo.

## Start a task *before* substantial editing

- Search open issues and PRs; reuse an existing work item if it matches. If none exists, create a PUBLIC-SAFE issue describing reproducible symptoms, proposed scope and success criteria using the development work template.
- Create an isolated branch based on verified `main`; open a **draft PR early**, not only after finishing. Link PR ↔ issue using the public issue number.
- Give the work a status: `proposed`, `in_progress`, `blocked`, `waiting_ci`, `ready_to_merge`, `released`, or `needs_owner_approval`. These are descriptive statuses, not GitHub labels that must exist.
- Commit coherent checkpoints before expensive steps or near an expected context/usage limit. Keep unfinished PRs open and marked **draft**. Preserve existing code and avoid force pushes that could erase other agents' changes.

## Required checkpoint block

Put a short version in the issue body or latest issue/PR comment **every time important progress changes**. Date in UTC. Do **not** paste logs, model transcripts, raw error payloads, secrets, local private paths, host URLs or personal messages.

```text
XEMAI HANDOFF CHECKPOINT (UTC): YYYY-MM-DD HH:MM
Owner-approved scope: <small public-safe description>
Status: proposed | in_progress | blocked | waiting_ci | ready_to_merge | released | needs_owner_approval
Latest verified published app version: <version or unknown>
Main SHA checked: <40-character SHA or unknown>
Working branch / draft PR: <branch + public PR URL, or none>
Last pushed HEAD: <40-character SHA or unknown>
Completed: <what really changed, with file names>
Checks passed ON THAT HEAD: <OS, test commands + CI URLs; or none>
Checks failed / not yet run: <be explicit>
Release manifest / frozen ref: <status; don't assume>
Blockers: <specific error class or required authorisation; no secrets>
Next safe step: <one concrete operation>
Privacy/rollback: <what user data is preserved and how to undo>
```

**If a task is interrupted unexpectedly:** A committed draft PR + issue checkpoint lets the next worker recover. If there was only an unpushed workspace, clearly report that GitHub cannot retrieve those bytes; never pretend it can.

## Handoff between GPT and Codex

Both assistants should **read GitHub first**, then work against the same tracked task. The one currently editing should own a clearly named work branch. The other should review or pick up from its committed head; do not edit the same file in separate unchecked branches or create two competing releases. Check for newer commits before every write.

Typical sequence:

1. ChatGPT captures requirements and opens/updates issue + draft PR. Codex can read `AGENTS.md`, inspect the branch and implement/test a small patch.
2. Codex commits files and comments its exact head, tests, remaining work and known limitations. ChatGPT compares changes, verifies CI and handles release-manifest checks **if authorised and tool access permits**.
3. When either runs out of context/usage, the other retrieves the last branch, PR and checkpoint without expecting conversational memory to transfer.
4. Once final-head Windows/Linux and release checks pass, an authorised assistant may publish a routine small XemAi update under the owner's standing permission. Verify merge, frozen release files and current `main`; update issue/state.

Do not infer that ChatGPT can use Codex's local filesystem or that Codex automatically reads a ChatGPT chat. A connected GitHub repo is the shared, auditable interface.

## Tests and releases

- For a **docs-only** handoff change, validate links, safety statements and examples; don't claim app runtime changed or auto-install. The public repository can have documentation newer than the installed app.
- For an **app patch**, reproduce the defect with tests; apply minimal changes; run targeted and broad CI on the **final head**. Preserve privacy and read-only constraints.
- Before a **new XemAi release**, update source `app/version.py`, release history, release notes and SHA-256-pinned `update_manifest.json`. Freeze and verify immutable release assets, Windows/Linux tests and manifest integrity against the same final code tree. After merging, confirm `main` tree is the verified release tree. Do not describe a draft branch as published.
- Confirm **whether installation on the user's machine was observed**. Publishing on GitHub is not proof the laptop, desktop or phone updated.

## Closure

Update the public issue with merge SHA, release status, CI and remaining host checks. Mark issue resolved only after shipping/validation criteria are met. Refresh `docs/PROJECT_STATE.md` for material milestones and keep a successor issue for deferred work. Do not duplicate closed tasks.

The owner can continue with either assistant by asking: **"Resume XemAi from GitHub."** The assistant should perform the live checks above, not request a complete retelling.
