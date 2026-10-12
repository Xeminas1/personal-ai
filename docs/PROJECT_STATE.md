# XemAi project state — public-safe handoff index

**Snapshot checked:** 2026-10-12 (UTC). This page is a **manual checkpoint, not a live GitHub API feed**. Before taking action, compare it with the actual latest `main` SHA, `app/version.py`, the manifest, open issues/draft PRs and recent CI, following [HANDOFF_PROTOCOL.md](HANDOFF_PROTOCOL.md). Newer verified GitHub changes take precedence over this snapshot.

## Last verified released XemAi application

| Field | Verified snapshot |
| --- | --- |
| Published XemAi app version | **v0.9.56** |
| `main` merge SHA at v0.9.56 release | `3be4fc3fe1ec4bf3bc48f04b458e15fceff6cf50` |
| Frozen release `release-v0.9.56` SHA | `b3e60ab06cdcc2004701a95d1da12881049e6ab5` |
| Release/merge relationship | Matching repository **tree** verified for those commits after PR #59 merge |
| Release PR | [#59 — Private GitHub dialogue pagination repair](https://github.com/Xeminas1/personal-ai/pull/59) |
| Latest verified release manifest | v0.9.56, **162 SHA-256 pinned assets** |
| Release CI at final tested source head | Windows/Linux regressions and full manifest verification **passed** at frozen head |
| Installed version on an owner's computer | **Unknown from GitHub alone** |

The code repository's newer **documentation-only** commits are not necessarily new app releases; the authoritative installed app version is the running host's report. GitHub merges cannot verify automatic installation on the laptop/PC.

## Pending / unfinished work

| ID | Item | State at snapshot | What remains |
| --- | --- | --- | --- |
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
- **Durable learning:** currently separate app prompts, memory and owner-reviewed lesson references from *actual* Qwen/adapter training. Weight fine-tuning is an **unimplemented/approval-gated plan**, not a side effect of private chat scores.
- **Private dialogue:** owner-enabled private XemAi ↔ ChatGPT discussion, adaptive by actual model/compute, with scored feedback and an independent scheduled ChatGPT check. No private issue data is published in this repository.
- **Data preservation:** chats, memory, models, saved settings, pairing and unrelated projects must survive routine updates.
- **Separate project:** XemTV source, device deployments and unfinished Codex builds are outside this repository's automatic update authority.

## Working method / how to pick up the next task

Open [GitHub PRs](https://github.com/Xeminas1/personal-ai/pulls?q=is%3Aopen) and [GitHub issues](https://github.com/Xeminas1/personal-ai/issues?q=is%3Aopen). Follow the latest meaningful linked issue/PR checkpoint before creating a branch. The owner may direct work to a particular task, in which case that instruction takes priority within existing safety limits.

**After significant progress** update the issue/PR checkpoint with exact SHAs, completed changes, unrun/passed/failed checks and a concrete next operation. **After publishing a release** refresh this page's verified version and pointers. Do not overwrite a more recent Codex checkpoint with outdated ChatGPT context.

## Privacy note

This page is intentionally free of personal chats, private bridge message IDs/content, credentials, local machine paths, host access details, private test datasets and unpublished XemTV state. Use private approved channels for sensitive evidence; use synthetic public fixtures in code and tests.
