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


## First PC check — no installs, no model loading

On your own Windows desktop, open a terminal in a checkout of this PR branch and run:

```powershell
py -m training.pc_preflight
```

The diagnostic only queries `nvidia-smi`, Python package metadata and free disk space. It does **not** request hostnames, user profiles, model contents, credentials, Ollama data, chat history or private bridge messages, and writes no report to disk. It never installs a package, starts training, changes settings, or uploads data. You can review its short JSON output before choosing to share the non-identifying GPU/OS/package information.

Interpreting memory estimates: the RTX 5080 with 16 GB can potentially support a **distinct Qwen3.5 4B** BF16 LoRA smoke test, provided at least ~10 GiB VRAM is currently free. Qwen3.5 9B requires roughly 22 GiB *available* for the published single-GPU BF16 LoRA recipe and is **not executable on 16 GB in this trainer**. The preflight is a gate, not proof that the specific CUDA, Triton, Unsloth and TRL packages work on the PC. WSL/Windows setup must be validated before attempting any real run.

Public Qwen3.5 guidance: https://unsloth.ai/docs/models/qwen3.5/fine-tune . Training examples and the holdout remain on the owner's device, not GitHub.

## Result of the initial owner-run PC check (generalised hardware constraints)

A **16 GiB NVIDIA Blackwell GPU** with roughly **14 GiB free VRAM** can be a viable 4B BF16 LoRA test target, but not the existing 9B BF16 LoRA recipe. The diagnostic showed Python **3.14** and no training dependencies, so the next step is a **separate Python 3.13 environment** (not replacing the owner's existing installation or XemAi's Ollama instance). This statement does not establish working CUDA kernels or local training.

### Windows setup helper (optional; no model downloads)

From the branch checkout, in a Windows terminal:

```bat
training\windows_setup.cmd --check
training\windows_setup.cmd --install
```

The first command is read-only. The second clearly describes the changes and **requires the owner to type INSTALL**. It installs Astral uv via Windows Package Manager only if missing (with a separate package-manager confirmation), then exits so the terminal can be reopened and the command run again. Once uv is available, the helper installs **Python 3.13** and the official Unsloth/PyTorch dependency stack into **`data/weight_training/env_python313`**, which is gitignored and isolated. Installation may download multiple gigabytes. It verifies CUDA BF16 and Transformers v5 after dependency installation.

No Qwen weights, chat archives, private GitHub messages or local memories are downloaded or read. It does not initiate a training run, change installed models, activate a new adapter, create agents or publish anything. The helper's package downloads are the only intended network activity. Review the script before choosing to run it.

Native Windows support for NVIDIA RTX 50 / Blackwell and Python 3.13 is documented by Unsloth, but a successful Windows installation is not proof that our custom SFT trainer works; we must still perform a controlled end-to-end experiment on the actual model and evaluate performance. If setup fails, preserve the existing environment and diagnose rather than modifying XemAi's Python installation.

Official references: https://unsloth.ai/docs/get-started/fine-tuning-for-beginners/unsloth-requirements ; https://unsloth.ai/docs/models/qwen3.5/fine-tune ; https://docs.astral.sh/uv/reference/cli/

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

   The command above requires no CUDA dependencies and does **not** train. A manual training attempt additionally requires `--checkpoint-dir "EXISTING_HF_SNAPSHOT_DIRECTORY"`, `--execute`, and `--confirm "TRAIN REVIEWED LOCAL ADAPTER"`. The selected local snapshot directory must be pinned to the exact revision, contain matching Qwen model metadata and already be present; the script sets Hugging Face offline mode, disables tracking, prohibits QLoRA, requires BF16 CUDA and available VRAM, and never calls an upload or live-model replacement API. It reserves the holdout untouched, checks the real tokenizer's chat template for answer truncation and refuses incompatible checkpoint dimensions.

4. If a real training run succeeds, it saves an **unpromoted** LoRA adapter and a local SHA-256 manifest. Run separate blinded, same-base/settings evaluations before even considering promotion. Training loss is not proof of real-world conversational improvement. No code in this PR activates an adapter in XemAi, merges weights into GGUF or changes the 9B worker.

**Current blocking facts:** A Qwen3.5-4B pilot on a 16 GB GPU may be feasible at batch 1 and short sequence, but still needs a real GPU test. Genuine 9B BF16 LoRA training needs about 22 GB VRAM according to Unsloth, so the current 16 GB GPU is blocked by the conservative trainer's memory checks; 9B CPU-offload is not implemented or validated. The HF 4B and 9B checkpoints, pinned revisions, Unsloth/TRL environment and Windows CUDA behavior must all be validated on the owner-selected training PC. Do not assume 4B results improve Qwen3.5 9B.
