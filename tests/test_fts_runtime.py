"""FTS5 runtime lifecycle: cross-thread access, cache invalidation, fallback.

These pin the defects measured on 2026-10-29 against the live engine path:

1. ``ThreadingHTTPServer`` creates a new request thread, but the cached
   ``sqlite3`` connection was built on whichever thread fused first. Every
   later thread raised ``ProgrammingError``; ``fusion.fuse`` caught the
   exception and silently served the legacy idf channel.
2. The cache key was ``len(chunks)`` only, so an equal-count text edit kept
   the old FTS rows: a new term was not found and a removed term still was.
3. An unavailable FTS5 module (or a broken connection) produced the same
   silent legacy fallback with no warning and no trace mark.

Public seams only: ``get_fts_connection``, ``close_fts_connection``,
``fts_bm25_scores``, ``search_trigram``, and ``fuse``. The synthetic corpus is
arranged so BM25 and the legacy idf channel pick different candidates, which is
what makes a silent fallback observable.
"""

import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import fusion
from fts_index import (
    FtsUnavailable,
    close_fts_connection,
    fts_bm25_scores,
    get_fts_connection,
    search_trigram,
)
from keywords import postings
from observe import trace


def make_index(entries):
    return {
        "chunks": [
            {
                "chunk_id": f"ch{i:02d}",
                "chapter": "1",
                "heading": heading,
                "text": text,
                "source": "src",
            }
            for i, (heading, text) in enumerate(entries)
        ],
        "figures": [],
    }


def zephyr_index():
    """12 chunks where BM25 prefers ch02 and the legacy tie-break prefers ch01.

    ``zephyr`` appears once in ch01 and six times plus a heading in ch02, so
    BM25 scores ch02 higher. The legacy channel counts presence, ties both,
    and breaks the tie on the lower position (ch01). Both carry dense ranks
    inside the fusion band, so the chosen candidate is observable in the
    fused first passage.
    """
    entries = [
        ("Filler", f"filler words number {i} about ordinary things")
        for i in range(12)
    ]
    entries[1] = ("Target", "a zephyr appears once")
    entries[2] = ("Zephyr", "zephyr zephyr zephyr zephyr zephyr zephyr")
    return make_index(entries)


def zephyr_ranks():
    ranks = {f"ch{i:02d}": 99 for i in range(12)}
    ranks["ch01"] = 1
    ranks["ch02"] = 2
    for i in (3, 4, 5, 6, 7):
        ranks[f"ch{i:02d}"] = i
    return ranks


def zephyr_passages():
    return [
        {
            "chunk_id": f"ch{i:02d}",
            "chapter": "1",
            "heading": "",
            "text": "",
            "source": "",
            "score": 0.9,
        }
        for i in (3, 4, 5, 6, 7)
    ]


class FtsThreadTests(unittest.TestCase):
    def test_worker_threads_share_the_cached_index(self):
        index = zephyr_index()
        get_fts_connection(index)  # connection born on the main thread
        control = fts_bm25_scores(index, "what is zephyr")
        self.assertNotEqual(control, {})
        control_trigram = [
            chunk["chunk_id"] for chunk in search_trigram(index, "ordinary")
        ]
        self.assertTrue(control_trigram)

        def work(_):
            scores = fts_bm25_scores(index, "what is zephyr")
            trigram = [
                chunk["chunk_id"] for chunk in search_trigram(index, "ordinary")
            ]
            return scores, trigram

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(work, range(32)))

        for scores, trigram in results:
            self.assertEqual(scores, control)
            self.assertEqual(trigram, control_trigram)

    def test_concurrent_fuse_matches_single_thread_control(self):
        ranks = zephyr_ranks()
        with patch.object(fusion, "LEXICAL_BACKEND", "fts5"):
            control_index = zephyr_index()
            with trace(source="test", write_log=False) as control_trace:
                control = [
                    hit["chunk_id"]
                    for hit in fusion.fuse(
                        control_index,
                        "what is zephyr",
                        zephyr_passages(),
                        postings(control_index),
                        ranks,
                    )
                ]
        # Positive control: FTS ran and picked the BM25 winner, not the legacy
        # tie-break winner (ch01).
        self.assertEqual(control[0], "ch02")

        shared = zephyr_index()
        get_fts_connection(shared)  # connection born on the main thread
        word_map = postings(shared)

        def work(_):
            return [
                hit["chunk_id"]
                for hit in fusion.fuse(
                    shared, "what is zephyr", zephyr_passages(), word_map, ranks
                )
            ]

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(work, range(32)))

        for result in results:
            self.assertEqual(result, control)
        self.assertIn(
            "lexical_backend=fts5",
            control_trace.to_dict()["outcome"]["transforms"],
        )


class FtsInvalidationTests(unittest.TestCase):
    def test_equal_count_text_change_rebuilds_the_index(self):
        index = make_index(
            [
                ("One", "needle in the first haystack"),
                ("Two", "ordinary second paragraph"),
                ("Three", "ordinary third paragraph"),
                ("Four", "ordinary fourth paragraph"),
            ]
        )
        self.assertIn(0, fts_bm25_scores(index, "needle"))
        first_conn = get_fts_connection(index)

        # Same chunk count, different word.
        index["chunks"][0]["text"] = "saffron in the first haystack"

        self.assertIn(0, fts_bm25_scores(index, "saffron"))
        self.assertEqual(fts_bm25_scores(index, "needle"), {})
        self.assertIsNot(get_fts_connection(index), first_conn)

    def test_rebuild_closes_the_replaced_connection(self):
        index = make_index(
            [
                ("One", "needle in the first haystack"),
                ("Two", "ordinary second paragraph"),
                ("Three", "ordinary third paragraph"),
                ("Four", "ordinary fourth paragraph"),
            ]
        )
        stale = get_fts_connection(index)
        index["chunks"][0]["text"] = "saffron in the first haystack"
        get_fts_connection(index)
        with self.assertRaises(sqlite3.ProgrammingError):
            stale.execute("SELECT 1")

    def test_unchanged_content_reuses_the_connection(self):
        index = zephyr_index()
        first = get_fts_connection(index)
        fts_bm25_scores(index, "what is zephyr")
        self.assertIs(get_fts_connection(index), first)

    def test_close_drops_the_cache_and_allows_a_rebuild(self):
        index = zephyr_index()
        conn = get_fts_connection(index)
        self.assertTrue(close_fts_connection(index))
        self.assertNotIn("_fts_conn", index)
        with self.assertRaises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")
        self.assertTrue(fts_bm25_scores(index, "what is zephyr"))

    def test_section_trail_is_indexed_and_anchor_survives_fusion(self):
        index = zephyr_index()
        index["chunks"][1]["section"] = "Replication > Leaderless > Quorums"
        index["chunks"][1]["anchor"] = "sec-quorums"
        scores = fts_bm25_scores(index, "what are quorums")
        self.assertIn(1, scores)
        ranks = zephyr_ranks()
        fused = fusion.fuse(
            index, "what are quorums", zephyr_passages(), postings(index), ranks
        )
        by_id = {p["chunk_id"]: p for p in fused}
        self.assertIn("ch01", by_id)
        self.assertEqual(
            by_id["ch01"]["section"], "Replication > Leaderless > Quorums"
        )
        self.assertEqual(by_id["ch01"]["anchor"], "sec-quorums")


class FtsFallbackTests(unittest.TestCase):
    def _legacy_result(self):
        ranks = zephyr_ranks()
        index = zephyr_index()
        with patch.object(fusion, "LEXICAL_BACKEND", "legacy"):
            return [
                hit["chunk_id"]
                for hit in fusion.fuse(
                    index,
                    "what is zephyr",
                    zephyr_passages(),
                    postings(index),
                    ranks,
                )
            ]

    def test_unavailable_fts_warns_and_uses_the_legacy_candidate(self):
        legacy = self._legacy_result()
        self.assertEqual(legacy[0], "ch01")  # negative control: differs from FTS

        index = zephyr_index()
        word_map = postings(index)
        ranks = zephyr_ranks()
        failure = sqlite3.OperationalError("no such module: fts5")
        with patch.object(fusion, "LEXICAL_BACKEND", "fts5"), patch(
            "sqlite3.connect", side_effect=failure
        ), trace(source="test", write_log=False) as tr, self.assertLogs(
            "fusion", level="WARNING"
        ) as logs:
            fused = [
                hit["chunk_id"]
                for hit in fusion.fuse(
                    index, "what is zephyr", zephyr_passages(), word_map, ranks
                )
            ]

        self.assertEqual(fused, legacy)
        self.assertTrue(any("legacy" in line for line in logs.output))
        self.assertIn(
            "lexical_backend=legacy",
            tr.to_dict()["outcome"]["transforms"],
        )

    def test_query_raises_an_explicit_error_when_sqlite_is_unavailable(self):
        index = zephyr_index()
        failure = sqlite3.OperationalError("no such module: fts5")
        with patch("sqlite3.connect", side_effect=failure):
            with self.assertRaises(FtsUnavailable):
                fts_bm25_scores(index, "what is zephyr")


if __name__ == "__main__":
    unittest.main()
