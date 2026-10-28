"""Held-out synthetic checks for the self-source identifier guard.

All fixtures are invented. These complement, and do not replace,
test_xemai_self_source_routing.py.
"""
import json
import unittest

from app.developer_guidance import (
    source_answer_needs_retry,
    unsupported_identifier_claims,
)

_RECORDS = [
    {"path": "app/tools.py",
     "content": "class ToolRegistry:\n    def register(self):\n        return build_tool_table()\n"},
    {"path": "app/developer_projects.py",
     "content": "class DeveloperProjects:\n    def read_file(self, path):\n        return None\n"},
]
_CONTEXT = (
    "VERIFIED READ-ONLY DEVELOPMENT FILE CONTENTS\n"
    "The application read the following files. Do not claim to have read other "
    "files. Identify the functions and paths you actually examined.\n"
    + json.dumps(_RECORDS)
)
_PAD = (" The wiring in tools.py and developer_projects.py was reviewed in "
        "detail for this request.") * 3
_QUESTION = "inspect tools.py and developer_projects.py"


def _retry(answer):
    return source_answer_needs_retry(_QUESTION, answer + _PAD, _CONTEXT)


class FalseNegatives(unittest.TestCase):
    """Invented identifiers must be caught across phrasings."""

    def test_keyword_claim(self):
        self.assertTrue(_retry("I found class DevTaskAgent in tools.py and developer_projects.py."))

    def test_verb_then_camelcase_without_noun(self):
        self.assertTrue(_retry("tools.py defines DeveloperProjectsManager; developer_projects.py is read-only."))

    def test_call_claim(self):
        self.assertTrue(_retry("In tools.py the helper `save_patch()` applies edits; developer_projects.py reads."))

    def test_list_claim(self):
        self.assertTrue(_retry("tools.py and developer_projects.py contain:\n- class ProjectPatch\n- class TestSuite"))

    def test_prefix_of_real_name_is_not_support(self):
        self.assertTrue(_retry("tools.py defines the class Tool and developer_projects.py defines the class Developer."))

    def test_instruction_text_is_not_evidence(self):
        # 'examined' appears only in the instruction paragraph, not in a file.
        self.assertEqual(unsupported_identifier_claims("It defines the class Examined here.", _CONTEXT), ["Examined"])


class FalsePositives(unittest.TestCase):
    """Truthful answers must not be sent back for retry."""

    def test_real_classes(self):
        self.assertFalse(_retry("tools.py defines class ToolRegistry and developer_projects.py defines class DeveloperProjects."))

    def test_real_call(self):
        self.assertFalse(_retry("tools.py calls `build_tool_table()`; developer_projects.py exposes read_file."))

    def test_explicit_negative_finding(self):
        self.assertFalse(_retry("tools.py does not contain class DevTaskAgent, and developer_projects.py has no ProjectPatch."))

    def test_never_claimed(self):
        self.assertFalse(_retry("Neither tools.py nor developer_projects.py defines the class SandboxRunner."))

    def test_ordinary_prose_with_keywords(self):
        self.assertFalse(_retry("This class of problem shows up when a function is reused; tools.py and developer_projects.py stay read-only."))

    def test_no_context_means_no_claims(self):
        self.assertEqual(unsupported_identifier_claims("It defines class Anything.", "no evidence"), [])


if __name__ == "__main__":
    unittest.main()
