# XemAi bridge discussion to Qwen weight training — shared GPT/Codex checkpoint

**Checked:** 2026-10-12 UTC. **Source:** verified public GitHub release, issues, draft PRs and CI. This is a **public-safe development record**, not an installed-host audit, proof of neural learning, a private dialogue transcript or a new grant of permissions.

## Start here before continuing

Read [AGENTS.md](../AGENTS.md), [PROJECT_STATE.md](PROJECT_STATE.md), [AI_COLLABORATION_RULES.md](AI_COLLABORATION_RULES.md), and [HANDOFF_PROTOCOL.md](HANDOFF_PROTOCOL.md), then fetch *current* `main`, `app/version.py`, `update_manifest.json`, open issues/PRs and CI. **Never merge a draft merely because this document lists its code.** Public issue [#61](https://github.com/Xeminas1/personal-ai/issues/61) holds the most recent work checkpoints. New GitHub commits supersede this dated description.

## Verified shipped app: v0.9.57

- [PR #63](https://github.com/Xeminas1/personal-ai/pull/63) merged: manual `bridge weight` candidate review, draft correction, exact-code approval/revoke, private on-host JSONL export after at least ten unique approved examples. This is *dataset preparation*, **not weight training**.
- Frozen release `release-v0.9.57` commit `621b7205df892833b311f3d833ade2a240565190`, merged code commit `775863bea3a7eba8dac494d81e39a75c6b7ba9e1`, matching source tree `9b3ffbc1a21c2039e0bbfaafe97d8727694eb9b9`.
- Windows/Linux suite [passed](https://github.com/Xeminas1/personal-ai/actions/runs/38304215857); **164** manifest-pinned SHA-256 assets [verified](https://github.com/Xeminas1/personal-ai/actions/runs/38304215866).
- Latest public `main` at this checkpoint: `6610004c4ff8c07454870d6095afa6598510f93c`. Later documentation-only commits do not themselves change the runtime version.
- **Installed host version cannot be proved from a GitHub merge**. The owner has shown that the shipped `bridge weight` commands run on their XemAi app, but do not infer more from that than observed.

## What was actually learned/trained

**Separate, local 4B pilot:** Owner-provided console evidence demonstrated 2/2 GPU optimiser steps on a *separate* official pinned Qwen3.5 4B BF16 checkpoint; sampled LoRA parameters changed and a private adapter was saved. On four short fictional holdouts (63 answer tokens), mean answer NLL went from **3.152394** (base) to **2.915653** (adapter), improvement **0.236741**. The result does not demonstrate general conversational ability, real bridge-learning impact, a change to Ollama, or any improvement to XemAi's live Qwen3.5 9B.

**Current production 9B:** unchanged. Owner's RTX 5080 has 16 GiB VRAM; published 9B BF16 LoRA memory estimate ~22 GiB, above the card's capacity. 8-bit/CPU-offload support for this particular Windows/Qwen3.5 stack remains unverified. The installed 9B Q8 Ollama inference model is not the pinned full training checkpoint. Do not announce weight training, improvement or deployment without a separately approved, reproducible actual 9B run and held-out comparison.

**Data:** Existing opt-in local bridge archive and individual human-reviewed SFT approvals are **not** model updates or independently verified ground truth. External ratings are feedback signals, not gradients, verified labels or authorisation. Synthetic tests and mocked training do not prove real-GPU training.

## Unmerged, separate development tracks

| Work | Verified public status | Precise release boundary |
| --- | --- | --- |
| [Draft PR #62](https://github.com/Xeminas1/personal-ai/pull/62) — training foundations | Head `fae8b739bf78b4ac7102244e0eae5fff55d429f0`; **draft/unmerged**. Earlier code and source tests passed; reviewed-bridge 4B runner only had synthetic/mock tests. | Needs reconciliation with shipped v0.9.57 commands, isolated GPU evaluation, consent to use actual reviewed data; *not* 9B training. |
| [Draft PR #64](https://github.com/Xeminas1/personal-ai/pull/64) — owner-written complete question for clipped excerpts | Head `1c6a286bee36c0f1eb336f728c461456abdc05cf`; **draft/unmerged**. Last code-only head `466a3670243d34635853908c2720ca88da2e5ade` passed [Windows/Linux](https://github.com/Xeminas1/personal-ai/actions/runs/38307704518); later docs-only commit was not verified as a release. | Existing archived questions can be silently clipped at 1,800 chars, while v0.9.57 review accepts at most 1,600. Introduces explicit `bridge weight rewrite N: STANDALONE QUESTION || CORRECTED ANSWER`, entirely owner-written with new source-bound confirmation. **Not in installed v0.9.57.** |
| [Draft PR #65](https://github.com/Xeminas1/personal-ai/pull/65) — private proposal inbox research | Branch `feature/bridge-weight-proposal-sync`, head `718c186042b72a539bf89a4b22b9239cc0d54c27`, **draft, untested and unmerged**, stacked on #64. Contains preliminary disabled-by-default inbox source and command routing. | The source is incomplete. Private GitHub fetch/error/locking require independent review. Background polling integration and a hardening write were **blocked by platform safety checks**; **do not retry around or bypass those restrictions via alternate tools/paths**. No app release or tested inbox import. |

A separate GitHub-connected assistant can already **read and respond to the owner's explicitly authorised private bridge issue** without the owner copying each message into a ChatGPT conversation; an existing owner-scheduled hourly task handles that dialogue. A **separate private staging issue** now holds clearly unverified and unapproved correction proposals. Neither private issue nor its messages belong in this **public** repository, public CI artifacts, public issue comments, test fixtures or model training logs. A proposal reaching a private GitHub issue is **not equivalent** to reaching the locally running XemAi's review archive. No automatic read/import of that private inbox has been released.

**Safety boundary:** The user explicitly wants to stop manually relaying dialogue, but this does not grant unrestricted automatic private-data copying, approval, model fine-tuning or deployment. Proposal import requires privacy review, effective owner opt-in, testing and a permitted release. Each corrected pair must have independently inspected question/target and an explicit local approval; actual GPU training and replacing the production model require a **separate** consequential approval. Preserve previous approved corrections and their revocation/export semantics.

## Specific blockers and next steps

1. **Release-history write blocked.** In preparing v0.9.58 on PR #64, a repository tool safety check blocked updating `app/self_knowledge.py` (authoritative release history). A temporary `app/version.py` bump was reverted to v0.9.57. Do **not** route around the restriction through another tool/path. The user/coding reviewer must resolve that explicitly before any new app release. Current `main`, frozen release and manifest are v0.9.57.
2. **Inbox integration blocked.** Do not ship the preliminary #65 code until a permitted security review, mocked private-repo access tests, exact-release CI and explicit activation authorization are complete. The assistant must not treat observed connector access as permission to change app credentials or autonomous collection settings.
3. **Full training workflow unverified.** Ten manually approved examples merely permit a private dataset export. Check sample quality and legal/privacy provenance, prepare independent holdout, validate training on a *separate* pinned model and measure changes before any owner-approved model update.
4. **Cross-session handoff:** Start at live public issue #61, review PRs #62/#64/#65, inspect actual diff/checks against current `main`, and avoid duplicate PRs. Do not infer that the first private proposal has been imported, that any candidate beyond what the user has actually confirmed is approved, or that the live Qwen 9B has learned from the bridge.

## Status shorthand

**Released:** v0.9.57 manual owner-reviewed candidate → JSONL export.

**Verified offline only:** tiny separate Qwen3.5 4B LoRA smoke pilot + four synthetic holdouts.

**Developed but not released:** owner-written full prompt for clipped examples (#64), separate 4B reviewed-data training experiment (#62).

**Incomplete/blocked:** automatic private proposal inbox (#65), v0.9.58 release-history gate, 9B LoRA feasibility.

**Not authorised or accomplished:** autonomous data approval, automatic weight updates, production 9B change, copying private material into public GitHub.
