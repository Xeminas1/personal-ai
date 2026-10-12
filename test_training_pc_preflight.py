"""Offline no-device tests for the read-only Windows/Linux PC preflight."""
from __future__ import annotations

import contextlib
import io
import json
import subprocess
import types
import unittest
from unittest.mock import patch

from training import pc_preflight


class PreflightTests(unittest.TestCase):
    def test_gpu_report_never_calls_shell_or_logs_identifiers(self):
        sample = types.SimpleNamespace(returncode=0, stdout="NVIDIA GeForce RTX 5080, 16384, 15104\n")
        with patch.object(subprocess, "run", return_value=sample) as run:
            result = pc_preflight._gpus()
        self.assertEqual(result, [{
            "model": "NVIDIA GeForce RTX 5080",
            "total_gib": 16.0,
            "free_gib": 14.75,
        }])
        args, kwargs = run.call_args
        self.assertEqual(args[0][0], "nvidia-smi")
        self.assertNotIn("shell", kwargs)
        self.assertEqual(kwargs["timeout"], 8)
        self.assertEqual(kwargs["stderr"], subprocess.DEVNULL)

    def test_failure_or_bad_gpu_data_fails_closed(self):
        for output in (
            "NVIDIA, not_a_number, 200\n",
            "NVIDIA, 4096, 8192\n",
            "GPU0, 2000001, 100\n",
            "host://example, 16000, 15000\n",
        ):
            with patch.object(subprocess, "run", return_value=types.SimpleNamespace(
                returncode=0, stdout=output
            )):
                self.assertEqual(pc_preflight._gpus(), [])
        with patch.object(subprocess, "run", side_effect=FileNotFoundError):
            self.assertEqual(pc_preflight._gpus(), [])
        with patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired("nvidia-smi", 8)):
            self.assertEqual(pc_preflight._gpus(), [])

    def test_snapshot_separates_4b_from_9b_and_is_read_only(self):
        with patch.object(pc_preflight, "_gpus", return_value=[
            {"model": "NVIDIA GeForce RTX 5080", "total_gib": 16.0, "free_gib": 14.7}
        ]):
            info = pc_preflight.snapshot()
        self.assertTrue(info["read_only"])
        self.assertFalse(info["training_started"])
        self.assertFalse(info["model_changed"])
        self.assertEqual(info["bf16_lora_memory_estimates_only"]["Qwen3.5-4B"]["supported_bf16_lora_memory_estimate"], "possible")
        self.assertEqual(info["bf16_lora_memory_estimates_only"]["Qwen3.5-9B"]["supported_bf16_lora_memory_estimate"], "insufficient_or_unknown")
        self.assertNotIn("hostname", json.dumps(info))
        self.assertNotIn("username", json.dumps(info))
        self.assertNotIn("token", json.dumps(info))

    def test_main_reports_structured_diagnostics_only(self):
        output = io.StringIO()
        with patch.object(pc_preflight, "_gpus", return_value=[]), contextlib.redirect_stdout(output):
            self.assertEqual(pc_preflight.main(), 0)
        value = json.loads(output.getvalue())
        self.assertEqual(value["gpus"], [])
        self.assertFalse(value["model_changed"])
        self.assertNotIn("C:\\Users\\", output.getvalue())


if __name__ == "__main__":
    unittest.main()
