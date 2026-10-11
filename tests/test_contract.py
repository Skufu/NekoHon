"""Contract test: the window builds against this fixture before the live server.

The 200 body is locked in README.md ("Contract"): keys answer, citations,
figures, refused. This test fails if the fixture drifts from that shape.
"""

import json
import unittest
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "ask_response.json"


class AskResponseContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with FIXTURE.open(encoding="utf-8") as handle:
            cls.response = json.load(handle)

    def test_top_level_keys(self):
        for key in ("answer", "citations", "figures", "refused"):
            self.assertIn(key, self.response)

    def test_types(self):
        self.assertIsInstance(self.response["answer"], str)
        self.assertIsInstance(self.response["citations"], list)
        self.assertIsInstance(self.response["figures"], list)
        self.assertIsInstance(self.response["refused"], bool)

    def test_citation_shape(self):
        for citation in self.response["citations"]:
            for key in ("chunk_id", "chapter", "quote"):
                self.assertIn(key, citation)

    def test_figure_shape(self):
        for figure in self.response["figures"]:
            for key in ("id", "chapter", "caption", "src"):
                self.assertIn(key, figure)


if __name__ == "__main__":
    unittest.main()
