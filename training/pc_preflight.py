"""Read-only Qwen training feasibility report for the owner's own PC.

No model loads, imports of torch/unsloth, downloads, account access, private
datasets, logs, changes to settings, or identifiers such as hostnames/UUIDs.
"""
from __future__ import annotations

import importlib.metadata
import json
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

GPU_MINIMUM = {"Qwen3.5-4B": (12.0, 10.0), "Qwen3.5-9B": (24.0, 22.0)}
_NAME = re.compile(r"^[A-Za-z0-9 .()+/_-]{1,90}$")
_DEPENDENCIES = ("torch", "transformers", "trl", "unsloth", "unsloth_zoo", "datasets", "peft")


def _gpus() -> list[dict]:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.free",
             "--format=csv,noheader,nounits"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            check=False, text=True, timeout=8,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0 or len(result.stdout) > 2048:
        return []
    found = []
    for line in result.stdout.splitlines()[:4]:
        fields = [part.strip() for part in line.split(",")]
        if len(fields) != 3 or not _NAME.fullmatch(fields[0]):
            continue
        try:
            total, free = (int(fields[1]), int(fields[2]))
        except ValueError:
            continue
        if not (0 <= free <= total <= 2_000_000):
            continue
        found.append({"model": fields[0],
                      "total_gib": round(total / 1024, 2),
                      "free_gib": round(free / 1024, 2)})
    return found


def snapshot() -> dict:
    gpu = _gpus()
    versions = {}
    for name in _DEPENDENCIES:
        try:
            value = importlib.metadata.version(name)
            versions[name] = value if re.fullmatch(r"[A-Za-z0-9.+_-]{1,50}", value) else "unknown"
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "not_installed"
    os_name = "windows" if sys.platform == "win32" else (
        "linux" if sys.platform.startswith("linux") else "other"
    )
    # Do not show personal folders, usernames, hostnames, network addresses, or mount names.
    try:
        free_gib = round(shutil.disk_usage(Path.cwd()).free / 1024**3, 1)
    except OSError:
        free_gib = None
    estimates = {}
    for target, (required_total, required_free) in GPU_MINIMUM.items():
        fits = any(g["total_gib"] >= required_total and g["free_gib"] >= required_free for g in gpu)
        estimates[target] = {
            "supported_bf16_lora_memory_estimate": "possible" if fits else "insufficient_or_unknown",
            "minimum_total_gib": required_total,
            "minimum_free_gib": required_free,
        }
    return {
        "read_only": True, "training_started": False, "model_changed": False,
        "operating_system": os_name,
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "architecture": platform.machine() if platform.machine() in {"AMD64", "x86_64", "aarch64", "ARM64"} else "other",
        "gpus": gpu, "disk_free_gib_at_working_directory": free_gib,
        "packages": versions, "bf16_lora_memory_estimates_only": estimates,
        "note": "Feasibility estimates only; BF16 CUDA, drivers, model load, training and offload are NOT validated.",
    }


def main() -> int:
    print(json.dumps(snapshot(), sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
