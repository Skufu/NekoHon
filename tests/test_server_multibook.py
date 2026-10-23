"""Tests for multi-book server routing, gzip compression, MIME figures, and import."""

import base64
import gzip
import http.client
import json
import tempfile
import threading
import unittest
import zipfile
from http.server import ThreadingHTTPServer
import sys
from pathlib import Path
from unittest import mock

import server
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixture_books import FixtureRoot

ROOT = Path(__file__).resolve().parent.parent


class ServerMultiBookTest(unittest.TestCase):
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

    def test_health_includes_books_catalog(self):
        status, _, data = self.request("GET", "/health")
        self.assertEqual(status, 200)
        payload = json.loads(data.decode("utf-8"))
        self.assertTrue(payload.get("ok"))
        self.assertIn("books", payload)
        self.assertIsInstance(payload["books"], list)
        book_ids = [b["book_id"] for b in payload["books"]]
        self.assertIn("fde", book_ids)

    def test_chunks_default_and_per_book(self):
        status, _, data = self.request("GET", "/chunks")
        self.assertEqual(status, 200)
        payload = json.loads(data.decode("utf-8"))
        self.assertEqual(payload["book_id"], "fde")
        self.assertIn("books", payload)
        self.assertTrue(payload["chunks"])

        # Check quantization book
        status, _, data = self.request("GET", "/chunks?book_id=quantization")
        self.assertEqual(status, 200)
        payload = json.loads(data.decode("utf-8"))
        self.assertEqual(payload["book_id"], "quantization")
        self.assertTrue(payload["chunks"])

        # Check ddia book
        status, _, data = self.request("GET", "/chunks?book_id=ddia")
        self.assertEqual(status, 200)
        payload = json.loads(data.decode("utf-8"))
        self.assertEqual(payload["book_id"], "ddia")
        self.assertTrue(payload["chunks"])

    def test_chunks_gzip_compression(self):
        status, headers, data = self.request(
            "GET", "/chunks", headers={"Accept-Encoding": "gzip"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Content-Encoding"), "gzip")
        decompressed = gzip.decompress(data)
        payload = json.loads(decompressed.decode("utf-8"))
        self.assertEqual(payload["book_id"], "fde")
        self.assertTrue(len(data) < len(decompressed))

    def test_figures_cover_mime_types(self):
        # Default FDE cover is PNG
        status, headers, data = self.request("GET", "/figures/cover")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Content-Type"), "image/png")
        self.assertTrue(len(data) > 0)

        # Quantization cover is JPG
        status, headers, data = self.request("GET", "/figures/cover?book_id=quantization")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Content-Type"), "image/jpeg")
        self.assertTrue(len(data) > 0)

        # DDIA cover is JPG
        status, headers, data = self.request("GET", "/figures/cover?book_id=ddia")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Content-Type"), "image/jpeg")
        self.assertTrue(len(data) > 0)

    def test_ask_unknown_book_404(self):
        status, _, data = self.request(
            "POST",
            "/ask",
            {"mode": "ask", "question": "What is data?", "book_id": "nonexistent_book"},
        )
        self.assertEqual(status, 404)
        payload = json.loads(data.decode("utf-8"))
        self.assertIn("error", payload)

    def test_ask_per_book_dispatches_correct_index(self):
        seen_books = []

        def fake_ask(index, question, **kwargs):
            seen_books.append(index.get("book_id"))
            return {"answer": "test answer [Ch. 1]", "citations": [], "figures": [], "refused": False}

        with mock.patch.object(server, "ask", fake_ask):
            status, _, data = self.request(
                "POST",
                "/ask",
                {"mode": "ask", "question": "What is quantization?", "book_id": "quantization"},
            )
            self.assertEqual(status, 200)
            self.assertEqual(seen_books[-1], "quantization")

            status, _, data = self.request(
                "POST",
                "/ask",
                {"mode": "ask", "question": "What is replication?", "book_id": "ddia"},
            )
            self.assertEqual(status, 200)
            self.assertEqual(seen_books[-1], "ddia")

    def test_import_mode_epub(self):
        # Create a minimal valid EPUB zip in memory
        with tempfile.TemporaryDirectory() as tmpdir:
            epub_path = Path(tmpdir) / "testbook.epub"
            with zipfile.ZipFile(epub_path, "w") as zf:
                zf.writestr("mimetype", "application/epub+zip")
                zf.writestr(
                    "META-INF/container.xml",
                    '<?xml version="1.0"?>'
                    '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                    '  <rootfiles>'
                    '    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
                    '  </rootfiles>'
                    '</container>',
                )
                zf.writestr(
                    "OEBPS/content.opf",
                    '<?xml version="1.0"?>'
                    '<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="pub-id" version="3.0">'
                    '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
                    '    <dc:title>Test Book</dc:title>'
                    '    <dc:creator>Test Author</dc:creator>'
                    '  </metadata>'
                    '  <manifest>'
                    '    <item id="ch01" href="ch01.xhtml" media-type="application/xhtml+xml"/>'
                    '  </manifest>'
                    '  <spine>'
                    '    <itemref idref="ch01"/>'
                    '  </spine>'
                    '</package>',
                )
                zf.writestr(
                    "OEBPS/ch01.xhtml",
                    '<?xml version="1.0"?>'
                    '<html xmlns="http://www.w3.org/1999/xhtml">'
                    '  <body>'
                    '    <h1>Chapter 1</h1>'
                    '    <p>This is a test paragraph for testbook import.</p>'
                    '  </body>'
                    '</html>',
                )

            data_b64 = base64.b64encode(epub_path.read_bytes()).decode("ascii")

            status, _, data = self.request(
                "POST",
                "/ask",
                {
                    "mode": "import",
                    "filename": "testmini.epub",
                    "book_id": "testmini",
                    "data_base64": data_b64,
                    "skip_embed": True,
                },
            )
            self.assertEqual(status, 200)
            payload = json.loads(data.decode("utf-8"))
            self.assertTrue(payload.get("ok"))
            self.assertEqual(payload.get("book_id"), "testmini")
            self.assertEqual(payload.get("book", {}).get("title"), "Test Book")
            self.assertTrue((server.ROOT / "data" / "index.testmini.json").is_file())


if __name__ == "__main__":
    unittest.main()
