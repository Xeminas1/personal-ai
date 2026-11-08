"""XemAi owner-approved weight tuning: dataset -> QLoRA adapter -> gate -> Ollama model.

Runs on the owner's GPU PC inside the separate training environment created by
training/SETUP_TRAINING.cmd (never imported by the XemAi app runtime). It is
started only by an explicit owner command ("weights train").

Pipeline (each stage writes <run>/status.json so the app can show progress):

  1. load    Read the owner's examples (JSONL, one {"messages": [...]} per line,
             last message = the assistant answer to learn). Deterministic split:
             ~20% held out and never trained on.
  2. anchor  The *base* model answers a fixed set of generic prompts. Some are
             replayed during training (so it doesn't forget how to talk), the rest
             measure drift afterwards.
  3. train   LoRA adapter on all language-model linear layers. 4-bit base
             (QLoRA) on CUDA so a 9B model fits a 16 GB GPU; full precision on CPU
             (used by the automated tests with a tiny model).
  4. gate    Mean answer-token loss (NLL) on held-out examples must drop by at least
             --min-gain, and loss on the base model's own anchor answers must not
             rise by more than --max-drift. Fail -> nothing is deployed.
  5. export  Merge/convert and `ollama create` a NEW model tag (the base model is
             never modified), then smoke-test it through Ollama. The app only starts
             using it after the owner types "weights use <run>".

Nothing here sends data anywhere except the local Ollama API and, for the first
run, downloading the public base checkpoint from Hugging Face.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

# Ollama tag (minus quantisation suffix) -> official Hugging Face checkpoint.
BASE_CHECKPOINTS = {
    "qwen3.5:9b": "Qwen/Qwen3.5-9B",
    "qwen3.5:4b": "Qwen/Qwen3.5-4B",
    "qwen3.5:2b": "Qwen/Qwen3.5-2B",
    "qwen3:8b": "Qwen/Qwen3-8B",
    "qwen3:4b": "Qwen/Qwen3-4B",
    "qwen3:1.7b": "Qwen/Qwen3-1.7B",
    "qwen3:0.6b": "Qwen/Qwen3-0.6B",
}

MIN_EXAMPLES = 10
MIN_HOLDOUT = 2

# Public, synthetic prompts. TRAIN anchors are replayed with the base model's own
# answers; EVAL anchors are only used to measure drift (never trained on).
ANCHOR_TRAIN_PROMPTS = [
    "Explain what a hash table is in two short paragraphs.",
    "Give me three tips for writing a clear email.",
    "What is the difference between weather and climate?",
    "Write a Python function that reverses a string.",
    "How do I convert 25 degrees Celsius to Fahrenheit?",
    "Summarise the water cycle for a ten-year-old.",
    "What should I check if my laptop is running slowly?",
    "Suggest a simple dinner I can cook in twenty minutes.",
    "Explain recursion with a short example.",
    "What does HTTP status code 404 mean?",
    "How can I stay focused while studying?",
    "Write a haiku-length description of autumn in your own words.",
    "What is a good way to back up important files?",
    "Explain what RAM does in a computer.",
    "How do vaccines train the immune system, briefly?",
    "Give me a short checklist for packing for a weekend trip.",
]
ANCHOR_EVAL_PROMPTS = [
    "Explain the difference between a list and a tuple in Python.",
    "What are two benefits of regular exercise?",
    "How does a refrigerator keep food cold?",
    "Write a one-sentence birthday message for a friend.",
    "What is the capital of Japan, and one fact about it?",
    "How do I find the area of a circle?",
    "What is version control and why use it?",
    "Give two ways to reduce stress before an exam.",
]


class TuneError(RuntimeError):
    """A clear, user-facing reason the run stopped."""


# --------------------------------------------------------------------------- data

def example_id(messages: list[dict]) -> str:
    canonical = json.dumps(messages, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _valid_messages(messages: Any) -> bool:
    if not isinstance(messages, list) or len(messages) < 2:
        return False
    for item in messages:
        if not isinstance(item, dict) or item.get("role") not in {"system", "user", "assistant"}:
            return False
        if not isinstance(item.get("content"), str) or not item["content"].strip():
            return False
    return messages[-1]["role"] == "assistant" and messages[-2]["role"] == "user"


def load_examples(path: Path) -> list[dict]:
    seen, rows = set(), []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise TuneError(f"Dataset line {number} is not valid JSON") from exc
        messages = row.get("messages") if isinstance(row, dict) else None
        if not _valid_messages(messages):
            raise TuneError(f"Dataset line {number} must end with a user message then an assistant answer")
        identifier = example_id(messages)
        if identifier in seen:
            continue
        seen.add(identifier)
        rows.append({"id": identifier, "source": str(row.get("source") or "unknown"), "messages": messages})
    return rows


def split_examples(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Stable ~20% holdout chosen by content hash, so reruns never leak holdout into training."""
    holdout = [row for row in rows if int(row["id"], 16) % 5 == 0]
    train = [row for row in rows if int(row["id"], 16) % 5 != 0]
    # Guarantee a usable holdout on small datasets without depending on luck.
    ordered = sorted(train, key=lambda row: row["id"])
    while len(holdout) < MIN_HOLDOUT and len(ordered) > MIN_HOLDOUT:
        holdout.append(ordered.pop())
    train = [row for row in train if row in ordered]
    return train, holdout


# ------------------------------------------------------------------- status/report

@dataclass
class Status:
    run_dir: Path
    data: dict = field(default_factory=dict)

    def update(self, stage: str, message: str, **extra: Any) -> None:
        self.data.update({"stage": stage, "message": message, "updated": time.time(), **extra})
        tmp = self.run_dir / "status.json.tmp"
        tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        os.replace(tmp, self.run_dir / "status.json")
        print(f"[{stage}] {message}", flush=True)


# ------------------------------------------------------------------- model loading

def checkpoint_for(ollama_base: str, override: str | None = None) -> str:
    if override:
        return override
    name = ollama_base.strip().lower().removesuffix(":latest")
    family, _, tag = name.partition(":")
    size = re.match(r"[0-9.]+b", tag)
    key = f"{family}:{size.group(0)}" if size else name
    if key not in BASE_CHECKPOINTS:
        raise TuneError(
            f"No known Hugging Face checkpoint for Ollama model '{ollama_base}'. "
            "Pass --hf-base with the matching official repository."
        )
    return BASE_CHECKPOINTS[key]


def lora_targets(model) -> list[str]:
    """Every Linear layer in the language model, excluding vision tower and output head."""
    import torch

    names = set()
    for name, module in model.named_modules():
        if "visual" in name or "vision" in name or name.endswith("lm_head"):
            continue
        is_linear = isinstance(module, torch.nn.Linear) or type(module).__name__ in {"Linear4bit", "Linear8bitLt"}
        if is_linear:
            names.add(name.rsplit(".", 1)[-1])
    names.discard("lm_head")
    if not names:
        raise TuneError("Could not find language-model linear layers to adapt")
    return sorted(names)


def model_class(source: str):
    """Load multimodal checkpoints (Qwen3.5) with their full official class.

    Keeping the original layout means the adapter's layer names and any merged
    checkpoint match what Ollama expects for that model; the vision tower is
    loaded but never adapted.
    """
    from transformers import AutoConfig, AutoModelForCausalLM

    config = AutoConfig.from_pretrained(source)
    if any(str(a).endswith("ForConditionalGeneration") for a in (config.architectures or [])):
        from transformers import AutoModelForImageTextToText

        return AutoModelForImageTextToText
    return AutoModelForCausalLM


def load_model(source: str, *, quantize: bool, dtype_name: str = "auto"):
    import torch
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(source)
    kwargs: dict[str, Any] = {}
    if quantize:
        from transformers import BitsAndBytesConfig

        kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True,
        )
        kwargs["device_map"] = {"": 0}
        kwargs["dtype"] = torch.bfloat16
    else:
        kwargs["dtype"] = torch.float32 if dtype_name == "float32" else torch.bfloat16 if dtype_name == "bfloat16" else "auto"
    model = model_class(source).from_pretrained(source, **kwargs)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    return model, tokenizer


# ------------------------------------------------------------------ tokenisation

def _template(tokenizer, messages: list[dict], *, generation_prompt: bool) -> list[int]:
    kwargs = {"tokenize": True, "add_generation_prompt": generation_prompt}
    try:
        ids = tokenizer.apply_chat_template(messages, enable_thinking=False, **kwargs)
    except TypeError:
        ids = tokenizer.apply_chat_template(messages, **kwargs)
    if isinstance(ids, dict) or hasattr(ids, "keys"):
        ids = ids["input_ids"]
    return list(ids)


def encode(tokenizer, messages: list[dict], max_len: int) -> tuple[list[int], list[int]] | None:
    """Token ids + labels where only the final assistant answer is learned."""
    prompt = _template(tokenizer, messages[:-1], generation_prompt=True)
    answer = tokenizer(messages[-1]["content"], add_special_tokens=False)["input_ids"]
    end = [tokenizer.eos_token_id] if tokenizer.eos_token_id is not None else []
    answer = list(answer) + end
    if not answer:
        return None
    answer = answer[: max_len // 2] if len(answer) > max_len // 2 and len(prompt) > max_len // 2 else answer
    room = max_len - len(answer)
    if room < 8:
        answer = answer[: max_len - 8]
        room = 8
    prompt = prompt[-room:]  # keep the most recent context
    ids = prompt + answer
    labels = [-100] * len(prompt) + answer
    return ids, labels


# --------------------------------------------------------------------- measurement

def mean_answer_nll(model, tokenizer, rows: list[dict], max_len: int) -> float:
    import torch

    total, count = 0.0, 0
    device = next(model.parameters()).device
    model.eval()
    with torch.no_grad():
        for row in rows:
            encoded = encode(tokenizer, row["messages"], max_len)
            if not encoded:
                continue
            ids, labels = encoded
            input_ids = torch.tensor([ids], device=device)
            label_ids = torch.tensor([labels], device=device)
            logits = model(input_ids=input_ids).logits[:, :-1, :].float()
            target = label_ids[:, 1:]
            mask = target != -100
            if not mask.any():
                continue
            losses = torch.nn.functional.cross_entropy(
                logits.reshape(-1, logits.size(-1)), target.reshape(-1).clamp(min=0), reduction="none",
            ).reshape(target.shape)
            total += float(losses[mask].sum())
            count += int(mask.sum())
    if not count:
        raise TuneError("No answer tokens to evaluate")
    return total / count


def generate_answers(model, tokenizer, prompts: Iterable[str], max_new_tokens: int) -> list[dict]:
    import torch

    rows = []
    device = next(model.parameters()).device
    model.eval()
    for prompt in prompts:
        messages = [{"role": "user", "content": prompt}]
        ids = torch.tensor([_template(tokenizer, messages, generation_prompt=True)], device=device)
        with torch.no_grad():
            out = model.generate(
                input_ids=ids, attention_mask=torch.ones_like(ids), max_new_tokens=max_new_tokens,
                do_sample=False, pad_token_id=tokenizer.pad_token_id,
            )
        text = tokenizer.decode(out[0, ids.shape[1]:], skip_special_tokens=True).strip()
        text = re.sub(r"(?s)<think>.*?</think>", "", text).strip() or text
        if text:
            rows.append({"id": example_id(messages + [{"role": "assistant", "content": text}]),
                         "source": "anchor", "messages": messages + [{"role": "assistant", "content": text}]})
    return rows


# ------------------------------------------------------------------------ training

@dataclass
class TrainConfig:
    epochs: int = 3
    lr: float = 1e-4
    rank: int = 16
    alpha: int = 32
    dropout: float = 0.05
    grad_accum: int = 8
    max_len: int = 2048
    seed: int = 7
    anchor_tokens: int = 256


def train_adapter(model, tokenizer, rows: list[dict], cfg: TrainConfig,
                  progress: Callable[[int, int, float], None] | None = None):
    import torch
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training

    random.seed(cfg.seed)
    torch.manual_seed(cfg.seed)
    quantized = bool(getattr(model, "is_loaded_in_4bit", False))
    if quantized:
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    elif torch.cuda.is_available():
        model.gradient_checkpointing_enable()
    # Regex so a layer name shared with the vision tower can never be adapted there.
    names = "|".join(re.escape(n) for n in lora_targets(model))
    lora = LoraConfig(r=cfg.rank, lora_alpha=cfg.alpha, lora_dropout=cfg.dropout,
                      target_modules=rf"^(?!.*(?:visual|vision)).*\.(?:{names})$", task_type="CAUSAL_LM")
    model = get_peft_model(model, lora)
    params = [p for p in model.parameters() if p.requires_grad]
    optimiser = torch.optim.AdamW(params, lr=cfg.lr, weight_decay=0.0)
    encoded = [e for e in (encode(tokenizer, row["messages"], cfg.max_len) for row in rows) if e]
    if not encoded:
        raise TuneError("No trainable examples after tokenisation")
    steps = max(1, math.ceil(len(encoded) * cfg.epochs / cfg.grad_accum))
    schedule = torch.optim.lr_scheduler.LambdaLR(
        optimiser, lambda s: min(1.0, (s + 1) / max(1, steps // 10)) * 0.5 * (1 + math.cos(math.pi * min(s, steps) / steps)),
    )
    device = next(model.parameters()).device
    model.train()
    step, micro, running, recent = 0, 0, 0.0, []
    order = list(range(len(encoded)))
    for _epoch in range(cfg.epochs):
        random.shuffle(order)
        for index in order:
            ids, labels = encoded[index]
            out = model(input_ids=torch.tensor([ids], device=device), labels=torch.tensor([labels], device=device))
            loss = out.loss / cfg.grad_accum
            loss.backward()
            value = out.loss.item()
            running += value
            recent = (recent + [value])[-cfg.grad_accum * 4:]
            micro += 1
            if micro % cfg.grad_accum == 0 or micro == len(encoded) * cfg.epochs:
                torch.nn.utils.clip_grad_norm_(params, 1.0)
                optimiser.step()
                schedule.step()
                optimiser.zero_grad(set_to_none=True)
                step += 1
                if progress:
                    progress(step, steps, sum(recent) / len(recent))
    model.eval()
    return model, {"optimizer_steps": step, "train_loss": running / max(1, micro), "examples": len(encoded)}


# -------------------------------------------------------------------------- export

def _ollama(url: str, path: str, payload: dict | None = None, timeout: int = 600) -> dict:
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(url.rstrip("/") + path, data=data,
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode() or "{}")


def ollama_exe() -> str:
    """Ollama's CLI, also when a detached process lacks it on PATH (Windows installs per-user)."""
    found = shutil.which("ollama")
    if found:
        return found
    candidate = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
    return str(candidate) if candidate.is_file() else "ollama"


def base_modelfile_lines(base: str) -> list[str]:
    """Keep the base model's chat template / renderer / parameters for the tuned copy."""
    try:
        text = subprocess.run([ollama_exe(), "show", "--modelfile", base], capture_output=True,
                              text=True, check=True, timeout=120).stdout
    except Exception:
        return []
    keep, block = [], None
    for line in text.splitlines():
        if block is not None:
            block.append(line)
            if line.rstrip().endswith('"""'):
                keep.append("\n".join(block))
                block = None
            continue
        head = line.split(" ", 1)[0].upper()
        if head in {"TEMPLATE", "SYSTEM"} and line.count('"""') == 1:
            block = [line]
        elif head in {"TEMPLATE", "SYSTEM", "PARAMETER", "RENDERER", "PARSER"}:
            keep.append(line)
    return keep


def smoke_test(url: str, model: str) -> dict:
    prompts = ["Say hello in one short sentence.", "What is 12 times 3?", "Name two primary colours."]
    replies = []
    for prompt in prompts:
        data = _ollama(url, "/api/chat", {"model": model, "stream": False, "think": False,
                                         "messages": [{"role": "user", "content": prompt}],
                                         "options": {"num_predict": 96, "temperature": 0}}, timeout=900)
        replies.append(str((data.get("message") or {}).get("content") or "").strip())
    ok = all(reply for reply in replies)
    for reply in replies:
        words = reply.split()
        if len(words) >= 12 and len(set(words)) / len(words) < 0.3:
            ok = False  # degenerate repetition
    return {"ok": ok, "replies": [reply[:200] for reply in replies]}


def export_to_ollama(*, run_dir: Path, adapter_dir: Path, source: str, ollama_base: str,
                     name: str, url: str, status: Status) -> dict:
    """Try Ollama-native strategies in order; keep the first that passes a smoke test."""
    attempts = []
    template = base_modelfile_lines(ollama_base)

    def create(from_lines: list[str], quantize: str | None) -> dict:
        modelfile = run_dir / "Modelfile"
        modelfile.write_text("\n".join(from_lines + template) + "\n", encoding="utf-8")
        cmd = [ollama_exe(), "create", name, "-f", str(modelfile)] + (["--quantize", quantize] if quantize else [])
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
        if proc.returncode != 0:
            raise TuneError((proc.stderr or proc.stdout).strip()[-400:] or "ollama create failed")
        return smoke_test(url, name)

    # 1) Base GGUF from Ollama + LoRA adapter (smallest, keeps vision tower untouched).
    status.update("export", "Packaging adapter on top of the base model in Ollama")
    try:
        result = create([f"FROM {ollama_base}", f"ADAPTER {adapter_dir.resolve()}"], None)
        attempts.append({"strategy": "ollama_adapter", **result})
        if result["ok"]:
            return {"model": name, "strategy": "ollama_adapter", "attempts": attempts}
    except Exception as exc:  # noqa: BLE001 - each strategy reports and we try the next
        attempts.append({"strategy": "ollama_adapter", "ok": False, "error": str(exc)[:400]})

    # 2) Merge into full-precision weights and let Ollama import + quantise them.
    status.update("export", "Merging adapter into full weights (needs ~20 GB RAM, a few minutes)")
    merged = run_dir / "merged"
    try:
        import torch
        from peft import PeftModel
        from transformers import AutoTokenizer

        base = model_class(source).from_pretrained(source, dtype=torch.bfloat16, device_map={"": "cpu"})
        before = {k: v.detach().clone() for k, v in base.state_dict().items() if k.endswith("proj.weight")}
        model = PeftModel.from_pretrained(base, str(adapter_dir)).merge_and_unload()
        after = model.state_dict()
        if not any(k in after and not torch.equal(after[k], v) for k, v in before.items()):
            raise TuneError("Merged weights are identical to the base; the adapter did not apply")
        del before
        model.save_pretrained(merged, safe_serialization=True)
        AutoTokenizer.from_pretrained(source).save_pretrained(merged)
        del model, base
        quant = re.search(r"-(q\d\w*)$", ollama_base.lower())
        result = create([f"FROM {merged.resolve()}"], (quant.group(1) if quant else "q8_0"))
        attempts.append({"strategy": "ollama_import_merged", **result})
        if result["ok"]:
            return {"model": name, "strategy": "ollama_import_merged", "attempts": attempts}
    except Exception as exc:  # noqa: BLE001
        attempts.append({"strategy": "ollama_import_merged", "ok": False, "error": str(exc)[:400]})
    finally:
        shutil.rmtree(merged, ignore_errors=True)  # ~18 GB; the adapter is kept
    raise TuneError("Ollama could not load the tuned model: " + json.dumps(attempts)[:900])


# ----------------------------------------------------------------------------- run

def run(args: argparse.Namespace) -> dict:
    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    status = Status(run_dir, {"run": run_dir.name, "started": time.time()})
    report: dict[str, Any] = {"run": run_dir.name, "ollama_base": args.ollama_base, "passed": False}
    try:
        import torch

        status.update("load", "Reading your examples")
        rows = load_examples(Path(args.dataset))
        if len(rows) < MIN_EXAMPLES:
            raise TuneError(f"Need at least {MIN_EXAMPLES} distinct examples to train; have {len(rows)}. "
                            "Add more with 'teach: <better answer>' or by rating good replies 9-10.")
        train_rows, holdout = split_examples(rows)
        report.update({"examples": len(rows), "train": len(train_rows), "holdout": len(holdout),
                       "sources": sorted({row["source"] for row in rows})})

        source = args.model_path or checkpoint_for(args.ollama_base, args.hf_base)
        quantize = torch.cuda.is_available() and not args.no_quantize
        status.update("load", f"Loading base model {source}" + (" in 4-bit" if quantize else ""))
        model, tokenizer = load_model(source, quantize=quantize, dtype_name=args.dtype)
        report["checkpoint"] = source
        report["quantized_4bit"] = quantize

        status.update("anchor", "Recording the base model's own answers to general prompts")
        anchor_train = generate_answers(model, tokenizer, ANCHOR_TRAIN_PROMPTS[: args.anchor_count], args.anchor_tokens)
        anchor_eval = generate_answers(model, tokenizer, ANCHOR_EVAL_PROMPTS[: max(2, args.anchor_count // 2)], args.anchor_tokens)
        # Replay roughly one anchor per three owner examples.
        replay = anchor_train[: max(1, len(train_rows) // 3)]

        status.update("measure", "Measuring the base model on held-out examples")
        base_holdout = mean_answer_nll(model, tokenizer, holdout, args.max_len)
        base_anchor = mean_answer_nll(model, tokenizer, anchor_eval, args.max_len) if anchor_eval else 0.0

        cfg = TrainConfig(epochs=args.epochs, lr=args.lr, rank=args.rank, alpha=args.rank * 2, max_len=args.max_len,
                          grad_accum=args.grad_accum)

        def progress(step: int, total: int, loss: float) -> None:
            status.update("train", f"Training step {step}/{total} (loss {loss:.3f})", step=step, steps=total)

        status.update("train", f"Training on {len(train_rows)} examples (+{len(replay)} replay)")
        model, train_info = train_adapter(model, tokenizer, train_rows + replay, cfg, progress)
        report["training"] = train_info

        status.update("measure", "Measuring the tuned adapter")
        tuned_holdout = mean_answer_nll(model, tokenizer, holdout, args.max_len)
        tuned_anchor = mean_answer_nll(model, tokenizer, anchor_eval, args.max_len) if anchor_eval else 0.0
        gain = base_holdout - tuned_holdout
        drift = tuned_anchor - base_anchor
        report["evaluation"] = {
            "holdout_nll_base": round(base_holdout, 4), "holdout_nll_tuned": round(tuned_holdout, 4),
            "holdout_gain": round(gain, 4), "anchor_nll_base": round(base_anchor, 4),
            "anchor_nll_tuned": round(tuned_anchor, 4), "anchor_drift": round(drift, 4),
            "min_gain": args.min_gain, "max_drift": args.max_drift,
        }
        adapter_dir = run_dir / "adapter"
        model.save_pretrained(adapter_dir)
        tokenizer.save_pretrained(adapter_dir)
        if gain < args.min_gain:
            raise TuneError(f"Not deployed: held-out improvement {gain:.3f} is below the {args.min_gain} minimum.")
        if drift > args.max_drift:
            raise TuneError(f"Not deployed: general-skill drift {drift:.3f} exceeds the {args.max_drift} limit.")
        report["gate"] = "passed"

        if args.skip_export:
            report["passed"] = True
            report["model"] = None
            status.update("ready", "Gate passed (export skipped)")
        else:
            del model
            if quantize:
                torch.cuda.empty_cache()
            name = args.name or f"xemai-qwen-tuned:{run_dir.name}"
            exported = export_to_ollama(run_dir=run_dir, adapter_dir=adapter_dir, source=source,
                                        ollama_base=args.ollama_base, name=name, url=args.ollama_url, status=status)
            report.update(exported)
            report["passed"] = True
            status.update("ready", f"Ready: {name}. Type 'weights use {run_dir.name}' to switch to it.", model=name)
    except TuneError as exc:
        report["error"] = str(exc)
        status.update("failed", str(exc))
    except Exception as exc:  # noqa: BLE001 - always leave a readable report
        report["error"] = f"{type(exc).__name__}: {exc}"[:800]
        status.update("failed", report["error"])
    report["finished"] = time.time()
    (run_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Owner-approved XemAi weight tuning")
    sub = p.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run", help="train, evaluate and (if it passes) export a tuned model")
    r.add_argument("--dataset", required=True)
    r.add_argument("--run-dir", required=True)
    r.add_argument("--ollama-base", required=True, help="the Ollama model to improve, e.g. qwen3.5:9b-q8_0")
    r.add_argument("--hf-base", help="override the Hugging Face checkpoint")
    r.add_argument("--model-path", help="local checkpoint directory (tests)")
    r.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    r.add_argument("--name", help="Ollama tag for the tuned model")
    r.add_argument("--epochs", type=int, default=3)
    r.add_argument("--lr", type=float, default=1e-4)
    r.add_argument("--rank", type=int, default=16)
    r.add_argument("--grad-accum", type=int, default=8)
    r.add_argument("--max-len", type=int, default=2048)
    r.add_argument("--anchor-count", type=int, default=len(ANCHOR_TRAIN_PROMPTS))
    r.add_argument("--anchor-tokens", type=int, default=160)
    r.add_argument("--min-gain", type=float, default=0.02)
    r.add_argument("--max-drift", type=float, default=0.15)
    r.add_argument("--dtype", default="auto", choices=["auto", "float32", "bfloat16"])
    r.add_argument("--no-quantize", action="store_true")
    r.add_argument("--skip-export", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    report = run(args)
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    sys.exit(main())
