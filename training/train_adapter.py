"""Explicit, offline-only BF16 LoRA experiment on a reviewed Qwen3.5 dataset.

Not integrated into XemAi chat, bridges, updater or Ollama. No automatic
downloads, model switch, merged weights or upload. A GPU experiment requires
an owner's new manual command and environment setup. Untested GPU path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import uuid
from pathlib import Path

from training.prepare_dataset import DatasetRejected, _private_output, _safe_path, verify

_MODELS = {"Qwen/Qwen3.5-4B": 12.0, "Qwen/Qwen3.5-9B": 24.0}
_HIDDEN_SIZE = {"Qwen/Qwen3.5-4B": 2560, "Qwen/Qwen3.5-9B": 4096}
_CONFIRMATION = "TRAIN REVIEWED LOCAL ADAPTER"
_REPO = Path(__file__).resolve().parent.parent


def plan(run: Path, model_id: str, revision: str, max_steps: int, sequence: int) -> dict:
    meta = verify(run)
    if model_id not in _MODELS:
        raise DatasetRejected("Model must be an explicitly allowlisted Qwen3.5 checkpoint.")
    if not re.fullmatch("[a-f0-9]{40}", revision):
        raise DatasetRejected("Exact 40-character upstream model revision is required.")
    if not 1 <= max_steps <= 200 or not 128 <= sequence <= 2048:
        raise DatasetRejected("Out-of-bounds training resource budget.")
    if meta["train_count"] < 8 or meta["heldout_count"] < 2:
        raise DatasetRejected("Not enough separated training and holdout examples.")
    return {
        "target": model_id, "revision": revision, "training_records": meta["train_count"],
        "reserved_holdout_records": meta["heldout_count"],
        "steps": max_steps, "max_sequence_length": sequence,
        "requires_vram_gb": _MODELS[model_id],
        "training_applied": False, "automatic_deployment": False,
    }


def _checkpoint(path: Path, revision: str, model_id: str) -> Path:
    path = _safe_path(path)
    if not path.is_dir() or path.name != revision:
        raise DatasetRejected("Expected an explicitly downloaded local checkpoint snapshot pinned to revision.")
    config_path = path / "config.json"
    tokenizer_path = path / "tokenizer_config.json"
    if not config_path.is_file() or not tokenizer_path.is_file():
        raise DatasetRejected("Incomplete local Qwen checkpoint.")
    if config_path.stat().st_size > 100_000 or tokenizer_path.stat().st_size > 2_000_000:
        raise DatasetRejected("Unexpected model configuration file size.")
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        tokenizer = json.loads(tokenizer_path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError, OSError) as exc:
        raise DatasetRejected("Invalid local checkpoint metadata.") from exc
    if (not isinstance(config, dict) or not isinstance(tokenizer, dict)
            or config.get("model_type") != "qwen3_5"
            or config.get("text_config", {}).get("hidden_size") != _HIDDEN_SIZE[model_id]):
        raise DatasetRejected("Local checkpoint architecture does not match the selected Qwen model.")
    # Filename and metadata are sanity checks, not cryptographic proof of upstream contents.
    # The owner must verify the full snapshot/revision from a trusted download separately.
    return path


def train(
    run: Path, *, model_id: str, revision: str, checkpoint_dir: Path,
    output_dir: Path, max_steps: int, sequence: int,
) -> Path:
    """One manually invoked local training run; never touches the active XemAi model."""
    parameters = plan(run, model_id, revision, max_steps, sequence)
    snapshot = _checkpoint(checkpoint_dir, revision, model_id)
    root = _private_output(output_dir)
    if root == _safe_path(run) or root in _safe_path(run).parents:
        raise DatasetRejected("Adapters and source dataset must use separate locations.")
    if root == snapshot or root in snapshot.parents:
        raise DatasetRejected("Never overwrite the original checkpoint.")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["WANDB_MODE"] = "disabled"
    os.environ["WANDB_DISABLED"] = "true"
    # Dependencies are optional and only imported after all safe preflight checks.
    try:
        from unsloth import FastLanguageModel  # Import first so GPU kernels are patched.
        import torch
        from datasets import Dataset
        from trl import SFTConfig, SFTTrainer
    except ImportError as exc:
        raise DatasetRejected("Missing optional training dependencies; use a separate GPU environment.") from exc
    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise DatasetRejected("CUDA BF16 GPU unavailable; CPU-only training is not permitted by this experimental runner.")
    props = torch.cuda.get_device_properties(0)
    vram = props.total_memory / (1024 ** 3)
    if vram < _MODELS[model_id]:
        raise DatasetRejected("Insufficient reported VRAM for the selected BF16 LoRA model.")
    free_vram = torch.cuda.mem_get_info(0)[0] / (1024 ** 3)
    required_free = 10.0 if model_id.endswith("-4B") else 22.0
    if free_vram < required_free:
        raise DatasetRejected("Too little free GPU memory; stop other workloads manually before training.")
    # Never import the held-out file into the training loop.
    with (_safe_path(run / "train.jsonl", file=True)).open(encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream]
    samples = [
        {"prompt": row["messages"][:-1], "completion": [row["messages"][-1]]}
        for row in rows
    ]
    if len(samples) != parameters["training_records"]:
        raise DatasetRejected("Training dataset count changed.")
    # Verify the real model's chat template can encode both prompt and answer
    # without truncating the supervised answer. Fail before creating output.
    apply_template = getattr(tokenizer, "apply_chat_template", None)
    if not callable(apply_template):
        raise DatasetRejected("Missing matching chat template for the base model.")
    for sample in samples:
        try:
            prompt_tokens = apply_template(sample["prompt"], tokenize=True, add_generation_prompt=True)
            full_tokens = apply_template(
                sample["prompt"] + sample["completion"], tokenize=True, add_generation_prompt=False
            )
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise DatasetRejected("Chat template cannot process the reviewed training format.") from exc
        if (not isinstance(prompt_tokens, list) or not isinstance(full_tokens, list)
                or not 1 <= len(prompt_tokens) < len(full_tokens) <= sequence):
            raise DatasetRejected("Training example would truncate the assistant answer or has no output tokens.")
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    result = root / ("adapter_" + uuid.uuid4().hex)
    result.mkdir(mode=0o700, exist_ok=False)
    if os.name != "nt":
        result.chmod(0o700)
    # Unsloth Qwen3.5 BF16 LoRA recipe: do not use QLoRA 4-bit.
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=str(snapshot), max_seq_length=sequence,
        load_in_4bit=False, load_in_16bit=True, full_finetuning=False,
    )
    model = FastLanguageModel.get_peft_model(
        model, r=16,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
        lora_alpha=16, lora_dropout=0, bias="none",
        use_gradient_checkpointing="unsloth", random_state=3407,
        max_seq_length=sequence,
    )
    # Conversational prompt/completion trains on the *reviewed corrected answer*
    # rather than treating wrong model responses or an external 0-10 score as truth.
    trainer = SFTTrainer(
        model=model,
        processing_class=tokenizer,
        train_dataset=Dataset.from_list(samples),
        args=SFTConfig(
            output_dir=str(result / "checkpoints"),
            max_length=sequence,
            completion_only_loss=True,
            packing=False,
            per_device_train_batch_size=1,
            gradient_accumulation_steps=4,
            max_steps=max_steps,
            logging_steps=10,
            save_strategy="no",
            report_to="none",
            optim="adamw_8bit",
            seed=3407,
            dataloader_num_workers=0,
        ),
    )
    trainer.train()
    adapter = result / "adapter"
    model.save_pretrained(str(adapter))
    tokenizer.save_pretrained(str(adapter))
    file_hashes = {}
    for file in sorted(adapter.iterdir()):
        if file.is_file() and not file.is_symlink():
            file_hashes[file.name] = hashlib.sha256(file.read_bytes()).hexdigest()
    if not file_hashes or not (adapter / "adapter_config.json").is_file():
        raise DatasetRejected("Adapter save failed; no model deployment attempted.")
    record = {
        **parameters, "training_applied": True, "adapter_files_sha256": file_hashes,
        "training_source_sha256": hashlib.sha256((_safe_path(run / "train.jsonl", file=True)).read_bytes()).hexdigest(),
        "runtime": "experimental_unverified_in_xemai", "deployment": "NONE",
        "heldout_used_for_training": False, "blind_quality_evaluation_completed": False,
    }
    record_path = result / "adapter_manifest.json"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(record_path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(record, stream, indent=2, sort_keys=True)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True, help="Exact prepared local dataset run directory.")
    parser.add_argument("--model", required=True, choices=tuple(_MODELS))
    parser.add_argument("--revision", required=True, help="Exact 40-hex upstream HuggingFace commit SHA.")
    parser.add_argument("--max-steps", type=int, default=10)
    parser.add_argument("--sequence", type=int, default=512)
    parser.add_argument("--checkpoint-dir", type=Path, help="Already-downloaded OFFLINE base snapshot (no downloading).")
    parser.add_argument("--output-dir", type=Path, default=_REPO / "data" / "weight_training" / "adapters")
    parser.add_argument("--execute", action="store_true", help="Run real adapter training, never used by default.")
    parser.add_argument("--confirm", help="Exact additional owner approval string for one training run.")
    args = parser.parse_args(argv)
    try:
        parameters = plan(args.run, args.model, args.revision, args.max_steps, args.sequence)
        if not args.execute:
            print("DRY RUN ONLY; no model loaded, downloaded or changed.")
            print("Model:", parameters["target"], "minimum GPU VRAM:", parameters["requires_vram_gb"], "GiB")
            print("Reviewed training rows:", parameters["training_records"], "reserved holdout:", parameters["reserved_holdout_records"])
            return 0
        if args.confirm != _CONFIRMATION or args.checkpoint_dir is None:
            raise DatasetRejected("Real training requires an explicit offline checkpoint and exact owner confirmation.")
        location = train(
            args.run, model_id=args.model, revision=args.revision,
            checkpoint_dir=args.checkpoint_dir, output_dir=args.output_dir,
            max_steps=args.max_steps, sequence=args.sequence,
        )
        print("Standalone local adapter saved (NOT DEPLOYED).")
        print("Location:", location)
        print("Quality not yet evaluated; original Qwen model unchanged.")
        return 0
    except (DatasetRejected, OSError, UnicodeError, ValueError) as exc:
        print("Training did not complete:", exc.__class__.__name__)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
