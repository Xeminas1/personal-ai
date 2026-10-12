"""Owner-triggered, offline, read-only Qwen3.5 4B holdout comparison.

Compare the unchanged base Qwen3.5 4B and a successfully saved 4B LoRA adapter
on the same four *fictional held-out* examples, token-for-token. This is a tiny
regression signal, NOT a conversational quality or intelligence benchmark.

Does not train, change adapter weights, deploy, upload or read personal messages.
"""
from __future__ import annotations

import argparse
from contextlib import nullcontext
import hashlib
import json
import math
import os
from pathlib import Path

from training import synthetic_smoke as pilot

CONFIRM = "EVALUATE SYNTHETIC 4B"
EXPECTED_REVISION = pilot.REVISION
EXPECTED_MODEL = pilot.MODEL_ID


class EvaluationError(Exception):
    """Known local evaluation error with no sensitive path detail."""


def _sha_file(file: Path) -> str:
    result = hashlib.sha256()
    with file.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def _manifest_runs() -> list[Path]:
    if pilot.OUTPUT_ROOT.is_symlink():
        raise EvaluationError("The local pilot output directory is an unsafe symlink.")
    if not pilot.OUTPUT_ROOT.is_dir():
        return []
    runs = []
    for path in sorted(pilot.OUTPUT_ROOT.iterdir()):
        if (path.is_dir() and not path.is_symlink()
                and path.name.startswith("synthetic_4b_")
                and (path / "smoke_manifest.json").is_file()
                and not (path / "smoke_manifest.json").is_symlink()):
            runs.append(path)
    return runs


def _select_run(run_id: str | None) -> Path:
    candidates = _manifest_runs()
    if run_id:
        if (not run_id.startswith("synthetic_4b_")
                or len(run_id) > 100
                or not all(ch.isascii() and (ch.isalnum() or ch == "_") for ch in run_id)):
            raise EvaluationError("Invalid local pilot run identifier.")
        candidates = [r for r in candidates if r.name == run_id]
    if not candidates:
        raise EvaluationError("No successful-looking synthetic pilot run was found.")
    if len(candidates) != 1:
        raise EvaluationError("Several saved runs were found; select one with --run-id.")
    return candidates[0]


def _verify_run(path: Path) -> dict:
    if path.is_symlink() or path.parent.resolve() != pilot.OUTPUT_ROOT.resolve():
        raise EvaluationError("The selected run is not inside the isolated pilot directory.")
    metadata = path / "smoke_manifest.json"
    if metadata.is_symlink() or not metadata.is_file() or metadata.stat().st_size > 80_000:
        raise EvaluationError("Local pilot manifest is missing or untrusted.")
    try:
        record = json.loads(metadata.read_text(encoding="utf-8"))
    except (ValueError, OSError, UnicodeError) as exc:
        raise EvaluationError("Local pilot manifest is invalid.") from exc
    if (not isinstance(record, dict) or record.get("model") != EXPECTED_MODEL
            or record.get("revision") != EXPECTED_REVISION
            or record.get("training_executed") is not True
            or record.get("deployed") is not False
            or record.get("train_examples") != 16
            or record.get("reserved_holdout_examples") != 4
            or not isinstance(record.get("sampled_lora_b_tensors_changed"), int)
            or record["sampled_lora_b_tensors_changed"] < 1):
        raise EvaluationError("The run does not document a completed isolated synthetic adapter.")
    expected_hashes = record.get("adapter_files_sha256")
    if not isinstance(expected_hashes, dict) or "adapter_config.json" not in expected_hashes:
        raise EvaluationError("No verifiable adapter metadata was recorded.")
    if not any(k.endswith(".safetensors") for k in expected_hashes):
        raise EvaluationError("No adapter weight file was recorded.")
    folder = path / "adapter"
    if folder.is_symlink() or not folder.is_dir():
        raise EvaluationError("Saved adapter folder is missing.")
    if not expected_hashes or len(expected_hashes) > 30:
        raise EvaluationError("Unexpected saved adapter file count.")
    for filename, sha in expected_hashes.items():
        if (not isinstance(filename, str)
                or filename in (".", "..")
                or "/" in filename or "\\" in filename
                or not filename.isascii()
                or not isinstance(sha, str) or len(sha) != 64
                or any(c not in "0123456789abcdef" for c in sha)):
            raise EvaluationError("Unexpected adapter filename or checksum.")
        file = folder / filename
        if file.is_symlink() or not file.is_file() or _sha_file(file) != sha:
            raise EvaluationError("Saved adapter file checksum does not match the training manifest.")
    return record


def check(run_id: str | None) -> Path:
    pilot._local_checkpoint()  # required official pinned 4B BF16 checkpoint
    selection = _select_run(run_id)
    record = _verify_run(selection)
    train, holdout = pilot._split()
    expected_sha = hashlib.sha256(json.dumps(train, sort_keys=True).encode("utf-8")).hexdigest()
    if record.get("training_data_sha256") != expected_sha:
        raise EvaluationError("Pilot training sample fingerprint mismatch.")
    if len(holdout) != 4:
        raise EvaluationError("Reserved holdout count changed.")
    print("Verified Qwen3.5 4B base checkpoint and unmodified adapter manifest.")
    print("Training examples:", len(train), "| Synthetic held-out examples:", len(holdout))
    print("Adapter tensors previously verified changed:", record["sampled_lora_b_tensors_changed"])
    print("Selected run:", selection.name)
    print("Read-only check passed. No GPU model loaded; no evaluation or training performed.")
    return selection


def _score_samples(model, torch, items: list[dict]) -> dict:
    """Mean held-out answer-token negative log-likelihood; same exact tokens."""
    losses = []
    n_tokens = 0
    for item in items:
        n_this = sum(value != -100 for value in item["labels"][1:])
        if n_this <= 0:
            raise EvaluationError("A reserved example has no supervised answer tokens.")
        sample = {
            key: torch.tensor([item[key]], dtype=torch.long, device="cuda:0")
            for key in ("input_ids", "attention_mask", "labels")
        }
        out = model(**sample)
        val = float(out.loss.detach().float().cpu().item())
        if not math.isfinite(val):
            raise EvaluationError("A non-finite holdout loss was observed.")
        losses.append(val * n_this)
        n_tokens += n_this
    if n_tokens <= 0:
        raise EvaluationError("Zero supervised held-out tokens.")
    return {"heldout_tokens": n_tokens, "mean_answer_nll": sum(losses) / n_tokens}


def evaluate(run_id: str | None) -> dict:
    selection = check(run_id)
    os.environ.update({
        "UNSLOTH_COMPILE_DISABLE": "1",
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1", "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
        "WANDB_DISABLED": "true", "WANDB_MODE": "disabled",
        "TOKENIZERS_PARALLELISM": "false",
    })
    try:
        from unsloth import FastLanguageModel
        import torch
        from peft import PeftModel
    except (ImportError, RuntimeError) as exc:
        raise EvaluationError("Local model-evaluation libraries could not be loaded.") from exc
    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise EvaluationError("CUDA BF16 is required for the local 4B evaluation.")
    free, total = torch.cuda.mem_get_info(0)
    if free < 10 * 1024**3:
        raise EvaluationError("Less than 10 GiB available GPU memory: close other GPU tasks first.")
    print("Loading original pinned Qwen3.5 4B base model, offline and read-only.")
    base, tokenizer = FastLanguageModel.from_pretrained(
        model_name=str(pilot.SNAPSHOT), max_seq_length=pilot.MAX_LENGTH,
        load_in_4bit=False, load_in_16bit=True, full_finetuning=False,
    )
    _, holdout = pilot._split()
    tokens = pilot._prepare_tokenized_data(tokenizer, holdout)
    print("Valid holdout examples:", len(tokens), "on the same base checkpoint.")
    model = PeftModel.from_pretrained(base, str(selection / "adapter"), is_trainable=False)
    if not callable(getattr(model, "disable_adapter", None)):
        raise EvaluationError("Local PEFT adapter cannot be disabled for fair base comparison.")
    model.eval()
    with torch.no_grad():
        print("Computing original 4B base answer loss (adapter disabled).")
        with model.disable_adapter():
            base_result = _score_samples(model, torch, tokens)
        print("Computing trained 4B adapter answer loss (same samples, adapter enabled).")
        adapted_result = _score_samples(model, torch, tokens)
    if base_result["heldout_tokens"] != adapted_result["heldout_tokens"]:
        raise EvaluationError("Base and adapted sample token counts differed.")
    delta = adapted_result["mean_answer_nll"] - base_result["mean_answer_nll"]
    print("HOLDOUT RESULT (FOUR FICTIONAL EXAMPLES ONLY)")
    print(f"Base mean answer NLL: {base_result['mean_answer_nll']:.6f}")
    print(f"Adapter mean answer NLL: {adapted_result['mean_answer_nll']:.6f}")
    print(f"Adapter minus base (lower is better): {delta:+.6f}")
    print("Held-out supervised answer tokens:", base_result["heldout_tokens"])
    print("No gradient updates, saved data changes, Ollama updates or uploads.")
    print("Tiny synthetic holdout loss alone does NOT establish conversation quality or intelligence.")
    return {"base": base_result, "adapted": adapted_result, "delta": delta}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true", help="Verify saved run hashes without GPU loading.")
    modes.add_argument("--evaluate", action="store_true", help="Read-only heldout base-versus-adapter comparison.")
    parser.add_argument("--run-id", help="Optional explicit synthetic_4b_... run directory name.")
    parser.add_argument("--confirm", default="", help="Exact required owner acknowledgement.")
    args = parser.parse_args(argv)
    try:
        if args.check:
            check(args.run_id)
        elif args.confirm != CONFIRM:
            raise EvaluationError("Evaluation not authorised; specify owner confirmation.")
        else:
            evaluate(args.run_id)
        return 0
    except EvaluationError as exc:
        print("EVALUATION STOPPED:", str(exc))
        return 2
    except Exception as exc:
        from training.failure_diagnostics import print_diagnostics
        print("EVALUATION STOPPED:", type(exc).__name__, "(no model weights changed).")
        print_diagnostics(exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
