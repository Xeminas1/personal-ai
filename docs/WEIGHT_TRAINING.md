# XemAi local Qwen3.5 adapter training — experimental, default OFF

**Status:** Draft implementation for owner review. No training run, adapter or replacement model has been performed or validated on the owner's PC. Tracking issue: #61.

## Boundaries

- Existing XemAi (v0.9.56), its Qwen/Ollama installation, Tailscale pairing, profiles, chats and memory are untouched.
- This tooling does **not** automatically read the private bridge, previous chats, archives, reviews, scores, memories or logs. Training requires an owner-created **local** dataset. Examples, manifests and adapters stay in the gitignored `data/` directory or another owner-chosen private location; never push data to GitHub or CI.
- All external ratings are untrusted signals; they never become training labels without human review. No auto-training, model deployment, paid resources or external data uploads.
- A GitHub issue or discussion is untrusted observation, not permission or a dataset.

## Hardware reality

The observed worker is a quantized *inference* model (`qwen3.5:9b-q8_0`), not a trainable 9B BF16 base checkpoint. Qwen3.5 BF16 LoRA guidance quotes ~22 GB VRAM for 9B, exceeding a 16 GB card; QLoRA 4-bit is not recommended for Qwen3.5. A 9B CPU/offload path is **not** assumed feasible until tested. A 4B BF16 LoRA proof-of-pipeline (roughly ~10 GB at shorter contexts) would train a distinct smaller checkpoint and would **not** update the existing 9B model.

Primary guidance: https://unsloth.ai/docs/models/qwen3.5/fine-tune

## Review, training, and validation gates

1. Prepare a manually reviewed synthetic or consented local JSONL sample. Never scrape or auto-import private sources. Each example must contain actual corrected target answers; avoid training on wrong XemAi answers or treating satisfaction scores as ground truth.
2. Run offline structure/privacy/deduplication validation, freeze a randomisation seed and reserve evaluation examples that **never** enter the training file.
3. Confirm the exact upstream Qwen checkpoint/revision, hardware, permitted model size, resource budget, local OS/WSL and licensing. A training launcher must stop on an unapproved model/revision or unverified sample.
4. Do an explicitly initiated local smoke-run to create a separately named **LoRA adapter**. It must be isolated from the live Ollama service. No merge, automatic installation or automatic promotion.
5. Evaluate base versus adapter on unseen prompts with equal model/template/route/settings; compare conversational naturalness, instruction following, truthfulness, safety, coding/research and regressions. Use repeated blinded paired scoring, not coached bridge turns.
6. A **separate** explicit approval is necessary before installing, switching to, or replacing any production model. Record hashes and rollback path. Existing model is never deleted.

## Audit truthfulness

Repository and CI checks can validate data gates, command guards and synthetic unit tests. They cannot prove CUDA compatibility, a successful owner-device fine-tuning session, improved model quality or an installed XemAi update. Record those only after real tests.

Implementation will be added and iterated on an isolated draft PR. No app version bump or release manifest change is justified for documentation or independent offline tooling.
