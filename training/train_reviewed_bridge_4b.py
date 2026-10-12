"""Manual Qwen3.5 4B LoRA experiment using owner-reviewed BRIDGE dataset.

The preceding on-device bridge export is *not* training consent. This runner
needs an already validated, split private dataset from prepare_dataset.prepare,
plus a new exact operator confirmation. No bridge, memory or GitHub access.

Only the distinct, PINNED PUBLIC Qwen3.5 4B checkpoint is allowed. The active
Ollama 9B inference model and all XemAi configuration remain untouched.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import uuid
from pathlib import Path

from training import synthetic_smoke as pilot
from training.prepare_dataset import DatasetRejected, _safe_path, verify

CONFIRMATION = "TRAIN REVIEWED BRIDGE 4B"
OUTPUT_ROOT = pilot.REPO / "data" / "weight_training" / "bridge_adapter_runs"
MAX_STEPS = 16
MAX_RECORDS = 1000


class BridgeTrainError(ValueError):
    """Safe failure; do not echo private candidate text or local paths."""


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _load_prepared(path: Path) -> tuple[list[dict], list[dict], dict]:
    """Revalidate schema, source approval manifest and content digests."""
    root = _safe_path(path)
    meta = verify(root)
    if (meta.get("schema") != 1 or meta.get("training_applied") is not False
            or meta.get("model_changed") is not False
            or meta.get("approved_for_automatic_training") is not False
            or meta.get("dataset_status") != "owner_supplied_review_claim_unverified"):
        raise BridgeTrainError("Prepared review dataset has an unexpected provenance or training state.")
    if meta["train_count"] < 8 or meta["heldout_count"] < 2:
        raise BridgeTrainError("At least 8 training and 2 held-out samples are required.")
    if meta["train_count"] + meta["heldout_count"] > MAX_RECORDS:
        raise BridgeTrainError("Prepared dataset exceeds the safe size budget.")
    batches = []
    for name in ("train.jsonl", "heldout.jsonl"):
        source = _safe_path(root / name, file=True)
        records = []
        for line in source.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            messages = record["messages"]
            records.append({
                "prompt": [dict(turn) for turn in messages[:-1]],
                "completion": [dict(messages[-1])],
            })
        batches.append(records)
    return batches[0], batches[1], meta


def _output_dir() -> Path:
    root = OUTPUT_ROOT.absolute()
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise BridgeTrainError("Adapter output path cannot contain symbolic links.")
    if not root.parent.name == "weight_training":
        raise BridgeTrainError("Adapter output location is unexpected.")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = root / ("reviewed_4b_" + uuid.uuid4().hex)
    target.mkdir(mode=0o700, exist_ok=False)
    return target


def preflight(run: Path) -> dict:
    _, _, meta = _load_prepared(run)
    pilot._local_checkpoint()
    print("Verified isolated pinned Qwen3.5 4B checkpoint.")
    print("Prepared reviewed training samples:", meta["train_count"])
    print("Held-out samples, never used for gradient updates:", meta["heldout_count"])
    print("Review provenance: owner-supplied attestation; facts not independently verified.")
    print("NO GPU load, model download, training or weight deployment performed.")
    return meta


def train(run: Path, *, steps: int = 4) -> dict:
    if not isinstance(steps, int) or not 1 <= steps <= MAX_STEPS:
        raise BridgeTrainError("The manual optimiser-step budget must be 1 to 16.")
    train_items, heldout_items, meta = _load_prepared(run)
    checkpoint = pilot._local_checkpoint()
    # The verified 4B training experiment succeeded with auto compilation
    # DISABLED. Apply this flag before importing Unsloth.
    os.environ.update({
        "UNSLOTH_COMPILE_DISABLE": "1",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
        "WANDB_DISABLED": "true",
        "WANDB_MODE": "disabled",
        "TOKENIZERS_PARALLELISM": "false",
    })
    try:
        from unsloth import FastLanguageModel
        import torch
        from datasets import Dataset
        from transformers import Trainer, TrainingArguments
    except (ImportError, RuntimeError) as exc:
        raise BridgeTrainError("CUDA BF16 training packages could not be loaded.") from exc
    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise BridgeTrainError("CUDA and BF16 training are required.")
    free, _ = torch.cuda.mem_get_info(0)
    if free < 10 * 1024**3:
        raise BridgeTrainError("Less than 10 GiB currently free on GPU; do not disturb the live worker.")
    print("Loading separate official Qwen3.5 4B checkpoint from local disk.")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=str(checkpoint), max_seq_length=pilot.MAX_LENGTH,
        load_in_4bit=False, load_in_16bit=True, full_finetuning=False,
    )
    # Exact same tokenizer/template/labels used in successfully tested 4B
    # pilot. Fail on excess length, token-prefix mismatch or zero answer loss.
    train_tokens = pilot._prepare_tokenized_data(tokenizer, train_items)
    heldout_tokens = pilot._prepare_tokenized_data(tokenizer, heldout_items)
    print("Training examples tokenised:", len(train_tokens), "held-out:", len(heldout_tokens))
    model = FastLanguageModel.get_peft_model(
        model, r=16,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
        lora_alpha=16, lora_dropout=0, bias="none",
        use_gradient_checkpointing="unsloth", random_state=3407,
        max_seq_length=pilot.MAX_LENGTH,
    )
    observed = []
    for name, tensor in model.named_parameters():
        if tensor.requires_grad and "lora_B" in name and tensor.numel():
            observed.append((tensor, tensor.detach().float().cpu().clone()))
            if len(observed) == 8:
                break
    if not observed:
        raise BridgeTrainError("No trainable LoRA-B adapter parameters were found.")
    dest = _output_dir()
    base_tokenizer = pilot._text_tokenizer(tokenizer)
    collator = pilot._batch_collator(torch, base_tokenizer.pad_token_id)
    trainer = Trainer(
        model=model, train_dataset=Dataset.from_list(train_tokens),
        data_collator=collator,
        args=TrainingArguments(
            output_dir=str(dest / "trainer_temp"),
            remove_unused_columns=False,
            per_device_train_batch_size=1, gradient_accumulation_steps=2,
            max_steps=steps, warmup_steps=0, learning_rate=2e-4, bf16=True,
            optim="adamw_8bit", seed=3407,
            save_strategy="no", report_to="none", logging_steps=1,
            dataloader_num_workers=0,
        ),
    )
    print("Beginning owner-authorised, isolated 4B LoRA training, steps:", steps)
    summary = trainer.train()
    loss = float(getattr(summary, "training_loss", float("nan")))
    if not math.isfinite(loss):
        raise BridgeTrainError("Training loss was not finite.")
    changed = sum(bool(torch.any(p.detach().float().cpu() != old).item())
                  for p, old in observed)
    if changed < 1:
        raise BridgeTrainError("No sampled adapter weights changed; training unsuccessful.")
    adapter_dir = dest / "adapter"
    model.save_pretrained(str(adapter_dir))
    tokenizer.save_pretrained(str(adapter_dir))
    digests = {p.name: _digest(p.read_bytes()) for p in sorted(adapter_dir.iterdir())
               if p.is_file() and not p.is_symlink()}
    if "adapter_config.json" not in digests or not any(
            name.endswith(".safetensors") for name in digests):
        raise BridgeTrainError("Adapter checkpoint was not saved correctly.")
    record = {
        "schema": 1, "kind": "explicit_reviewed_bridge_4b_lora",
        "model": pilot.MODEL_ID, "revision": pilot.REVISION,
        "source_train_sha256": meta["train_sha256"],
        "source_heldout_sha256": meta["heldout_sha256"],
        "train_count_available": len(train_items),
        "heldout_count": len(heldout_items),
        "optimizer_steps": steps,
        "training_loss": loss,
        "sampled_lora_b_tensors_changed": changed,
        "adapter_files_sha256": digests,
        "manual_review_claim_not_independently_verified": True,
        "weights_trained": True,
        "deployed": False, "xemai_9b_modified": False,
        "heldout_quality_not_yet_evaluated": True,
    }
    (dest / "manifest.json").write_text(
        json.dumps(record, sort_keys=True, indent=2), encoding="utf-8"
    )
    print("REVIEWED BRIDGE 4B LORA TRAINING COMPLETE (NOT DEPLOYED).")
    print("Changed LoRA-B parameter tensors:", changed)
    print("Measured training loss:", f"{loss:.6f}")
    print("Saved adapter and manifest to separate private directory:", dest.name)
    print("No claim of improved 9B, general quality or independent fact-checking.")
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="No GPU/weights; check reviewed source.")
    mode.add_argument("--train", action="store_true", help="Owner-approved 4B training.")
    parser.add_argument("--run", type=Path, required=True, help="Exact local prepared dataset run.")
    parser.add_argument("--steps", type=int, default=4)
    parser.add_argument("--confirm", default="")
    args = parser.parse_args(argv)
    try:
        if args.check:
            preflight(args.run)
        elif args.confirm != CONFIRMATION:
            raise BridgeTrainError("Additional explicit owner consent required for 4B GPU training.")
        else:
            train(args.run, steps=args.steps)
        return 0
    except (BridgeTrainError, DatasetRejected) as exc:
        print("Bridge adapter stopped safely:", type(exc).__name__)
        return 2
    except Exception as exc:
        from training.failure_diagnostics import print_diagnostics
        print("Bridge adapter stopped:", type(exc).__name__)
        print_diagnostics(exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
