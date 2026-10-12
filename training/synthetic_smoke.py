"""Owner-triggered, local-only synthetic BF16 LoRA smoke test for Qwen3.5 4B.

Not a production trainer, an intelligence benchmark, or an XemAi update.
Uses no user conversations, bridge records, memories, review scores, or logs.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import re
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REVISION = "c7429d5a8ed57f4a9cfdaf1af76a8943eba0ae97"
MODEL_ID = "Qwen/Qwen3.5-4B"
SNAPSHOT = REPO / "data" / "weight_training" / "models" / REVISION
OUTPUT_ROOT = REPO / "data" / "weight_training" / "pilot_runs"
CONFIRMATION = "TRAIN SYNTHETIC 4B"
STEPS = 2
MAX_LENGTH = 384
MIN_FREE_GIB = 10.0

# Publicly inspectable fictional, independently constructed examples. These do
# not come from the private GitHub bridge or previous owner conversations.
EXAMPLES = (
    ("I asked for the second item, not the first.", "Understood—the second item. Thanks for correcting me."),
    ("Could you make this sound friendly? Actually, it's for my manager.", "Of course. I'll keep it professional but approachable."),
    ("I already restarted the application twice. What's one different step?", "Try opening it without recently added plugins to see whether a plugin causes the crash."),
    ("I want the earlier train. Options are 09:10 and 09:40. The second one, please.", "The second option is 09:40, which is later. Did you mean 09:40?"),
    ("The app has no internet access. Please don't tell me to restart my router.", "Got it. Check whether the app itself has network permission before changing the router."),
    ("I said no onions, but you included them.", "You're right—I missed your no-onions request. I'll leave onions out."),
    ("Your answer sounded confident, but you didn't check the source.", "Good point. I shouldn't present that as confirmed without checking the source."),
    ("I prefer a quick answer, not a long explanation.", "Understood. I'll keep the answer short and focus on the next useful step."),
    ("The second option is almond milk. Make it unsweetened.", "Unsweetened almond milk, understood."),
    ("That last curry was far too spicy for me!", "Fair point—I underestimated it last time. A plain rice dish may be a gentler choice."),
    ("I think the test passed, but I haven't actually run it.", "Then it hasn't passed yet. We should run it before claiming success."),
    ("The warning disappeared, but the crash still happens.", "So the warning is gone, but the crash remains. Let's investigate the crash separately."),
    ("I asked you to review the message, not send it.", "Understood. I'll review the draft only and won't send anything."),
    ("We don't know the restaurant menu. What can you recommend?", "I can't confirm individual dishes, but a simple non-spicy option may be safer if available."),
    ("I changed my mind. Keep the original layout.", "Understood—I'll preserve the original layout instead of applying the redesign."),
    ("You mentioned a fix, but haven't tested it yet.", "Correct—it's a proposed fix, not a verified solution until the tests run."),
    ("It still vibrates even though notifications are off.", "Check whether an alarm or reminder is causing the vibration; those can behave differently."),
    ("I don't want the file deleted. Just show me the duplicates.", "I'll identify the duplicates without deleting or changing any files."),
    ("You said you know my preferences, but I didn't tell you any.", "You're right. I shouldn't infer preferences that you haven't shared."),
    ("Do these two numbers prove an improvement? I only have one measurement.", "Not yet. We need comparable measurements before claiming an improvement."),
)


class PilotError(Exception):
    """Safe, content-free operational failure."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _local_checkpoint() -> Path:
    if SNAPSHOT.is_symlink() or not SNAPSHOT.is_dir():
        raise PilotError("Pinned local 4B checkpoint is missing or unsafe.")
    files = ("config.json", "tokenizer_config.json", "model.safetensors.index.json")
    if any(not (SNAPSHOT / filename).is_file() or (SNAPSHOT / filename).is_symlink() for filename in files):
        raise PilotError("Pinned checkpoint metadata or shard index is incomplete.")
    try:
        config = json.loads((SNAPSHOT / "config.json").read_text(encoding="utf-8"))
        index = json.loads((SNAPSHOT / "model.safetensors.index.json").read_text(encoding="utf-8"))
    except (ValueError, OSError, UnicodeError) as exc:
        raise PilotError("Checkpoint metadata cannot be read.") from exc
    if (config.get("model_type") != "qwen3_5"
            or not isinstance(config.get("text_config"), dict)
            or config["text_config"].get("hidden_size") != 2560):
        raise PilotError("Checkpoint is not the expected Qwen3.5 4B architecture.")
    weight_map = index.get("weight_map")
    if not isinstance(weight_map, dict) or not weight_map:
        raise PilotError("Checkpoint has no weight-map entries.")
    shards = set(weight_map.values())
    if not 1 <= len(shards) <= 8:
        raise PilotError("Unexpected number of checkpoint shards.")
    for shard in shards:
        if not isinstance(shard, str) or not re.fullmatch(r"model\.safetensors(?:-\d{5}-of-\d{5})?\.safetensors", shard):
            raise PilotError("Unexpected checkpoint shard name.")
        file = SNAPSHOT / shard
        if file.is_symlink() or not file.is_file() or file.stat().st_size < 100_000_000:
            raise PilotError("A checkpoint weight shard is missing or incomplete.")
    return SNAPSHOT


def _split() -> tuple[list[dict], list[dict]]:
    def record(pair: tuple[str, str]) -> dict:
        return {"prompt": [{"role": "user", "content": pair[0]}],
                "completion": [{"role": "assistant", "content": pair[1]}]}
    # These holdouts are NOT evaluated automatically by this smoke run.
    return [record(p) for p in EXAMPLES[:16]], [record(p) for p in EXAMPLES[16:]]


def _safe_output() -> Path:
    for path in (OUTPUT_ROOT, OUTPUT_ROOT.parent, OUTPUT_ROOT.parent.parent):
        if path.is_symlink():
            raise PilotError("Unsafe output directory alias.")
    OUTPUT_ROOT.mkdir(parents=True, mode=0o700, exist_ok=True)
    result = OUTPUT_ROOT / ("synthetic_4b_" + uuid.uuid4().hex)
    result.mkdir(mode=0o700, exist_ok=False)
    return result


def check() -> None:
    _local_checkpoint()
    training, heldout = _split()
    print("Pinned Qwen3.5 4B checkpoint: present (metadata and shard sizes checked).")
    print("Synthetic training examples:", len(training), "reserved holdout:", len(heldout))
    print("Python:", sys.version.split()[0])
    for name in ("torch", "unsloth", "transformers", "trl"):
        try:
            version = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            version = "NOT INSTALLED"
        print(name + ": " + version)
    print("Read-only check complete. No model loaded and no training performed.")


def _text_tokenizer(processor):
    """Obtain the actual text tokeniser without assuming processor return types."""
    tokenizer = getattr(processor, "tokenizer", processor)
    if not callable(getattr(tokenizer, "encode", None)):
        raise PilotError("The local Qwen text tokenizer does not implement encode().")
    return tokenizer


def _prepare_tokenized_data(processor, training: list[dict]) -> list[dict]:
    """Build explicit supervised masks with Qwen3.5 non-thinking template.

    Qwen3.5 has distinct unfinished thinking and completed-assistant prefixes.
    Never compare default tokenized apply_chat_template outputs, which may be a
    processor mapping or use non-matching thinking prefixes.
    """
    apply = getattr(processor, "apply_chat_template", None)
    if not callable(apply):
        raise PilotError("The model has no chat-template renderer.")
    tokenizer = _text_tokenizer(processor)
    rows = []
    for sample in training:
        try:
            prompt = apply(sample["prompt"], tokenize=False, add_generation_prompt=True, enable_thinking=False)
            full = apply(
                sample["prompt"] + sample["completion"],
                tokenize=False, add_generation_prompt=False, enable_thinking=False,
            )
            if not isinstance(prompt, str) or not isinstance(full, str):
                raise PilotError("The Qwen chat renderer did not return text.")
            answer = sample["completion"][-1]["content"]
            if not full.startswith(prompt) or answer not in full[len(prompt):]:
                raise PilotError("Qwen completion does not follow the expected non-thinking prompt prefix.")
            prompt_ids = tokenizer.encode(prompt, add_special_tokens=False)
            full_ids = tokenizer.encode(full, add_special_tokens=False)
        except PilotError:
            raise
        except (ValueError, TypeError, KeyError, AttributeError, RuntimeError) as exc:
            raise PilotError("Qwen chat-template encoding failed.") from exc
        if (not isinstance(prompt_ids, list) or not isinstance(full_ids, list)
                or not 0 < len(prompt_ids) < len(full_ids) <= MAX_LENGTH):
            raise PilotError("Training tokens are malformed or exceed the length limit.")
        if full_ids[:len(prompt_ids)] != prompt_ids:
            raise PilotError("Qwen prompt token prefix differs from completed chat tokens.")
        supervised = len(full_ids) - len(prompt_ids)
        if supervised < 3:
            raise PilotError("No meaningful answer tokens remain available for supervised loss.")
        labels = [-100] * len(prompt_ids) + full_ids[len(prompt_ids):]
        if not any(token != -100 for token in labels):
            raise PilotError("Assistant completion loss mask is empty.")
        rows.append({
            "input_ids": full_ids, "attention_mask": [1] * len(full_ids),
            "labels": labels,
        })
    return rows


def _batch_collator(torch, pad_token_id: int):
    """Pad tokenised examples; -100 masks the prompt and padded loss."""
    if not isinstance(pad_token_id, int) or pad_token_id < 0:
        raise PilotError("Missing valid tokenizer padding ID.")
    def collate(features):
        width = max(len(row["input_ids"]) for row in features)
        def pad(items, value):
            return [list(x) + [value] * (width - len(x)) for x in items]
        ids = pad((r["input_ids"] for r in features), pad_token_id)
        masks = pad((r["attention_mask"] for r in features), 0)
        labels = pad((r["labels"] for r in features), -100)
        if not any(v != -100 for row in labels for v in row):
            raise PilotError("Batch contains no supervised assistant tokens.")
        return {
            "input_ids": torch.tensor(ids, dtype=torch.long),
            "attention_mask": torch.tensor(masks, dtype=torch.long),
            "labels": torch.tensor(labels, dtype=torch.long),
        }
    return collate


def tokenizer_check() -> None:
    """CPU-only test using the actual locally downloaded tokenizer and chat template."""
    snapshot = _local_checkpoint()
    os.environ.update({
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1", "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
    })
    try:
        from transformers import AutoTokenizer
        tokenizer = AutoTokenizer.from_pretrained(str(snapshot), local_files_only=True)
        training, heldout = _split()
        rows = _prepare_tokenized_data(tokenizer, training)
    except PilotError:
        raise
    except Exception as exc:
        raise PilotError("Local tokenizer template check did not complete.") from exc
    supervised = sum(sum(v != -100 for v in row["labels"]) for row in rows)
    print("Qwen3.5 4B real local tokenizer: validated without GPU model loading.")
    print("Training prompts:", len(training), "held-out examples:", len(heldout),
          "supervised answer tokens:", supervised)
    print("No training, model updates or downloads performed.")


def train(*, compatibility_no_compile: bool = False) -> dict:
    snapshot = _local_checkpoint()
    training, heldout = _split()
    if len(training) < 10 or len(heldout) < 2:
        raise PilotError("Synthetic training split is not valid.")
    # Set all network/telemetry safeguards BEFORE model-library imports.
    # Official Unsloth support flag: disable the auto-compiler when explicitly requested.
    if compatibility_no_compile:
        os.environ["UNSLOTH_COMPILE_DISABLE"] = "1"
        print("Compatibility mode: Unsloth auto-compiler disabled for this one process.")
    os.environ.update({
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1", "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
        "WANDB_DISABLED": "true", "WANDB_MODE": "disabled",
        "TOKENIZERS_PARALLELISM": "false",
    })
    try:
        from unsloth import FastLanguageModel  # patch before torch/trl imports
        import torch
        from datasets import Dataset
        from transformers import Trainer, TrainingArguments
    except (ImportError, RuntimeError) as exc:
        raise PilotError("CUDA training libraries failed to load; the live model is unchanged.") from exc
    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise PilotError("CUDA BF16 is unavailable. No model training started.")
    free, total = torch.cuda.mem_get_info(0)
    free_gib = free / (1024**3)
    print(f"GPU memory available before loading: {free_gib:.2f} GiB (total {total / (1024**3):.2f} GiB).")
    if free_gib < MIN_FREE_GIB:
        raise PilotError("Less than 10 GiB of GPU memory is free. Stop other GPU work and retry later.")

    print("Stage 1/4: Loading the pinned 4B base model into the local training process.")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=str(snapshot), max_seq_length=MAX_LENGTH,
        load_in_4bit=False, load_in_16bit=True, full_finetuning=False,
    )
    print("Stage 2/4: Preparing Qwen3.5 non-thinking tokens and completion-only loss masks.")
    rows = _prepare_tokenized_data(tokenizer, training)
    masked_tokens = sum(sum(value != -100 for value in row["labels"]) for row in rows)
    print("Validated supervised answer tokens:", masked_tokens, "across", len(rows), "fictional examples.")

    print("Stage 3/4: Attaching a separate LoRA adapter.")
    model = FastLanguageModel.get_peft_model(
        model, r=16,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        lora_alpha=16, lora_dropout=0, bias="none",
        use_gradient_checkpointing="unsloth", random_state=3407,
        max_seq_length=MAX_LENGTH,
    )
    # Prove at least one *trainable* LoRA-B parameter actually changed.
    sampled = []
    for name, parameter in model.named_parameters():
        if parameter.requires_grad and "lora_B" in name and parameter.numel():
            sampled.append((parameter, parameter.detach().float().cpu().clone()))
            if len(sampled) == 8:
                break
    if not sampled:
        raise PilotError("No trainable LoRA-B adapter parameters found.")

    out = _safe_output()
    text_tokenizer = _text_tokenizer(tokenizer)
    pad_id = getattr(text_tokenizer, "pad_token_id", None)
    collate = _batch_collator(torch, pad_id)
    # Use explicit token-level labels rather than TRL's conversational prefix
    # inference, which is known to mismatch Qwen3.5 thinking-mode templates.
    trainer = Trainer(
        model=model,
        train_dataset=Dataset.from_list(rows),
        data_collator=collate,
        args=TrainingArguments(
            output_dir=str(out / "trainer_temp"),
            remove_unused_columns=False,
            per_device_train_batch_size=1, gradient_accumulation_steps=2,
            max_steps=STEPS, warmup_steps=0, learning_rate=2e-4,
            bf16=True, optim="adamw_8bit", seed=3407,
            logging_steps=1, save_strategy="no", report_to="none",
            dataloader_num_workers=0,
        ),
    )
    print("Stage 4/4: Running two GPU optimiser updates on fictional examples.")
    summary = trainer.train()
    loss = float(getattr(summary, "training_loss", float("nan")))
    if not math.isfinite(loss):
        raise PilotError("Training loss was not finite; adapter not promoted.")
    changed = sum(bool(torch.any(p.detach().float().cpu() != old).item()) for p, old in sampled)
    if changed == 0:
        raise PilotError("No sampled LoRA-B weights changed; training was not demonstrated.")

    dest = out / "adapter"
    model.save_pretrained(str(dest))
    tokenizer.save_pretrained(str(dest))
    adapter_files = {p.name: _sha(p.read_bytes()) for p in sorted(dest.iterdir())
                     if p.is_file() and not p.is_symlink()}
    if "adapter_config.json" not in adapter_files or not any(
            key.endswith(".safetensors") for key in adapter_files):
        raise PilotError("Trained LoRA adapter files were not saved correctly.")
    record = {
        "kind": "synthetic_smoke_training_only",
        "model": MODEL_ID, "revision": REVISION,
        "steps_requested": STEPS, "training_loss": loss,
        "train_examples": len(training), "reserved_holdout_examples": len(heldout),
        "training_data_sha256": _sha(json.dumps(training, sort_keys=True).encode("utf-8")),
        "adapter_files_sha256": adapter_files, "sampled_lora_b_tensors_changed": changed,
        "training_executed": True, "independent_quality_verified": False,
        "deployed": False, "xemai_9b_modified": False,
    }
    (out / "smoke_manifest.json").write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
    print("SYNTHETIC 4B ADAPTER TRAINING COMPLETED (NOT DEPLOYED).")
    print("LoRA-B parameter tensors changed:", changed, "training loss:", round(loss, 5))
    print("Adapter and manifest saved locally:", out)
    print("This does NOT prove improved conversational quality or change XemAi's 9B model.")
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true", help="Inspect local checkpoint without training.")
    modes.add_argument("--tokenizer-check", action="store_true", help="CPU-only live-tokenizer validation; no GPU model load.")
    modes.add_argument("--train", action="store_true", help="Train exactly two gradient-update steps on synthetic data.")
    parser.add_argument("--compat-no-compile", action="store_true",
                        help="Owner-selected diagnostic workaround: disable Unsloth compilation for this one run.")
    parser.add_argument("--confirm", default="", help="Required explicit consent phrase for --train.")
    args = parser.parse_args(argv)
    try:
        if args.check:
            check()
        elif args.tokenizer_check:
            tokenizer_check()
        elif args.confirm != CONFIRMATION:
            raise PilotError("Training was not authorised. Explicit confirmation is required.")
        else:
            train(compatibility_no_compile=args.compat_no_compile)
        return 0
    except PilotError as exc:
        print("PILOT STOPPED SAFELY:", str(exc))
        return 2
    except Exception as exc:
        # Preserve privacy by printing only sanitised error details / module basenames,
        # not the full library traceback with machine-specific absolute paths.
        from training.failure_diagnostics import print_diagnostics
        print("PILOT STOPPED:", type(exc).__name__, "(no existing XemAi model was modified).")
        print_diagnostics(exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
