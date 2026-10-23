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


_DISCONNECTS = (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)
_NOT_FOUND = {"error": "not found"}
_JSON_TYPE = "application/json; charset=utf-8"
_HTML_TYPE = "text/html; charset=utf-8"


class Handler(BaseHTTPRequestHandler):
    server_version = "nekohon/0.1"
    disable_nagle_algorithm = True

    def _cors(self):
        origin = self.headers.get("Origin") or ""
        if origin in ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def _send_json(self, status, payload, send_body=True):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", _JSON_TYPE)
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

    def do_GET(self):
        _handle_get_or_head(self, send_body=True)

    def do_HEAD(self):
        _handle_get_or_head(self, send_body=False)

    def do_OPTIONS(self):
        _handle_options(self)

    def do_POST(self):
        _handle_post(self)

    def _stream_ask(self, request, book):
        _stream_response(self, request, book)


def _query_book_id(h):
    query = urllib.parse.parse_qs(urllib.parse.urlparse(h.path).query)
    return query.get("book_id", [""])[0] or DEFAULT_BOOK_ID


def _serve_health(h, send_body):
    h._send_json(200, {
        "ok": True,
        "book_id": DEFAULT_BOOK_ID,
        "ollama": ollama_up(),
        "books": get_books_catalog(),
        "warm": dict(WARM_STATUS),
    }, send_body=send_body)


def _serve_index_page(h, send_body):
    headers = {"Cache-Control": "no-store"}
    page = WEB_OUT / "index.html"
    if not page.is_file():
        page = Path(__file__).resolve().parents[1] / "window" / "index.html"
        if not page.is_file():
            h._send_json(404, _NOT_FOUND, send_body=send_body)
            return
    h._send_bytes(200, page.read_bytes(), _HTML_TYPE, headers=headers, send_body=send_body)


def _find_cover(book_id, book, figures_dir):
    cover_name = (book or {}).get("cover_file")
    if cover_name and (figures_dir / cover_name).is_file():
        return figures_dir / cover_name
    for ext in (".png", ".jpg", ".jpeg", ".webp", ".svg"):
        cand = figures_dir / f"cover{ext}"
        if cand.is_file():
            return cand
    if book_id == DEFAULT_BOOK_ID:
        cand = ROOT / "data" / "figures" / "cover.png"
        if cand.is_file():
            return cand
    return None


def _find_figure(figure_id, book_id, book, figures_dir):
    path = figure_file(figure_id, (book or {}).get("figures") or [], figures_dir=figures_dir)
    if path is not None or book_id != DEFAULT_BOOK_ID:
        return path
    for cat in get_books_catalog():
        other_id = cat.get("book_id")
        if other_id and other_id != DEFAULT_BOOK_ID:
            other_book = get_book_index(other_id)
            other_dir = get_figures_dir(other_id)
            cand = figure_file(figure_id, (other_book or {}).get("figures") or [], figures_dir=other_dir)
            if cand:
                return cand
    return None


def _serve_figure(h, route, send_body):
    book_id = _query_book_id(h)
    figure_id = route[len("/figures/"):]
    book = get_book_index(book_id)
    figures_dir = get_figures_dir(book_id)
    if figure_id == "cover":
        path = _find_cover(book_id, book, figures_dir)
    else:
        path = _find_figure(figure_id, book_id, book, figures_dir)
    if path is None:
        h._send_json(404, _NOT_FOUND, send_body=send_body)
        return
    kind = MIME_TYPES.get(path.suffix.lower(), "application/octet-stream")
    h._send_bytes(200, path.read_bytes(), kind, send_body=send_body)


def _serve_chunks(h, send_body):
    book_id = _query_book_id(h)
    gzipped = "gzip" in (h.headers.get("Accept-Encoding") or "")
    body = chunks_gzip(book_id) if gzipped else chunks_body(book_id)
    if body is None:
        h._send_json(500, {"error": "missing index"}, send_body=send_body)
        return
    h.send_response(200)
    h.send_header("Content-Type", _JSON_TYPE)
    if gzipped:
        h.send_header("Content-Encoding", "gzip")
    h.send_header("Vary", "Accept-Encoding")
    h.send_header("Content-Length", str(len(body)))
    h._cors()
    h.end_headers()
    if send_body:
        h.wfile.write(body)


def _serve_static(h, route, send_body):
    if not (WEB_OUT / "index.html").is_file():
        return False
    try:
        base = WEB_OUT.resolve()
        unquoted = urllib.parse.unquote(route)
        if "\x00" in unquoted:
            h._send_json(404, _NOT_FOUND, send_body=send_body)
            return True
        clean_rel = unquoted.replace("\\", "/").lstrip("/")
        if ":" in clean_rel or clean_rel.startswith("/"):
            h._send_json(404, _NOT_FOUND, send_body=send_body)
            return True
        candidate = (base / clean_rel).resolve()
        if not (candidate.is_file() and candidate.is_relative_to(base)):
            return False
        guessed_type, _ = mimetypes.guess_type(str(candidate))
        content_type = guessed_type or MIME_TYPES.get(candidate.suffix.lower(), "application/octet-stream")
        if content_type.startswith("text/") or content_type in ("application/javascript", "application/json"):
            content_type = f"{content_type}; charset=utf-8"
        extra_headers = {}
        if route.startswith("/_next/static/"):
            extra_headers["Cache-Control"] = "public, max-age=31536000, immutable"
        h._send_bytes(200, candidate.read_bytes(), content_type, headers=extra_headers, send_body=send_body)
        return True
    except Exception:
        return False


def _handle_get_or_head(h, send_body=True):
    route = h._route()
    if route == "/health":
        _serve_health(h, send_body)
    elif route == "/":
        _serve_index_page(h, send_body)
    elif route.startswith("/figures/"):
        _serve_figure(h, route, send_body)
    elif route == "/chunks":
        _serve_chunks(h, send_body)
    elif not _serve_static(h, route, send_body):
        h._send_json(404, _NOT_FOUND, send_body=send_body)


def _handle_options(h):
    h.send_response(204)
    h._cors()
    h.send_header("Access-Control-Allow-Methods", "GET, HEAD, POST, OPTIONS")
    h.send_header("Access-Control-Allow-Headers", "Content-Type")
    h.send_header("Access-Control-Max-Age", "600")
    h.send_header("Content-Length", "0")
    h.end_headers()


def _validate_ask_request(request):
    mode = request.get("mode")
    if mode not in MODES and mode not in EXTRA_MODES:
        return 400, "bad mode"
    if mode in ("ask", "answer") and not request.get("question"):
        return 400, "missing question"
    if mode == "explain" and not request.get("selection"):
        return 400, "missing selection"
    return None


def _run_mode(mode, book, request, generate_fn=None):
    extra = {} if generate_fn is None else {"generate_fn": generate_fn}
    history = sanitize_history(request.get("history"))
    chunk_id = request.get("chunk_id")
    end_chunk_id = request.get("end_chunk_id") or None
    selection = request.get("selection") or ""
    heading = request.get("heading") or ""
    if mode == "ask":
        return ask(
            book, request["question"], history=history,
            pin_chunk=chunk_id, end_chunk_id=end_chunk_id,
            selection=selection, heading=heading, **extra,
        )
    if mode == "answer":
        return respond(
            book, request["question"], history=history,
            pin_chunk=chunk_id, end_chunk_id=end_chunk_id,
            selection=selection, heading=heading, **extra,
        )
    if mode == "explain":
        return explain(
            book, selection, chunk_id=chunk_id,
            end_chunk_id=end_chunk_id, heading=heading, **extra,
        )
    return quiz(book, chunk_id=chunk_id, **extra)


def _handle_post(h):
    if h._route() != "/ask":
        h._send_json(404, _NOT_FOUND)
        return
    request = h._read_request()
    if not isinstance(request, dict):
        h._send_json(400, {"error": "invalid json"})
        return
    mode = request.get("mode")
    if mode == "import":
        _handle_import(h, request)
        return
    invalid = _validate_ask_request(request)
    if invalid:
        h._send_json(invalid[0], {"error": invalid[1]})
        return
    book_id = request.get("book_id") or DEFAULT_BOOK_ID
    book = get_book_index(book_id)
    if book is None:
        if request.get("book_id"):
            h._send_json(404, {"error": f"unknown book {book_id}"})
        else:
            h._send_json(500, {"error": "missing index"})
        return
    if request.get("stream"):
        _stream_response(h, request, book)
        return
    try:
        body = _run_mode(mode, book, request)
    except ValueError as exc:
        h._send_json(400, {"error": str(exc)})
        return
    except (urllib.error.URLError, TimeoutError, RuntimeError):
        h._send_json(500, {"error": "answer model unavailable"})
        return
    except SystemExit as exc:
        h._send_json(500, {"error": f"index error: {exc}"})
        return
    h._send_json(200, body)


def _normalize_book_id(raw):
    return re.sub(r"[^a-zA-Z0-9_-]", "-", raw).lower().strip("-") or "imported"


def _import_source(request):
    data_b64 = request.get("data_base64")
    epub_path_str = request.get("epub_path")
    if data_b64:
        try:
            raw_data = base64.b64decode(data_b64)
        except Exception as exc:
            return None, None, f"invalid base64: {exc}"
        filename = request.get("filename") or ""
        book_id = _normalize_book_id(request.get("book_id") or Path(filename).stem.lower())
        books_dir = ROOT / "books"
        books_dir.mkdir(parents=True, exist_ok=True)
        epub_path = books_dir / f"{book_id}.epub"
        epub_path.write_bytes(raw_data)
        return epub_path, book_id, None
    if epub_path_str:
        epub_path = Path(epub_path_str)
        if not epub_path.is_absolute():
            epub_path = ROOT / epub_path
        if not epub_path.is_file():
            return None, None, f"file not found: {epub_path_str}"
        return epub_path, _normalize_book_id(request.get("book_id") or epub_path.stem.lower()), None
    return None, None, "missing data_base64 or epub_path"


def _ingest_import(request, epub_path, book_id):
    from engine.ingest import ingest_epub, update_books_catalog
    from engine.retrieval.retrieve import embed_index, save_index

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

    return {
        "ok": True,
        "book_id": book_id,
        "book": catalog_entry,
        "books": get_books_catalog(),
    }


def _handle_import(h, request):
    try:
        epub_path, book_id, error = _import_source(request)
        if error:
            h._send_json(400, {"error": error})
            return
        h._send_json(200, _ingest_import(request, epub_path, book_id))
    except Exception as exc:
        traceback.print_exc()
        h._send_json(500, {"error": f"import failed: {exc}"})


def _write_frame(h, payload):
    h.wfile.write((json.dumps(payload) + "\n").encode("utf-8"))
    h.wfile.flush()


def _stream_generate(h, mode):
    calls = {"n": 0}

    def generate(system, user, model=ANSWER_MODEL, prefill=""):
        calls["n"] += 1
        if calls["n"] > 1:
            _write_frame(h, {"type": "reset"})
        live = bool(prefill) or (
            system in (EXPLAIN_GLOSS_SYSTEM, ANSWER_GLOSS_SYSTEM, FOLLOWUP_GLOSS_SYSTEM)
        ) or (
            system == SYSTEM and mode != "quiz"
        )

        def on_token(text):
            _write_frame(h, {"type": "token", "text": text})

        return ollama_generate_stream(
            system, user, model=model, prefill=prefill,
            on_token=on_token if live else None,
        )

    generate._is_live = True
    return generate


def _frame_quietly(h, payload):
    try:
        _write_frame(h, payload)
    except _DISCONNECTS:
        pass


def _stream_response(h, request, book):
    mode = request["mode"]
    generate = _stream_generate(h, mode)

    h.send_response(200)
    h.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
    h.send_header("Cache-Control", "no-store")
    h.send_header("Connection", "close")
    h._cors()
    h.end_headers()
    try:
        body = _run_mode(mode, book, request, generate_fn=generate)
    except _DISCONNECTS:
        return
    except ValueError as exc:
        _frame_quietly(h, {"type": "error", "error": str(exc)})
        return
    except (urllib.error.URLError, TimeoutError, RuntimeError):
        _frame_quietly(h, {"type": "error", "error": "answer model unavailable"})
        return
    except SystemExit as exc:
        _frame_quietly(h, {"type": "error", "error": f"index error: {exc}"})
        return
    except Exception as exc:
        traceback.print_exc()
        _frame_quietly(h, {"type": "error", "error": f"engine error: {exc}"})
        return
    _frame_quietly(h, {"type": "final", "body": body})


def load_book():
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
