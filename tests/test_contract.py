"""Contract test: the window builds against this fixture before the live server.

The 200 body is locked in AGENTS.md ("HTTP contract"): keys answer, citations,
figures, refused. This test fails if the fixture drifts from that shape. It also
pins the route shape (only the documented routes answer) and the exact
refusal sentence, so server.py and prompt.py do not restate those rules.
"""

import http.client
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from engine.answering import prompt
from engine import server
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


class RouteShapeTest(unittest.TestCase):
    """Only the documented routes answer; everything else is 404."""

    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.httpd.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=5)

    def status(self, method, path, payload=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        body = json.dumps(payload) if payload is not None else None
        connection.request(
            method, path, body=body, headers={"Content-Type": "application/json"}
        )
        response = connection.getresponse()
        response.read()
        connection.close()
        return response.status

    def test_health_answers(self):
        self.assertEqual(self.status("GET", "/health"), 200)

    def test_an_unknown_route_is_404(self):
        self.assertEqual(self.status("GET", "/nope"), 404)
        self.assertEqual(self.status("GET", "/ask"), 404)
        self.assertEqual(self.status("POST", "/nope"), 404)

    def test_ask_rejects_a_mode_outside_the_contract(self):
        self.assertEqual(self.status("POST", "/ask", {"mode": "bogus"}), 400)
        self.assertEqual(self.status("POST", "/ask", {"mode": "ask"}), 400)


class PromptContractTest(unittest.TestCase):
    def test_the_four_modes_are_the_contract_modes(self):
        self.assertEqual(server.MODES, ("ask", "answer", "explain", "quiz"))

    def test_the_refusal_sentence_is_exact(self):
        self.assertEqual(prompt.REFUSAL, "Not in this book.")
        self.assertIn("Not in this book.", prompt.SYSTEM)
        self.assertIn("Not in this book.", prompt.SYSTEM_ANSWER)


if __name__ == "__main__":
    unittest.main()
