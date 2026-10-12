"""Standard-library-only checks for safe 9B planning (no torch, model or network)."""
import contextlib
import io
import unittest
from unittest.mock import patch
from training import assess_9b


class Assess9BTests(unittest.TestCase):
    def baseline(self):
        return {
            "gpus": [{
                "model": "NVIDIA GeForce RTX 5080",
                "total_gib": 15.89, "free_gib": 14.47,
            }],
            "disk_free_gib_at_working_directory": 640.0,
        }

    def test_known_5080_is_not_bf16_training_ready(self):
        result = assess_9b.assess(self.baseline(), deps={
            "bitsandbytes": "0.49.0",
            "accelerate": "1.0.0",
        })
        self.assertEqual(
            result["bf16_single_gpu_capacity"],
            "does_not_meet_published_vram_estimate",
        )
        self.assertEqual(result["eight_bit_lora"],
                         "experimental_unverified_not_ready_to_train")
        self.assertFalse(result["downloads_started"])
        self.assertFalse(result["training_started"])
        self.assertFalse(result["live_ollama_modified"])
        self.assertFalse(result["existing_ollama_quantized_model_trainable_as_hf_base"])
        self.assertTrue(result["eight_bit_indicators"]["sufficient_disk_for_separate_9b_source"])
        self.assertEqual(result["official_source_weights_gb"], 19.31)

    def test_unknown_gpu_and_low_disk_are_handled_without_installing(self):
        result = assess_9b.assess({
            "gpus": [], "disk_free_gib_at_working_directory": None,
        }, deps={})
        self.assertIsNone(result["gpu_total_gib"])
        self.assertIsNone(result["gpu_free_gib"])
        self.assertFalse(result["eight_bit_indicators"]["gpu_detected"])
        self.assertFalse(result["eight_bit_indicators"]["bitsandbytes_installed"])
        self.assertFalse(result["eight_bit_indicators"]["sufficient_disk_for_separate_9b_source"])

    def test_more_vram_means_estimate_only_never_claims_training_ready(self):
        info = self.baseline()
        info["gpus"] = [{"total_gib": 48, "free_gib": 38}]
        result = assess_9b.assess(info, deps={})
        self.assertEqual(result["bf16_single_gpu_capacity"],
                         "meets_published_vram_estimate_only")
        self.assertNotIn("ready", result["bf16_single_gpu_capacity"])
        self.assertFalse(result["training_started"])

    def test_main_opt_in_check_never_reads_or_changes_models(self):
        stdout = io.StringIO()
        with patch.object(assess_9b, "snapshot", return_value=self.baseline()):
            with contextlib.redirect_stdout(stdout):
                code = assess_9b.main(["--check"])
        self.assertEqual(code, 0)
        self.assertIn("READ ONLY", stdout.getvalue())
        self.assertIn("NOT a suitable", stdout.getvalue())
        self.assertIn("No network, download, training, or changes made", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
