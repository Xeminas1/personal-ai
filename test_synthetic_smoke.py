"""CPU-only synthetic validation of the local Qwen 4B pilot's strict gates."""
import contextlib
import io
import json
import tempfile
import unittest
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

    def test_synthetic_examples_are_separated(self):
        train, heldout = smoke._split()
        self.assertEqual(len(train), 16)
        self.assertEqual(len(heldout), 4)
        self.assertEqual(len(set(x['prompt'][0]['content'] for x in train+heldout)), 20)
        self.assertTrue(all(x['completion'][0]['role']=='assistant' for x in train))

if __name__=='__main__':
    unittest.main()
