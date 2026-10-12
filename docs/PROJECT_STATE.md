# XemAi project state — public-safe handoff index

**Snapshot checked:** 2026-10-12 (UTC). This page is a **manual checkpoint, not a live GitHub API feed**. Before taking action, compare it with the actual latest `main` SHA, `app/version.py`, the manifest, open issues/draft PRs and recent CI, following [HANDOFF_PROTOCOL.md](HANDOFF_PROTOCOL.md). Newer verified GitHub changes take precedence over this snapshot.

## Last verified released XemAi application

| Field | Verified snapshot |
| --- | --- |
| Published XemAi app version | **v0.9.57** |
| `main` merge SHA at v0.9.57 release | `775863bea3a7eba8dac494d81e39a75c6b7ba9e1` |
| Frozen release `release-v0.9.57` SHA | `621b7205df892833b311f3d833ade2a240565190` |
| Release/merge relationship | Matching repository **tree** verified for those commits after **PR #63** merge |
| Release PR | [#63 — Owner-reviewed private bridge correction export](https://github.com/Xeminas1/personal-ai/pull/63) |
| Latest verified release manifest | v0.9.57, **164 SHA-256 pinned assets** |
| Release CI at final tested source head | Windows/Linux regressions and full manifest verification **passed** at frozen head |
| Installed version on an owner's computer | **Unknown from GitHub alone** |

The code repository's newer **documentation-only** commits are not necessarily new app releases; the authoritative installed app version is the running host's report. GitHub merges cannot verify automatic installation on the laptop/PC.

## 2026-10-12 — v0.9.57 private bridge corrections released

**Observed GitHub release:** Narrow PR #63 merged as `775863bea3a7eba8dac494d81e39a75c6b7ba9e1`. Frozen release ref `release-v0.9.57` points to `621b7205df892833b311f3d833ade2a240565190`, and the merge and release have **matching Git trees** (`9b3ffbc1a21c2039e0bbfaafe97d8727694eb9b9`). Exact release-head Windows/Linux app regression [passed](https://github.com/Xeminas1/personal-ai/actions/runs/38304215857), as did the full 164 HTTPS/SHA-256 asset [verification](https://github.com/Xeminas1/personal-ai/actions/runs/38304215866).

Manual user commands `bridge weight status`, `bridge weight draft N: CORRECTED ANSWER`, `bridge weight approve N CODE`, `bridge weight revoke N` and `bridge weight export` allow the owner to review and export separately opted-in local bridge candidates. They do **not** automatically pull conversations, contact GitHub, access other chats, move files to the separate GPU PC, train models or deploy adapters. The feature's installed-host acceptance and whether `bridge learning on` has archived any candidate remain **unknown** to GitHub. Model-weight learning remains planned/experimentally proven only for a distinct fictional 4B smoke run. No live 9B model weights changed.

Broader experimental training PR [#62](https://github.com/Xeminas1/personal-ai/pull/62) is **still draft/unmerged**, and based on the older main; reconcile the now-shipped manual bridge review commands before merging it, and separately validate a memory-compatible 9B training method.

## 2026-10-12 — Bridge learning development, direct private GitHub access and truthful handoff

**Public-safe full handoff:** [BRIDGE_WEIGHT_TRAINING_HANDOFF.md](BRIDGE_WEIGHT_TRAINING_HANDOFF.md). Public [issue #61](https://github.com/Xeminas1/personal-ai/issues/61) and its newest checkpoints remain the live tracker. **v0.9.57 is still the only verified released app**; documentation-only GitHub updates do not alter the installed application.

- The user has demonstrated on the running app that private bridge learning collection and the `bridge weight` commands are functional, including explicit approval of an individual owner-reviewed SFT correction. This does **not** establish independent accuracy, exported dataset, gradient training or any 9B model improvement.
- Existing bridge question excerpts can exceed the v0.9.57 review limit and be incomplete. [Draft PR #64](https://github.com/Xeminas1/personal-ai/pull/64) adds explicit **owner-written, complete question + corrected answer** replacement rather than reconstructing missing text. Last code-head `466a3670243d34635853908c2720ca88da2e5ade` passed [Windows/Linux app CI](https://github.com/Xeminas1/personal-ai/actions/runs/38307704518), but #64 **is not merged or released**. New release-history maintenance hit a tool safety block; do not circumvent it, and do not tell the user the new `bridge weight rewrite` command is installed.
- A directly connected GitHub assistant can read/reply in the separately authorised **private** XemAi dialogue, removing the need to manually relay every conversational turn. A separate private proposal staging issue exists with unverified, unapproved example suggestions; it does **not** feed the local training archive automatically. [Draft PR #65](https://github.com/Xeminas1/personal-ai/pull/65) contains incomplete untested opt-in proposal inbox research stacked on #64. Its background integration and further hardening were blocked by safety checks. **No release or automated import**.
- [Draft PR #62](https://github.com/Xeminas1/personal-ai/pull/62) contains offline owner-gated training infrastructure. A **separate Qwen3.5 4B LoRA synthetic pilot** demonstrably changed adapter tensors and lowered NLL on four tiny fictional holdout cases, not on owner's private dialogue or the live 9B model. 9B BF16 LoRA requires more memory than the owner's known 16 GiB GPU under the published reference estimate; a compatible 9B technique is not yet validated.
- Never conflate hourly ChatGPT private-issue replies, owner-reviewed *local candidates*, owner-approved training **data**, successful **4B** pilot, and actual production **9B** model-weight changes. None of these transitions occurs automatically.
- Changes to private access, autonomous data sharing, approvals or model weights require specific owner permission. Tool safety blocks are binding; no alternative method may be used to bypass them.

## Pending / unfinished work

| ID | Item | State at snapshot | What remains |
| --- | --- | --- | --- |
| [Issue #61](https://github.com/Xeminas1/personal-ai/issues/61) | Owner-controlled bridge → Qwen weight training | **Open; split drafts #62/#64/#65** | Resolve release/inbox safety blockers; test and separately authorise private example import and actual 9B training. Current app stays v0.9.57. |
| [Draft PR #64](https://github.com/Xeminas1/personal-ai/pull/64) | Owner-written complete questions for clipped archive entries | **Draft; Windows/Linux code tests passed, release blocked** | Authoritative version history write blocked. No v0.9.58 manifest or installed upgrade. |
| [Draft PR #65](https://github.com/Xeminas1/personal-ai/pull/65) | Private correction proposal inbox research | **Draft, incomplete and untested** | Needs permitted security/design review, approval gates and exact-head CI; do not deploy or bypass blocked integration. |
| [Issue #54](https://github.com/Xeminas1/personal-ai/issues/54) | Repair private bridge response-size failure with safe comment pagination | **Closed; shipped v0.9.56** | Confirm installed host successfully polls and posts to the existing private issue |

**Issue #54 is fixed in published v0.9.56.** Frozen-source regression and manifest checks passed and match the merged release tree. A real host acceptance check is still needed to confirm XemAi's running version, private issue polling and whether it replies; installed-host state cannot be inferred from GitHub.

### Cross-session collaboration itself

The following tracked repository documents describe how ChatGPT/Codex can resume interrupted work:

- [`AGENTS.md`](../AGENTS.md) — first-read instructions and resume prompt;
- [`docs/AI_COLLABORATION_RULES.md`](AI_COLLABORATION_RULES.md) — owner preferences, delegated routine update permission, protected actions and privacy;
- [`docs/HANDOFF_PROTOCOL.md`](HANDOFF_PROTOCOL.md) — draft PR/checkpoint mechanism and exact handoff template;
- [`.github/ISSUE_TEMPLATE/development-work.md`](../.github/ISSUE_TEMPLATE/development-work.md) — new-task issue template.

These are **shared instructions, not software that transparently migrates chat context**. Both assistants must read the latest connected GitHub state each time; a session unable to access GitHub must say so.

## Long-running XemAi priorities (goals, not shipped claims)

- **Natural conversation:** correct latest user intent, reference resolution, warmth/humour, useful next steps; avoid endless meta-analysis. Use existing `conversation test` evaluation and fresh held-out examples, not coached bridge messages alone.
- **Honesty and evidence:** truth and calibrated uncertainty over agreement; reproducible coding and research results.
- **Durable learning:** separate app prompts, memory, approved lessons, owner-reviewed SFT datasets and actual neural-weight updates. A tiny **separate 4B** LoRA pilot completed, but bridge-derived 4B/9B training has not been demonstrated and live 9B weights remain unchanged. Feedback scores alone cannot update weights.
- **Private dialogue:** owner-enabled private XemAi ↔ ChatGPT discussion, adaptive by actual model/compute, with scored feedback and an independent scheduled ChatGPT check. No private issue data is published in this repository.
- **Data preservation:** chats, memory, models, saved settings, pairing and unrelated projects must survive routine updates.
- **Separate project:** XemTV source, device deployments and unfinished Codex builds are outside this repository's automatic update authority.

## Working method / how to pick up the next task

Open [GitHub PRs](https://github.com/Xeminas1/personal-ai/pulls?q=is%3Aopen) and [GitHub issues](https://github.com/Xeminas1/personal-ai/issues?q=is%3Aopen). Follow the latest meaningful linked issue/PR checkpoint before creating a branch. The owner may direct work to a particular task, in which case that instruction takes priority within existing safety limits.

**After significant progress** update the issue/PR checkpoint with exact SHAs, completed changes, unrun/passed/failed checks and a concrete next operation. **After publishing a release** refresh this page's verified version and pointers. Do not overwrite a more recent Codex checkpoint with outdated ChatGPT context.

## Privacy note

This page is intentionally free of personal chats, private bridge message IDs/content, credentials, local machine paths, host access details, private test datasets and unpublished XemTV state. Use private approved channels for sensitive evidence; use synthetic public fixtures in code and tests.
