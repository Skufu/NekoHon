"""Reader routes: GET /chunks, CORS for the dev UI, and stream=1 frames.

The frame protocol is exercised with stubbed generation — no Ollama, no
index. The /chunks payload is a pure projection of an index dict; the live
route is checked against the real index when it exists on disk.
"""

import http.client
import json
import struct
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
import sys
from pathlib import Path
from unittest import mock

from engine.answering import answer
from engine import server
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixture_books import FixtureRoot
from engine.figures import figure_cards
from engine.answering.prompt import PARAPHRASE_SYSTEM, SPELL_SYSTEM, SYSTEM, SYSTEM_ANSWER
from engine.retrieval.retrieve import chunks_payload

FAKE_INDEX = {
    "book_id": "demo",
    "figures": [
        {"id": "figure-1-1", "chapter": "1", "caption": "A graph.",
         "file": "x.png"},
    ],
    "chunks": [
        {
            "chunk_id": "ch01-001", "chapter": "1",
            "heading": "What a Graph Is", "section": "What a Graph Is",
            "source": "ch01", "embedding": [0.5] * 4,
            "figures": ["figure-1-1"],
            "text": "What a Graph Is\nA graph is dots and lines.",
        },
        {
            "chunk_id": "ch01-002", "chapter": "1",
            "heading": "What a Graph Is", "section": "Edges",
            "source": "ch01", "embedding": [0.25] * 4,
            "figures": [],
            "text": "What a Graph Is\nAn edge joins two dots.",
        },
    ],
}


class ChunksPayloadTest(unittest.TestCase):
    def setUp(self):
        self.payload = chunks_payload(FAKE_INDEX)

    def test_reading_order_and_no_vectors(self):
        ids = [chunk["chunk_id"] for chunk in self.payload["chunks"]]
        self.assertEqual(ids, ["ch01-001", "ch01-002"])
        for chunk in self.payload["chunks"]:
            self.assertNotIn("embedding", chunk)

    def test_the_leading_heading_line_is_dropped_from_the_text(self):
        self.assertEqual(
            self.payload["chunks"][0]["text"], "A graph is dots and lines."
        )
        self.assertEqual(self.payload["chunks"][0]["heading"], "What a Graph Is")

    def test_figures_arrive_as_cards(self):
        self.assertEqual(
            self.payload["chunks"][0]["figures"],
            [{"id": "figure-1-1", "chapter": "1", "caption": "A graph.",
              "src": "/figures/figure-1-1?book_id=demo"}],
        )
        self.assertEqual(self.payload["chunks"][1]["figures"], [])


class ReaderRouteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = FixtureRoot().__enter__()
        cls.addClassCleanup(cls.fixture.__exit__, None, None, None)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.httpd.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=5)

    def request(self, method, path, payload=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        body = json.dumps(payload) if payload is not None else None
        head = {"Content-Type": "application/json"}
        head.update(headers or {})
        connection.request(method, path, body=body, headers=head)
        response = connection.getresponse()
        data = response.read()
        status = response.status
        response_headers = dict(response.getheaders())
        connection.close()
        return status, response_headers, data

    def test_chunks_answers_or_says_the_index_is_missing(self):
        status, _, data = self.request("GET", "/chunks")
        if server.load_book() is None:
            self.assertEqual(status, 500)
            return
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertTrue(payload["chunks"])
        for chunk in payload["chunks"]:
            self.assertNotIn("embedding", chunk)

    def test_cors_echoes_only_the_known_origins(self):
        for origin in ("http://localhost:3100", "http://127.0.0.1:3200"):
            _, headers, _ = self.request(
                "GET", "/health", headers={"Origin": origin}
            )
            self.assertEqual(headers.get("Access-Control-Allow-Origin"), origin)
        _, headers, _ = self.request(
            "GET", "/health", headers={"Origin": "http://evil.example"}
        )
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_options_preflight(self):
        status, headers, _ = self.request("OPTIONS", "/ask")
        self.assertEqual(status, 204)
        self.assertIn("POST", headers.get("Access-Control-Allow-Methods", ""))
        self.assertIn("Content-Type",
                      headers.get("Access-Control-Allow-Headers", ""))

    def stream_frames(self, payload):
        status, headers, data = self.request("POST", "/ask", payload)
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Content-Type"),
                         "application/x-ndjson; charset=utf-8")
        return [json.loads(line)
                for line in data.decode("utf-8").splitlines() if line]

    def test_stream_frames(self):
        """Mode answer: the SYSTEM draft is held (the retry may discard it),
        so the retry is the first and only live generation and tokens arrive
        after its reset. Before the fix the draft streamed first and the pane
        wiped and re-streamed it."""
        def fake_respond(index, question, generate_fn=None, **kwargs):
            generate_fn(SYSTEM, "user", "model")
            generate_fn(SYSTEM, "user", "model", prefill="[Ch. ")
            return {"answer": "A graph is dots and lines. [Ch. 1]",
                    "citations": [], "figures": [], "refused": False}

        def fake_stream(system, user, model=None, prefill="", on_token=None,
                        **kwargs):
            for piece in ("A graph ", "is dots."):
                if on_token:
                    on_token(piece)
            return "A graph is dots."

        with mock.patch.object(server, "respond", fake_respond), \
                mock.patch.object(server, "ollama_generate_stream", fake_stream):
            frames = self.stream_frames(
                {"mode": "answer", "question": "what is a graph?", "stream": 1})
        types = [frame["type"] for frame in frames]
        self.assertEqual(types, ["reset", "token", "token", "final"])
        # No token frame may precede the reset: that is the load-back-again bug.
        self.assertEqual(types.index("reset"), 0)
        self.assertEqual(frames[1]["text"], "A graph ")
        self.assertEqual(frames[-1]["body"]["answer"],
                         "A graph is dots and lines. [Ch. 1]")

    def test_ask_mode_streams_the_main_generation_from_the_first_frame(self):
        """Ask mode has no retry: its single SYSTEM generation is the answer
        and streams live from the first frame, with no reset before it."""
        def fake_ask(index, question, generate_fn=None, **kwargs):
            generate_fn(SYSTEM, "user", "model")
            return {"answer": "A graph is dots. [Ch. 1]", "citations": [],
                    "figures": [], "refused": False}

        def fake_stream(system, user, model=None, prefill="", on_token=None,
                        **kwargs):
            if on_token:
                on_token("A graph ")
                on_token("is dots.")
            return "A graph is dots."

        with mock.patch.object(server, "ask", fake_ask), \
                mock.patch.object(server, "ollama_generate_stream", fake_stream):
            frames = self.stream_frames(
                {"mode": "ask", "question": "what is a graph?", "stream": 1})
        self.assertEqual([frame["type"] for frame in frames],
                         ["token", "token", "final"])
        self.assertEqual(frames[0]["text"], "A graph ")

    def test_the_prefill_retry_streams_live(self):
        """The `[Ch. ` retry is live even as the first generation: its
        continuation is what the parse turns into the body."""
        seen = {}

        def fake_respond(index, question, generate_fn=None, **kwargs):
            generate_fn(SYSTEM, "user", "model", prefill="[Ch. ")
            return {"answer": "[Ch. 1] A graph is dots. [Ch. 1]",
                    "citations": [], "figures": [], "refused": False}

        def fake_stream(system, user, model=None, prefill="", on_token=None,
                        **kwargs):
            seen["prefill"] = prefill
            if on_token:
                on_token("[Ch. 1] A graph ")
                on_token("is dots.")
            return "[Ch. 1] A graph is dots."

        with mock.patch.object(server, "respond", fake_respond), \
                mock.patch.object(server, "ollama_generate_stream", fake_stream):
            frames = self.stream_frames(
                {"mode": "answer", "question": "what is a graph?", "stream": 1})
        self.assertEqual(seen["prefill"], "[Ch. ")
        self.assertEqual([frame["type"] for frame in frames],
                         ["token", "token", "final"])

    def test_plain_register_draft_and_rewrites_are_held(self):
        """The plain-register draft (SYSTEM_ANSWER) and its rewrites
        (PARAPHRASE_SYSTEM) are assembled at the end: no token frames."""
        calls = []

        def fake_respond(index, question, generate_fn=None, **kwargs):
            generate_fn(SYSTEM_ANSWER, "user", "model")
            generate_fn(PARAPHRASE_SYSTEM, "Sentence: A graph is dots.", "model")
            return {"answer": "A graph is dots. [Ch. 1]", "citations": [],
                    "figures": [], "refused": False}

        def fake_stream(system, user, model=None, prefill="", on_token=None,
                        **kwargs):
            calls.append((system, on_token))
            if on_token:
                on_token("must not stream")
            return "draft"

        with mock.patch.object(server, "respond", fake_respond), \
                mock.patch.object(server, "ollama_generate_stream", fake_stream):
            frames = self.stream_frames(
                {"mode": "answer", "stream": 1,
                 "question": "explain a graph in simple words"})
        self.assertEqual([frame["type"] for frame in frames],
                         ["reset", "final"])
        self.assertEqual([system for system, _ in calls],
                         [SYSTEM_ANSWER, PARAPHRASE_SYSTEM])
        self.assertTrue(all(on_token is None for _, on_token in calls))

    def test_the_reading_repair_is_held_and_the_ask_that_follows_streams(self):
        """The spelling repair (SPELL_SYSTEM) runs before the answer in ask
        mode; it is provisional, so it emits no tokens — the SYSTEM call that
        follows streams after its reset."""
        def fake_ask(index, question, generate_fn=None, **kwargs):
            generate_fn(SPELL_SYSTEM, 'User query: "grahp"', "model")
            generate_fn(SYSTEM, "user", "model")
            return {"answer": "A graph is dots. [Ch. 1]", "citations": [],
                    "figures": [], "refused": False}

        def fake_stream(system, user, model=None, prefill="", on_token=None,
                        **kwargs):
            if on_token:
                on_token("A graph ")
            return "A graph "

        with mock.patch.object(server, "ask", fake_ask), \
                mock.patch.object(server, "ollama_generate_stream", fake_stream):
            frames = self.stream_frames(
                {"mode": "ask", "question": "what is a grahp?", "stream": 1})
        self.assertEqual([frame["type"] for frame in frames],
                         ["reset", "token", "final"])

    def test_stream_error_frame(self):
        def broken(index, question, generate_fn=None, **kwargs):
            raise RuntimeError("boom")

        with mock.patch.object(server, "respond", broken):
            status, _, data = self.request(
                "POST", "/ask",
                {"mode": "answer", "question": "what is a graph?", "stream": 1},
            )
        self.assertEqual(status, 200)
        frames = [json.loads(line)
                  for line in data.decode("utf-8").splitlines() if line]
        self.assertEqual(
            frames,
            [{"type": "error", "error": "answer model unavailable"}],
        )


class FigureCardsTest(unittest.TestCase):
    def test_size_comes_from_the_png_header(self):
        head = (b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR"
                + struct.pack(">II", 600, 300))
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "x.png").write_bytes(head)
            cards = figure_cards(["figure-1-1"], FAKE_INDEX["figures"],
                                 figures_dir=folder)
        self.assertEqual(cards[0]["width"], 600)
        self.assertEqual(cards[0]["height"], 300)

    def test_a_missing_file_still_yields_a_card(self):
        cards = figure_cards(["figure-1-1"], FAKE_INDEX["figures"],
                             figures_dir="no-such-dir")
        self.assertEqual(cards[0]["id"], "figure-1-1")
        self.assertNotIn("width", cards[0])


class PrefillStreamTest(unittest.TestCase):
    """The token stream carries the prefill; the return stays the continuation."""

    class FakeResponse:
        def __init__(self, lines):
            self._lines = lines

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def __iter__(self):
            return iter(self._lines)

    def test_the_prefill_leads_the_token_stream(self):
        lines = [
            b'{"message": {"content": "7] A graph is dots."}}\n',
            b'{"done": true, "message": {"content": ""}}\n',
        ]
        seen = []
        with mock.patch.object(
            urllib.request,
            "urlopen",
            return_value=self.FakeResponse(lines),
        ):
            text = answer.ollama_generate_stream(
                "system", "user", "model", prefill="[Ch. ", on_token=seen.append
            )
        # The pane shows the whole text ([Ch. 7]…), never a bare `7]…`.
        self.assertEqual(seen, ["[Ch. ", "7] A graph is dots."])
        # The callers still prepend the prefill themselves.
        self.assertEqual(text, "7] A graph is dots.")


if __name__ == "__main__":
    unittest.main()
