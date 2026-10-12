"""Synthetic checks for an explicit, no-auto-install Windows training helper."""
from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parent / "training" / "windows_setup.cmd"


class WindowsTrainingSetupTests(unittest.TestCase):
    def test_explicit_opt_in_and_isolation_in_source(self):
        text = SCRIPT.read_text(encoding="utf-8").lower()
        self.assertIn('if /i "%~1"=="--install" goto install', text)
        self.assertIn('if /i not "%confirm%"=="install"', text)
        self.assertIn('set "env_dir=%~dp0..\\data\\weight_training\\env_python313"', text)
        self.assertIn('uv python install 3.13', text)
        self.assertIn('uv pip install --python "%env_py%" unsloth --torch-backend=auto', text)
        self.assertNotIn('ollama rm', text)
        self.assertNotIn('git push', text)
        self.assertNotIn('--execute', text)
        self.assertNotIn('pip install --system', text)
        self.assertNotIn('uv pip install --system', text)
        self.assertNotIn('curl -', text)
        self.assertNotIn('irm https', text)

    @unittest.skipUnless(os.name == "nt", "Windows-only read-only CMD check")
    def test_windows_check_never_installs_or_calls_training(self):
        result = subprocess.run(
            ["cmd", "/d", "/c", str(SCRIPT), "--check"],
            capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("read-only", result.stdout.lower())
        self.assertIn("no installation, training or model changes", result.stdout.lower())


if __name__ == "__main__":
    unittest.main()
