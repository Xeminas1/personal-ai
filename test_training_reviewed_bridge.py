"""CPU-only contract checks for consented bridge dataset -> local 4B LoRA.

Tests use fictional text and a fully mocked GPU/trainer, no Hugging Face calls.
GPU training in the owner's actual stack remains a separate host experiment.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from training import synthetic_smoke as smoke
from training import train_reviewed_bridge_4b as reviewed
from training.prepare_dataset import prepare


class TrainingIntegrationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.weights = self.root / smoke.REVISION
        self.weights.mkdir(parents=True)
        (self.weights / "config.json").write_text(json.dumps({
            "model_type": "qwen3_5", "text_config": {"hidden_size": 2560},
        }))
        (self.weights / "tokenizer_config.json").write_text("{}")
        (self.weights / "model.safetensors.index.json").write_text(json.dumps({
            "weight_map": {"w": "model.safetensors-00001-of-00002.safetensors"}}))
        with (self.weights / "model.safetensors-00001-of-00002.safetensors").open("wb") as handle:
            handle.truncate(100_200_000)
        source = self.root / "bridge_reviewed.jsonl"
        with source.open("w", encoding="utf-8") as handle:
            for num in range(16):
                sample = {
                    "reviewed": True, "consent": True, "source": "owner_consented",
                    "messages": [
                        {"role": "user", "content": (
                            f"Please verify fictional example {num} using the provided tests.")},
                        {"role": "assistant", "content": (
                            f"Example {num}: a result is unverified until the test is run.")},
                    ],
                }
                handle.write(json.dumps(sample) + "\n")
        self.run = prepare(source, self.root / "prepared",
                           seed="reviewed-bridge-test-v1", label="weightreview")
        self.outputs = self.root / "data" / "weight_training" / "bridge_adapter_runs"
        patcher = patch.object(smoke, "SNAPSHOT", self.weights)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher2 = patch.object(reviewed, "OUTPUT_ROOT", self.outputs)
        patcher2.start()
        self.addCleanup(patcher2.stop)

    def test_preflight_has_no_gpu_or_trainer_import(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(reviewed.main(["--check", "--run", str(self.run)]), 0)
        self.assertIn("Prepared reviewed training samples:", output.getvalue())
        self.assertIn("NO GPU load", output.getvalue())
        self.assertFalse(self.outputs.exists())

    def test_user_did_not_authorise_weights_via_dataset_export(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(reviewed.main(["--train", "--run", str(self.run)]), 2)
        self.assertIn("BridgeTrainError", output.getvalue())
        self.assertFalse(self.outputs.exists())

    def test_unapproved_or_tampered_prepared_data_is_rejected(self):
        (self.run / "train.jsonl").write_text('{"messages":[]} \n')
        with self.assertRaises(ValueError):
            reviewed._load_prepared(self.run)
        self.assertFalse(self.outputs.exists())

    def test_mocked_training_uses_true_prompt_mask_and_separate_adapter(self):
        class FakeTensor:
            def __init__(self, value):
                self.value = value
            def detach(self): return self
            def float(self): return self
            def cpu(self): return self
            def clone(self): return FakeTensor(self.value)
            def __ne__(self, other): return self.value != other.value
        class FakeParameter(FakeTensor):
            requires_grad = True
            def numel(self): return 1
        weight = FakeParameter(0)
        test = self
        class FakeModel:
            def named_parameters(self):
                return iter([("mock.lora_B.weight", weight)])
            def save_pretrained(self, directory):
                folder=Path(directory);folder.mkdir()
                (folder/"adapter_config.json").write_text('{"safe":true}')
                (folder/"adapter_model.safetensors").write_bytes(b"fake tensors only")
        class FakeTokenizer:
            pad_token_id=0
            def apply_chat_template(self, messages, *, tokenize,
                                    add_generation_prompt, enable_thinking):
                test.assertFalse(enable_thinking)
                test.assertFalse(tokenize)
                prefix="".join(m["role"]+": "+m["content"]+"\n" for m in messages[:-1])
                if add_generation_prompt:
                    return "".join(m["role"]+": "+m["content"]+"\n" for m in messages)+"assistant: "
                return prefix + "assistant: "+messages[-1]["content"]+"<end>"
            def encode(self, text, *, add_special_tokens):
                return list(text.encode("utf-8"))
            def save_pretrained(self, directory):
                (Path(directory)/"tokenizer_config.json").write_text("{}")
        class FakeFastModel:
            @staticmethod
            def from_pretrained(**kwargs):
                test.assertFalse(kwargs["load_in_4bit"])
                test.assertEqual(kwargs["model_name"],str(test.weights))
                return FakeModel(), FakeTokenizer()
            @staticmethod
            def get_peft_model(model, **kwargs): return model
        class FakeDataset:
            @staticmethod
            def from_list(rows): return rows
        class FakeTrainer:
            def __init__(self, *, model, train_dataset, data_collator, args):
                test.assertGreaterEqual(len(train_dataset),8)
                test.assertEqual(args.max_steps, 2)
                test.assertFalse(args.remove_unused_columns)
                batch=data_collator([train_dataset[0]])
                mask=batch["labels"].values[0]
                test.assertIn(-100,mask)
                test.assertTrue(any(v!=-100 for v in mask))
            def train(self):
                weight.value=1
                return types.SimpleNamespace(training_loss=1.8)
        gib=1024**3
        cuda=types.SimpleNamespace(is_available=lambda:True,
            is_bf16_supported=lambda:True,
            mem_get_info=lambda idx:(13*gib,16*gib))
        fake_torch=types.ModuleType("torch")
        fake_torch.cuda=cuda
        fake_torch.long=object()
        fake_torch.tensor=lambda values, dtype:types.SimpleNamespace(values=values)
        fake_torch.any=lambda value:types.SimpleNamespace(item=lambda:value)
        unsloth=types.ModuleType("unsloth");unsloth.FastLanguageModel=FakeFastModel
        datasets=types.ModuleType("datasets");datasets.Dataset=FakeDataset
        transformers=types.ModuleType("transformers")
        transformers.Trainer=FakeTrainer
        transformers.TrainingArguments=lambda **kw:types.SimpleNamespace(**kw)
        with patch.dict(sys.modules,{"torch":fake_torch,"unsloth":unsloth,
                                     "datasets":datasets,"transformers":transformers}):
            result=reviewed.train(self.run,steps=2)
        test.assertTrue(result["weights_trained"])
        test.assertFalse(result["deployed"])
        test.assertFalse(result["xemai_9b_modified"])
        test.assertTrue(result["heldout_quality_not_yet_evaluated"])
        self.assertEqual(result["sampled_lora_b_tensors_changed"],1)
        self.assertEqual(len(list(self.outputs.iterdir())),1)
        saved=next(self.outputs.iterdir())
        self.assertTrue((saved/"adapter"/"adapter_config.json").is_file())
        self.assertTrue((saved/"manifest.json").is_file())
        self.assertEqual(result["source_train_sha256"],
                         hashlib.sha256((self.run/"train.jsonl").read_bytes()).hexdigest())


if __name__=="__main__":
    unittest.main()
