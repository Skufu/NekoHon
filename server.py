"""ask-this-book engine. stdlib only; the route shape is locked in README.md.

POST /ask in mode "ask" retrieves from the nomic index and checks the quote.
explain and quiz are live since Phase 6 and use the same index. No new routes.
"""

import json
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from answer import ask, explain, quiz
from figures import figure_file
from retrieve import INDEX, load_index

HOST = "127.0.0.1"
PORT = 8000
OLLAMA_URL = "http://127.0.0.1:11434/"
MODES = ("ask", "explain", "quiz")
FIXTURE = Path(__file__).resolve().parent / "tests" / "fixtures" / "ask_response.json"
BOOK = None


def load_fixture():
    with FIXTURE.open(encoding="utf-8") as handle:
        return json.load(handle)


def ollama_up(timeout=1.0):
    """True if a local Ollama answers on its port. Never raises."""
    try:
        with urllib.request.urlopen(OLLAMA_URL, timeout=timeout):
            return True
    except Exception:
        return False


class Handler(BaseHTTPRequestHandler):
    server_version = "ask-this-book/0.1"

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
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
        self._send_json(404, {"error": "not found"})

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
        if mode == "ask" and not request.get("question"):
            self._send_json(400, {"error": "missing question"})
            return
        if mode == "explain" and not request.get("selection"):
            self._send_json(400, {"error": "missing selection"})
            return
        book = load_book()
        if book is None:
            self._send_json(500, {"error": "missing index"})
            return
        try:
            if mode == "ask":
                body = ask(book, request["question"])
            elif mode == "explain":
                body = explain(book, request.get("selection") or "")
            else:
                body = quiz(book)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        except (urllib.error.URLError, TimeoutError, RuntimeError):
            self._send_json(500, {"error": "answer model unavailable"})
            return
        self._send_json(200, body)


def load_book():
    """The nomic index. Loaded once. A later embedder does not swap in silently."""
    global BOOK
    if BOOK is None and INDEX.is_file():
        BOOK = load_index(INDEX)
    return BOOK


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
