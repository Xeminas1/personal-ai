# XemAi project state — public-safe handoff index

**Snapshot checked:** 2026-10-12 (UTC). This page is a **manual checkpoint, not a live GitHub API feed**. Before taking action, compare it with the actual latest `main` SHA, `app/version.py`, the manifest, open issues/draft PRs and recent CI, following [HANDOFF_PROTOCOL.md](HANDOFF_PROTOCOL.md). Newer verified GitHub changes take precedence over this snapshot.

## Last verified released XemAi application

| Field | Verified snapshot |
| --- | --- |
| Published XemAi app version | **v0.9.54** |
| `main` merge SHA at v0.9.54 release | `fd4abc0dc65692c9aa5432848d885a1ec3a07a84` |
| Frozen release `release-v0.9.54` SHA | `49d473d7d99cad1d2a5ec0a19c935917263752c7` |
| Release/merge relationship | Matching repository **tree** verified for those commits |
| Release PR | [#53 — Bridge polling diagnostics and short natural replies](../pull/53) |
| Latest verified release manifest | v0.9.54, **159 SHA-256 pinned assets** |
| Release CI at final tested source head | Windows and Linux regression checks **passed**, manifest verification **passed** |
| Installed version on an owner's computer | **Unknown from GitHub alone** |

The code repository's newer **documentation-only** commits are not necessarily new app releases; the authoritative installed app version is the running host's report. GitHub merges cannot verify automatic installation on the laptop/PC.

## Pending / unfinished work

| ID | Item | State at snapshot | What remains |
| --- | --- | --- | --- |
| [Issue #54](https://github.com/Xeminas1/personal-ai/issues/54) | Investigate bounded GitHub bridge comments JSON read and synthetic reproduction | **Open; not shipped** | Reproduce size/transport failure, propose permitted minimal patch, verify privacy and tests, then publish **only if** required checks pass |

**Issue #54 is not a v0.9.55 release.** The v0.9.54 patch made polling status observable and permitted short safe replies, but it did not fix any underlying GitHub API response-size/transport problem. There is no verified published v0.9.55 as of this snapshot. A previous tool restriction applied to an attempted fix; do not bypass a real platform block. Consult the live issue and available permissions for current status.

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
