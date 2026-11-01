"""SQLite index storage: round-trip fidelity and persisted FTS5.

The engine reads the same dict from a database as it did from JSON, and the
persisted FTS tables answer exactly like the in-memory build. These tests use
tiny fixtures only; they never touch `data/` or a model.
"""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import fts_index
import store


def fixture():
    return {
        "book_id": "fixture",
        "title": "A Fixture",
        "embedder": "nomic-embed-text",
        "embedding_dims": 3,
        "chunks": [
            {
                "chunk_id": "c1",
                "chapter": 1,
                "heading": "Watermarks",
                "section": "Streams",
                "doc": "doc-1",
                "anchor": "watermarks",
                "text": "Watermarks track how far event time has advanced.",
                "blocks": [{"kind": "paragraph", "text": "Watermarks track event time."}],
                "figures": ["figure-1-1"],
                "source": "ch. 1",
                "embedding": [0.25, -0.5, 0.75],
                "embedding_input_sha256": "abc123",
                "custom_field": {"kept": True},
            },
            {
                "chunk_id": "c2",
                "chapter": 2,
                "heading": "Compaction",
                "text": "Compaction merges immutable segments in the background.",
                "source": "ch. 2",
                "embedding": [0.0, 1.0, 0.0],
            },
        ],
        "figures": [
            {
                "id": "figure-1-1",
                "chapter": 1,
                "caption": "A watermark advances with event time.",
                "referencing_paragraph": "See the watermark above.",
                "file": "figure-1-1.png",
                "anchor": "figure-1-1",
                "source": "ch. 1",
                "embedding": [1.0, 0.0, 0.0],
                "embedding_input_sha256": "def456",
            }
        ],
    }


class StoreRoundTripTest(unittest.TestCase):
    def test_round_trip_keeps_every_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.sqlite"
            data = fixture()
            store.write_index(path, data)
            loaded = store.read_index(path)

        self.assertEqual(loaded["book_id"], "fixture")
        self.assertEqual(loaded["embedding_dims"], 3)
        self.assertEqual(loaded["chunks"][0]["custom_field"], {"kept": True})
        self.assertEqual(
            loaded["chunks"][0]["blocks"],
            [{"kind": "paragraph", "text": "Watermarks track event time."}],
        )
        self.assertEqual(loaded["chunks"][0]["figures"], ["figure-1-1"])
        self.assertEqual(loaded["chunks"][0]["embedding"], [0.25, -0.5, 0.75])
        self.assertEqual(loaded["figures"][0]["id"], "figure-1-1")
        self.assertEqual(
            loaded["figures"][0]["embedding_input_sha256"], "def456"
        )
        # Absent optional keys stay absent rather than inventing empty values.
        self.assertNotIn("section", loaded["chunks"][1])
        self.assertNotIn("blocks", loaded["chunks"][1])

    def test_storage_check_reports_missing_fts_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.sqlite"
            store.write_index(path, fixture())
            self.assertEqual(store.check_database(path), [])
            conn = sqlite3.connect(path)
            conn.execute("DELETE FROM chunks_fts WHERE rowid = 0")
            conn.commit()
            conn.close()
            issues = store.check_database(path)
        self.assertEqual(len(issues), 1)
        self.assertIn("chunks_fts rows 1 != chunks 2", issues[0])

    def test_replacing_a_database_keeps_the_previous_file_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.sqlite"
            store.write_index(path, fixture())
            before = store.read_index(path)
            with self.assertRaises(TypeError):
                store.write_index(path, None)
            after = store.read_index(path)
        self.assertEqual(before["chunks"], after["chunks"])

    def test_a_name_near_the_filesystem_limit_still_writes(self):
        """An imported book id can be 200+ characters, and 240-byte names are
        legal. The atomic write must not add the target's name to a temp
        name: measured 2026-11-01, a 240-byte target made a 253-byte temp
        file, and the `-journal` SQLite creates beside it crossed the
        filesystem's 255-byte limit with "unable to open database file".
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"index.{'a' * 227}.sqlite"
            self.assertEqual(len(path.name), 240)
            store.write_index(path, fixture())
            self.assertEqual(store.read_index(path)["book_id"], "fixture")


class PersistedFtsTest(unittest.TestCase):
    def test_persisted_fts_matches_in_memory_fts(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.sqlite"
            data = fixture()
            store.write_index(path, data)
            loaded = store.read_index(path)
            loaded["_db_path"] = str(path)

            for question in ("watermark", "compaction segments", "immutable"):
                self.assertEqual(
                    fts_index.fts_bm25_scores(data, question),
                    fts_index.fts_bm25_scores(loaded, question),
                )
            trigrams = [
                c["chunk_id"] for c in fts_index.search_trigram(loaded, "watermark")
            ]
            self.assertEqual(trigrams, ["c1"])
            conn = fts_index.get_fts_connection(loaded)
            self.assertEqual(
                conn.execute("SELECT count(*) FROM chunks_fts").fetchone()[0], 2
            )
            fts_index.close_fts_connection(loaded)


if __name__ == "__main__":
    unittest.main()
