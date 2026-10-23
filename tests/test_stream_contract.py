import io
import json
import unittest
from contextlib import redirect_stderr
from unittest import mock

from engine import server
BOOK = {
    "chunks": [{
        "chunk_id": "c1",
        "chapter": "1",
        "text": "Change data capture streams row-level changes.",
    }],
    "figures": [],
}
REQUEST = {"mode": "ask", "question": "CDC", "stream": 1}


class DirectHandler(server.Handler):
    def __init__(self, wfile):
        self.wfile = wfile
        self.rfile = io.BytesIO(b"")
        self.headers = {}
        self.command = "POST"
        self.requestline = "POST /ask HTTP/1.1"
        self.request_version = "HTTP/1.1"
        self.client_address = ("127.0.0.1", 0)
        self.connection = None


class StreamContractTest(unittest.TestCase):
    def stream(self, book=BOOK, request=REQUEST, patched="ask", raiser=None):
        wfile = io.BytesIO()
        if patched:
            with mock.patch.object(server, patched, raiser):
                DirectHandler(wfile)._stream_ask(request, book)
        else:
            DirectHandler(wfile)._stream_ask(request, book)
        body = wfile.getvalue().split(b"\r\n\r\n", 1)[1]
        return [json.loads(line)
                for line in body.decode("utf-8").splitlines() if line]

    def assert_ends_with_error(self, frames, error=None):
        self.assertEqual(frames[-1]["type"], "error")
        self.assertTrue(frames[-1].get("error"))
        self.assertNotIn("final", [frame["type"] for frame in frames])
        if error is not None:
            self.assertEqual(frames[-1]["error"], error)
        return frames[-1]

    def test_runtime_error_from_ask_emits_an_error_frame(self):
        def boom(index, question, generate_fn=None, **kwargs):
            raise RuntimeError("boom")

        frames = self.stream(raiser=boom)
        self.assert_ends_with_error(frames, "answer model unavailable")

    def test_any_other_exception_still_frames_an_error(self):
        def boom(index, question, generate_fn=None, **kwargs):
            raise KeyError("blew up mid-stream")

        stderr = io.StringIO()
        with redirect_stderr(stderr):
            frames = self.stream(raiser=boom)
        self.assert_ends_with_error(frames, "engine error: 'blew up mid-stream'")
        self.assertIn("Traceback", stderr.getvalue())

    def test_value_error_frames_its_message(self):
        def refuses(index, question, generate_fn=None, **kwargs):
            raise ValueError("question too long")

        frames = self.stream(raiser=refuses)
        self.assert_ends_with_error(frames, "question too long")

    def test_system_exit_frames_an_index_error(self):
        def refuses(index, question, generate_fn=None, **kwargs):
            raise SystemExit("bad chunk index")

        frames = self.stream(raiser=refuses)
        self.assert_ends_with_error(frames, "index error: bad chunk index")

    def test_a_healthy_stream_ends_with_final(self):
        def fake_ask(index, question, generate_fn=None, **kwargs):
            return {"answer": "Change data capture. [Ch. 1]", "citations": [],
                    "figures": [], "refused": False}

        frames = self.stream(raiser=fake_ask)
        self.assertEqual([frame["type"] for frame in frames], ["final"])
        self.assertEqual(frames[-1]["body"]["answer"],
                         "Change data capture. [Ch. 1]")


if __name__ == "__main__":
    unittest.main()
