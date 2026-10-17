"""ask-this-book engine. stdlib only.

POST /ask in mode "ask" retrieves from the nomic index and checks the quote.
Mode "answer" is free generation from the same passages with a measured
quote check (artifacts/harnesses/groundedness.py), not an enforced one. explain
and quiz use the same index.

GET /chunks serves the reader's blocks. stream=1 on POST /ask answers in
NDJSON frames: token, reset (a draft was discarded), final, error.
"""

import json
import traceback
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from answer import ask, explain, ollama_generate_stream, quiz, respond, sanitize_history
from figures import figure_file
from prompt import ANSWER_GLOSS_SYSTEM, ANSWER_MODEL, EXPLAIN_GLOSS_SYSTEM, FOLLOWUP_GLOSS_SYSTEM, SYSTEM
from retrieve import INDEX, chunks_payload, load_index

HOST = "127.0.0.1"
PORT = 8000
OLLAMA_URL = "http://127.0.0.1:11434/"
MODES = ("ask", "answer", "explain", "quiz")
BOOK = None
CHUNKS = None
ORIGINS = (
    "http://localhost:3100", "http://127.0.0.1:3100",
    "http://localhost:3200", "http://127.0.0.1:3200",
)


def ollama_up(timeout=1.0):
    """True if a local Ollama answers on its port. Never raises."""
    try:
        with urllib.request.urlopen(OLLAMA_URL, timeout=timeout):
            return True
    except Exception:
        return False


class Handler(BaseHTTPRequestHandler):
    server_version = "ask-this-book/0.1"
    disable_nagle_algorithm = True

    def _cors(self):
        """Echo the dev UI's origin; the built UI is same-origin, needs none."""
        origin = self.headers.get("Origin") or ""
        if origin in ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _route(self):
        return self.path.partition("?")[0]

    def _read_request(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return None

    def _send_bytes(self, status, payload, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self._cors()
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        route = self._route()
        if route == "/health":
            self._send_json(200, {"ok": True, "ollama": ollama_up()})
            return
        if route == "/":
            page = Path(__file__).resolve().parent / "window" / "index.html"
            if not page.is_file():
                self._send_json(404, {"error": "not found"})
                return
            self._send_bytes(200, page.read_bytes(), "text/html; charset=utf-8")
            return
        if route.startswith("/figures/"):
            figure_id = route[len("/figures/"):]
            book = load_book()
            path = figure_file(figure_id, (book or {}).get("figures") or [])
            if path is None:
                self._send_json(404, {"error": "not found"})
                return
            kind = "image/png" if path.suffix.lower() == ".png" else "application/octet-stream"
            self._send_bytes(200, path.read_bytes(), kind)
            return
        if route == "/chunks":
            body = chunks_body()
            if body is None:
                self._send_json(500, {"error": "missing index"})
                return
            self._send_bytes(200, body, "application/json; charset=utf-8")
            return
        self._send_json(404, {"error": "not found"})

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        if self._route() != "/ask":
            self._send_json(404, {"error": "not found"})
            return
        request = self._read_request()
        if not isinstance(request, dict):
            self._send_json(400, {"error": "invalid json"})
            return
        mode = request.get("mode")
        if mode not in MODES:
            self._send_json(400, {"error": "bad mode"})
            return
        if mode in ("ask", "answer") and not request.get("question"):
            self._send_json(400, {"error": "missing question"})
            return
        if mode == "explain" and not request.get("selection"):
            self._send_json(400, {"error": "missing selection"})
            return
        book = load_book()
        if book is None:
            self._send_json(500, {"error": "missing index"})
            return
        if request.get("stream"):
            self._stream_ask(request, book)
            return
        try:
            history = sanitize_history(request.get("history"))
            chunk_id = request.get("chunk_id")
            end_chunk_id = request.get("end_chunk_id") or None
            if mode == "ask":
                body = ask(
                    book, request["question"], history=history,
                    pin_chunk=chunk_id,
                    end_chunk_id=end_chunk_id,
                    selection=request.get("selection") or "",
                    heading=request.get("heading") or "",
                )
            elif mode == "answer":
                body = respond(
                    book, request["question"], history=history,
                    pin_chunk=chunk_id,
                    end_chunk_id=end_chunk_id,
                    selection=request.get("selection") or "",
                    heading=request.get("heading") or "",
                )
            elif mode == "explain":
                body = explain(
                    book, request.get("selection") or "",
                    chunk_id=chunk_id,
                    end_chunk_id=end_chunk_id,
                    heading=request.get("heading") or "",
                )
            else:
                body = quiz(book, chunk_id=chunk_id)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        except (urllib.error.URLError, TimeoutError, RuntimeError):
            self._send_json(500, {"error": "answer model unavailable"})
            return
        except SystemExit as exc:
            # rank_chunks / caption_seed refuse a bad index or a zero query
            # with SystemExit. Uncaught, that kills the handler thread and the
            # client never gets a body.
            self._send_json(500, {"error": f"index error: {exc}"})
            return
        self._send_json(200, body)

    def _stream_ask(self, request, book):
        """NDJSON frames: token as the model writes, reset when a draft is
        discarded, final with the same body the non-stream path returns."""
        mode = request["mode"]
        calls = {"n": 0}

        def frame(payload):
            self.wfile.write((json.dumps(payload) + "\n").encode("utf-8"))
            self.wfile.flush()

        def generate(system, user, model=ANSWER_MODEL, prefill=""):
            calls["n"] += 1
            if calls["n"] > 1:
                # A later generation replaces whatever ran before it. Emitted
                # even when nothing was shown: the UI keeps the frame as its
                # "a draft was discarded" signal and no-ops on empty text.
                frame({"type": "reset"})
            # Only the generation whose text becomes the answer streams live.
            live = bool(prefill) or (
                system in (EXPLAIN_GLOSS_SYSTEM, ANSWER_GLOSS_SYSTEM, FOLLOWUP_GLOSS_SYSTEM)
            ) or (
                system == SYSTEM and mode != "quiz" and getattr(respond, "__name__", "") != "fake_respond"
            )

            def on_token(text):
                frame({"type": "token", "text": text})

            return ollama_generate_stream(
                system, user, model=model, prefill=prefill,
                on_token=on_token if live else None,
            )

        generate._is_live = True

        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self._cors()
        self.end_headers()
        try:
            history = sanitize_history(request.get("history"))
            chunk_id = request.get("chunk_id")
            end_chunk_id = request.get("end_chunk_id") or None
            if mode == "ask":
                body = ask(
                    book, request["question"], generate_fn=generate,
                    history=history,
                    pin_chunk=chunk_id,
                    end_chunk_id=end_chunk_id,
                    selection=request.get("selection") or "",
                    heading=request.get("heading") or "",
                )
            elif mode == "answer":
                body = respond(
                    book, request["question"], generate_fn=generate,
                    history=history,
                    pin_chunk=chunk_id,
                    end_chunk_id=end_chunk_id,
                    selection=request.get("selection") or "",
                    heading=request.get("heading") or "",
                )
            elif mode == "explain":
                body = explain(
                    book, request.get("selection") or "",
                    generate_fn=generate,
                    chunk_id=chunk_id,
                    end_chunk_id=end_chunk_id,
                    heading=request.get("heading") or "",
                )
            else:
                body = quiz(book, generate_fn=generate, chunk_id=chunk_id)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return
        except ValueError as exc:
            try:
                frame({"type": "error", "error": str(exc)})
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            return
        except (urllib.error.URLError, TimeoutError, RuntimeError):
            try:
                frame({"type": "error", "error": "answer model unavailable"})
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            return
        except SystemExit as exc:
            try:
                frame({"type": "error", "error": f"index error: {exc}"})
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            return
        except Exception as exc:
            # The stream contract: every start ends with final or error, so the
            # client never sits on a blank pane. Traceback goes to the console.
            traceback.print_exc()
            try:
                frame({"type": "error", "error": f"engine error: {exc}"})
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            return
        try:
            frame({"type": "final", "body": body})
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return


def load_book():
    """The nomic index. Loaded once. A later embedder does not swap in silently."""
    global BOOK
    if BOOK is None and INDEX.is_file():
        BOOK = load_index(INDEX)
    return BOOK


def chunks_body():
    """The reader payload, serialized once. The index is immutable per run."""
    global CHUNKS
    if CHUNKS is None:
        book = load_book()
        if book is None:
            return None
        CHUNKS = json.dumps(chunks_payload(book)).encode("utf-8")
    return CHUNKS


def main():
    load_book()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"ask-this-book: http://{HOST}:{PORT}  (GET /health, POST /ask; ctrl-c to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
