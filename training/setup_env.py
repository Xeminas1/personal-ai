"""One-time creation of XemAi's separate weight-training environment.

Started by the owner's 'weights setup' command on the GPU PC. Creates
data/weight_training/venv with PyTorch (CUDA 12.8 build, needed for RTX 50-series
GPUs), transformers, peft and bitsandbytes. The XemAi app's own Python install is
never modified. Progress goes to data/weight_training/setup_status.json.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

TORCH_INDEX = "https://download.pytorch.org/whl/cu128"
PACKAGES = [
    "transformers>=5.0", "peft>=0.15", "accelerate>=1.0", "bitsandbytes>=0.45",
    "safetensors", "huggingface_hub>=0.30", "tokenizers",
]


def write(status_path: Path, stage: str, message: str) -> None:
    tmp = status_path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"stage": stage, "message": message, "updated": time.time(),
                               "pid": os.getpid()}), encoding="utf-8")
    os.replace(tmp, status_path)
    print(f"[{stage}] {message}", flush=True)


def run(cmd: list[str]) -> None:
    print("$", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--cpu", action="store_true", help="CPU-only torch (testing)")
    args = parser.parse_args(argv)
    root = Path(args.data_dir) / "weight_training"
    root.mkdir(parents=True, exist_ok=True)
    status = root / "setup_status.json"
    venv = root / "venv"
    python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    try:
        write(status, "installing", "Creating the training environment")
        if not python.is_file():
            run([sys.executable, "-m", "venv", str(venv)])
        run([str(python), "-m", "pip", "install", "--upgrade", "pip"])
        write(status, "installing", "Installing PyTorch with GPU support (about 3 GB)")
        torch = [str(python), "-m", "pip", "install", "--upgrade", "torch"]
        run(torch if args.cpu else torch + ["--index-url", TORCH_INDEX])
        write(status, "installing", "Installing transformers, peft and bitsandbytes")
        run([str(python), "-m", "pip", "install", "--upgrade", *PACKAGES])
        write(status, "installing", "Checking the GPU")
        probe = subprocess.run([str(python), "-c",
                                "import torch,peft,transformers;"
                                "print(torch.cuda.is_available() and torch.cuda.get_device_name(0) or 'cpu');"
                                "print(round(torch.cuda.get_device_properties(0).total_memory/2**30,1) if torch.cuda.is_available() else 0)"],
                               capture_output=True, text=True, check=True)
        device, memory = (probe.stdout.strip().splitlines() + ["cpu", "0"])[:2]
        if device == "cpu" and not args.cpu:
            write(status, "failed", "Installed, but PyTorch can't see an NVIDIA GPU. Update the NVIDIA driver and run 'weights setup' again.")
            return 1
        if not args.cpu and float(memory) < 11:
            write(status, "failed", f"{device} has {memory} GB; at least 12 GB of GPU memory is needed to tune a 9B model.")
            return 1
        write(status, "ready", f"Ready on {device} ({memory} GB).")
        return 0
    except subprocess.CalledProcessError as exc:
        write(status, "failed", f"Install step failed (exit {exc.returncode}); see data/weight_training/setup.log.")
        return 1
    except Exception as exc:  # noqa: BLE001
        write(status, "failed", f"{type(exc).__name__}: {exc}"[:300])
        return 1


if __name__ == "__main__":
    sys.exit(main())
