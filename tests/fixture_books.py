import json
import tempfile
from pathlib import Path
from unittest import mock

from engine import ingest
from engine import server
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6360f8cfc0f01f0005000201a5f645400000000049454e44ae426082"
)
JPG = b"\xff\xd8\xff\xe0fixture\xff\xd9"
BOOKS = {"fde": "Fixture FDE", "quantization": "Fixture Quantization", "ddia": "Fixture DDIA"}


def _index(book_id, title):
    return {
        "book_id": book_id, "title": title, "embedding_dims": 4, "figures": [],
        "chunks": [{
            "chunk_id": "ch01-001", "chapter": "1", "heading": "Intro",
            "section": "Intro", "source": "ch01", "embedding": [0.5] * 4,
            "figures": [], "text": f"Intro\n{title} is a fixture book.",
        }],
    }


class FixtureRoot:
    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        data = root / "data"
        (data / "figures" / "quantization").mkdir(parents=True)
        (data / "figures" / "ddia").mkdir(parents=True)
        (data / "figures" / "cover.png").write_bytes(PNG)
        (data / "figures" / "quantization" / "cover.jpg").write_bytes(JPG)
        (data / "figures" / "ddia" / "cover.jpg").write_bytes(JPG)
        catalog = []
        for book_id, title in BOOKS.items():
            name = "index.json" if book_id == "fde" else f"index.{book_id}.json"
            (data / name).write_text(json.dumps(_index(book_id, title)), encoding="utf-8")
            catalog.append({
                "book_id": book_id, "title": title, "chunk_count": 1,
                "index_path": f"data/{name}",
                "figures_dir": "data/figures" if book_id == "fde" else f"data/figures/{book_id}",
            })
        (data / "books.json").write_text(json.dumps(catalog), encoding="utf-8")
        self.root = root
        self._patches = [
            mock.patch.object(server, "ROOT", root),
            mock.patch.object(server, "INDEX", data / "index.json"),
            mock.patch.object(ingest, "ROOT", root),
            mock.patch.object(server, "INDEX_CACHE", {}),
            mock.patch.object(server, "CHUNKS_JSON_CACHE", {}),
            mock.patch.object(server, "CHUNKS_GZIP_CACHE", {}),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self._patches):
            p.stop()
        self._tmp.cleanup()
