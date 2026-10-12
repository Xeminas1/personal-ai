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

## Optional public model checkpoint — separate from XemAi (owner permission required)

The owner has confirmed CUDA and BF16 work in an isolated Windows Python 3.13 + Unsloth environment on an RTX 5080 with ~13.7 GiB free VRAM. This **does not mean real fine-tuning has run**.

To prepare a *separate* Qwen3.5 4B BF16 LoRA pilot, the exact official public checkpoint is pinned to Hugging Face commit `c7429d5a8ed57f4a9cfdaf1af76a8943eba0ae97` (Apache-2.0; approximately **9.34 GB**). The source is [Qwen/Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B/tree/c7429d5a8ed57f4a9cfdaf1af76a8943eba0ae97). A 4B checkpoint is **not interchangeable** with the running 9B Ollama model.

Use `training\\windows_model_download.cmd --check` for read-only status; `training\\windows_model_download.cmd --download` only after deciding the network/storage cost is acceptable, then type **DOWNLOAD**. The download uses the installed isolated `hf` CLI with a fixed source and revision and suppresses implicit credential use. It writes only to local gitignored `data/weight_training/models/<revision>`, verifies architecture and required large public shards, and does **not** access private bridge records, change Ollama, train weights or upload anything. An interrupted download can be resumed by rerunning the command; incomplete shards never count as a successful checkpoint.

Source-level privacy and mocked Windows consent checks run in CI. Real network download and model loading **cannot be verified on GitHub Actions**. No training dataset exists until the owner separately prepares human-reviewed, consented and selected records. Before a real LoRA run, review the source, ensure at least 10 distinct approved records and reserve held-out examples not trained on. The available ~13.7 GiB GPU headroom is only an estimate; a real 4B training smoke run may still fail due to CUDA memory or kernel incompatibilities and must be stopped without altering XemAi.

## First genuinely trainable smoke pilot (after 4B checkpoint download)

The owner has now confirmed that the official, revision-pinned Qwen3.5 4B checkpoint downloaded and the public shard/architecture validator succeeded. This is **not** proof that model loading or training works yet. The installed Qwen3.5 9B model remains unchanged.

The next separate training package is also reproducible from the files in this draft PR:

- `training/synthetic_smoke.py`: inspectable fictional dialogues only (16 training + four reserved holdouts), no source from bridge, messages or memory; pinned locally downloaded 4B checkpoint; no network requests or uploads.
- Run `python -m training.synthetic_smoke --check` in the isolated Python 3.13 environment first. This reads the checkpoint index, shard presence, model architecture and installed package versions only.
- With the owner's separate decision to use GPU resources, run `python -m training.synthetic_smoke --train --confirm "TRAIN SYNTHETIC 4B"` (or `training/TRAIN_SYNTHETIC_QWEN4B.cmd` in a complete PR checkout; the downloadable add-on uses a root-level wrapper). The extra confirmation string is required. Training uses **two optimisation steps** of BF16 LoRA at 384 tokens maximum, and checks at least one LoRA-B parameter tensor really changed. It stores a separate adapter and local SHA-256 file manifest below the gitignored `data/weight_training/pilot_runs/`.
- The simple synthetic holdout is NOT automatically graded and does not prove improved quality. The result's `training_executed` flag describes a run, not XemAi app training. The adapter is **not activated** in Ollama, does not apply to the 9B model, and is not a release.

**Limitations:** Windows/GitHub CI only executes safety and offline synthetic checks without a real GPU. Actual Unsloth/Triton/Qwen3.5 CUDA loading may fail, may use significant VRAM and compute, and is stopped rather than silently using QLoRA or overwriting the existing inference model. No public repo issue or tests contain owner data. A failed training run may leave a new incomplete temporary run folder, never a production model change. The smoke script proves measured adapter parameter change *only if* the PC training completes and its output is verified. Neither a low loss nor two tiny training steps establish improved general intelligence.

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

## 2026-10-12: First owner-host pilot stopped at Qwen3.5 template validation (fixed in draft)

**Observed host result:** RTX 5080 CUDA BF16 preflight succeeded and the complete pinned public 4B checkpoint loaded (723/723 weights). The initial experimental pilot exited safely at stage 2/4 with `The assistant completion would be truncated or untrainable`. **No optimizer steps ran; no adapter was saved or installed.** This is NOT evidence that the Qwen model or the user's GPU cannot train.

The original guard called `apply_chat_template(..., tokenize=True)` once on an unfinished prompt and again on a completed assistant turn, then assumed both calls returned plain Python lists with a matching token-length relationship. Qwen3.5 thinking-mode prefixes can differ, and multimodal processors may return structured tokenization results. TRL has documented Qwen3.5 prompt/completion token-prefix mismatches (see [trl#5213](https://github.com/huggingface/trl/issues/5213)). The exact failing subtype on this host is **not yet measured**, because the original guard did not record a subtype.

**Correction:** The revised synthetic pilot explicitly renders non-thinking Qwen3.5 chat text, checks answer inclusion and prompt prefix, tokenizes with the model's actual underlying text tokenizer, enforces untruncated supervised tokens, and uses a Transformers `Trainer` with pre-tokenized `input_ids`, `attention_mask`, and per-token `labels`. User prompt tokens and padding have label `-100`, so training loss applies only to the intended assistant continuation. This avoids depending on TRL's automatic Qwen3.5 prompt/completion masking. The code still refuses to train if the token prefix is genuinely incompatible. A separate `--tokenizer-check` validates the installed **real local tokenizer on CPU without loading 4B GPU weights**; it must pass before repeating the training attempt. This is a model-format compatibility adjustment, NOT a claim that GPU training succeeded.

Run the read-only fixed precheck first via `CHECK_SYNTHETIC_PILOT.cmd` (now `--tokenizer-check`); it prints supervised token counts without sample text. Only if that succeeds and the owner consents again should `TRAIN_SYNTHETIC_QWEN4B.cmd` be run. Keep the 4B checkpoint and Python environment unchanged. The general-purpose `training/train_adapter.py` is a separate experimental path and must **not** be treated as production-ready merely because the synthetic pilot's masking is repaired.

## 2026-10-12: First optimiser-step runtime failure on RTX 5080 (investigation)

The owner ran the actual, revision-pinned Qwen3.5-4B BF16 + LoRA smoke test on Windows. Model weights and Qwen3.5 tokenization loaded, all 286 synthetic supervised answer tokens were prepared, the LoRA adapter attached (21,233,664 trainable parameters), and the GPU training loop entered step 0/2. After about 5m03s it exited with `RuntimeError` **before any completed optimiser steps or confirmed adapter save**. The visible warning said `causal_conv1d_fn` fell back to a slower reference PyTorch implementation because the optimised package was absent. The warning does **not** establish that the fallback caused the runtime error. The original exception details were intentionally suppressed for privacy, so the exact underlying cause is **unknown**. Do not imply any XemAi 9B model learning occurred.

**New experimental diagnostics**: `training/failure_diagnostics.py` emits a bounded error category, redacted first-line cause, module/function location without host paths, optional live CUDA memory data, and an error fingerprint; no local raw logs, private chats or tokens are copied or uploaded. Tests cover common CUDA out-of-memory, compiler, convolution, precision and tensor-shape errors plus redaction. Prompt the owner to **share only the `DIAGNOSTIC:` lines**, after checking them for privacy.

**Opt-in compatibility retry**: `training/TRAIN_COMPAT_QWEN4B.cmd` requires typing `DIAGNOSE` and runs the same synthetic two-step training with `--compat-no-compile`, which sets Unsloth's documented `UNSLOTH_COMPILE_DISABLE=1` **before importing Unsloth**. This can help isolate compilation-related errors; it does not install or build `causal-conv1d`, and the retry may still be slow or fail. The flag and error report do not alter XemAi's installed Ollama 9B model, host configuration, or Python training packages. The owner-facing root-folder overlay ZIP uses the same source code as this PR. **No real training success is claimed until the owner confirms completed steps, non-zero LoRA-B deltas, and saved adapter files.**

References: [Unsloth environment flags](https://unsloth.ai/docs/basics/unsloth-environment-flags), [Qwen3.5 training notes](https://unsloth.ai/docs/models/qwen3.5/fine-tune). Installing random third-party Windows GPU wheels for `causal-conv1d` without matching Python/PyTorch/CUDA evidence is not part of this plan.


## 2026-10-12: Synthetic BF16 LoRA fine-tuning success on owner's RTX 5080

**Observed success from user-shared host output:** The owner retried the pinned, offline Qwen3.5 4B smoke run with `UNSLOTH_COMPILE_DISABLE=1` and completed **2/2 optimiser steps** in **171.8 seconds** (2m52s). Synthetic training loss readings were 2.484 and 2.46; aggregate **2.47189**. The training code found **eight sampled LoRA-B parameter tensors changed**, wrote a private adapter and SHA-256 manifest, and the batch wrapper finished **exit status 0**. The `causal_conv1d_fn` reference-kernel warning appeared, but training succeeded despite it. The earlier failure's precise root cause remains unconfirmed: do not infer disabling compilation was necessarily the only difference responsible.

The run used **16 fictional training examples**, four separate fictional holdout examples not used in training, and a recorded total of **286 supervised answer tokens**. The LoRA setup included **21,233,664 trainable parameters**. The adapter was written **only on the owner's machine**. The GitHub connector cannot inspect that adapter's bytes, so the record is based on the user's local console result, not on an independent remote audit. The active XemAi Qwen3.5 9B Ollama worker, memory, bridge, and settings were NOT changed; the 4B LoRA weights are incompatible with the 9B model.

### Optional read-only holdout comparison (new experimental utility)

`training/evaluate_synthetic_adapter.py` can confirm that the previously saved local training manifest and adapter file checksums match and score the **same four reserved synthetic examples** against **(a)** the original pinned 4B base with the LoRA adapter disabled and **(b)** the same 4B model with the saved adapter enabled. It uses Hugging Face PEFT's documented `PeftModel.disable_adapter()` context to prevent holding two BF16 4B copies in GPU memory ([PEFT reference](https://huggingface.co/docs/peft/en/package_reference/peft_model)). It uses no training, network, chat access, new installs, model promotion, or file writes.

- Read-only CPU preflight: `python -m training.evaluate_synthetic_adapter --check` from the existing environment, or `training/CHECK_4B_HOLDOUT.cmd`. This validates hashes and chooses the one completed saved run; if several eligible runs are found, supply an explicit `--run-id` rather than guessing.
- Owner-authorised GPU comparison: `python -m training.evaluate_synthetic_adapter --evaluate --confirm "EVALUATE SYNTHETIC 4B"`, or `training/EVALUATE_4B_HOLDOUT.cmd` (which separately requires typing `EVALUATE`). Requires GPU headroom and may take time. It prints base/adapted answer-token negative log-likelihood and their difference (lower is better).
- **Never confuse the holdout metric with an intelligence improvement**. Four synthetic examples cannot establish robust gains in dialogue, reasoning, coding, safety or truthfulness, even if the adapted holdout loss is lower. The held-out examples themselves may also be similar to training examples; additional real but owner-consented, independently evaluated benchmarks would be required for any promotion.

This utility is currently validated only by **synthetic, CPU-only regression tests and GitHub Actions**. A real post-training 4B base+PEFT loading comparison on the owner's RTX 5080 remains to be run and could reveal additional Windows/Unsloth compatibility issues. No weight-training automation or automatic production model updates are implied.


## 2026-10-12: Genuine held-out 4B base vs adapter comparison succeeded on owner's GPU

**Owner-provided complete execution log, status 0.** Read-only, offline Qwen3.5 4B holdout evaluator verified the local adapter manifest/file checksums and loaded the originally pinned 4B model. It scored the same four fictional prompt/answer holdouts against the unchanged base (adapter disabled) and the trained adapter (enabled). The 4 examples contain **63 supervised answer tokens**. Results:

| Same four synthetic held-outs | Mean supervised answer-token NLL |
| --- | ---: |
| Original Qwen3.5 4B base | 3.152394 |
| Same base + trained LoRA | 2.915653 |
| Adapter minus base (lower is better) | **-0.236741** |

The trained adapter therefore has a **lower answer-token loss on this specific four-example synthetic holdout**. The successful two-step BF16 LoRA run also demonstrated changed saved weights (8 sampled LoRA-B tensors) and this held-out comparison demonstrates a measurable out-of-training-sample effect on this very narrow test. The 16 available training examples were not all processed: training stopped at epoch 0.25 (two optimizer steps, gradient accumulation 2, batch size 1; ~four example presentations).

**Interpretation limits:** The holdouts are fictional and similar in style/subject to the training data. Four short examples and 63 answer tokens are not independent evidence that general reasoning, coding, truthfulness, conversations or XemAi application performance improved; the observed NLL could reflect narrow transfer or overlap. No blind human preference test, coding regression benchmark, confidence interval, or multi-seed run was completed. Nor has the saved adapter been merged into, or run as, XemAi's actual **9B** inference model. Evaluation did not train, modify, upload, promote, or deploy anything. Both actual GPU train/eval results are provided by the owner via console text; GitHub CI is CPU-only and cannot independently inspect private local adapter weights.

**Next gating question: how to train the live 9B safely?** The [official Unsloth Qwen3.5 training guide](https://unsloth.ai/docs/models/qwen3.5/fine-tune) estimates approximately **22GB VRAM for Qwen3.5 9B BF16 LoRA** and specifically advises **against QLoRA (4-bit) for Qwen3.5** because of unusually high quantization differences. The owner's RTX 5080 has about 15.9 GiB physical GPU memory, so neither a 9B BF16 LoRA run using the current script nor an unsupported automatic 4-bit conversion should be presented as production-ready. Possible later paths require separately evaluated offloading/distributed compute/more VRAM or an explicitly acknowledged experimental 4-bit QLoRA tradeoff. Protect running 9B Ollama, conversation privacy, and require owner approval for any such pilot. Next quality checks should use representative owner-reviewed synthetic benchmarks and require measurable gains before any adapter deployment.



## 2026-10-12: Dedicated 9B feasibility checkpoint (zero training)

The successful separate 4B experiment and narrow four-example held-out comparison justify investigating XemAi's actual Qwen3.5 9B model, **not automatically switching the running model or treating 4B improvements as transferable to 9B**.

The official Qwen3.5 9B Hugging Face safetensors index gives a base-weight total of **19,306,216,416 bytes (~19.31 GB)** (https://huggingface.co/Qwen/Qwen3.5-9B/blob/main/model.safetensors.index.json). This BF16 training source is NOT identical to the already-installed quantized Ollama 9B inference artifact. The owner has not downloaded a separate pinned 9B training snapshot for this workflow.

The new standalone training/assess_9b.py is a **no-network, standard-library-only, non-destructive** Windows/GPU feasibility reporter. It queries NVIDIA VRAM totals/free bytes, training-folder disk space, and locally present bitsandbytes/accelerate package metadata. It does NOT import torch/Unsloth, load model weights, download files, train or save data. training/CHECK_9B_FEASIBILITY.cmd is the double-click Windows entry point (uses python -B to avoid creating bytecode caches); source is also packaged as a root-folder ZIP. The synthetic test_training_9b_feasibility.py checks 16GB, no-GPU and larger-GPU cases. These are advisory tests, **not evidence of Windows GPU training compatibility**.

Possible separately reviewed routes:

- **BF16 9B LoRA**: published Unsloth estimate ~22GB VRAM (https://unsloth.ai/docs/models/qwen3.5/fine-tune), above the owner's 16GB RTX 5080; do not attempt to run the 4B BF16 script against 9B.
- **8-bit base + LoRA adapters**: potentially lower weight VRAM; Hugging Face documents training extra adapter parameters over 8-bit weights (https://huggingface.co/docs/transformers/quantization/bitsandbytes), and Unsloth documents load_in_8bit=True generally (https://unsloth.ai/docs/get-started/fine-tuning-llms-guide). **Actual 9B Qwen3.5/Windows support, peak VRAM and training quality have NOT been validated.** A future model download or pilot requires separate owner approval.
- **4-bit QLoRA**: not recommended as a default due to Unsloth's Qwen3.5-specific quantization-quality warning. Do not silently fall back.
- **CPU offload**: requires concrete backward/gradient support on this particular Windows and model stack; inference-only CPU offload does not establish training feasibility.

The ONLY next action here is to run the read-only 9B feasibility check and review the sanitized report. This is not authorization to download public 9B model files (~19.31 GB), use private bridge chats, train the active 9B model, or deploy any adapter.

