"""Offline, synthetic validation of shared public project-handoff documents.

No GitHub API calls, local private data, model inference or Git credentials.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent

REQUIRED = {
    "AGENTS.md": (
        "Required start-of-session checklist",
        "Permission and safety boundaries",
        "Session checkpoints are mandatory",
        "First prompt for a new ChatGPT/Codex session",
    ),
    "docs/AI_COLLABORATION_RULES.md": (
        "Standing authorisation",
        "Private/public separation",
        "Shared ChatGPT",
        "What counts as learning",
    ),
    "docs/HANDOFF_PROTOCOL.md": (
        "One source of truth",
        "Required checkpoint block",
        "First minute of a new session",
        "Handoff between GPT and Codex",
    ),
    "docs/PROJECT_STATE.md": (
        "Snapshot checked",
        "Last verified released XemAi application",
        "Pending / unfinished work",
        "public-safe handoff index",
    ),
    ".github/ISSUE_TEMPLATE/development-work.md": (
        "Current handoff checkpoint",
        "Owner-approved scope",
        "Checks failed / not yet run",
    ),
}


class SharedHandoffTests(unittest.TestCase):
    def test_required_documents_and_headings_exist(self):
        for name, sections in REQUIRED.items():
            with self.subTest(path=name):
                value = (ROOT / name).read_text(encoding="utf-8")
                self.assertGreater(len(value.strip()), 400)
                for section in sections:
                    self.assertIn(section, value)

    def test_all_entrypoints_reference_the_handoff_protocol(self):
        for name in ("AGENTS.md", "docs/PROJECT_STATE.md",
                     "docs/AI_COLLABORATION_RULES.md"):
            with self.subTest(path=name):
                content = (ROOT / name).read_text(encoding="utf-8")
                self.assertIn("HANDOFF_PROTOCOL.md", content)

    def test_shared_docs_warn_about_public_private_boundary(self):
        for name in ("AGENTS.md", "docs/AI_COLLABORATION_RULES.md",
                     "docs/HANDOFF_PROTOCOL.md", "docs/PROJECT_STATE.md"):
            with self.subTest(path=name):
                content = (ROOT / name).read_text(encoding="utf-8").lower()
                self.assertIn("private", content)
                self.assertIn("public", content)

    def test_no_credentials_or_private_issue_links_in_shared_docs(self):
        for name in REQUIRED:
            content = (ROOT / name).read_text(encoding="utf-8")
            with self.subTest(path=name):
                self.assertNotRegex(content, r"(?i)github_pat_[a-z0-9_]{12,}")
                self.assertNotRegex(content, r"(?i)gh[pousr]_[a-z0-9]{20,}")
                self.assertNotRegex(content, r"(?i)sk-[a-z0-9_-]{20,}")
                self.assertNotRegex(content, r"https?://github\.com/[^\s)]+private-bridge/issues/")
                self.assertNotRegex(content, r"(?i)\\users\\[^\s]+")

    def test_checkpoint_has_resume_fields(self):
        content = (ROOT / "docs/HANDOFF_PROTOCOL.md").read_text(encoding="utf-8")
        for required in ("Main SHA checked:", "Last pushed HEAD:",
                         "Checks passed ON THAT HEAD:", "Checks failed / not yet run:",
                         "Next safe step:", "Privacy/rollback:"):
            self.assertIn(required, content)


if __name__ == "__main__":
    unittest.main()
