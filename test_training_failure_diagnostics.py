"""Pure CPU tests: preserve debugging value without leaking paths or secrets."""
from __future__ import annotations

import contextlib
import io
import types
import unittest
from unittest.mock import patch

from training import failure_diagnostics as diag


def raise_with_message(message):
    raise RuntimeError(message)


class DiagnosticTests(unittest.TestCase):
    def _capture(self, message: str) -> str:
        try:
            raise_with_message(message)
        except RuntimeError as exc:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                diag.print_diagnostics(exc)
            return output.getvalue()

    def test_redact_sensitive_exception_fields(self):
        output = self._capture(
            "failure at C:\\Users\\Someone\\secrets\\key.txt from "
            "https://sample.example/download?token=privatetoken "
            "HF_TOKEN=topsecret-123 please email admin@example.org")
        self.assertNotIn("Someone", output)
        self.assertNotIn("key.txt", output)
        self.assertNotIn("privatetoken", output)
        self.assertNotIn("topsecret", output)
        self.assertNotIn("admin@example", output)
        self.assertIn("[local-path]", output)
        self.assertIn("[secret]", output)
        self.assertIn("[email]", output)
        self.assertIn("DIAGNOSTIC: location =", output)
        self.assertNotIn("test_failure_diagnostics.py:", output.split("DIAGNOSTIC: cause =")[1].splitlines()[0])

    def test_expected_runtime_categories(self):
        examples = {
            "CUDA out of memory. Tried to allocate 2.0 GiB": "cuda_or_host_out_of_memory",
            "torch._inductor.error: compiler failed": "compiler_or_triton",
            "causal_conv1d_fn kernel failed": "selective_state_or_convolution_kernel",
            "expected size 8, stride 1222 at dim=0": "tensor_shape_or_layout",
            "expected BFloat16 but got Float": "precision_or_dtype",
            "backward gradient calculation failed": "backward_or_gradient",
        }
        for error, category in examples.items():
            with self.subTest(category=category):
                self.assertIn("category = " + category, self._capture(error))

    def test_never_prints_full_credential_or_traceback(self):
        text = self._capture("Bearer mySensitiveOpaqueCredential\nat C:\\Users\\MyUser\\notes")
        self.assertNotIn("mySensitiveOpaqueCredential", text)
        self.assertNotIn("MyUser", text)
        self.assertNotIn("Traceback (", text)
        self.assertIn("fingerprint =", text)

    def test_no_torch_import_for_diagnostics(self):
        with patch.object(diag.sys, "modules", {"torch": None}):
            self.assertIn("DIAGNOSTIC:", self._capture("random runtime error"))

    def test_print_gpu_memory_if_already_loaded(self):
        cuda = types.SimpleNamespace(
            is_available=lambda: True,
            memory_allocated=lambda: 2*1024**3,
            memory_reserved=lambda: 3*1024**3,
            max_memory_allocated=lambda: 4*1024**3,
            mem_get_info=lambda index: (8*1024**3, 16*1024**3),
        )
        with patch.dict(diag.sys.modules, {"torch": types.SimpleNamespace(cuda=cuda)}):
            self.assertIn("allocated=2.00, reserved=3.00, peak=4.00",
                          self._capture("reference implementation failed"))


if __name__ == "__main__":
    unittest.main()
