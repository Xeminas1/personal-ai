"""CPU-only synthetic validation of the local Qwen 4B pilot's strict gates."""
import contextlib
import io
import json
import tempfile
import unittest
import sys
import types
from pathlib import Path
from unittest.mock import patch
from training import synthetic_smoke as smoke

class PilotSafetyTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.checkpoint = self.root / smoke.REVISION
        self.output = self.root / 'data' / 'weight_training' / 'pilot_runs'
        self.checkpoint.mkdir()
        (self.checkpoint / 'config.json').write_text(json.dumps({'model_type':'qwen3_5', 'text_config':{'hidden_size': 2560}}))
        (self.checkpoint / 'tokenizer_config.json').write_text('{}')
        (self.checkpoint / 'model.safetensors.index.json').write_text(json.dumps({'weight_map':{'w':'model.safetensors-00001-of-00002.safetensors'}}))
        with (self.checkpoint / 'model.safetensors-00001-of-00002.safetensors').open('wb') as f:
            f.truncate(100_100_000)  # Sparse file; no real model weights and no network.
        patcher = patch.multiple(smoke, SNAPSHOT=self.checkpoint, OUTPUT_ROOT=self.output)
        patcher.start(); self.addCleanup(patcher.stop)

    def test_check_is_read_only_and_no_gpu_import(self):
        text = io.StringIO()
        with contextlib.redirect_stdout(text):
            self.assertEqual(smoke.main(['--check']),0)
        self.assertIn('metadata and shard sizes checked',text.getvalue())
        self.assertFalse(self.output.exists())

    def test_refuses_unconfirmed_training(self):
        text = io.StringIO()
        with contextlib.redirect_stdout(text):
            self.assertEqual(smoke.main(['--train']),2)
        self.assertIn('not authorised',text.getvalue())
        self.assertFalse(self.output.exists())

    def test_incorrect_checkpoint_rejected(self):
        (self.checkpoint/'config.json').write_text(json.dumps({'model_type':'qwen3_5','text_config':{'hidden_size':4096}}))
        with self.assertRaises(smoke.PilotError): smoke._local_checkpoint()
        self.assertFalse(self.output.exists())

    def test_mock_training_confirms_changed_lora_and_no_deployment(self):
        class FakeTensor:
            def __init__(self, value): self.value = value
            def detach(self): return self
            def float(self): return self
            def cpu(self): return self
            def clone(self): return FakeTensor(self.value)
            def __ne__(self, other): return self.value != other.value
        class FakeParameter(FakeTensor):
            requires_grad = True
            def numel(self): return 1
        weight = FakeParameter(0)
        testcase = self
        class FakeModel:
            def named_parameters(self): return iter([('one.lora_B.weight', weight)])
            def save_pretrained(self, directory):
                d=Path(directory); d.mkdir()
                (d/'adapter_config.json').write_text('{}')
                (d/'adapter_model.safetensors').write_bytes(b'fake synthetic gradient test only')
        class FakeTokenizer:
            def apply_chat_template(self, messages, tokenize, add_generation_prompt):
                return list(range(10*len(messages)))
            def save_pretrained(self, directory):
                (Path(directory)/'tokenizer.json').write_text('{}')
        class FakeFastModel:
            @staticmethod
            def from_pretrained(**kwargs):
                testcase.assertEqual(kwargs['load_in_4bit'],False)
                return FakeModel(),FakeTokenizer()
            @staticmethod
            def get_peft_model(model,**kwargs):return model
        class FakeDataset:
            @staticmethod
            def from_list(items):return items
        class FakeTrainer:
            def __init__(self, *, train_dataset, args, **kwargs):
                testcase.assertEqual(len(train_dataset),16)
                testcase.assertEqual(args.max_steps,2)
                testcase.assertTrue(args.completion_only_loss)
            def train(self):
                weight.value = 1
                return types.SimpleNamespace(training_loss=1.25)
        gib=1024**3
        cuda=types.SimpleNamespace(is_available=lambda:True,is_bf16_supported=lambda:True,
                                   mem_get_info=lambda n: (12*gib,16*gib))
        mock_torch=types.ModuleType('torch');mock_torch.cuda=cuda
        mock_torch.any=lambda b:types.SimpleNamespace(item=lambda: b)
        mock_unsloth=types.ModuleType('unsloth');mock_unsloth.FastLanguageModel=FakeFastModel
        mock_datasets=types.ModuleType('datasets');mock_datasets.Dataset=FakeDataset
        mock_trl=types.ModuleType('trl');mock_trl.SFTTrainer=FakeTrainer
        mock_trl.SFTConfig=lambda **kwargs:types.SimpleNamespace(**kwargs)
        with patch.dict(sys.modules,{'unsloth':mock_unsloth,'torch':mock_torch,
                  'trl':mock_trl,'datasets':mock_datasets}):
            manifest=smoke.train()
        self.assertTrue(manifest['training_executed'])
        self.assertFalse(manifest['deployed'])
        self.assertEqual(manifest['sampled_lora_b_tensors_changed'],1)
        self.assertEqual(manifest['reserved_holdout_examples'],4)
        self.assertEqual(len(list(self.output.iterdir())),1)

    def test_synthetic_examples_are_separated(self):
        train, heldout = smoke._split()
        self.assertEqual(len(train), 16)
        self.assertEqual(len(heldout), 4)
        self.assertEqual(len(set(x['prompt'][0]['content'] for x in train+heldout)), 20)
        self.assertTrue(all(x['completion'][0]['role']=='assistant' for x in train))

if __name__=='__main__':
    unittest.main()
