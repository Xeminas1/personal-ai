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
            pad_token_id = 0
            def apply_chat_template(self, messages, *, tokenize, add_generation_prompt, enable_thinking):
                testcase.assertFalse(enable_thinking)
                testcase.assertFalse(tokenize)
                prefix = ('<|im_start|>user\\n' + messages[0]['content']
                          + '<|im_end|>\\n<|im_start|>assistant\\n<think>\\n\\n</think>\\n\\n')
                if add_generation_prompt:
                    return prefix
                return prefix + messages[-1]['content'] + '<|im_end|>\\n'
            def encode(self, rendered_text, *, add_special_tokens):
                testcase.assertFalse(add_special_tokens)
                return [ord(ch) for ch in rendered_text]
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
            def __init__(self, *, train_dataset, args, data_collator, **kwargs):
                testcase.assertEqual(len(train_dataset),16)
                testcase.assertEqual(args.max_steps,2)
                testcase.assertFalse(args.remove_unused_columns)
                batch=data_collator([train_dataset[0]])
                masked=batch['labels'].values[0]
                testcase.assertTrue(-100 in masked)
                testcase.assertTrue(any(t>=0 for t in masked))
                testcase.assertEqual(len(batch['input_ids'].values[0]),len(masked))
            def train(self):
                weight.value = 1
                return types.SimpleNamespace(training_loss=1.25)
        gib=1024**3
        cuda=types.SimpleNamespace(is_available=lambda:True,is_bf16_supported=lambda:True,
                                   mem_get_info=lambda n: (12*gib,16*gib))
        mock_torch=types.ModuleType('torch');mock_torch.cuda=cuda
        mock_torch.any=lambda b:types.SimpleNamespace(item=lambda: b)
        mock_torch.long=object()
        mock_torch.tensor=lambda values, dtype: types.SimpleNamespace(values=values)
        mock_unsloth=types.ModuleType('unsloth');mock_unsloth.FastLanguageModel=FakeFastModel
        mock_datasets=types.ModuleType('datasets');mock_datasets.Dataset=FakeDataset
        mock_transformers=types.ModuleType('transformers')
        mock_transformers.Trainer=FakeTrainer
        mock_transformers.TrainingArguments=lambda **kwargs:types.SimpleNamespace(**kwargs)
        with patch.dict(sys.modules,{'unsloth':mock_unsloth,'torch':mock_torch,
                  'transformers':mock_transformers,'datasets':mock_datasets}):
            manifest=smoke.train()
        self.assertTrue(manifest['training_executed'])
        self.assertFalse(manifest['deployed'])
        self.assertEqual(manifest['sampled_lora_b_tensors_changed'],1)
        self.assertEqual(manifest['reserved_holdout_examples'],4)
        self.assertEqual(len(list(self.output.iterdir())),1)

    def test_qwen_template_normalization_masks_prompt_not_answer(self):
        class FakeQwen:
            pad_token_id = 0
            def apply_chat_template(self, messages, *, tokenize, add_generation_prompt, enable_thinking):
                self._last_flags = (tokenize, add_generation_prompt, enable_thinking)
                self_prefix = "<|im_start|>user\n" + messages[0]["content"] + "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
                return self_prefix if add_generation_prompt else self_prefix + messages[-1]["content"] + "<|im_end|>\n"
            def encode(self, text, *, add_special_tokens):
                self._encode_special = add_special_tokens
                return list(text.encode("utf-8"))
        tok = FakeQwen()
        examples, _ = smoke._split()
        rows = smoke._prepare_tokenized_data(tok, examples)
        self.assertEqual(len(rows), 16)
        self.assertTrue(all(row["labels"].count(-100) > 0 for row in rows))
        self.assertTrue(all(any(token != -100 for token in row["labels"]) for row in rows))
        self.assertEqual(tok._last_flags[-1], False)
        self.assertFalse(tok._encode_special)
        expected = list(('"'+examples[0]['completion'][0]['content']+'"').encode("utf-8"))
        self.assertIn(ord(examples[0]["completion"][0]["content"][0]), rows[0]["labels"])
        self.assertGreater(len(expected), 0)

    def test_qwen_thinking_prefix_mismatch_fails_before_training(self):
        class ThinkingOnly:
            def apply_chat_template(self, messages, *, tokenize, add_generation_prompt, enable_thinking):
                return "prompt<think>\n" if add_generation_prompt else "prompt<think>\n\n</think>\nresponse"
            def encode(self, text, *, add_special_tokens):
                return list(text.encode("utf-8"))
        examples, _ = smoke._split()
        with self.assertRaisesRegex(smoke.PilotError, "prefix"):
            smoke._prepare_tokenized_data(ThinkingOnly(), examples)
        self.assertFalse(self.output.exists())

    def test_cpu_tokenizer_preflight_runs_without_cuda_or_training(self):
        class FakeQwen:
            def apply_chat_template(self, messages, *, tokenize, add_generation_prompt, enable_thinking):
                prefix = "user\n"+messages[0]["content"]+"\nassistant\n<think>\n\n</think>\n\n"
                return prefix if add_generation_prompt else prefix+messages[-1]["content"]+"<|im_end|>"
            def encode(self, text, *, add_special_tokens):
                return list(text.encode("utf-8"))
        transformers = types.ModuleType("transformers")
        class AutoTokenizer:
            @staticmethod
            def from_pretrained(name, **kwargs):
                self.assertTrue(kwargs.get("local_files_only"))
                return FakeQwen()
        transformers.AutoTokenizer = AutoTokenizer
        output = io.StringIO()
        with patch.dict(sys.modules, {"transformers": transformers}), contextlib.redirect_stdout(output):
            self.assertEqual(smoke.main(["--tokenizer-check"]), 0)
        self.assertIn("supervised answer tokens:", output.getvalue())
        self.assertFalse(self.output.exists())

    def test_synthetic_examples_are_separated(self):
        train, heldout = smoke._split()
        self.assertEqual(len(train), 16)
        self.assertEqual(len(heldout), 4)
        self.assertEqual(len(set(x['prompt'][0]['content'] for x in train+heldout)), 20)
        self.assertTrue(all(x['completion'][0]['role']=='assistant' for x in train))

if __name__=='__main__':
    unittest.main()
