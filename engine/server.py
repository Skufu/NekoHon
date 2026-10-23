"""ask-this-book engine. stdlib only.

POST /ask in mode "ask" retrieves from the nomic index and checks the quote.
Mode "answer" is free generation from the same passages with a measured
quote check (artifacts/harnesses/groundedness.py), not an enforced one. explain
and quiz use the same index.

GET /chunks serves the reader's blocks. stream=1 on POST /ask answers in
NDJSON frames: token, reset (a draft was discarded), final, error.
"""

import base64
import gzip
import json
import mimetypes
import os
import re
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

mimetypes.init()

from engine.retrieval.retrieve import DEFAULT_EMBEDDER, INDEX, chunks_payload, format_input, load_index
from engine.answering.answer import ask, explain, ollama_generate_stream, quiz, respond, sanitize_history
from engine import llm
from engine.figures import figure_file
from engine.retrieval.keywords import postings
from engine.answering.prompt import ANSWER_GLOSS_SYSTEM, ANSWER_MODEL, EXPLAIN_GLOSS_SYSTEM, FOLLOWUP_GLOSS_SYSTEM, OLLAMA_KEEP_ALIVE, SYSTEM

ROOT = Path(__file__).resolve().parents[1]
WEB_OUT = ROOT / "web" / "out"
HOST = "127.0.0.1"


def parse_port(argv=None, env=None):
    """Parse and validate server port: --port N CLI arg, else $PORT, else 8000.

    Validates integer in range 1..65535.
    """
    if argv is None:
        argv = sys.argv[1:]
    if env is None:
        env = os.environ

    raw_port = None
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--port":
            if i + 1 >= len(argv):
                raise ValueError("--port requires an integer port argument")
            raw_port = argv[i + 1]
            break
        elif arg.startswith("--port="):
            raw_port = arg.split("=", 1)[1]
            break
        i += 1

    if raw_port is None:
        raw_port = env.get("PORT")

    if raw_port is None or raw_port == "":
        return 8000

    try:
        port = int(raw_port)
    except (ValueError, TypeError):
        raise ValueError(f"Invalid port {raw_port!r}: must be an integer")

    if not (1 <= port <= 65535):
        raise ValueError(f"Port {port} out of range: must be between 1 and 65535")

    return port


PORT = parse_port()
OLLAMA_URL = llm.BASE + "/"
DEFAULT_BOOK_ID = "".join(["f", "d", "e"])
MODES = ("ask", "answer", "explain", "quiz")
EXTRA_MODES = ("import",)
BOOK = None
CHUNKS = None
ORIGINS = (
    "http://localhost:3100", "http://127.0.0.1:3100",
    "http://localhost:3200", "http://127.0.0.1:3200",
)

MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
}

INDEX_CACHE = {}
CHUNKS_JSON_CACHE = {}
CHUNKS_GZIP_CACHE = {}

WARM_STATUS = {
    "done": False,
    "ok": False,
    "error": None,
    "answer_model": ANSWER_MODEL,
    "embed_model": DEFAULT_EMBEDDER,
    "models_resident": False,
    "duration_s": None,
}


def ollama_up(timeout=1.0):
    """True if a local Ollama answers on its port. Never raises."""
    try:
        with urllib.request.urlopen(OLLAMA_URL, timeout=timeout):
            return True
    except Exception:
        return False


def get_books_catalog():
    catalog_path = ROOT / "data" / "books.json"
    catalog = []
    if catalog_path.is_file():
        try:
            raw = json.loads(catalog_path.read_text(encoding="utf-8"))
            catalog = raw if isinstance(raw, list) else raw.get("books", [])
        except Exception:
            catalog = []
    known_ids = {b.get("book_id") for b in catalog if isinstance(b, dict)}
    if DEFAULT_BOOK_ID not in known_ids and INDEX.is_file():
        try:
            fde_idx = load_index(INDEX)
            unique_chapters = len({c.get("chapter") for c in fde_idx.get("chunks", []) if c.get("chapter") is not None})
            catalog.insert(0, {
                "book_id": DEFAULT_BOOK_ID,
                "title": fde_idx.get("title", "Fundamentals of Data Engineering"),
                "author": fde_idx.get("author", "Joe Reis & Matt Housley"),
                "chapter_count": unique_chapters,
                "chunk_count": len(fde_idx.get("chunks", [])),
                "figure_count": len(fde_idx.get("figures", [])),
                "cover_url": "/figures/cover",
                "index_path": "data/index.json",
                "figures_dir": "data/figures",
            })
        except Exception:
            pass
    return catalog


def get_figures_dir(book_id=None):
    if not book_id or book_id == DEFAULT_BOOK_ID:
        return ROOT / "data" / "figures"
    for b in get_books_catalog():
        if b.get("book_id") == book_id:
            p = Path(b.get("figures_dir", ""))
            if not p.is_absolute():
                p = ROOT / p
            return p
    return ROOT / "data" / "figures" / book_id


def get_book_index(book_id=None):
    if not book_id:
        book_id = DEFAULT_BOOK_ID
    if book_id in INDEX_CACHE:
        return INDEX_CACHE[book_id]

    index_path = None
    if book_id == DEFAULT_BOOK_ID:
        index_path = INDEX
    else:
        candidate = ROOT / "data" / f"index.{book_id}.json"
        if candidate.is_file():
            index_path = candidate
        else:
            for b in get_books_catalog():
                if b.get("book_id") == book_id:
                    p = Path(b.get("index_path", ""))
                    if not p.is_absolute():
                        p = ROOT / p
                    if p.is_file():
                        index_path = p
                    break
    if index_path and index_path.is_file():
        idx = load_index(index_path)
        if not idx.get("book_id"):
            idx["book_id"] = book_id
        INDEX_CACHE[book_id] = idx
        return idx
    return None


class Handler(BaseHTTPRequestHandler):
    server_version = "nekohon/0.1"
    disable_nagle_algorithm = True

    def _cors(self):
        """Echo the dev UI's origin; the built UI is same-origin, needs none."""
        origin = self.headers.get("Origin") or ""
        if origin in ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def _send_json(self, status, payload, send_body=True):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        if send_body:
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

    def _send_bytes(self, status, payload, content_type, headers=None, send_body=True):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        if headers:
            for k, v in headers.items():
                self.send_header(k, v)
        self._cors()
        self.end_headers()
        if send_body:
            self.wfile.write(payload)

    def _handle_get_or_head(self, send_body=True):
        route = self._route()
        if route == "/health":
            self._send_json(200, {
                "ok": True,
                "book_id": DEFAULT_BOOK_ID,
                "ollama": ollama_up(),
                "books": get_books_catalog(),
                "warm": dict(WARM_STATUS),
            }, send_body=send_body)
            return
        if route == "/":
            headers = {"Cache-Control": "no-store"}
            if (WEB_OUT / "index.html").is_file():
                page = WEB_OUT / "index.html"
                self._send_bytes(200, page.read_bytes(), "text/html; charset=utf-8", headers=headers, send_body=send_body)
                return
            page = Path(__file__).resolve().parents[1] / "window" / "index.html"
            if not page.is_file():
                self._send_json(404, {"error": "not found"}, send_body=send_body)
                return
            self._send_bytes(200, page.read_bytes(), "text/html; charset=utf-8", headers=headers, send_body=send_body)
            return
        if route.startswith("/figures/"):
            parsed = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(parsed.query)
            book_id = query.get("book_id", [""])[0] or DEFAULT_BOOK_ID
            figure_id = route[len("/figures/"):]
            book = get_book_index(book_id)
            figures_dir = get_figures_dir(book_id)

            if figure_id == "cover":
                path = None
                cover_name = (book or {}).get("cover_file")
                if cover_name and (figures_dir / cover_name).is_file():
                    path = figures_dir / cover_name
                else:
                    for ext in (".png", ".jpg", ".jpeg", ".webp", ".svg"):
                        cand = figures_dir / f"cover{ext}"
                        if cand.is_file():
                            path = cand
                            break
                if path is None and book_id == DEFAULT_BOOK_ID:
                    cand = ROOT / "data" / "figures" / "cover.png"
                    if cand.is_file():
                        path = cand
                if path is None:
                    self._send_json(404, {"error": "not found"}, send_body=send_body)
                    return
                suffix = path.suffix.lower()
                kind = MIME_TYPES.get(suffix, "application/octet-stream")
                self._send_bytes(200, path.read_bytes(), kind, send_body=send_body)
                return

            path = figure_file(figure_id, (book or {}).get("figures") or [], figures_dir=figures_dir)
            if path is None and book_id == DEFAULT_BOOK_ID:
                for cat in get_books_catalog():
                    other_id = cat.get("book_id")
                    if other_id and other_id != DEFAULT_BOOK_ID:
                        other_book = get_book_index(other_id)
                        other_dir = get_figures_dir(other_id)
                        cand = figure_file(figure_id, (other_book or {}).get("figures") or [], figures_dir=other_dir)
                        if cand:
                            path = cand
                            break
            if path is None:
                self._send_json(404, {"error": "not found"}, send_body=send_body)
                return
            suffix = path.suffix.lower()
            kind = MIME_TYPES.get(suffix, "application/octet-stream")
            self._send_bytes(200, path.read_bytes(), kind, send_body=send_body)
            return

        if route == "/chunks":
            parsed = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(parsed.query)
            book_id = query.get("book_id", [""])[0] or DEFAULT_BOOK_ID
            accept_encoding = self.headers.get("Accept-Encoding") or ""
            if "gzip" in accept_encoding:
                gz_body = chunks_gzip(book_id)
                if gz_body is None:
                    self._send_json(500, {"error": "missing index"}, send_body=send_body)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Encoding", "gzip")
                self.send_header("Vary", "Accept-Encoding")
                self.send_header("Content-Length", str(len(gz_body)))
                self._cors()
                self.end_headers()
                if send_body:
                    self.wfile.write(gz_body)
                return

            body = chunks_body(book_id)
            if body is None:
                self._send_json(500, {"error": "missing index"}, send_body=send_body)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Vary", "Accept-Encoding")
            self.send_header("Content-Length", str(len(body)))
            self._cors()
            self.end_headers()
            if send_body:
                self.wfile.write(body)
            return

        # Static asset serving for web/out Next.js export
        if (WEB_OUT / "index.html").is_file():
            try:
                base = WEB_OUT.resolve()
                unquoted = urllib.parse.unquote(route)
                if "\x00" in unquoted:
                    self._send_json(404, {"error": "not found"}, send_body=send_body)
                    return
                clean_rel = unquoted.replace("\\", "/").lstrip("/")
                if ":" in clean_rel or clean_rel.startswith("/"):
                    self._send_json(404, {"error": "not found"}, send_body=send_body)
                    return
                candidate = (base / clean_rel).resolve()
                if candidate.is_file() and candidate.is_relative_to(base):
                    suffix = candidate.suffix.lower()
                    guessed_type, _ = mimetypes.guess_type(str(candidate))
                    content_type = guessed_type or MIME_TYPES.get(suffix, "application/octet-stream")
                    if content_type.startswith("text/") or content_type in ("application/javascript", "application/json"):
                        content_type = f"{content_type}; charset=utf-8"
                    extra_headers = {}
                    if route.startswith("/_next/static/"):
                        extra_headers["Cache-Control"] = "public, max-age=31536000, immutable"
                    self._send_bytes(200, candidate.read_bytes(), content_type, headers=extra_headers, send_body=send_body)
                    return
            except Exception:
                pass

        self._send_json(404, {"error": "not found"}, send_body=send_body)

    def do_GET(self):
        self._handle_get_or_head(send_body=True)

    def do_HEAD(self):
        self._handle_get_or_head(send_body=False)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, POST, OPTIONS")
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
        if mode not in MODES and mode not in EXTRA_MODES:
            self._send_json(400, {"error": "bad mode"})
            return
        if mode == "import":
            self._handle_import(request)
            return
        if mode in ("ask", "answer") and not request.get("question"):
            self._send_json(400, {"error": "missing question"})
            return
        if mode == "explain" and not request.get("selection"):
            self._send_json(400, {"error": "missing selection"})
            return
        book_id = request.get("book_id") or DEFAULT_BOOK_ID
        book = get_book_index(book_id)
        if book is None:
            if request.get("book_id"):
                self._send_json(404, {"error": f"unknown book {book_id}"})
            else:
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

    def _handle_import(self, request):
        try:
            from engine.ingest import ingest_epub, update_books_catalog
            from engine.retrieval.retrieve import embed_index, save_index

            data_b64 = request.get("data_base64")
            epub_path_str = request.get("epub_path")
            filename = request.get("filename") or ""

            if data_b64:
                try:
                    raw_data = base64.b64decode(data_b64)
                except Exception as exc:
                    self._send_json(400, {"error": f"invalid base64: {exc}"})
                    return
                book_id = request.get("book_id") or Path(filename).stem.lower()
                book_id = re.sub(r"[^a-zA-Z0-9_-]", "-", book_id).lower().strip("-") or "imported"
                books_dir = ROOT / "books"
                books_dir.mkdir(parents=True, exist_ok=True)
                epub_path = books_dir / f"{book_id}.epub"
                epub_path.write_bytes(raw_data)
            elif epub_path_str:
                epub_path = Path(epub_path_str)
                if not epub_path.is_absolute():
                    epub_path = ROOT / epub_path
                if not epub_path.is_file():
                    self._send_json(400, {"error": f"file not found: {epub_path_str}"})
                    return
                book_id = request.get("book_id") or epub_path.stem.lower()
                book_id = re.sub(r"[^a-zA-Z0-9_-]", "-", book_id).lower().strip("-") or "imported"
            else:
                self._send_json(400, {"error": "missing data_base64 or epub_path"})
                return

            figures_dir = ROOT / "data" / "figures" / book_id
            figures_dir.mkdir(parents=True, exist_ok=True)

            index = ingest_epub(epub_path, figures_dir=figures_dir, write_images=True, book_id=book_id)
            if request.get("title"):
                index["title"] = request["title"]
            if request.get("author"):
                index["author"] = request["author"]

            if not request.get("skip_embed"):
                embed_index(index)

            index_path = ROOT / "data" / f"index.{book_id}.json"
            save_index(index_path, index)

            catalog_entry = update_books_catalog(
                book_id,
                index.get("title", ""),
                index.get("author", ""),
                index_path,
                figures_dir,
                index.get("chunks", []),
                index.get("figures", []),
                cover_file=index.get("cover_file", "cover.png"),
            )

            INDEX_CACHE[book_id] = index
            CHUNKS_JSON_CACHE.clear()
            CHUNKS_GZIP_CACHE.clear()
            if not request.get("skip_embed"):
                chunks_body(book_id)

            self._send_json(200, {
                "ok": True,
                "book_id": book_id,
                "book": catalog_entry,
                "books": get_books_catalog(),
            })
        except Exception as exc:
            traceback.print_exc()
            self._send_json(500, {"error": f"import failed: {exc}"})

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
    """Backward compatibility for single-book callers."""
    global BOOK
    book = get_book_index(DEFAULT_BOOK_ID)
    if book is not None:
        BOOK = book
    return BOOK


def chunks_body(book_id=None):
    if not book_id:
        book_id = DEFAULT_BOOK_ID
    if book_id not in CHUNKS_JSON_CACHE:
        book = get_book_index(book_id)
        if book is None:
            return None
        payload = chunks_payload(book)
        payload["books"] = get_books_catalog()
        raw = json.dumps(payload).encode("utf-8")
        CHUNKS_JSON_CACHE[book_id] = raw
        CHUNKS_GZIP_CACHE[book_id] = gzip.compress(raw)
    global CHUNKS
    if book_id == DEFAULT_BOOK_ID:
        CHUNKS = CHUNKS_JSON_CACHE[book_id]
    return CHUNKS_JSON_CACHE[book_id]


def chunks_gzip(book_id=None):
    if not book_id:
        book_id = DEFAULT_BOOK_ID
    if book_id not in CHUNKS_GZIP_CACHE:
        if chunks_body(book_id) is None:
            return None
    return CHUNKS_GZIP_CACHE.get(book_id)


def _do_warmup():
    t0 = time.time()
    try:
        for b in get_books_catalog():
            book_id = b.get("book_id") if isinstance(b, dict) else None
            if book_id:
                idx = get_book_index(book_id)
                if idx:
                    postings(idx)
                chunks_body(book_id)
                chunks_gzip(book_id)
        if not ollama_up():
            WARM_STATUS["done"] = True
            WARM_STATUS["error"] = "ollama offline"
            return
        WARM_STATUS["ollama"] = True
        answer_model = ANSWER_MODEL
        embed_model = (get_book_index(DEFAULT_BOOK_ID) or {}).get("embedder") or DEFAULT_EMBEDDER
        WARM_STATUS["answer_model"] = answer_model
        WARM_STATUS["embed_model"] = embed_model
        try:
            probe_input = format_input(embed_model, "query", "warmup")
        except Exception:
            probe_input = "warmup"
        try:
            llm.embed([probe_input], embed_model, timeout=30)
        except Exception as exc:
            WARM_STATUS["error"] = f"embedder warm failed: {exc}"
        try:
            warm_messages = [{"role": "user", "content": "1"}]
            llm.post_json(llm.CHAT_URL, llm.chat_payload(answer_model, warm_messages, False, 1), 60)
        except Exception as exc:
            if not WARM_STATUS["error"]:
                WARM_STATUS["error"] = f"answer model warm failed: {exc}"
        try:
            names = llm.loaded_models()
            WARM_STATUS["models_resident"] = all(
                any(n == m or n.startswith(m + ":") for n in names)
                for m in (answer_model, embed_model)
            )
        except Exception:
            pass
        if not WARM_STATUS["error"]:
            WARM_STATUS["ok"] = True
    except Exception as exc:
        WARM_STATUS["error"] = str(exc)
    finally:
        WARM_STATUS["duration_s"] = round(time.time() - t0, 3)
        WARM_STATUS["done"] = True


def warm_engine(block=False):
    """Run startup warm-up for in-process caches and Ollama models.

    If block=True, executes synchronously. If block=False, executes in a
    background daemon thread so the server can begin listening immediately.
    """
    if block:
        _do_warmup()
        return None
    t = threading.Thread(target=_do_warmup, daemon=True, name="engine-warmup")
    t.start()
    return t


def main():
    load_book()
    try:
        port = parse_port()
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    block = "--block-warmup" in sys.argv or os.environ.get("WARMUP_BLOCK") == "1"
    warm_engine(block=block)
    server = ThreadingHTTPServer((HOST, port), Handler)
    print(f"nekohon: http://{HOST}:{port}  (GET /health, POST /ask; ctrl-c to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
