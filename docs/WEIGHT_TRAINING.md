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


## Prototype CLI (owner-invoked only)

Run from the repository root with Python 3.12+. No new packages are needed to **prepare and verify** a dataset. The commands below describe capabilities of this branch; they do not install anything on the owner's computer.

1. Manually create a private JSONL file inside the gitignored `data/` folder (or another owner-chosen local private folder). It needs **at least 10 distinct consented/reviewed examples**, one object per line. Example of a single fictional entry (this is deliberately not an actual bridge comment):

   ```json
   {"reviewed":true,"consent":true,"source":"synthetic","messages":[{"role":"user","content":"The second option, please."},{"role":"assistant","content":"Certainly. You chose the second option."}]}
   ```

   All messages must alternate user/assistant and end in the *desired corrected assistant answer*, not an incorrect historical answer. A field saying `reviewed=true` is **not** independent validation; the human must check the contents and permissions. Privacy filters catch some sensitive material but do not guarantee anonymity.

2. Explicitly prepare and reserve an untouched holdout:

   ```powershell
   python -m training.prepare_dataset prepare --input "$PWD/data/weight_training/manual_examples.jsonl" --reviewed-and-consented --label pilot
   python -m training.prepare_dataset verify --run "ABSOLUTE_PATH_PRINTED_BY_PREPARE"
   ```

   Preparation refuses unreviewed records, malformed dialogue, likely secrets/identifiers, duplicates, and output inside a tracked source-code directory. It does not open any old local archives or bridge data. Prepared files and their SHA-256 manifest stay private under `data/weight_training/` by default; their examples are never copied into GitHub CI.

3. On the PC, after installing a separately reviewed CUDA/Unsloth environment and **explicitly** downloading an exact pinned upstream BF16 checkpoint, inspect the **dry-run** plan:

   ```powershell
   python -m training.train_adapter --run "PREPARED_RUN_DIRECTORY" --model "Qwen/Qwen3.5-4B" --revision "40_HEX_UPSTREAM_COMMIT"
   ```

   The command above requires no CUDA dependencies and does **not** train. A manual training attempt additionally requires `--checkpoint-dir "EXISTING_HF_SNAPSHOT_DIRECTORY"`, `--execute`, and `--confirm "TRAIN REVIEWED LOCAL ADAPTER"`. The selected local snapshot directory must be pinned to the exact revision and already present; the script sets Hugging Face offline mode, disables tracking, prohibits QLoRA, requires BF16 CUDA and available VRAM, and never calls an upload or live-model replacement API. It reserves the holdout untouched.

4. If a real training run succeeds, it saves an **unpromoted** LoRA adapter and a local SHA-256 manifest. Run separate blinded, same-base/settings evaluations before even considering promotion. Training loss is not proof of real-world conversational improvement. No code in this PR activates an adapter in XemAi, merges weights into GGUF or changes the 9B worker.

**Current blocking facts:** A Qwen3.5-4B pilot on a 16 GB GPU may be feasible at batch 1 and short sequence, but still needs a real GPU test. Genuine 9B BF16 LoRA training needs about 22 GB VRAM according to Unsloth, so the current 16 GB GPU is blocked by the conservative trainer's memory checks; 9B CPU-offload is not implemented or validated. The HF 4B and 9B checkpoints, pinned revisions, Unsloth/TRL environment and Windows CUDA behavior must all be validated on the owner-selected training PC. Do not assume 4B results improve Qwen3.5 9B.
