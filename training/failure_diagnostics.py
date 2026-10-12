"""Privacy-conscious diagnostics for failed local synthetic fine-tuning.

Report a useful RuntimeError category and sanitized failure location, not host
paths, environment variables, chat history, model inputs or full tracebacks.
No file writes, upload or network activity.
"""
from __future__ import annotations

import hashlib
import re
import sys
import traceback


def _category(message: str) -> str:
    content = message.casefold()
    if any(term in content for term in ("out of memory", "outofmemoryerror", "cublas_status_alloc_failed")):
        return "cuda_or_host_out_of_memory"
    if any(term in content for term in ("device-side assert", "illegal memory access", "misaligned address")):
        return "cuda_kernel_error"
    if any(term in content for term in ("inductor", "torch.compile", "dynamo", "triton", "ptxas")):
        return "compiler_or_triton"
    if any(term in content for term in ("causal_conv1d", "causal-conv1d", "conv1d", "mamba")):
        return "selective_state_or_convolution_kernel"
    if any(term in content for term in ("shape", "stride", "dimension", "size mismatch", "expected size")):
        return "tensor_shape_or_layout"
    if any(term in content for term in ("bf16", "bfloat16", "half", "dtype", "scalar type")):
        return "precision_or_dtype"
    if any(term in content for term in ("backward", "grad", "autograd")):
        return "backward_or_gradient"
    return "uncategorised_runtime"


# URLs, emails, opaque strings, filesystem paths and likely credentials must
# not be repeated from arbitrary library exceptions in the console output.
_REDACTIONS = (
    (re.compile(r"(?i)https?://[^\s)]+"), "[URL]"),
    (re.compile(r"(?i)\bBearer\s+\S+"), "[secret]"),
    (re.compile(r"(?i)\b(?:HF_TOKEN|API_KEY|PASSWORD|TOKEN|SECRET)\s*[=:]\s*[^\s,;]+"), "[secret]"),
    (re.compile(r"\b[A-Za-z]:[\\/][^\s,;)\]\"']+"), "[local-path]"),
    (re.compile(r"(?<!\w)/(?:home|Users|tmp|mnt|workspace|runner|work|opt)/[^\s,;)\]\"']+"), "[local-path]"),
    (re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"), "[email]"),
    (re.compile(r"\b[A-Za-z0-9_-]{60,}\b"), "[opaque]"),
)


def _message_line(exc: BaseException) -> str:
    raw = str(exc).splitlines()[0][:800] if str(exc) else "(no explanation provided)"
    for pattern, replacement in _REDACTIONS:
        raw = pattern.sub(replacement, raw)
    # Avoid echoing arbitrary nonprintable characters or multiline surprises.
    raw = "".join(ch if " " <= ch <= "~" else "?" for ch in raw).strip()
    return (raw[:300] or "(no explanation provided)")


def _last_origin(exc: BaseException) -> str:
    stack = traceback.extract_tb(exc.__traceback__)
    for frame in reversed(stack):
        filename = frame.filename.replace("\\", "/").rsplit("/", 1)[-1]
        name = re.sub(r"[^a-zA-Z0-9_]", "_", frame.name)[:48]
        if re.fullmatch(r"[a-zA-Z0-9_-]{1,55}\.py", filename) and name:
            return f"{filename}:{frame.lineno}:{name}"
    return "unknown"


def _root_cause(exc: BaseException) -> BaseException:
    seen = set()
    current = exc
    for _ in range(8):
        nxt = current.__cause__ or (current.__context__ if not current.__suppress_context__ else None)
        if nxt is None or id(nxt) in seen:
            break
        seen.add(id(current))
        current = nxt
    return current


def print_diagnostics(exc: BaseException) -> None:
    """Emit bounded, sanitized lines that the owner may share for debugging."""
    root = _root_cause(exc)
    line = _message_line(root)
    kind = _category(str(root))
    fingerprint = hashlib.sha256((type(root).__name__ + ":" + str(root)).encode(
        "utf-8", errors="replace"
    )).hexdigest()[:12]
    print("DIAGNOSTIC: type =", type(root).__name__, "category =", kind)
    print("DIAGNOSTIC: cause =", line)
    print("DIAGNOSTIC: location =", _last_origin(root), "fingerprint =", fingerprint)
    torch = sys.modules.get("torch")
    try:
        cuda = getattr(torch, "cuda", None)
        if cuda is not None and cuda.is_available():
            allocated = cuda.memory_allocated() / 1024**3
            reserved = cuda.memory_reserved() / 1024**3
            peak = cuda.max_memory_allocated() / 1024**3
            free, total = cuda.mem_get_info(0)
            print(f"DIAGNOSTIC: GPU GiB allocated={allocated:.2f}, reserved={reserved:.2f}, "
                  f"peak={peak:.2f}, free={free/1024**3:.2f}, total={total/1024**3:.2f}")
    except Exception:
        print("DIAGNOSTIC: GPU memory summary unavailable after error.")
    print("DIAGNOSTIC: no adapter was confirmed saved or deployed.")
