"""Read-only, no-network feasibility report for Qwen3.5 9B adapter training.

No imports of torch, Unsloth, bitsandbytes, Ollama, Hugging Face clients, or
training modules. No GPU allocation, network calls, file edits or private data.
The 9B inference model currently used by Ollama is NOT an HF training checkpoint.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import re
import shutil
import subprocess
from pathlib import Path

_SAFE_GPU = re.compile(r"^[A-Za-z0-9 .()+/_-]{1,90}$")


def snapshot() -> dict:
    """Gather only bounded, non-identifying local resource totals."""
    cards = []
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.free",
             "--format=csv,noheader,nounits"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=8, check=False, text=True,
        )
        if proc.returncode == 0 and len(proc.stdout) <= 2048:
            for line in proc.stdout.splitlines()[:4]:
                fields = [chunk.strip() for chunk in line.split(",")]
                if len(fields) != 3 or not _SAFE_GPU.fullmatch(fields[0]):
                    continue
                try:
                    total, free = int(fields[1]), int(fields[2])
                except ValueError:
                    continue
                if 0 <= free <= total <= 2_000_000:
                    cards.append({"total_gib": round(total / 1024, 2),
                                  "free_gib": round(free / 1024, 2)})
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        disk = round(shutil.disk_usage(Path.cwd()).free / 1024**3, 1)
    except OSError:
        disk = None
    return {"gpus": cards, "disk_free_gib_at_working_directory": disk}



BF16_LORA_GIB = 22.0  # Published Unsloth Qwen3.5 9B approximation.
BASE_SAFETENSORS_BYTES = 19_306_216_416  # Official HF 9B shard index total_size.
RECOMMENDED_FREE_DISK_GIB = 30.0
RECOMMENDED_8BIT_FREE_GIB = 13.5  # Heuristic for considering only; NOT a fit guarantee.


def assess(info: dict, *, deps: dict | None = None) -> dict:
    """Produce an advisory plan, not a training authorization or capability claim."""
    deps = {} if deps is None else dict(deps)
    cards = info.get("gpus") or []
    usable = [gpu for gpu in cards
              if isinstance(gpu, dict) and isinstance(gpu.get("total_gib"), (int, float))
              and isinstance(gpu.get("free_gib"), (int, float))
              and gpu["total_gib"] >= 0 and 0 <= gpu["free_gib"] <= gpu["total_gib"]]
    best = max(usable, key=lambda card: card["free_gib"], default=None)
    vram = best["total_gib"] if best else 0
    free = best["free_gib"] if best else 0
    disk = info.get("disk_free_gib_at_working_directory")
    disk_ok = isinstance(disk, (int, float)) and disk >= RECOMMENDED_FREE_DISK_GIB
    gpu_ok = vram >= BF16_LORA_GIB and free >= BF16_LORA_GIB
    evidence_8bit = {
        "gpu_detected": bool(best),
        "at_least_13_5_gib_currently_free": free >= RECOMMENDED_8BIT_FREE_GIB,
        "bitsandbytes_installed": deps.get("bitsandbytes") not in (None, "not_installed"),
        "accelerate_installed": deps.get("accelerate") not in (None, "not_installed"),
        "sufficient_disk_for_separate_9b_source": disk_ok,
    }
    return {
        "read_only": True,
        "training_started": False,
        "downloads_started": False,
        "live_ollama_modified": False,
        "model": "Qwen3.5-9B",
        "gpu_total_gib": vram if best else None,
        "gpu_free_gib": free if best else None,
        "disk_free_gib": disk,
        "official_source_weights_gb": round(BASE_SAFETENSORS_BYTES / 1e9, 2),
        "recommended_free_disk_gib_before_source_download": RECOMMENDED_FREE_DISK_GIB,
        "published_bf16_lora_vram_estimate_gib": BF16_LORA_GIB,
        "bf16_single_gpu_capacity": "meets_published_vram_estimate_only" if gpu_ok else "does_not_meet_published_vram_estimate",
        "eight_bit_lora": "experimental_unverified_not_ready_to_train",
        "eight_bit_indicators": evidence_8bit,
        "four_bit_qlora": "not_recommended_for_qwen3_5_by_unsloth",
        "cpu_offload": "not_yet_validated_for_9b_training_on_this_windows_install",
        "existing_ollama_quantized_model_trainable_as_hf_base": False,
        "next_step": "Review feasibility before any separate owner-approved 9B source download, model load or training experiment.",
    }


def report(value: dict, *, print_fn=print) -> None:
    print_fn("XemAi Qwen3.5 9B LOCAL FEASIBILITY REPORT — READ ONLY")
    gpu = value["gpu_total_gib"]
    if gpu is None:
        print_fn("NVIDIA GPU: not detected by nvidia-smi")
    else:
        print_fn(f"NVIDIA GPU memory: {gpu:.2f} GiB total; {value['gpu_free_gib']:.2f} GiB free")
    disk = value["disk_free_gib"]
    print_fn(f"Training-folder disk space: {disk:.1f} GiB free" if disk is not None else
             "Training-folder disk space: unavailable")
    print_fn(f"Official 9B BF16 source shards: approximately {value['official_source_weights_gb']:.2f} GB")
    print_fn("9B BF16 LoRA reference: approximately 22 GiB VRAM required.")
    if value["bf16_single_gpu_capacity"] == "does_not_meet_published_vram_estimate":
        print_fn("BF16 LoRA: NOT a suitable direct single-GPU 16 GB training route.")
    else:
        print_fn("BF16 LoRA: VRAM estimate met, but training and compatibility NOT validated.")
    print_fn("8-bit LoRA: an EXPERIMENTAL possibility; no compatibility or VRAM fit proven.")
    if not value["eight_bit_indicators"]["bitsandbytes_installed"]:
        print_fn("bitsandbytes: absent/unknown in local Python environment (no installation performed).")
    if not value["eight_bit_indicators"]["accelerate_installed"]:
        print_fn("accelerate: absent/unknown in local Python environment (no installation performed).")
    if not value["eight_bit_indicators"]["at_least_13_5_gib_currently_free"]:
        print_fn("8-bit pilot resource indicator: below conservative free-VRAM precheck.")
    if not value["eight_bit_indicators"]["sufficient_disk_for_separate_9b_source"]:
        print_fn("9B public checkpoint: less than recommended 30 GiB free disk space or cannot determine.")
    print_fn("4-bit QLoRA: currently discouraged for Qwen3.5; no silent fallback.")
    print_fn("CPU offload: not validated on this PC; no training implied.")
    print_fn("Ollama 9B inference file is NOT the official BF16 training checkpoint.")
    print_fn("Result: plan/research stage only. No network, download, training, or changes made.")
    print_fn("Official guidance: https://unsloth.ai/docs/models/qwen3.5/fine-tune")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="Print only the non-destructive 9B feasibility report.")
    args = parser.parse_args(argv)
    if not args.check:
        parser.print_help()
        return 0
    info = snapshot()
    deps = {}
    for dep in ("bitsandbytes", "accelerate"):
        try:
            deps[dep] = importlib.metadata.version(dep)
        except importlib.metadata.PackageNotFoundError:
            deps[dep] = "not_installed"
    result = assess(info, deps=deps)
    report(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
