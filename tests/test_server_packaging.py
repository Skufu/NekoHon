"""Unit tests for server packaging, static asset serving, and path traversal protection.

Validates:
1. GET / serves web/out/index.html when present.
2. GET / falls back to window/index.html when web/out is absent.
3. Static assets under /_next/static/ serve with correct MIME type and immutable cache control.
4. Traversal attempts (..%2f, absolute, backslashes, %2e%2e, drive letters) fail with 404.
5. Standard engine routes (/ask, /health, /figures/, /chunks) are never shadowed.
"""

import http.client
import json
import tempfile
import threading
import unittest
import urllib.parse
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import server


class ServerPackagingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Spin up test server on an ephemeral port
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request("GET", path)
            resp = conn.getresponse()
            body = resp.read()
            headers = {k.lower(): v for k, v in resp.getheaders()}
            return resp.status, headers, body
        finally:
            conn.close()

    def test_serves_web_out_index_html_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "index.html").write_text("<!doctype html><html><body>NekoHon Next Export</body></html>", encoding="utf-8")
            with mock.patch.object(server, "WEB_OUT", tmp_path):
                status, headers, body = self._get("/")
                self.assertEqual(status, 200)
                self.assertIn("NekoHon Next Export", body.decode("utf-8"))
                self.assertIn("text/html", headers.get("content-type", "").lower())

    def test_falls_back_to_window_index_html_when_web_out_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty_path = Path(tmp) / "nonexistent_dir"
            with mock.patch.object(server, "WEB_OUT", empty_path):
                status, headers, body = self._get("/")
                self.assertEqual(status, 200)
                # window/index.html content
                self.assertIn("NekoHon", body.decode("utf-8"))
                self.assertIn("text/html", headers.get("content-type", "").lower())

    def test_serves_next_static_assets_with_immutable_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "index.html").write_text("index", encoding="utf-8")
            static_dir = tmp_path / "_next" / "static" / "chunks"
            static_dir.mkdir(parents=True)
            js_file = static_dir / "bundle.js"
            js_file.write_text("console.log('test-bundle');", encoding="utf-8")

            with mock.patch.object(server, "WEB_OUT", tmp_path):
                status, headers, body = self._get("/_next/static/chunks/bundle.js")
                self.assertEqual(status, 200)
                self.assertEqual(body.decode("utf-8"), "console.log('test-bundle');")
                self.assertIn("javascript", headers.get("content-type", "").lower())
                cache_control = headers.get("cache-control", "")
                self.assertIn("immutable", cache_control.lower())
                self.assertIn("max-age=31536000", cache_control.lower())

    def test_traversal_attempts_blocked_with_404(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "index.html").write_text("index", encoding="utf-8")

            with mock.patch.object(server, "WEB_OUT", tmp_path):
                traversals = [
                    "/..%2f..%2fserver.py",
                    "/..%2F..%2Fserver.py",
                    r"/..\..\server.py",
                    r"/..%5c..%5cserver.py",
                    r"/%2e%2e/%2e%2e/server.py",
                    r"/..%2f..%2f..%2f..%2fWindows%2fwin.ini",
                    r"/C:/Windows/win.ini",
                    r"/C:\Windows\win.ini",
                    "//etc/passwd",
                    "/%00../server.py",
                    "/sub/../../server.py",
                ]
                for path in traversals:
                    status, headers, body = self._get(path)
                    self.assertEqual(
                        status, 404,
                        f"Expected 404 for traversal path: {path!r}, got {status}"
                    )

    def test_routes_not_shadowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "index.html").write_text("index", encoding="utf-8")
            # Create files with same names as routes inside web/out
            (tmp_path / "health").write_text("shadow-health", encoding="utf-8")
            (tmp_path / "chunks").write_text("shadow-chunks", encoding="utf-8")

            with mock.patch.object(server, "WEB_OUT", tmp_path):
                # /health should return JSON health from engine, NOT shadow-health file
                status, headers, body = self._get("/health")
                self.assertEqual(status, 200)
                data = json.loads(body.decode("utf-8"))
                self.assertIn("ok", data)
                self.assertIn("ollama", data)

                # /chunks should return chunks payload, NOT shadow-chunks file
                status, headers, body = self._get("/chunks")
                self.assertEqual(status, 200)
                chunks_data = json.loads(body.decode("utf-8"))
                self.assertIn("chunks", chunks_data)


if __name__ == "__main__":
    unittest.main()
