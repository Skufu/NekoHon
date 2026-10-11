"""ask-this-book engine. stdlib only; the route shape is locked in README.md.

Phase 1: GET /health probes Ollama on localhost, POST /ask returns the
contract fixture unchanged. Retrieval and generation land in later phases.
"""

import json
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8000
OLLAMA_URL = "http://127.0.0.1:11434/"
MODES = ("ask", "explain", "quiz")
FIXTURE = Path(__file__).resolve().parent / "tests" / "fixtures" / "ask_response.json"


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

    def do_GET(self):
        if self._route() == "/health":
            self._send_json(200, {"ok": True, "ollama": ollama_up()})
        else:
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
        self._send_json(200, load_fixture())


def main():
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
