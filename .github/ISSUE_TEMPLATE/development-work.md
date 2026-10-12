---
name: XemAi development work / assistant handoff
about: Track an authorised XemAi change so ChatGPT and Codex can resume it from GitHub
title: "[XemAi] "
labels: []
assignees: []
---

<!-- PUBLIC REPOSITORY: do not paste private GitHub dialogue, chats, logs, personal data, host identifiers or credentials. Use synthetic reproduction steps. -->

## Objective and evidence

- What is being requested or what reproducible **public-safe** defect exists?
- Current app version and `main` SHA (verify, don't guess):
- Related issue / PR / release link:
- Observed behavior vs expected behavior:
- Evidence type: actual test | code inspection | owner report | hypothesis.

## Owner-approved scope and boundaries

- Minimal intended files/systems:
- Changes NOT authorised (model training, secrets, privileges, data sharing, migrations, other repos, etc.):
- Data/worker/config preservation and rollback plan:

## Acceptance criteria

- [ ] Reproduce or define a falsifiable baseline and targeted regression.
- [ ] Make a small reversible change on an isolated branch.
- [ ] Use fictional/synthetic test fixtures; do not publish private data.
- [ ] Pass relevant Windows and Linux checks on the **exact last PR head**.
- [ ] For runtime release: correct version/history/notes, frozen refs, SHA-256 assets, manifest verification and final-tree match.
- [ ] Verify merge and release publication; do **not** assume user's machine installed it.
- [ ] Update this issue and `docs/PROJECT_STATE.md` if this is a material milestone.

## Current handoff checkpoint

```text
XEMAI HANDOFF CHECKPOINT (UTC): YYYY-MM-DD HH:MM
Owner-approved scope:
Status: proposed
Latest verified published app version:
Main SHA checked:
Working branch / draft PR:
Last pushed HEAD:
Completed:
Checks passed ON THAT HEAD:
Checks failed / not yet run:
Release manifest / frozen ref:
Blockers:
Next safe step:
Privacy/rollback:
```

See `AGENTS.md` and `docs/HANDOFF_PROTOCOL.md`. Update this checkpoint as each meaningful step completes; avoid claiming unperformed work.
