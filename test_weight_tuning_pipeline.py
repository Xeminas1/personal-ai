"""Real (CPU) training of a tiny Qwen3.5-architecture model through training/xemai_tune.py.

Not a mock: gradients flow through genuine LoRA layers on the hybrid
linear-attention + full-attention Qwen3.5 blocks, the held-out loss is measured
before and after, and the gate decides. Skipped when torch/transformers/peft are
not installed (the app itself never needs them).
"""
from __future__ import annotations

import importlib.util
import json
import random
import tempfile
import unittest
import unittest.mock
from pathlib import Path

HAS_STACK = all(importlib.util.find_spec(m) for m in ("torch", "transformers", "peft", "tokenizers"))

COLOURS = ["red", "blue", "green", "amber", "violet", "silver", "orange", "teal"]
THINGS = ["kettle", "bicycle", "garden", "lamp", "window", "boat", "piano", "tent",
          "clock", "drum", "scarf", "chair", "train", "kite", "mug", "rug"]


def synthetic_rows(count: int = 24) -> list[dict]:
    """Invented owner-style corrections that all follow one learnable answer style."""
    rng = random.Random(3)
    rows = []
    for index in range(count):
        thing, colour = THINGS[index % len(THINGS)], rng.choice(COLOURS)
        rows.append({"source": "teach", "messages": [
            {"role": "user", "content": f"what colour is the {thing} number {index}"},
            {"role": "assistant", "content": f"Short answer: the {thing} is {colour}. Anything else?"},
        ]})
    return rows


def build_tiny_model(directory: Path) -> None:
    import torch
    from tokenizers import Tokenizer, models, pre_tokenizers
    from transformers import PreTrainedTokenizerFast, Qwen3_5ForCausalLM, Qwen3_5TextConfig

    from training.xemai_tune import ANCHOR_EVAL_PROMPTS, ANCHOR_TRAIN_PROMPTS

    specials = ["<|endoftext|>", "<|im_start|>", "<|im_end|>", "<unk>"]
    words = set()
    texts = [m["content"] for row in synthetic_rows(64) for m in row["messages"]]
    texts += ANCHOR_TRAIN_PROMPTS + ANCHOR_EVAL_PROMPTS + ["user", "assistant", "system"]
    for text in texts:
        words.update(pre_tokenizers.Whitespace().pre_tokenize_str(text) and
                     [w for w, _ in pre_tokenizers.Whitespace().pre_tokenize_str(text)])
    vocab = {token: i for i, token in enumerate(specials + sorted(words))}
    raw = Tokenizer(models.WordLevel(vocab=vocab, unk_token="<unk>"))
    raw.pre_tokenizer = pre_tokenizers.Whitespace()
    tokenizer = PreTrainedTokenizerFast(tokenizer_object=raw, unk_token="<unk>", eos_token="<|im_end|>",
                                        pad_token="<|endoftext|>")
    tokenizer.chat_template = (
        "{% for m in messages %}<|im_start|> {{ m['role'] }} {{ m['content'] }} <|im_end|> {% endfor %}"
        "{% if add_generation_prompt %}<|im_start|> assistant {% endif %}"
    )
    tokenizer.save_pretrained(directory)
    config = Qwen3_5TextConfig(
        vocab_size=len(vocab), hidden_size=64, intermediate_size=128, num_hidden_layers=4,
        num_attention_heads=4, num_key_value_heads=2, head_dim=16,
        linear_num_key_heads=2, linear_num_value_heads=4, linear_key_head_dim=16, linear_value_head_dim=16,
        layer_types=["linear_attention", "full_attention", "linear_attention", "full_attention"],
        max_position_embeddings=512, pad_token_id=tokenizer.pad_token_id,
        eos_token_id=tokenizer.eos_token_id, bos_token_id=tokenizer.eos_token_id, tie_word_embeddings=False,
    )
    torch.manual_seed(0)
    Qwen3_5ForCausalLM(config).save_pretrained(directory)


@unittest.skipUnless(HAS_STACK, "torch/transformers/peft not installed")
class WeightTuningPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.model_dir = cls.root / "tiny"
        build_tiny_model(cls.model_dir)
        cls.dataset = cls.root / "dataset.jsonl"
        cls.dataset.write_text("\n".join(json.dumps(r) for r in synthetic_rows()) + "\n", encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_pipeline(self, run_name: str, *extra: str) -> dict:
        from training import xemai_tune

        run_dir = self.root / run_name
        args = xemai_tune.parser().parse_args([
            "run", "--dataset", str(self.dataset), "--run-dir", str(run_dir),
            "--ollama-base", "qwen3.5:9b-q8_0", "--model-path", str(self.model_dir),
            "--skip-export", "--dtype", "float32", "--epochs", "8", "--lr", "3e-3",
            "--grad-accum", "2", "--rank", "8", "--max-len", "128",
            "--anchor-count", "4", "--anchor-tokens", "8", "--max-drift", "100", *extra,
        ])
        report = xemai_tune.run(args)
        self.assertEqual(json.loads((run_dir / "report.json").read_text())["passed"], report["passed"])
        return report

    def test_real_training_lowers_heldout_loss_and_passes_gate(self):
        report = self.run_pipeline("r1")
        print("\nTINY-MODEL EVAL:", json.dumps(report["evaluation"]), report["training"])
        self.assertTrue(report["passed"], report.get("error"))
        evaluation = report["evaluation"]
        self.assertGreater(report["holdout"], 1)
        self.assertGreater(evaluation["holdout_gain"], 0.5)  # the style was genuinely learned
        self.assertLess(evaluation["holdout_nll_tuned"], evaluation["holdout_nll_base"])
        self.assertGreater(report["training"]["optimizer_steps"], 10)
        adapter = self.root / "r1" / "adapter"
        self.assertTrue((adapter / "adapter_model.safetensors").is_file())
        from safetensors import safe_open

        keys = list(safe_open(str(adapter / "adapter_model.safetensors"), "pt").keys())
        targets = {k.split(".lora_")[0].rsplit(".", 1)[-1] for k in keys}
        # Both Qwen3.5 attention kinds are adapted, plus the MLP.
        self.assertTrue({"q_proj", "v_proj", "o_proj"} <= targets, targets)
        self.assertTrue(any("in_proj" in t for t in targets), targets)  # gated DeltaNet layers
        self.assertTrue({"gate_proj", "up_proj", "down_proj"} <= targets, targets)
        self.assertNotIn("lm_head", targets)
        self.assertEqual(json.loads((self.root / "r1" / "status.json").read_text())["stage"], "ready")

    def test_multimodal_qwen35_trains_language_layers_only(self):
        import torch
        from transformers import AutoTokenizer, Qwen3_5Config, Qwen3_5ForConditionalGeneration
        from training import xemai_tune

        text = json.loads((self.model_dir / "config.json").read_text())
        config = Qwen3_5Config(
            text_config={k: v for k, v in text.items()
                         if k not in {"architectures", "model_type", "transformers_version", "dtype"}},
            vision_config=dict(depth=1, hidden_size=32, intermediate_size=64, num_heads=2, out_hidden_size=64,
                               patch_size=14, spatial_merge_size=2, temporal_patch_size=2),
        )
        torch.manual_seed(0)
        mm = self.root / "tiny-mm"
        Qwen3_5ForConditionalGeneration(config).save_pretrained(mm)
        AutoTokenizer.from_pretrained(self.model_dir).save_pretrained(mm)
        self.assertEqual(xemai_tune.model_class(str(mm)).__name__, "AutoModelForImageTextToText")
        original = self.model_dir
        try:
            type(self).model_dir = mm
            report = self.run_pipeline("r4")
        finally:
            type(self).model_dir = original
        self.assertTrue(report["passed"], report.get("error"))
        self.assertGreater(report["evaluation"]["holdout_gain"], 0.5)
        from safetensors import safe_open

        keys = list(safe_open(str(self.root / "r4" / "adapter" / "adapter_model.safetensors"), "pt").keys())
        self.assertTrue(keys and all(".language_model." in k for k in keys), keys[:3])
        self.assertFalse(any("visual" in k for k in keys))

    def test_gate_blocks_insufficient_improvement(self):
        report = self.run_pipeline("r2", "--min-gain", "1000")
        self.assertFalse(report["passed"])
        self.assertIn("Not deployed", report["error"])
        self.assertEqual(json.loads((self.root / "r2" / "status.json").read_text())["stage"], "failed")

    def test_gate_blocks_general_skill_drift(self):
        report = self.run_pipeline("r3", "--max-drift", "-1000")
        self.assertFalse(report["passed"])
        self.assertIn("drift", report["error"])


FAKE_OLLAMA = r'''#!{python}
import json, os, sys
log = os.environ["FAKE_OLLAMA_LOG"]
args = sys.argv[1:]
if args[:2] == ["show", "--modelfile"]:
    print('FROM /models/blob\nTEMPLATE """{{ .Prompt }}"""\nPARAMETER temperature 0.7\nRENDERER qwen3.5\nLICENSE """x"""')
    sys.exit(0)
if args[0] == "create":
    modelfile = open(args[args.index("-f") + 1]).read()
    with open(log, "a") as stream:
        stream.write(json.dumps({"args": args, "modelfile": modelfile}) + "\n")
    if "ADAPTER" in modelfile and os.environ.get("FAKE_ADAPTER_FAILS"):
        print("Error: unsupported architecture for adapters", file=sys.stderr)
        sys.exit(1)
    sys.exit(0)
sys.exit(2)
'''


@unittest.skipUnless(HAS_STACK, "torch/transformers/peft not installed")
class OllamaExportTests(unittest.TestCase):
    """The export path with a stand-in `ollama` CLI and chat API (no real Ollama here)."""

    def setUp(self):
        import os
        import stat
        import sys
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.model_dir = root / "tiny"
        build_tiny_model(self.model_dir)
        dataset = root / "d.jsonl"
        dataset.write_text("\n".join(json.dumps(r) for r in synthetic_rows()), encoding="utf-8")
        self.dataset, self.root = dataset, root
        bin_dir = root / "bin"
        bin_dir.mkdir()
        if os.name == "nt":
            (bin_dir / "fake_ollama.py").write_text(FAKE_OLLAMA.split("\n", 1)[1])
            (bin_dir / "ollama.cmd").write_text(f'@"{sys.executable}" "%~dp0fake_ollama.py" %*\r\n')
        else:
            script = bin_dir / "ollama"
            script.write_text(FAKE_OLLAMA.replace("{python}", sys.executable))
            script.chmod(script.stat().st_mode | stat.S_IEXEC)
        self.log = root / "ollama.log"
        env = {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "FAKE_OLLAMA_LOG": str(self.log)}
        patcher = unittest.mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.reply = "Hello there, nice to meet you."

        test = self

        class Chat(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                test.chat_models.append(body["model"])
                raw = json.dumps({"message": {"content": test.reply}}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *args):
                pass

        self.chat_models = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Chat)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close()))

    def run_export(self, run="r1"):
        from training import xemai_tune

        args = xemai_tune.parser().parse_args([
            "run", "--dataset", str(self.dataset), "--run-dir", str(self.root / run),
            "--ollama-base", "qwen3.5:9b-q8_0", "--model-path", str(self.model_dir),
            "--dtype", "float32", "--epochs", "6", "--lr", "3e-3", "--grad-accum", "2", "--rank", "8",
            "--max-len", "128", "--anchor-count", "2", "--anchor-tokens", "4", "--max-drift", "100",
            "--ollama-url", f"http://127.0.0.1:{self.server.server_port}", "--name", f"xemai-qwen-tuned:{run}",
        ])
        return xemai_tune.run(args)

    def creates(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_adapter_on_base_model_is_tried_first_and_keeps_template(self):
        report = self.run_export()
        self.assertTrue(report["passed"], report.get("error"))
        self.assertEqual((report["model"], report["strategy"]), ("xemai-qwen-tuned:r1", "ollama_adapter"))
        create = self.creates()[0]
        self.assertIn("FROM qwen3.5:9b-q8_0", create["modelfile"])
        self.assertIn("ADAPTER ", create["modelfile"])
        self.assertIn('TEMPLATE """{{ .Prompt }}"""', create["modelfile"])
        self.assertIn("RENDERER qwen3.5", create["modelfile"])
        self.assertNotIn("LICENSE", create["modelfile"])
        self.assertNotIn("/models/blob", create["modelfile"])
        self.assertEqual(set(self.chat_models), {"xemai-qwen-tuned:r1"})  # smoke-tested the NEW tag only

    def test_falls_back_to_merged_import_with_matching_quantisation(self):
        import os
        with unittest.mock.patch.dict(os.environ, {"FAKE_ADAPTER_FAILS": "1"}):
            report = self.run_export("r2")
        self.assertTrue(report["passed"], report.get("error"))
        self.assertEqual(report["strategy"], "ollama_import_merged")
        merged = self.creates()[-1]
        self.assertIn("--quantize", merged["args"])
        self.assertEqual(merged["args"][merged["args"].index("--quantize") + 1], "q8_0")
        self.assertTrue(merged["modelfile"].splitlines()[0].rstrip("/\\").endswith("merged"))
        self.assertFalse((self.root / "r2" / "merged").exists())  # large merge cleaned up
        self.assertTrue((self.root / "r2" / "adapter" / "adapter_model.safetensors").exists())

    def test_degenerate_output_is_not_offered(self):
        self.reply = "the the the the the the the the the the the the the the"
        report = self.run_export("r3")
        self.assertFalse(report["passed"])
        self.assertIn("could not load", report["error"])


class DatasetRulesTests(unittest.TestCase):
    def test_split_is_stable_disjoint_and_has_holdout(self):
        from training.xemai_tune import example_id, split_examples

        rows = [{"id": example_id(r["messages"]), **r} for r in synthetic_rows(30)]
        train, holdout = split_examples(rows)
        self.assertGreaterEqual(len(holdout), 2)
        self.assertFalse({r["id"] for r in train} & {r["id"] for r in holdout})
        self.assertEqual(len(train) + len(holdout), 30)
        self.assertEqual(split_examples(list(reversed(rows)))[1].__len__(), len(holdout))

    def test_too_few_examples_is_a_clear_refusal(self):
        from training import xemai_tune

        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "d.jsonl"
            data.write_text("\n".join(json.dumps(r) for r in synthetic_rows(4)), encoding="utf-8")
            report = xemai_tune.run(xemai_tune.parser().parse_args(
                ["run", "--dataset", str(data), "--run-dir", str(Path(tmp) / "r"), "--ollama-base", "qwen3:8b"]))
            self.assertFalse(report["passed"])
            self.assertIn("at least 10", report["error"])

    def test_malformed_rows_are_rejected(self):
        from training.xemai_tune import TuneError, load_examples

        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "d.jsonl"
            data.write_text(json.dumps({"messages": [{"role": "user", "content": "hi"}]}), encoding="utf-8")
            with self.assertRaises(TuneError):
                load_examples(data)

    def test_checkpoint_mapping(self):
        from training.xemai_tune import TuneError, checkpoint_for

        self.assertEqual(checkpoint_for("qwen3.5:9b-q8_0"), "Qwen/Qwen3.5-9B")
        self.assertEqual(checkpoint_for("qwen3:8b"), "Qwen/Qwen3-8B")
        self.assertEqual(checkpoint_for("qwen3:1.7b"), "Qwen/Qwen3-1.7B")
        self.assertEqual(checkpoint_for("anything", "Org/Custom"), "Org/Custom")
        with self.assertRaises(TuneError):
            checkpoint_for("llama3:8b")


if __name__ == "__main__":
    unittest.main()
