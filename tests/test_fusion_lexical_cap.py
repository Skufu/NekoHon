"""MAX_LEXICAL_CANDIDATES: the knob must be inert at 1 and select at k>1.

Fake index, injected ranks, no Ollama. `old_fuse` is a copy of the pre-knob
body (single candidate: min by score, lexical rank 1); at k=1 the shipped
`fuse` must produce the same window, in the same order, on the same fixtures.
"""

import unittest
from unittest import mock

import fusion
from fusion import fuse
from fts_index import fts_bm25_scores
from keywords import postings


def make_index(texts):
    chunks = [
        {"chunk_id": f"ch{i:02d}", "chapter": "1", "heading": "", "text": text}
        for i, text in enumerate(texts)
    ]
    return {"chunks": chunks, "figures": []}


def passage(chunk_id):
    return {
        "chunk_id": chunk_id,
        "chapter": "1",
        "heading": "",
        "text": "",
        "source": "",
        "score": 0.9,
    }


def scores(index, question, ranks):
    band = max(1, round(fusion.RANK_BAND * len(index["chunks"])))
    return fts_bm25_scores(index, question, ranks=ranks, band=band)


def old_fuse(index, question, passages, word_map, ranks):
    """The pre-2026-11-02 body, kept here as the equivalence reference."""
    chunks = index["chunks"]
    if not chunks or not passages:
        return passages
    found = scores(index, question, ranks)
    if not found:
        return passages
    best = min(found, key=lambda position: (-found[position], position))
    candidate = dict(
        chunk_id=chunks[best]["chunk_id"],
        chapter=chunks[best].get("chapter"),
        heading=chunks[best].get("heading", ""),
        text=chunks[best].get("text", ""),
        source=chunks[best].get("source", ""),
        score=None,
    )
    by_id = {hit["chunk_id"]: hit for hit in passages}
    by_id.setdefault(candidate["chunk_id"], candidate)
    lex_rank = {candidate["chunk_id"]: 1}
    fused = []
    for chunk_id, hit in by_id.items():
        dense = ranks.get(chunk_id)
        if not dense:
            continue
        score = 1.0 / (fusion.RRF_K + dense)
        if lex_rank.get(chunk_id):
            score += 1.0 / (fusion.RRF_K + lex_rank[chunk_id])
        fused.append((score, dense, lex_rank.get(chunk_id, 0), hit))
    fused.sort(key=lambda item: (-item[0], item[1], item[2]))
    return [hit for _, _, _, hit in fused[: len(passages)]]


def wide_fixture():
    """40 chunks (band 8): four BM25 candidates, one of them outside the band."""
    texts = ["the filler words here"] * 40
    texts[3] = "the pragmatic lead"
    texts[5] = "pragmatic appears here too"
    texts[7] = "pragmatic again right here"
    texts[9] = "pragmatic far in the tail"
    index = make_index(texts)
    ranks = {
        "ch03": 1, "ch05": 2, "ch07": 3, "ch09": 9,
        "ch10": 10, "ch11": 11, "ch12": 12, "ch13": 13, "ch14": 14,
    }
    passages = [passage(f"ch{i:02d}") for i in (10, 11, 12, 13, 14)]
    return index, "what is pragmatic", passages, ranks


class InertAtOneTests(unittest.TestCase):
    def test_k1_matches_the_pre_knob_path(self):
        fixtures = []
        index, question, passages, ranks = wide_fixture()
        fixtures.append((index, question, passages, ranks))
        # A candidate already inside the dense window is re-placed, not added.
        texts = ["the filler words here"] * 8
        texts[3] = "the pragmatic lead"
        index = make_index(texts)
        fixtures.append((
            index,
            "what is pragmatic about flexibility",
            [passage(f"ch{i:02d}") for i in (0, 1, 2, 3, 4)],
            {"ch00": 1, "ch01": 2, "ch02": 3, "ch03": 4, "ch04": 5, "ch05": 6, "ch06": 7},
        ))
        # No lexical score at all: the passages come back untouched.
        index = make_index(["the data of the book"] * 20)
        fixtures.append((
            index,
            "what is the data of the book",
            [passage(f"ch{i:02d}") for i in (0, 1, 2, 3, 4)],
            {f"ch{i:02d}": i + 1 for i in range(20)},
        ))
        for index, question, passages, ranks in fixtures:
            with mock.patch.object(fusion, "MAX_LEXICAL_CANDIDATES", 1):
                shipped = [h["chunk_id"] for h in fuse(
                    index, question, list(passages), postings(index), ranks)]
            expected = [h["chunk_id"] for h in old_fuse(
                index, question, list(passages), postings(index), ranks)]
            self.assertEqual(shipped, expected)
            self.assertEqual(len(shipped), len(set(shipped)))

    def test_k1_ignores_the_second_candidate(self):
        index, question, passages, ranks = wide_fixture()
        with mock.patch.object(fusion, "MAX_LEXICAL_CANDIDATES", 1):
            ids = [h["chunk_id"] for h in fuse(
                index, question, list(passages), postings(index), ranks)]
        self.assertIn("ch03", ids)
        self.assertNotIn("ch05", ids)
        self.assertNotIn("ch07", ids)


class CandidateCapTests(unittest.TestCase):
    def test_k3_admits_the_three_strongest_candidates(self):
        index, question, passages, ranks = wide_fixture()
        with mock.patch.object(fusion, "MAX_LEXICAL_CANDIDATES", 3):
            ids = [h["chunk_id"] for h in fuse(
                index, question, list(passages), postings(index), ranks)]
        self.assertEqual(len(ids), len(passages))
        for candidate in ("ch03", "ch05", "ch07"):
            self.assertIn(candidate, ids)
        self.assertEqual(len(ids), len(set(ids)))

    def test_the_band_still_vetoes_a_tail_candidate_at_k5(self):
        index, question, passages, ranks = wide_fixture()
        with mock.patch.object(fusion, "MAX_LEXICAL_CANDIDATES", 5):
            ids = [h["chunk_id"] for h in fuse(
                index, question, list(passages), postings(index), ranks)]
        self.assertNotIn("ch09", ids)

    def test_no_scores_returns_the_passages_at_any_k(self):
        index = make_index(["the data of the book"] * 20)
        passages = [passage(f"ch{i:02d}") for i in (0, 1, 2, 3, 4)]
        ranks = {f"ch{i:02d}": i + 1 for i in range(20)}
        for k in (1, 3, 5):
            with mock.patch.object(fusion, "MAX_LEXICAL_CANDIDATES", k):
                self.assertEqual(
                    fuse(index, "what is the data of the book", list(passages),
                         postings(index), ranks),
                    passages,
                )


class AdditionsTests(unittest.TestCase):
    def test_additions_keep_the_dense_head_and_append(self):
        index, question, passages, ranks = wide_fixture()
        dense_ids = [p["chunk_id"] for p in passages]
        fused = fuse(index, question, list(passages), postings(index), ranks, added=1)
        ids = [h["chunk_id"] for h in fused]
        self.assertEqual(ids[: len(dense_ids)], dense_ids)
        self.assertEqual(ids[len(dense_ids):], ["ch03"])
        self.assertEqual(len(ids), len(set(ids)))

    def test_two_additions_append_in_bm25_order(self):
        index, question, passages, ranks = wide_fixture()
        dense_ids = [p["chunk_id"] for p in passages]
        ids = [h["chunk_id"] for h in fuse(
            index, question, list(passages), postings(index), ranks, added=2)]
        self.assertEqual(ids[: len(dense_ids)], dense_ids)
        self.assertEqual(ids[len(dense_ids):], ["ch03", "ch05"])

    def test_an_addition_already_in_the_window_is_skipped(self):
        index, question, passages, ranks = wide_fixture()
        passages = [passage("ch03")] + passages
        ids = [h["chunk_id"] for h in fuse(
            index, question, list(passages), postings(index), ranks, added=1)]
        self.assertEqual(ids[0], "ch03")
        self.assertEqual(ids.count("ch03"), 1)
        # The strongest candidate already sits in the window, so the slot
        # goes to the next admissible chunk rather than duplicating it.
        self.assertEqual(ids[-1], "ch05")

    def test_additions_respect_the_band(self):
        index, question, passages, ranks = wide_fixture()
        ids = [h["chunk_id"] for h in fuse(
            index, question, list(passages), postings(index), ranks, added=5)]
        self.assertNotIn("ch09", ids)
        self.assertEqual(len(ids), len(passages) + 3)

    def test_added_zero_is_the_rrf_path(self):
        index, question, passages, ranks = wide_fixture()
        with mock.patch.object(fusion, "MAX_LEXICAL_CANDIDATES", 1):
            without = [h["chunk_id"] for h in fuse(
                index, question, list(passages), postings(index), ranks)]
            explicit = [h["chunk_id"] for h in fuse(
                index, question, list(passages), postings(index), ranks, added=0)]
        self.assertEqual(without, explicit)


if __name__ == "__main__":
    unittest.main()
