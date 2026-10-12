"""CPU-only tests for a local read-only 4B base vs adapter holdout evaluator."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from training import evaluate_synthetic_adapter as eval4b
from training import synthetic_smoke as pilot


class EvaluateSyntheticAdapterTests(unittest.TestCase):
    def setUp(self):
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        self.root = Path(root.name)
        self.snapshot = self.root / pilot.REVISION
        self.snapshot.mkdir()
        (self.snapshot / "config.json").write_text(json.dumps(
            {"model_type": "qwen3_5", "text_config": {"hidden_size": 2560}}))
        (self.snapshot / "tokenizer_config.json").write_text("{}")
        (self.snapshot / "model.safetensors.index.json").write_text(json.dumps({
            "weight_map": {"w": "model.safetensors-00001-of-00002.safetensors"}}))
        with (self.snapshot / "model.safetensors-00001-of-00002.safetensors").open("wb") as h:
            h.truncate(100_100_000)  # Sparse synthetic placeholder, no real model downloaded.
        self.output = self.root / "data" / "weight_training" / "pilot_runs"
        self.run = self.output / ("synthetic_4b_" + "a" * 32)
        self.adapter = self.run / "adapter"
        self.adapter.mkdir(parents=True)
        (self.adapter / "adapter_config.json").write_text("{}")
        (self.adapter / "adapter_model.safetensors").write_bytes(b"not actual model weights")
        hashes = {
            f.name: hashlib.sha256(f.read_bytes()).hexdigest()
            for f in self.adapter.iterdir()
        }
        train, _ = pilot._split()
        record = {
            "model": pilot.MODEL_ID, "revision": pilot.REVISION,
            "training_executed": True, "deployed": False,
            "train_examples": 16, "reserved_holdout_examples": 4,
            "sampled_lora_b_tensors_changed": 8,
            "training_data_sha256": hashlib.sha256(json.dumps(
                train, sort_keys=True).encode()).hexdigest(),
            "adapter_files_sha256": hashes,
        }
        (self.run / "smoke_manifest.json").write_text(json.dumps(record))
        patches = patch.multiple(pilot, OUTPUT_ROOT=self.output, SNAPSHOT=self.snapshot)
        patches.start()
        self.addCleanup(patches.stop)

    def test_check_hashes_are_offline_and_read_only(self):
        before = sorted(str(f) for f in self.root.rglob("*"))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(eval4b.main(["--check"]), 0)
        after = sorted(str(f) for f in self.root.rglob("*"))
        self.assertEqual(before, after)
        self.assertIn("no gpu", output.getvalue().lower())
        self.assertIn("Read-only check passed", output.getvalue())

    def test_cannot_run_gpu_without_explicit_owner_confirmation(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(eval4b.main(["--evaluate"]), 2)
        self.assertIn("not authorised", out.getvalue())

    def test_wrong_manifest_or_adapter_hash_refused(self):
        (self.adapter / "adapter_model.safetensors").write_bytes(b"tampered")
        with self.assertRaisesRegex(eval4b.EvaluationError, "checksum"):
            eval4b._verify_run(self.run)

    def test_missing_confirmation_of_training_refused(self):
        meta = self.run / "smoke_manifest.json"
        obj = json.loads(meta.read_text())
        obj["sampled_lora_b_tensors_changed"] = 0
        meta.write_text(json.dumps(obj))
        with self.assertRaisesRegex(eval4b.EvaluationError, "completed"):
            eval4b._verify_run(self.run)

    def test_explicit_run_id_cannot_escape_private_training_root(self):
        for name in ("../outside", "synthetic_4b_../../outside", "C:\\Windows\\System32",
                     "synthetic_4b_" + "x" * 120):
            with self.subTest(name=name):
                with self.assertRaises(eval4b.EvaluationError):
                    eval4b._select_run(name)

    def test_heldout_loss_uses_only_supervised_answer_tokens(self):
        class FakeTensor:
            def __init__(self, value): self.value = value
            def detach(self): return self
            def float(self): return self
            def cpu(self): return self
            def item(self): return self.value
        class FakeModel:
            def __init__(self): self.calls = []
            def __call__(self, **kwargs):
                self.calls.append(kwargs)
                return types.SimpleNamespace(loss=FakeTensor(2.0))
        def tensor(value, dtype, device):
            self.assertEqual(device, "cuda:0")
            return value
        torch = types.SimpleNamespace(long=object(), tensor=tensor)
        model = FakeModel()
        examples = [
            {"input_ids": [1, 2, 3, 4], "attention_mask": [1, 1, 1, 1],
             "labels": [-100, -100, 3, 4]},
            {"input_ids": [5, 6, 7], "attention_mask": [1, 1, 1],
             "labels": [-100, -100, 7]},
        ]
        result = eval4b._score_samples(model, torch, examples)
        self.assertEqual(result["heldout_tokens"], 3)
        self.assertAlmostEqual(result["mean_answer_nll"], 2.0)
        self.assertEqual(len(model.calls), 2)

    def test_incomplete_holdout_fails_closed(self):
        model = lambda **kwargs: None
        torch = types.SimpleNamespace(long=object(), tensor=lambda *args, **kwargs: None)
        with self.assertRaisesRegex(eval4b.EvaluationError, "no supervised"):
            eval4b._score_samples(model, torch, [{
                "input_ids": [3, 4], "attention_mask": [1, 1],
                "labels": [-100, -100],
            }])


if __name__ == "__main__":
    unittest.main()
