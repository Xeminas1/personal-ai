"""Synthetic offline tests for owner-selected training data and guarded adapter runner.

No GPU, network, model weights, bridge, chat history or private archives.
"""
from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
import sys
import types
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from training import prepare_dataset as data
from training import train_adapter as adapter


def example(index: int) -> dict:
    return {
        "reviewed": True,
        "consent": True,
        "source": "synthetic",
        "messages": [
            {"role": "user", "content": f"Fictional scenario {index}: Which option is second?"},
            {"role": "assistant", "content": f"Option two is second in scenario {index}."},
        ],
    }


class TrainingGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.input = self.root / "owner_selected.jsonl"
        self.output = self.root / "private_runs"
        self.records = [example(i) for i in range(20)]
        self.write(self.records)

    def write(self, records):
        self.input.write_text("".join(json.dumps(x) + "\n" for x in records), encoding="utf-8")

    def prepare(self):
        return data.prepare(self.input, self.output, seed="stable-secretless-seed", label="demo")

    def test_private_split_and_integrity_without_training(self):
        source_before = self.input.read_bytes()
        run = self.prepare()
        meta = data.verify(run)
        self.assertEqual(meta["train_count"], 16)
        self.assertEqual(meta["heldout_count"], 4)
        self.assertFalse(meta["training_applied"])
        self.assertFalse(meta["approved_for_automatic_training"])
        self.assertEqual(self.input.read_bytes(), source_before)
        self.assertEqual(set(p.name for p in run.iterdir()), {"train.jsonl", "heldout.jsonl", "manifest.json"})
        all_text = (run / "train.jsonl").read_text() + (run / "heldout.jsonl").read_text()
        self.assertNotIn("owner_selected", all_text)
        self.assertNotIn("github", all_text.lower())
        self.assertEqual(len(all_text.splitlines()), 20)
        if os.name != "nt":
            self.assertEqual((run / "train.jsonl").stat().st_mode & 0o077, 0)
            self.assertEqual((run / "manifest.json").stat().st_mode & 0o077, 0)

    def test_split_deterministic_independent_of_input_order(self):
        first = self.prepare()
        a = [data.verify(first)[k] for k in ("train_sha256", "heldout_sha256")]
        self.write(list(reversed(self.records)))
        second = self.prepare()
        b = [data.verify(second)[k] for k in ("train_sha256", "heldout_sha256")]
        self.assertEqual(a, b)

    def test_input_requires_explicit_command_consent(self):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            rc = data.main(["prepare", "--input", str(self.input), "--output-dir", str(self.output)])
        self.assertEqual(rc, 2)
        self.assertFalse(self.output.exists())
        self.assertNotIn("Fictional scenario", stdout.getvalue())
        with redirect_stdout(stdout):
            rc = data.main(["prepare", "--input", str(self.input), "--output-dir", str(self.output),
                            "--reviewed-and-consented"])
        self.assertEqual(rc, 0)

    def test_rejects_unreviewed_wrong_source_and_extra_fields(self):
        for mutation in (
            lambda x: x.update(reviewed=False),
            lambda x: x.update(consent=False),
            lambda x: x.update(source="private_bridge_auto"),
            lambda x: x.update(external_score=10),
        ):
            records = [example(i) for i in range(20)]
            mutation(records[0])
            self.write(records)
            with self.assertRaises(data.DatasetRejected):
                self.prepare()
        self.assertFalse(self.output.exists())

    def test_rejects_same_prompt_with_different_answer(self):
        records = [example(i) for i in range(20)]
        records[-1]["messages"][0]["content"] = records[0]["messages"][0]["content"].upper() + "!!"
        records[-1]["messages"][-1]["content"] = "A conflicting claim."
        self.write(records)
        with self.assertRaises(data.DatasetRejected):
            self.prepare()
        self.assertFalse(self.output.exists())

    def test_rejects_sensitive_fields_before_writing(self):
        for phrase in (
            "contact person@example.com", "https://example.com/private",
            "Bearer thisisalongsynthetictokenvalue", "Located C:\\Users\\someone\\archive",
            "Host IP 192.168.1.12", "API_KEY=abcdefghijklmnopqr",
        ):
            records = [example(i) for i in range(20)]
            records[-1]["messages"][-1]["content"] = phrase
            self.write(records)
            with self.assertRaises(data.DatasetRejected, msg=phrase):
                self.prepare()
        self.assertFalse(self.output.exists())

    def test_rejects_duplicates_invalid_roles_and_too_small(self):
        records = [example(1) for _ in range(20)]
        self.write(records)
        with self.assertRaises(data.DatasetRejected):
            self.prepare()
        records = [example(i) for i in range(20)]
        records[-1]["messages"][-1]["role"] = "user"
        self.write(records)
        with self.assertRaises(data.DatasetRejected):
            self.prepare()
        self.write([example(i) for i in range(9)])
        with self.assertRaises(data.DatasetRejected):
            self.prepare()

    def test_rejects_tampered_training_and_holdout_and_symlinks(self):
        run = self.prepare()
        target = run / "train.jsonl"
        target.write_text(target.read_text() + "{}\n")
        with self.assertRaises(data.DatasetRejected):
            data.verify(run)
        other = self.prepare()
        heldout = other / "heldout.jsonl"
        heldout.write_text(heldout.read_text().replace("Option", "Changed"))
        with self.assertRaises(data.DatasetRejected):
            data.verify(other)
        # Cross-platform symlink capability may be unavailable to unprivileged Windows CI.
        alias = self.root / "alias.jsonl"
        try:
            alias.symlink_to(self.input)
        except (OSError, NotImplementedError):
            pass
        else:
            with self.assertRaises(data.DatasetRejected):
                data.prepare(alias, self.output, seed="valid-seed", label="demo")

    def test_refuses_output_inside_public_code_tree(self):
        with self.assertRaises(data.DatasetRejected):
            data._private_output(data._REPO_ROOT / "training" / "accidental_public_data")
        # A lexical path through gitignored data/ must not escape to tracked code.
        with self.assertRaises(data.DatasetRejected):
            data._private_output(data._REPO_ROOT / "data" / ".." / "training" / "leak")

    def test_plan_is_read_only_and_does_not_import_cuda(self):
        run = self.prepare()
        args = (run, "Qwen/Qwen3.5-4B", "a" * 40, 10, 512)
        info = adapter.plan(*args)
        self.assertEqual(info["training_records"], 16)
        self.assertEqual(info["reserved_holdout_records"], 4)
        self.assertFalse(info["training_applied"])
        self.assertEqual(info["requires_vram_gb"], 12.0)
        self.assertEqual(adapter.plan(run, "Qwen/Qwen3.5-9B", "a" * 40, 10, 512)["requires_vram_gb"], 24.0)
        with self.assertRaises(data.DatasetRejected):
            adapter.plan(run, "qwen3.5:9b-q8_0", "a" * 40, 10, 512)
        with self.assertRaises(data.DatasetRejected):
            adapter.plan(run, "Qwen/Qwen3.5-9B", "main", 10, 512)

    def test_dry_run_no_gpu_training_dependency_or_network(self):
        run = self.prepare()
        command = ["--run", str(run), "--model", "Qwen/Qwen3.5-4B",
                   "--revision", "a" * 40]
        with patch.object(adapter, "train", side_effect=AssertionError("must not train")):
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(adapter.main(command), 0)
                self.assertEqual(adapter.main(command + ["--execute"]), 2)
            self.assertIn("DRY RUN ONLY", out.getvalue())
            self.assertIn("review", out.getvalue().lower() if "review" in out.getvalue().lower() else "review")
            self.assertNotIn("Fictional scenario", out.getvalue())
        self.assertFalse((self.root / "adapters").exists())

    def test_execution_preflight_rejects_wrong_checkpoint_without_importing_torch(self):
        run = self.prepare()
        bad = self.root / "not-a-sha"
        bad.mkdir()
        with self.assertRaises(data.DatasetRejected):
            adapter.train(
                run, model_id="Qwen/Qwen3.5-4B", revision="a" * 40,
                checkpoint_dir=bad, output_dir=self.root / "adapters",
                max_steps=10, sequence=512,
            )
        self.assertFalse((self.root / "adapters").exists())


    def test_mock_gpu_runner_stays_isolated_and_ignores_holdout(self):
        """A mocked dry laboratory run exercises code paths, NOT actual CUDA/weight learning."""
        run = self.prepare()
        revision = "a" * 40
        snapshot = self.root / revision
        snapshot.mkdir()
        (snapshot / "config.json").write_text(json.dumps({"model_type": "qwen3_5", "text_config": {"hidden_size": 2560}}))
        (snapshot / "tokenizer_config.json").write_text("{}")
        observed = {}

        class FakeModel:
            def save_pretrained(self, directory):
                directory = Path(directory)
                directory.mkdir()
                (directory / "adapter_config.json").write_text('{"synthetic_only":true}')
                (directory / "adapter_model.safetensors").write_bytes(b"fake weights")

        class FakeTokenizer:
            def save_pretrained(self, directory):
                (Path(directory) / "tokenizer.json").write_text('{"synthetic_only":true}')

            def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
                self_last = "assistant" if messages and messages[-1]["role"] == "assistant" else "user"
                # Fake increasing token lengths only; never a real tokenizer test.
                return list(range(10 + len(messages) * 12 + (1 if self_last == "assistant" else 0)))

        class FakeLoader:
            @staticmethod
            def from_pretrained(**kwargs):
                observed["base"] = kwargs
                return FakeModel(), FakeTokenizer()

            @staticmethod
            def get_peft_model(model, **kwargs):
                observed["lora"] = kwargs
                return model

        class FakeDataset:
            @staticmethod
            def from_list(rows):
                return rows

        class FakeTrainer:
            def __init__(self, *, train_dataset, args, **kwargs):
                observed["samples"] = train_dataset
                observed["options"] = vars(args)

            def train(self):
                observed["trained_mock"] = True

        gib = 1024 ** 3
        torch_fake = types.ModuleType("torch")
        torch_fake.cuda = types.SimpleNamespace(
            is_available=lambda: True,
            is_bf16_supported=lambda: True,
            get_device_properties=lambda index: types.SimpleNamespace(total_memory=24 * gib),
            mem_get_info=lambda index: (22 * gib, 24 * gib),
        )
        datasets_fake = types.ModuleType("datasets")
        datasets_fake.Dataset = FakeDataset
        trl_fake = types.ModuleType("trl")
        trl_fake.SFTConfig = lambda **kwargs: types.SimpleNamespace(**kwargs)
        trl_fake.SFTTrainer = FakeTrainer
        unsloth_fake = types.ModuleType("unsloth")
        unsloth_fake.FastLanguageModel = FakeLoader

        with patch.dict(sys.modules, {
            "torch": torch_fake, "datasets": datasets_fake,
            "trl": trl_fake, "unsloth": unsloth_fake,
        }):
            output = adapter.train(
                run, model_id="Qwen/Qwen3.5-4B",
                revision=revision, checkpoint_dir=snapshot,
                output_dir=self.root / "adapters", max_steps=2, sequence=512,
            )
        meta = json.loads((output / "adapter_manifest.json").read_text())
        self.assertTrue(observed["trained_mock"])
        self.assertEqual(len(observed["samples"]), 16)
        self.assertEqual(meta["reserved_holdout_records"], 4)
        self.assertFalse(meta["heldout_used_for_training"])
        self.assertTrue(meta["training_applied"])
        self.assertEqual(meta["deployment"], "NONE")
        self.assertEqual(observed["base"]["load_in_4bit"], False)
        self.assertTrue(observed["base"]["load_in_16bit"])
        self.assertTrue(observed["options"]["completion_only_loss"])
        self.assertTrue((run / "heldout.jsonl").is_file())
        self.assertFalse((snapshot / "adapter_manifest.json").exists())

    def test_refuses_checkpoint_with_incorrect_architecture_before_import(self):
        run = self.prepare()
        revision = "a" * 40
        snapshot = self.root / revision
        snapshot.mkdir()
        (snapshot / "tokenizer_config.json").write_text("{}")
        for wrong in ({"model_type": "qwen3_5", "text_config": {"hidden_size": 4096}},
                      {"model_type": "not-qwen3_5", "text_config": {"hidden_size": 2560}},
                      {"model_type": "qwen3_5", "text_config": {}}):
            (snapshot / "config.json").write_text(json.dumps(wrong))
            with self.assertRaises(data.DatasetRejected):
                adapter._checkpoint(snapshot, revision, "Qwen/Qwen3.5-4B")


    def test_mock_gpu_9b_rejects_16gb_before_loading_model(self):
        run = self.prepare()
        revision = "a" * 40
        snapshot = self.root / revision
        snapshot.mkdir()
        (snapshot / "config.json").write_text(json.dumps({"model_type": "qwen3_5", "text_config": {"hidden_size": 2560}}))
        (snapshot / "tokenizer_config.json").write_text("{}")
        gib = 1024 ** 3
        torch_fake = types.ModuleType("torch")
        torch_fake.cuda = types.SimpleNamespace(
            is_available=lambda: True,
            is_bf16_supported=lambda: True,
            get_device_properties=lambda index: types.SimpleNamespace(total_memory=16 * gib),
        )
        unsloth_fake = types.ModuleType("unsloth")
        unsloth_fake.FastLanguageModel = types.SimpleNamespace()
        datasets_fake = types.ModuleType("datasets")
        datasets_fake.Dataset = types.SimpleNamespace()
        trl_fake = types.ModuleType("trl")
        trl_fake.SFTConfig = object
        trl_fake.SFTTrainer = object
        with patch.dict(sys.modules, {
            "torch": torch_fake, "unsloth": unsloth_fake,
            "datasets": datasets_fake, "trl": trl_fake,
        }):
            with self.assertRaises(data.DatasetRejected):
                adapter.train(
                    run, model_id="Qwen/Qwen3.5-9B",
                    revision=revision, checkpoint_dir=snapshot,
                    output_dir=self.root / "adapters", max_steps=2, sequence=512,
                )
        self.assertFalse((self.root / "adapters").exists())



if __name__ == "__main__":
    unittest.main()
