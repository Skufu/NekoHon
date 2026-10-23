import unittest

from engine.retrieval.fusion import fuse
from engine.retrieval.keywords import postings


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


class FusionTests(unittest.TestCase):
    def test_a_strong_anchor_leads_and_the_weakest_dense_passage_drops(self):
        texts = ["the filler words here"] * 8
        texts[3] = "the pragmatic lead cares about flexibility"
        texts[7] = "flexibility shows up here too"
        index = make_index(texts)
        passages = [passage(f"ch{i:02d}") for i in (0, 1, 2, 4, 5)]
        ranks = {"ch00": 3, "ch01": 4, "ch02": 5, "ch03": 1, "ch04": 6, "ch05": 7}
        fused = fuse(index, "what is pragmatic about flexibility", passages,
                     postings(index), ranks)
        self.assertEqual([hit["chunk_id"] for hit in fused],
                         ["ch03", "ch00", "ch01", "ch02", "ch04"])

    def test_both_channels_outrank_a_single_channel_top(self):
        texts = ["the filler words here"] * 10
        texts[5] = "the pragmatic lead cares about flexibility"
        index = make_index(texts)
        passages = [passage(f"ch{i:02d}") for i in (0, 1, 2, 3, 4)]
        ranks = {"ch00": 1, "ch01": 3, "ch02": 4, "ch03": 5, "ch04": 6, "ch05": 2}
        fused = fuse(index, "what is pragmatic about flexibility", passages,
                     postings(index), ranks)
        self.assertEqual(fused[0]["chunk_id"], "ch05")
        self.assertEqual(len(fused), 5)

    def test_a_chunk_from_the_tail_is_never_admitted(self):
        texts = ["the filler words here"] * 8
        texts[3] = "the pragmatic lead cares about flexibility"
        index = make_index(texts)
        passages = [passage(f"ch{i:02d}") for i in (0, 1, 2, 4, 5)]
        ranks = {"ch00": 3, "ch01": 4, "ch02": 5, "ch03": 8, "ch04": 6, "ch05": 7}
        fused = fuse(index, "what is pragmatic about flexibility", passages,
                     postings(index), ranks)
        self.assertEqual(fused, passages)

    def test_no_rank_evidence_fails_closed(self):
        texts = ["the filler words here"] * 8
        texts[3] = "the pragmatic lead cares about flexibility"
        index = make_index(texts)
        passages = [passage(f"ch{i:02d}") for i in (0, 1, 2, 4, 5)]
        fused = fuse(index, "what is pragmatic about flexibility", passages,
                     postings(index), {})
        self.assertEqual(fused, passages)

    def test_common_words_leave_the_passages_alone(self):
        index = make_index(["the data of the book"] * 20)
        passages = [passage(f"ch{i:02d}") for i in (15, 16, 17, 18, 19)]
        ranks = {f"ch{i:02d}": 1 for i in (15, 16, 17, 18, 19)}
        fused = fuse(index, "what is the data of the book", passages,
                     postings(index), ranks)
        self.assertEqual(fused, passages)

    def test_a_present_chunk_is_not_duplicated_or_reordered(self):
        texts = ["the filler words here"] * 8
        texts[3] = "the pragmatic lead cares about flexibility"
        index = make_index(texts)
        passages = [passage("ch03")] + [passage(f"ch{i:02d}") for i in (0, 1, 2, 4)]
        ranks = {"ch00": 3, "ch01": 4, "ch02": 5, "ch03": 1, "ch04": 6}
        fused = fuse(index, "what is pragmatic about flexibility", passages,
                     postings(index), ranks)
        self.assertEqual(fused, passages)

    def test_only_the_strongest_candidate_joins_the_pool(self):
        texts = ["the filler words here"] * 8
        texts[3] = "the pragmatic lead"
        texts[5] = "pragmatic appears here too"
        index = make_index(texts)
        passages = [passage(f"ch{i:02d}") for i in (0, 1, 2, 4, 6)]
        ranks = {"ch00": 4, "ch01": 5, "ch02": 6, "ch03": 1,
                 "ch04": 7, "ch05": 2, "ch06": 8}
        fused = fuse(index, "what is pragmatic", passages,
                     postings(index), ranks)
        ids = [hit["chunk_id"] for hit in fused]
        self.assertIn("ch03", ids)
        self.assertNotIn("ch05", ids)


if __name__ == "__main__":
    unittest.main()
