# Weight training — teaching XemAi permanently

XemAi can now change its own model weights from your corrections. Everything is
started by you, tested automatically before it's offered, and reversible with one
command. Your examples never leave your own computers.

## Quick start

1. **Correct replies as you chat.** When XemAi gets something wrong, reply with
   `teach: <the answer it should have given>`. Rating a great reply **9–10** also
   counts as an example, and approved `bridge weight` corrections are included.
2. **One-time setup** (PC must be on): type `weights setup`. This installs the
   training tools into a separate folder on the PC (`data/weight_training/venv`,
   about 6 GB). Takes 10–20 minutes; `weights` shows progress.
3. **Train** once you have at least 10 examples: type `weights train`. The first
   run also downloads the official Qwen3.5 9B checkpoint (~19 GB). While it trains
   (roughly 20–60 minutes), chat keeps working on the laptop's own model.
4. **Check** with `weights`. Each run shows its held-out score before and after.
   If the run passed, type `weights use r1` (or whichever run) to switch to it.
5. **Undo** any time with `weights rollback`.

## What "passed" means

A run is only offered if, on examples it was **never trained on**, the tuned model
predicts your preferred answers better than the original (held-out loss drops by at
least 0.02), **and** it hasn't drifted on general questions (its loss on the
original model's own answers to separate everyday prompts rises by at most 0.15).
Otherwise it's discarded and the reason is shown.

Then the adapter is packaged into Ollama as a new model `xemai-qwen-tuned:rN` and
smoke-tested. The original `qwen3.5:9b-q8_0` is never modified or deleted.

## How it works

| Step | Where | Detail |
| --- | --- | --- |
| Collect | Always-on host | `teach:` corrections, replies rated 9–10, approved bridge corrections. Corrections win if a prompt appears twice. |
| Send | Host → PC worker | Over the existing paired, token-authenticated worker link. |
| Train | PC (RTX 5080) | 4-bit QLoRA (rank 16) on every language-model linear layer; vision tower untouched. ~20% of examples held out. Base-model answers to generic prompts are replayed so it doesn't forget how to talk. |
| Gate | PC | Held-out gain and general-skill drift, as above. |
| Package | PC Ollama | Base model + LoRA adapter; if Ollama can't load that, merged weights re-quantised to q8_0. Smoke-tested via the Ollama API. |
| Use | Your command | `weights use rN` pins the tuned tag; model discovery never picks a tuned model by itself. |

Files on the PC under `data/weight_training/`: `venv/` (tools), `runs/rN/`
(`dataset.jsonl`, `adapter/`, `report.json`, `train.log`), `active.json` (the pin).
On the host: `teach.jsonl`.

## Limits and honest caveats

- Training happens on the PC. The laptop's `qwen3:1.7b` is not tuned (yet); tuned
  answers apply whenever chat runs on the PC.
- Small datasets teach style, preferences and specific facts best. A handful of
  examples will not make the model broadly smarter; more varied corrections help.
- The held-out score measures how well it predicts *your* preferred answers. It is
  evidence, not proof of better conversations — keep judging real replies.
- The first real run on the PC is the real test of the Ollama packaging step;
  `report.json` records which strategy worked.

## For developers

- Pipeline: [`training/xemai_tune.py`](../training/xemai_tune.py); setup:
  [`training/setup_env.py`](../training/setup_env.py); app side:
  [`app/weight_training.py`](../app/weight_training.py).
- Tests: `test_weight_training.py` (no ML packages) and
  `test_weight_tuning_pipeline.py` (real CPU training of a tiny Qwen3.5, needs
  torch/transformers/peft). CI: `.github/workflows/weight-training.yml`.
