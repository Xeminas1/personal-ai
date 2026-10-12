"""Offline regression checks for the owner-consented public checkpoint download."""
from __future__ import annotations

import os
import re
import subprocess
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parent / "training" / "windows_model_download.cmd"
REV = "c7429d5a8ed57f4a9cfdaf1af76a8943eba0ae97"


class DownloadConsentTests(unittest.TestCase):
    def test_owner_explicitly_approves_pinned_public_model(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('set "MODEL=Qwen/Qwen3.5-4B"', source)
        self.assertIn('set "REV=' + REV + '"', source)
        self.assertIn('if /I "%~1"=="--download" goto DOWNLOAD', source)
        self.assertIn('if not "%CONFIRM%"=="DOWNLOAD"', source)
        self.assertIn('HF_HUB_DISABLE_IMPLICIT_TOKEN=1', source)
        self.assertIn('HF_HUB_DISABLE_TELEMETRY=1', source)
        self.assertIn('download %MODEL% --revision %REV% --local-dir "%MODEL_DIR%"', source)
        self.assertIn(r'env_python313\Scripts\hf.exe', source)
        self.assertIn(r'\data\weight_training', source)
        self.assertNotIn('ollama create', source.lower())
        self.assertNotIn('ollama rm', source.lower())
        self.assertNotIn('HF_TOKEN=', source)
        self.assertNotIn('--execute', source)
        self.assertNotIn('git push', source)
        self.assertNotIn('curl -', source)

    @unittest.skipUnless(os.name == "nt", "Windows-only no-action smoke check")
    def test_without_download_flag_performs_no_install_or_model_actions(self):
        result = subprocess.run(
            ["cmd", "/d", "/c", str(SCRIPT)],
            capture_output=True, text=True, check=False, timeout=10
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("no action selected", result.stdout.lower())
        self.assertNotIn("download was", result.stdout.lower())


if __name__ == "__main__":
    unittest.main()
