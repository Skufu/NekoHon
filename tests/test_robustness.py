import http.client
import json
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixture_books import FixtureRoot, PNG

from engine import server
from engine.retrieval import readings, retrieve


class RacyCache(dict):
    def __contains__(self, key):
        return True


class LruRaceTest(unittest.TestCase):
    def test_missing_key_after_contains_returns_none(self):
        self.assertIsNone(retrieve._lru_get(RacyCache(), "gone"))

    def test_present_key_moves_to_end(self):
        cache = {"a": 1, "b": 2}
        self.assertEqual(retrieve._lru_get(cache, "a"), 1)
        self.assertEqual(list(cache), ["b", "a"])


class ServerGuardsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = FixtureRoot().__enter__()
        cls.addClassCleanup(cls.fixture.__exit__, None, None, None)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.httpd.server_address[1]
        cls.addClassCleanup(cls.thread.join, 5)
        cls.addClassCleanup(cls.httpd.server_close)
        cls.addClassCleanup(cls.httpd.shutdown)

    def test_oversize_content_length_is_413_without_reading_body(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        conn.putrequest("POST", "/ask")
        conn.putheader("Content-Type", "application/json")
        conn.putheader("Content-Length", str(server.MAX_BODY_BYTES + 1))
        conn.endheaders()
        response = conn.getresponse()
        self.assertEqual(response.status, 413)
        self.assertIn("error", json.loads(response.read()))
        conn.close()

    def test_import_rejects_paths_outside_books(self):
        outside = self.fixture.root / "outside.epub"
        outside.write_bytes(b"x")
        for path in (str(outside), "../outside.epub", "books/../outside.epub"):
            _, _, error = server._import_source({"epub_path": path})
            self.assertTrue(error, path)
            self.assertIn("books", error)

    def test_import_accepts_paths_under_books(self):
        books = self.fixture.root.resolve() / "books"
        books.mkdir(exist_ok=True)
        (books / "ok.epub").write_bytes(b"x")
        for path in ("books/ok.epub", str(books / "ok.epub")):
            epub, book_id, error = server._import_source({"epub_path": path})
            self.assertIsNone(error)
            self.assertEqual(epub, (books / "ok.epub").resolve())
            self.assertEqual(book_id, "ok")

    def test_figure_book_id_cannot_escape_figures_root(self):
        (self.fixture.root / "cover.png").write_bytes(PNG)
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", "/figures/cover?book_id=../..")
        response = conn.getresponse()
        response.read()
        conn.close()
        self.assertEqual(response.status, 404)

    def test_import_clears_id_keyed_caches(self):
        retrieve._RANK_CACHE[(1, 1, "m", "q")] = []
        retrieve._DENSE_RANK_CACHE[(1, 1, "m", "q")] = {}
        readings._SORTED_WMAP_CACHE[1] = (0, [])
        books = self.fixture.root / "books"
        books.mkdir(exist_ok=True)
        (books / "tiny.epub").write_bytes(b"x")
        index = {"title": "T", "chunks": [], "figures": []}
        with mock.patch("engine.ingest.ingest_epub", return_value=index), \
                mock.patch("engine.ingest.update_books_catalog", return_value={}), \
                mock.patch("engine.retrieval.retrieve.save_index"):
            server._ingest_import({"skip_embed": True}, books / "tiny.epub", "tiny")
        self.assertFalse(retrieve._RANK_CACHE)
        self.assertFalse(retrieve._DENSE_RANK_CACHE)
        self.assertFalse(readings._SORTED_WMAP_CACHE)


if __name__ == "__main__":
    unittest.main()
